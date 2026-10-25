"""Shiller workbook parsing, the live CAPE chain, and recording/replaying real provider answers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.errors import DataError
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.catalog import build_catalog
from rotationlab.data.providers.http import FixtureClient, RecordingClient, ReplayClient
from rotationlab.data.providers.recorder import SAMPLE, record
from rotationlab.data.providers.shiller import ShillerProvider, parse_workbook, shiller_date
from rotationlab.data.view import StoreViewFactory
from tests.fixtures import fakes
from tests.fixtures.build_fixtures import alfred_rows, cpi_vintages

FX = Path(__file__).resolve().parents[1] / "fixtures"
XLS = FX / "shiller_ie_data.xls"


def test_shiller_dates_follow_the_workbook_convention() -> None:
    assert shiller_date(1871.1) == pd.Timestamp("1871-10-31")
    assert shiller_date("2025.01") == pd.Timestamp("2025-01-31")
    assert shiller_date("1871.12") == pd.Timestamp("1871-12-31")
    assert (
        shiller_date("Date") is None and shiller_date(float("nan")) is None and shiller_date(1871.13) is None
    )


def test_workbook_parse_and_provider() -> None:
    df = parse_workbook(XLS.read_bytes())
    assert (
        df.loc["1871-10-31", "P"] == 4.64
        and pd.isna(df.loc["2025-10-31", "E"])
        and pd.isna(df.loc["1871-01-31", "CAPE"])
    )
    with pytest.raises(DataError):
        parse_workbook(b"not an excel file")
    http = FixtureClient({r"first": b"<html>moved</html>", r"second": XLS})
    p = ShillerProvider(http, ["https://first/ie_data.xls", "https://second/ie_data.xls"])
    e = p.fetch_frame(
        SeriesSpec(SeriesId("shiller:E"), "shiller", "E", SeriesKind.MACRO, Frequency.MONTHLY, lag="6M"), None
    )
    assert e["obs_date"].max() == pd.Timestamp("2025-09-30") and e["vintage_date"].max() == pd.Timestamp(
        "2026-03-31"
    )
    assert len(http.requests) == 2  # first URL failed, second answered
    with pytest.raises(DataError):
        p.fetch_frame(
            SeriesSpec(SeriesId("shiller:X"), "shiller", "X", SeriesKind.MACRO, Frequency.MONTHLY), None
        )
    with pytest.raises(DataError, match="no source answered"):
        ShillerProvider(FixtureClient({r".": b"x"}), ["https://a/x.xls"]).fetch_frame(
            SeriesSpec(SeriesId("shiller:P"), "shiller", "P", SeriesKind.INDEX, Frequency.MONTHLY), None
        )


def test_earnings_chain_prefers_live_shiller_and_falls_back_to_the_mirror(bundle, static_store) -> None:
    catalog = build_catalog(bundle)
    mirror_only = StoreViewFactory(
        static_store.observations(), catalog, {}, WeekdayCalendar(), chains=bundle.series.chains
    )
    v0 = mirror_only.at(date(2026, 3, 31))
    assert v0.series("macro:SP_EARNINGS").index[-1] == pd.Timestamp("2023-06-30")  # the mirror stops there
    assert [p.series_id for p in v0.chain_provenance("macro:SP_EARNINGS")] == ["static:shiller:Earnings"]
    live = parse_workbook(XLS.read_bytes())["E"].dropna()
    rows = pd.DataFrame(
        {
            "series_id": "shiller:E",
            "obs_date": live.index,
            "vintage_date": live.index + pd.offsets.MonthEnd(6),
            "value": live.to_numpy(),
        }
    )
    both = pd.concat([static_store.observations(), rows], ignore_index=True)
    v = StoreViewFactory(both, catalog, {}, WeekdayCalendar(), chains=bundle.series.chains).at(
        date(2026, 3, 31)
    )
    s = v.series("macro:SP_EARNINGS")
    assert s.index[-1] == pd.Timestamp("2025-09-30") and s.iloc[-1] == 230.6  # the live workbook goes further
    assert v.chain_provenance("macro:SP_EARNINGS")[0].series_id == "shiller:E"


def test_recording_and_replay_round_trip(tmp_path) -> None:
    inner = FixtureClient(
        {r"chart/SPY": FX / "yahoo_SPY_2024.json", r"api\.bls\.gov": fakes.bls_json({"X": []})}
    )
    rec = RecordingClient(inner, tmp_path, label="t")
    a = rec.get("https://query1.finance.yahoo.com/v8/finance/chart/SPY", {"period1": "1", "period2": "999"})
    b = rec.post_json(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/", {"seriesid": ["X"], "registrationkey": "secret"}
    )
    index = json.loads((tmp_path / "index.json").read_text())
    assert all("secret" not in k for k in index) and any("period2=*" in k for k in index)
    rep = ReplayClient(tmp_path)
    assert (
        rep.get("https://query1.finance.yahoo.com/v8/finance/chart/SPY", {"period1": "1", "period2": "12345"})
        == a
    )
    assert (
        rep.post_json(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            {"seriesid": ["X"], "registrationkey": "other"},
        )
        == b
    )
    with pytest.raises(DataError, match="not recorded"):
        rep.get("https://example.com/x")


def test_record_all_providers_offline_then_replay(tmp_path, bundle) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "x.csv",
            (FX.parent.parent / "data/raw/ff_10_industry_portfolios.csv").read_text(encoding="latin-1"),
        )
    routes = {
        r"finance/chart": FX / "yahoo_SPY_2024.json",
        r"stooq\.com": FX / "stooq_spy.csv",
        r"series_id=CPIAUCSL": fakes.fred_observations(alfred_rows(cpi_vintages())),
        r"series_id=(DGS10|TB3MS)": fakes.fred_observations(
            [("2024-12-02", "9999-12-31", "2024-12-01", "4.2")]
        ),
        r"F-F_Research_Data_Factors_CSV": FX / "F-F_Research_Data_Factors_CSV.zip",
        r"10_Industry": buf.getvalue(),
        r"6dca-aqww": FX / "cftc_gold.json",
        r"api\.bls\.gov": fakes.bls_json({"CUSR0000SA0": [(2024, 11, "315.0")]}),
        r"ie_data": XLS,
    }
    catalog = build_catalog(bundle)
    rows = record(
        bundle,
        catalog,
        tmp_path,
        date(2026, 10, 24),
        env={"FRED_API_KEY": "k", "STOOQ_API_KEY": "k"},
        transport=lambda name, pc: FixtureClient(routes),
    )
    assert {r["series_id"] for r in rows} == {sid for items in SAMPLE.values() for sid, _ in items}
    errors = {r["series_id"]: r["error"] for r in rows if r["error"]}
    assert set(errors) <= {"cftc:088691:noncomm_net"}, errors  # fixture has 2024 data only
    from tests.integration.test_recorded import replay_all

    replay_all(tmp_path, bundle)
