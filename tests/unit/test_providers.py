"""Parsers and vintage logic of every provider, offline on fixtures (tests/fixtures/fakes.py)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.errors import DataError
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.providers.cftc import CftcProvider, parse_cot
from rotationlab.data.providers.fred import FredProvider, alfred_frame, parse_graph_csv, parse_observations
from rotationlab.data.providers.french import FrenchProvider
from rotationlab.data.providers.http import FixtureClient, UrllibClient
from rotationlab.data.providers.static import FREDMD_CODES, STATIC_CATALOG, StaticProvider, fredmd_series_id
from rotationlab.data.providers.stooq import StooqProvider, parse_csv, stooq_symbol
from rotationlab.data.providers.yahoo import YahooProvider, parse_chart
from tests.fixtures import fakes
from tests.fixtures.build_fixtures import alfred_rows, cpi_vintages

FX = Path(__file__).resolve().parents[1] / "fixtures"


def spec(sid, kind, freq, lag="0D", vintages="none", params=()) -> SeriesSpec:
    p, code = sid.split(":", 1)
    return SeriesSpec(SeriesId(sid), p, code, kind, freq, lag=lag, vintages=vintages, params=tuple(params))


# ---------------------------------------------------------------------------- yahoo
def test_yahoo_chart_fixture() -> None:
    out = parse_chart((FX / "yahoo_SPY_2024.json").read_bytes())
    close, div = out["close"], out["dividend"]
    assert close.index[0] == pd.Timestamp("2024-01-02")  # session open 09:30 New York → same date
    assert len(close) == 251  # 252 sessions, last close null
    assert div.to_dict() == {
        pd.Timestamp("2024-03-15"): 1.5949,
        pd.Timestamp("2024-06-21"): 1.759,
        pd.Timestamp("2024-09-20"): 1.7458,
        pd.Timestamp("2024-12-20"): 1.9663,
    }
    assert out["split"].empty


def test_yahoo_dates_use_exchange_timezone() -> None:
    # a session that opens at 09:30 New York is 14:30 UTC (winter) or 13:30 UTC (summer); late-evening
    # UTC timestamps of Asian exchanges must not shift US dates – here: the date stays the session date
    days = [date(2024, 3, 8), date(2024, 3, 11)]  # around the DST switch
    raw = fakes.yahoo_chart("SPY", days, [1.0, 2.0], splits={date(2024, 3, 11): (2, 1)})
    out = parse_chart(raw)
    assert list(out["close"].index.date) == days and out["split"].iloc[0] == 2.0


def test_yahoo_provider_requests_window_and_fields() -> None:
    http = FixtureClient({r"chart/SPY": FX / "yahoo_SPY_2024.json"})
    p = YahooProvider(http, today=date(2025, 1, 2))
    f = p.fetch_frame(spec("yahoo:SPY:close", SeriesKind.PRICE, Frequency.DAILY), date(2024, 12, 1))
    assert f["obs_date"].min() >= pd.Timestamp("2024-12-01") and (f["vintage_date"] == f["obs_date"]).all()
    p.fetch_frame(spec("yahoo:SPY:dividend", SeriesKind.DIVIDEND, Frequency.DAILY), date(2024, 12, 1))
    assert len(http.requests) == 1  # close and dividend share one request
    assert "period1=1733011200" in http.requests[0] and "events=div,splits" in http.requests[0]


def test_yahoo_error_payload() -> None:
    with pytest.raises(DataError):
        parse_chart(json.dumps({"chart": {"result": None, "error": {"code": "Not Found"}}}).encode())


# ---------------------------------------------------------------------------- stooq
def test_stooq() -> None:
    s = parse_csv((FX / "stooq_spy.csv").read_bytes())
    assert len(s) == 252 and s.index.is_monotonic_increasing
    assert stooq_symbol("SPY") == "spy.us" and stooq_symbol("^spx") == "^spx"
    with pytest.raises(DataError):
        parse_csv(b"No data")
    http = FixtureClient({r"stooq\.com/q/d/l/\?s=spy\.us": FX / "stooq_spy.csv"})
    f = StooqProvider(http).fetch_frame(
        spec("stooq:SPY:close", SeriesKind.PRICE, Frequency.DAILY), date(2024, 12, 2)
    )
    assert f["obs_date"].min() == pd.Timestamp("2024-12-02") and "d1=20241202" in http.requests[0]


# ---------------------------------------------------------------------------- FRED / ALFRED
CPI = spec("fred:CPIAUCSL", SeriesKind.MACRO, Frequency.MONTHLY, lag="1M", vintages="alfred")


def test_fred_observations_parse() -> None:
    df, count = parse_observations((FX / "alfred_CPIAUCSL.json").read_bytes())
    assert count == len(df) == 155 and df["realtime_start"].dtype.kind == "M"
    with pytest.raises(DataError):
        parse_observations(json.dumps({"error_code": 400, "error_message": "Bad Request. api_key"}).encode())


def test_alfred_full_frame_vintages_backfill_and_period_end() -> None:
    rows, _ = parse_observations((FX / "alfred_CPIAUCSL.json").read_bytes())
    f = alfred_frame(rows, CPI, clip=None)
    assert f.attrs["real_vintages"] is True
    assert (f["obs_date"] == f["obs_date"] + pd.offsets.MonthEnd(0)).all()  # period ends
    may08 = f[f["obs_date"] == pd.Timestamp("2008-05-31")]
    assert may08["vintage_date"].tolist() == [pd.Timestamp("2008-06-15"), pd.Timestamp("2009-02-20")]
    # 2004-01 entered the archive only on 2006-01-01 → an extra row at the lag-model date
    jan04 = f[f["obs_date"] == pd.Timestamp("2004-01-31")]
    assert jan04["vintage_date"].iloc[0] == pd.Timestamp("2004-02-29") and f.attrs["backfilled"] == 22
    assert (f["vintage_date"] >= f["obs_date"]).all()


def test_alfred_backfill_ignores_delayed_releases_inside_the_archive() -> None:
    """Fable review 2026-10-24: a release delayed by a shutdown (Sept 2025 published 2025-12-02) is not
    pre-archive history; it must stay unknown at the lag-model date 2025-10-31."""
    rows = pd.DataFrame(
        {
            "realtime_start": pd.to_datetime(["2000-01-15", "2000-01-15", "2000-02-17", "2025-12-02"]),
            "realtime_end": "9999-12-31",
            "date": pd.to_datetime(["1998-01-01", "1999-12-01", "2000-01-01", "2025-09-01"]),
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    f = alfred_frame(rows, spec("fred:X", SeriesKind.MACRO, Frequency.MONTHLY, "1M", "alfred"), clip=None)
    assert f.attrs["backfilled"] == 1  # only 1998-01 (first vintage = archive start, far beyond the lag)
    assert f[f["obs_date"] == "1998-01-31"]["vintage_date"].tolist() == [
        pd.Timestamp("1998-02-28"),
        pd.Timestamp("2000-01-15"),
    ]
    assert f[f["obs_date"] == "2025-09-30"]["vintage_date"].tolist() == [pd.Timestamp("2025-12-02")]


def test_alfred_incremental_drops_clipped_periods() -> None:
    clip = date(2008, 7, 1)
    rows, _ = parse_observations(fakes.fred_observations(alfred_rows(cpi_vintages(), clip=clip)))
    f = alfred_frame(rows, CPI, clip=clip)
    assert f["vintage_date"].min() > pd.Timestamp(clip)  # nothing forged at the clip date
    assert pd.Timestamp("2008-07-15") in set(f["vintage_date"])  # June CPI, released after the clip
    assert f.attrs["backfilled"] == 0


def test_alfred_clamps_releases_inside_their_own_period() -> None:
    rows = pd.DataFrame(
        {
            "realtime_start": pd.to_datetime(["2026-10-10", "2026-10-24"]),
            "realtime_end": ["2026-10-23", "9999-12-31"],
            "date": pd.to_datetime(["2026-10-01"] * 2),
            "value": [55.0, 54.6],
        }
    )
    f = alfred_frame(
        rows, spec("fred:UMCSENT", SeriesKind.MACRO, Frequency.MONTHLY, "1M", "alfred"), clip=date(2026, 9, 1)
    )
    assert f.attrs["clamped"] == 2 and f["vintage_date"].tolist() == [pd.Timestamp("2026-10-31")]
    assert f["value"].tolist() == [54.6]  # the later (final) reading wins at period end


def test_fred_paginates() -> None:
    rows = alfred_rows(cpi_vintages())
    pages = {
        0: fakes.fred_observations(rows, offset=0, limit=100),
        100: fakes.fred_observations(rows, offset=100, limit=100),
    }
    http = FixtureClient(
        {r"api\.stlouisfed\.org": lambda url: pages[int(url.split("offset=")[1].split("&")[0])]}
    )
    p = FredProvider(http, api_key="k")
    p_page = __import__("rotationlab.data.providers.fred", fromlist=["PAGE"])
    old = p_page.PAGE
    p_page.PAGE = 100
    try:
        f = p.fetch_frame(CPI, None)
    finally:
        p_page.PAGE = old
    assert len(http.requests) == 2 and len(f) > 100
    assert "realtime_start=1776-07-04" in http.requests[0] and "output_type=1" in http.requests[0]


def test_fred_without_key_uses_fredgraph_and_lag_model() -> None:
    http = FixtureClient({r"fredgraph\.csv\?id=UNRATE": FX / "fredgraph_UNRATE.csv"})
    f = FredProvider(http, api_key=None).fetch_frame(
        spec("fred:UNRATE", SeriesKind.MACRO, Frequency.MONTHLY, "1M", "none"), None
    )
    assert f.attrs["real_vintages"] is False and "no FRED_API_KEY" in f.attrs["note"]
    assert len(f) == 8  # '.' dropped
    assert f["vintage_date"].iloc[0] == pd.Timestamp("2025-02-28")  # Jan 2025 + 1M
    old_header = b"DATE,UNRATE\n2025-01-01,4.0\n"
    assert parse_graph_csv(old_header, "UNRATE").iloc[0] == 4.0


def test_alfred_series_are_never_lag_modelled_without_key() -> None:
    http = FixtureClient({r"fredgraph": FX / "fredgraph_UNRATE.csv"})
    with pytest.raises(DataError, match="need FRED_API_KEY"):
        FredProvider(http, api_key=None).fetch_frame(CPI, None)
    assert http.requests == []


# ---------------------------------------------------------------------------- French, CFTC
def test_french_zip_matches_static_copy() -> None:
    http = FixtureClient({r"F-F_Research_Data_Factors_CSV\.zip": FX / "F-F_Research_Data_Factors_CSV.zip"})
    p = FrenchProvider(http)
    rf = p.fetch_frame(
        spec(
            "french:ff3:RF",
            SeriesKind.RETURN,
            Frequency.MONTHLY,
            params=[("file", "F-F_Research_Data_Factors_CSV.zip"), ("column", "RF")],
        ),
        None,
    )
    mkt = p.fetch_frame(
        spec(
            "french:ff3:MKT_RF",
            SeriesKind.RETURN,
            Frequency.MONTHLY,
            params=[("file", "F-F_Research_Data_Factors_CSV.zip"), ("column", "Mkt-RF")],
        ),
        None,
    )
    assert len(http.requests) == 1
    st = StaticProvider("data/raw")
    st_rf = st.fetch_frame(STATIC_CATALOG[SeriesId("static:french:ff3:RF")].spec, None)
    assert np.array_equal(rf["value"].to_numpy(), st_rf["value"].to_numpy())
    assert rf["obs_date"].iloc[0] == pd.Timestamp("1926-07-31") and abs(mkt["value"].iloc[0] - 0.0289) < 1e-12
    with pytest.raises(DataError):
        p.fetch_frame(
            spec(
                "french:ff3:XX",
                SeriesKind.RETURN,
                Frequency.MONTHLY,
                params=[("file", "F-F_Research_Data_Factors_CSV.zip"), ("column", "XX")],
            ),
            None,
        )


def test_cftc() -> None:
    df = parse_cot((FX / "cftc_gold.json").read_bytes())
    assert df["noncomm_net"].iloc[0] == 200_000 and df.index[0] == pd.Timestamp("2024-01-02")
    http = FixtureClient({r"6dca-aqww": FX / "cftc_gold.json"})
    s = spec(
        "cftc:088691:noncomm_net",
        SeriesKind.POSITIONING,
        Frequency.WEEKLY,
        "7D",
        params=[("market", "088691"), ("field", "noncomm_net")],
    )
    f = CftcProvider(http).fetch_frame(s, None)
    assert (f["vintage_date"] - f["obs_date"] == pd.Timedelta(days=7)).all() and len(f) == 12
    assert "cftc_contract_market_code=088691" in http.requests[0]


# ---------------------------------------------------------------------------- static, http
def test_static_catalog_covers_fredmd_and_constructs() -> None:
    assert len(FREDMD_CODES) == 126 and fredmd_series_id("S&P 500") == "static:fredmd:SP500"
    lags = {sid: e.spec.lag for sid, e in STATIC_CATALOG.items()}
    assert lags["static:fredmd:GS10"] == "0D" and lags["static:fredmd:INDPRO"] == "1M"
    assert lags["static:fredmd:PCEPI"] == "2M" and lags["static:shiller:Earnings"] == "6M"
    assert lags["static:FF_MKT"] == "0D" and lags["static:WB_ENERGY"] == "0D"


def test_static_fingerprint_changes_with_raw_files(tmp_path) -> None:
    import shutil

    raw = tmp_path / "raw"
    shutil.copytree("data/raw", raw)
    p = StaticProvider(raw)
    a = p.fingerprint()
    (raw / "vix_daily.csv").write_text((raw / "vix_daily.csv").read_text() + "2026-10-23,20,20,20,20\n")
    assert StaticProvider(raw).fingerprint() != a


def test_urllib_client_retries_then_fails(monkeypatch) -> None:
    import urllib.error
    import urllib.request

    calls = []

    def boom(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    c = UrllibClient(retries=2, backoff_s=0.0, sleep=lambda s: None)
    with pytest.raises(DataError, match="giving up after 3 attempts"):
        c.get("https://api.stlouisfed.org/x", {"api_key": "secret"})
    assert len(calls) == 3


def test_urllib_client_does_not_retry_client_errors_and_redacts_keys(monkeypatch) -> None:
    import urllib.error
    import urllib.request

    def denied(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", denied)
    with pytest.raises(DataError) as e:
        UrllibClient(retries=3, sleep=lambda s: None).get(
            "https://api.stlouisfed.org/x", {"api_key": "secret"}
        )
    assert "secret" not in str(e.value) and "403" in str(e.value)


# ---------------------------------------------------------------------------- error paths
def test_fred_with_key_for_plain_series_and_incremental_alfred() -> None:
    rows = [
        ("2026-10-20", "9999-12-31", "2026-10-15", "4.10"),
        ("2026-10-20", "9999-12-31", "2026-10-16", "."),
    ]
    http = FixtureClient(
        {
            r"series_id=DGS10": fakes.fred_observations(rows),
            r"series_id=CPIAUCSL": fakes.fred_observations(
                alfred_rows(cpi_vintages(), clip=date(2008, 7, 1))
            ),
        }
    )
    p = FredProvider(http, api_key="k")
    f = p.fetch_frame(spec("fred:DGS10", SeriesKind.YIELD, Frequency.DAILY, "1D"), date(2026, 10, 15))
    assert f["value"].tolist() == [4.10] and f["vintage_date"].iloc[0] == pd.Timestamp("2026-10-16")
    assert "observation_start=2026-10-14" in http.requests[0]
    g = p.fetch_frame(CPI, date(2008, 7, 1))
    assert "realtime_start=2008-07-01" in http.requests[-1] and g["vintage_date"].min() > pd.Timestamp(
        "2008-07-01"
    )


def test_cftc_error_paths() -> None:
    with pytest.raises(DataError):
        parse_cot(json.dumps({"error": True, "message": "bad query"}).encode())
    assert parse_cot(b"[]").empty
    s = spec(
        "cftc:088691:noncomm_net",
        SeriesKind.POSITIONING,
        Frequency.WEEKLY,
        "7D",
        params=[("market", "088691"), ("field", "noncomm_net")],
    )
    assert CftcProvider(FixtureClient({r"6dca-aqww": b"[]"})).fetch_frame(s, date(2026, 1, 1)).empty
    with pytest.raises(DataError):
        CftcProvider(FixtureClient({})).fetch_frame(
            spec(
                "cftc:1:x", SeriesKind.POSITIONING, Frequency.WEEKLY, params=[("market", "1"), ("field", "x")]
            ),
            None,
        )


def test_stooq_yahoo_french_error_paths() -> None:
    with pytest.raises(DataError):
        StooqProvider(FixtureClient({})).fetch_frame(
            spec("stooq:SPY:volume", SeriesKind.PRICE, Frequency.DAILY), None
        )
    with pytest.raises(DataError):
        parse_csv(b"Date,Open\n2026-01-02,1\n")
    y = YahooProvider(FixtureClient({r"chart/SPY": FX / "yahoo_SPY_2024.json"}), today=date(2025, 1, 2))
    with pytest.raises(DataError):
        y.fetch_frame(spec("yahoo:SPY:volume", SeriesKind.PRICE, Frequency.DAILY), None)
    assert y.fetch_frame(spec("yahoo:SPY:split", SeriesKind.SPLIT, Frequency.DAILY), None).empty
    with pytest.raises(DataError):
        FrenchProvider(FixtureClient({})).fetch_frame(
            spec("french:x:y", SeriesKind.RETURN, Frequency.MONTHLY), None
        )
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "no csv")
    with pytest.raises(DataError, match="no CSV"):
        FrenchProvider(FixtureClient({r"X\.zip": buf.getvalue()})).fetch_frame(
            spec(
                "french:x:y",
                SeriesKind.RETURN,
                Frequency.MONTHLY,
                params=[("file", "X.zip"), ("column", "y")],
            ),
            None,
        )
