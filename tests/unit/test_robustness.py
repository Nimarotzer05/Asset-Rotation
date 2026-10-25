"""Second macro source (BLS) in chains, revision clusters, data-health report, log schema evolution."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from rotationlab.config.models import QualityConfig, SeriesCatalogConfig
from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.errors import DataError
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data import quality as q
from rotationlab.data.catalog import build_catalog, check_catalog
from rotationlab.data.health import health_report, health_tables
from rotationlab.data.providers.bls import BlsProvider, parse_bls
from rotationlab.data.providers.http import FixtureClient
from rotationlab.data.store import PointInTimeStore
from rotationlab.data.view import StoreViewFactory
from tests.fixtures import fakes

CPI_BLS = SeriesSpec(
    SeriesId("bls:CUSR0000SA0"), "bls", "CUSR0000SA0", SeriesKind.MACRO, Frequency.MONTHLY, lag="1M"
)


def test_bls_parser_and_provider() -> None:
    raw = fakes.bls_json(
        {"CUSR0000SA0": [(2026, 7, "332.813"), (2026, 8, "334.131"), (2026, 9, "-"), (2025, 13, "320.0")]}
    )
    s = parse_bls(raw, "CUSR0000SA0")
    assert list(s.index) == [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")] and s.iloc[-1] == 334.131
    with pytest.raises(DataError):
        parse_bls(fakes.bls_json({}, status="REQUEST_NOT_PROCESSED"), "CUSR0000SA0")
    with pytest.raises(DataError, match="missing"):
        parse_bls(fakes.bls_json({"OTHER": []}), "CUSR0000SA0")
    http = FixtureClient({r"api\.bls\.gov": raw})
    f = BlsProvider(http, api_key="key", today=date(2026, 10, 24)).fetch_frame(CPI_BLS, None)
    assert f["obs_date"].tolist() == [pd.Timestamp("2026-07-31"), pd.Timestamp("2026-08-31")]
    assert f["vintage_date"].iloc[-1] == pd.Timestamp("2026-09-30")
    payload = json.loads(http.requests[0].split("#", 1)[1])
    assert payload == {
        "endyear": "2026",
        "registrationkey": "key",
        "seriesid": ["CUSR0000SA0"],
        "startyear": "2017",
    }
    assert (
        BlsProvider(FixtureClient({r"bls": fakes.bls_json({"CUSR0000SA0": []})}))
        .fetch_frame(CPI_BLS, date(2026, 1, 1))
        .empty
    )


def test_macro_chain_bridges_a_fred_outage(bundle) -> None:
    fred = pd.DataFrame(
        {
            "series_id": "fred:CPIAUCSL",
            "obs_date": pd.to_datetime(["2026-06-30", "2026-07-31"]),
            "vintage_date": pd.to_datetime(["2026-07-15", "2026-08-13"]),
            "value": [332.568, 332.813],
        }
    )
    bls = pd.DataFrame(
        {
            "series_id": "bls:CUSR0000SA0",
            "obs_date": pd.to_datetime(["2026-07-31", "2026-08-31"]),
            "vintage_date": pd.to_datetime(["2026-08-31", "2026-09-30"]),
            "value": [332.9, 334.131],
        }
    )
    cat = build_catalog(bundle)
    f = StoreViewFactory(pd.concat([fred, bls]), cat, {}, WeekdayCalendar(), chains=bundle.series.chains)
    v = f.at(date(2026, 9, 30))
    s = v.series("macro:CPI")
    assert s.tolist() == [332.568, 332.813, 334.131]  # July stays FRED's, August comes from BLS
    assert [p.series_id for p in v.chain_provenance("macro:CPI")] == ["fred:CPIAUCSL", "bls:CUSR0000SA0"]
    assert v.last_obs("macro:CPI") == date(2026, 8, 31)
    assert f.at(date(2026, 9, 29)).series("macro:CPI").index[-1] == pd.Timestamp(
        "2026-07-31"
    )  # BLS lag respected


def test_chain_config_is_validated(bundle) -> None:
    with pytest.raises(ValueError):
        SeriesCatalogConfig(chains={"cpi": ["fred:CPIAUCSL", "bls:CUSR0000SA0"]})
    with pytest.raises(ValueError):
        SeriesCatalogConfig(chains={"macro:X": ["fred:CPIAUCSL"]})
    bad = bundle.model_copy(
        update={
            "series": bundle.series.model_copy(
                update={
                    "chains": {
                        "macro:BAD": ["fred:CPIAUCSL", "fred:DGS10"],
                        "macro:GONE": ["fred:CPIAUCSL", "bls:NOPE"],
                    }
                }
            )
        }
    )
    problems = " | ".join(check_catalog(bad, build_catalog(bad)))
    assert (
        "chain macro:BAD: chain mixes frequencies" in problems
        and "chain macro:GONE: series bls:NOPE" in problems
    )
    assert check_catalog(bundle, build_catalog(bundle)) == []


def test_revision_cluster() -> None:
    spec = SeriesSpec(SeriesId("yahoo:SPY:close"), "yahoo", "SPY:close", SeriesKind.PRICE, Frequency.DAILY)
    cfg = QualityConfig()
    log = pd.DataFrame(
        {
            "series_id": "yahoo:SPY:close",
            "run_date": ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-02"],
            "revised": [2, 2, 1, 40],
            "rebased": [False, False, False, False],
        }
    )
    r = q.revision_cluster(spec, log, date(2026, 10, 22), cfg)
    assert (
        r is not None and r.status == q.Status.WARN and "5 revisions" in r.detail
    )  # the old burst is outside the window
    assert (
        q.revision_cluster(spec, log.assign(rebased=[True, False, False, False]), date(2026, 10, 22), cfg)
        is None
    )
    assert q.revision_cluster(spec, log.assign(revised=[1, 1, 1, 0]), date(2026, 10, 22), cfg) is None
    macro = SeriesSpec(SeriesId("fred:X"), "fred", "X", SeriesKind.MACRO, Frequency.MONTHLY)
    assert q.revision_cluster(macro, log, date(2026, 10, 22), cfg) is None  # statistics are revised by design
    assert q.revision_cluster(spec, pd.DataFrame(), date(2026, 10, 22), cfg) is None
    assert q.revision_cluster(spec, log.assign(series_id="other"), date(2026, 10, 22), cfg) is None


def test_health_report_and_log_schema_evolution(tmp_path) -> None:
    s = PointInTimeStore(tmp_path / "s")
    s.append_log(
        "ingest_log",
        pd.DataFrame(
            {
                "ingested_at": ["2026-10-20T06:30:00Z"],
                "run_date": ["2026-10-20"],
                "series_id": ["yahoo:SPY:close"],
                "provider": ["yahoo"],
                "fetched": [10],
                "new": [1],
                "revised": [0],
                "rejected": [0],
                "error": [""],
                "seconds": [0.4],
            }
        ),
    )
    s.append_log(
        "ingest_log",
        pd.DataFrame(
            {
                "ingested_at": ["2026-10-21T06:30:00Z"],
                "run_date": ["2026-10-21"],
                "series_id": ["yahoo:SPY:close"],
                "provider": ["yahoo"],
                "fetched": [0],
                "new": [0],
                "revised": [0],
                "rejected": [0],
                "late": [0],
                "rebased": [False],
                "error": ["ConnectionError: down"],
                "seconds": [3.0],
            }
        ),
    )
    log = s.read_log("ingest_log")
    assert len(log) == 2 and "late" in log.columns  # the log gained a column: rewritten
    s.append_log(
        "quality_log",
        q.to_frame(
            [
                q.QualityResult("staleness", "yahoo:SPY:close", q.Status.BLOCKING, "3 behind"),
                q.QualityResult("gaps", "yahoo:SPY:close", q.Status.OK, ""),
            ],
            "2026-10-21T06:30:00Z",
        ),
    )
    t = health_tables(s, date(2026, 10, 22), days=30)
    assert t["providers"].loc["yahoo", "runs"] == 2 and t["providers"].loc["yahoo", "fetch_errors"] == 1
    assert t["checks"].loc["staleness", "blocking"] == 1 and list(t["open"].index) == ["yahoo:SPY:close"]
    md = health_report(s, date(2026, 10, 22), days=30)
    assert "## Provider" in md and "staleness" in md and "Offen im letzten Lauf" in md
    empty = health_report(PointInTimeStore(None), date(2026, 10, 22))
    assert "_keine Einträge_" in empty
