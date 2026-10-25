"""End-to-end ingest against simulated providers whose answers change from day to day.

Market world (2024): SPY with dividends, XLK with a 2-for-1 split, Stooq as second source.
Macro world (2004–2009): CPI with real-time vintages from a fake ALFRED (tests/fixtures/build_fixtures.py).
"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest

from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.ingest import run_ingest
from rotationlab.data.providers.fred import FredProvider
from rotationlab.data.providers.http import FixtureClient
from rotationlab.data.providers.stooq import StooqProvider
from rotationlab.data.providers.yahoo import YahooProvider
from rotationlab.data.quality import Status
from rotationlab.data.store import PointInTimeStore
from rotationlab.data.view import StoreViewFactory
from tests.fixtures import fakes
from tests.fixtures.build_fixtures import alfred_rows, cpi_vintages

CAL = NYSECalendar()
SESSIONS = list(CAL.trading_days(date(2024, 1, 2), date(2024, 12, 31)))
SPLIT_DAY = date(2024, 6, 10)


class MarketWorld:
    """Truth for SPY and XLK; `today` controls what the fake servers know."""

    def __init__(self) -> None:
        rng = np.random.default_rng(5)
        self.spy = 470 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, len(SESSIONS))))
        self.xlk = 400 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, len(SESSIONS))))
        self.today = SESSIONS[100]
        self.yahoo_down = False
        self.revise: dict[date, float] = {}
        self.missing: set[date] = set()

    def known(self) -> list[int]:
        return [i for i, d in enumerate(SESSIONS) if d < self.today]

    def yahoo(self, url: str) -> bytes:
        if self.yahoo_down:
            raise ConnectionError("yahoo unreachable")
        q = parse_qs(urlparse(url).query)
        sym = urlparse(url).path.rsplit("/", 1)[1]
        p1 = int(q["period1"][0])
        idx = [
            i
            for i in self.known()
            if fakes._open_ts(SESSIONS[i]) >= p1 - 86400 and SESSIONS[i] not in self.missing
        ]
        days = [SESSIONS[i] for i in idx]
        if sym == "SPY":
            closes = [round(float(self.spy[i]) * self.revise.get(SESSIONS[i], 1.0), 4) for i in idx]
            divs = {d: 1.75 for d in (date(2024, 3, 15), date(2024, 6, 21), date(2024, 9, 20)) if d in days}
            return fakes.yahoo_chart("SPY", days, closes, dividends=divs)
        split_known = self.today > SPLIT_DAY
        closes = [float(self.xlk[i]) / (2.0 if split_known and SESSIONS[i] < SPLIT_DAY else 1.0) for i in idx]
        closes = [c / 2.0 if SESSIONS[i] >= SPLIT_DAY else c for c, i in zip(closes, idx, strict=True)]
        splits = {SPLIT_DAY: (2, 1)} if split_known and SPLIT_DAY in days else None
        return fakes.yahoo_chart("XLK", days, [round(c, 4) for c in closes], splits=splits)

    def stooq(self, url: str) -> bytes:
        q = parse_qs(urlparse(url).query)
        sym = q["s"][0]
        d1 = (
            date.fromisoformat(f"{q['d1'][0][:4]}-{q['d1'][0][4:6]}-{q['d1'][0][6:]}")
            if "d1" in q
            else date(1900, 1, 1)
        )
        idx = [i for i in self.known() if SESSIONS[i] >= d1]
        base = self.spy if sym == "spy.us" else self.xlk / 2.0
        return fakes.stooq_csv([SESSIONS[i] for i in idx], [round(float(base[i]) * 0.98, 4) for i in idx])


SERIES = [
    "yahoo:SPY:close",
    "yahoo:SPY:dividend",
    "yahoo:SPY:split",
    "stooq:SPY:close",
    "yahoo:XLK:close",
    "yahoo:XLK:dividend",
    "yahoo:XLK:split",
    "stooq:XLK:close",
]


@pytest.fixture
def market(bundle, catalog):
    world = MarketWorld()
    store = PointInTimeStore(None)

    def run(today: date, full: bool = False):
        world.today = today
        provs = {
            "yahoo": YahooProvider(FixtureClient({r"finance/chart": world.yahoo}), today=today),
            "stooq": StooqProvider(FixtureClient({r"stooq\.com": world.stooq})),
        }
        return run_ingest(store, bundle, catalog, provs, CAL, today, full=full, only_series=SERIES)

    return world, store, run


def view(store, catalog, bundle, d: date):
    return StoreViewFactory.from_store(store, catalog, bundle.universe, CAL).at(d)


def test_daily_runs_new_rows_revisions_and_blocking_staleness(market, catalog, bundle) -> None:
    world, store, run = market
    d0 = SESSIONS[100]
    rep = run(d0, full=True)
    assert not rep.blocking and rep.totals()["new"] > 300
    assert store.last_obs("yahoo:SPY:close") == SESSIONS[99]

    rep = run(SESSIONS[101])  # one more session
    spy = next(s for s in rep.series if s["series_id"] == "yahoo:SPY:close")
    assert spy["new"] == 1 and spy["since"] != ""  # incremental window

    world.revise = {SESSIONS[99]: 1.02}  # silent +2 % correction of an old close
    rep = run(SESSIONS[102])
    assert any(
        r.check == "revision" and r.status == Status.WARN and r.series_id == "yahoo:SPY:close"
        for r in rep.quality
    )
    before = (
        view(store, catalog, bundle, SESSIONS[101]).series("yahoo:SPY:close").loc[pd.Timestamp(SESSIONS[99])]
    )
    after = (
        view(store, catalog, bundle, SESSIONS[102]).series("yahoo:SPY:close").loc[pd.Timestamp(SESSIONS[99])]
    )
    assert after == pytest.approx(before * 1.02, rel=1e-6)  # both vintages kept, each visible in its time

    world.yahoo_down = True  # Yahoo fails for a week
    rep = run(SESSIONS[106])
    assert any(r.check == "fetch" for r in rep.quality)
    blocking = {r.series_id for r in rep.blocking}
    assert (
        "yahoo:SPY:close" in blocking and "yahoo:SPY:dividend" not in blocking
    )  # only the required close blocks
    v = view(store, catalog, bundle, SESSIONS[106])
    prov = v.provenance("SPY", "close")
    assert (
        prov[-1].series_id == "stooq:SPY:close" and prov[-1].end == SESSIONS[105]
    )  # Stooq bridges the outage
    assert v.close(["SPY"])["SPY"].index[-1] == pd.Timestamp(SESSIONS[105])


def test_weekend_flow_is_on_time_and_late_arrivals_are_dated_on_arrival(market, catalog, bundle) -> None:
    world, store, run = market
    friday = date(2024, 5, 17)
    run(friday, full=True)
    run(date(2024, 5, 20))  # Monday morning: Friday's close arrives
    rows = store.series_rows("yahoo:SPY:close")
    fri = rows[rows["obs_date"] == pd.Timestamp(friday)]
    assert fri["vintage_date"].iloc[0] == pd.Timestamp(friday)  # normal flow keeps the session date
    gap = date(2024, 5, 21)
    world.missing = {gap}  # Yahoo skips Tuesday's session …
    run(date(2024, 5, 23))
    assert pd.Timestamp(gap) not in set(store.series_rows("yahoo:SPY:close")["obs_date"])
    world.missing = set()
    rep = run(date(2024, 6, 3))  # … and delivers it 13 days later
    assert any(r.check == "late_arrival" and r.series_id == "yahoo:SPY:close" for r in rep.quality)
    rows = store.series_rows("yahoo:SPY:close")
    assert rows[rows["obs_date"] == pd.Timestamp(gap)]["vintage_date"].iloc[0] == pd.Timestamp("2024-06-03")
    assert (
        pd.Timestamp(gap)
        not in view(store, catalog, bundle, date(2024, 5, 31)).series("yahoo:SPY:close").index
    )
    assert pd.Timestamp(gap) in view(store, catalog, bundle, date(2024, 6, 3)).series("yahoo:SPY:close").index


def test_split_rebases_history_without_a_fake_jump(market, catalog, bundle) -> None:
    world, store, run = market
    run(date(2024, 6, 3), full=True)
    run(date(2024, 6, 10))  # split takes effect on 06-10, not yet known
    rep = run(date(2024, 6, 11))  # Yahoo now reports the split and re-based history
    assert any(r.check == "revision" and "uniformly by 0.5" in r.detail for r in rep.quality)
    v = view(store, catalog, bundle, date(2024, 6, 11))
    px = v.series("yahoo:XLK:close")
    assert px.loc["2024-01-02"] == pytest.approx(world.xlk[0] / 2, rel=1e-6)  # the whole history re-based
    r = px.pct_change().dropna()
    assert r.abs().max() < 0.08  # no -50 % artefact anywhere
    tr = v.total_return(["XLK"], freq=None)["XLK"].pct_change().dropna()
    assert tr.abs().max() < 0.08
    old = view(store, catalog, bundle, date(2024, 6, 7)).series("yahoo:XLK:close")
    assert old.loc["2024-01-02"] == pytest.approx(world.xlk[0], rel=1e-6)  # the past view keeps the old basis
    # Fable review 2026-10-24: the view AT the split day must not mix the old basis of the history with the
    # new basis of the split-day close (both were learned in the 06-11 run, so both are dated 06-11)
    at_split = view(store, catalog, bundle, date(2024, 6, 10)).series("yahoo:XLK:close")
    assert (
        at_split.index[-1] == pd.Timestamp("2024-06-07") and at_split.pct_change().dropna().abs().max() < 0.08
    )
    assert view(store, catalog, bundle, date(2024, 6, 11)).series("yahoo:XLK:close").index[
        -1
    ] == pd.Timestamp("2024-06-10")


def test_cross_source_check_runs_on_chains(market) -> None:
    world, _, run = market
    rep = run(SESSIONS[60], full=True)
    xs = {r.series_id: r for r in rep.quality if r.check == "cross_source"}
    assert set(xs) == {"yahoo:SPY:close", "yahoo:XLK:close"} and all(
        r.status == Status.OK for r in xs.values()
    )
    world.revise = {SESSIONS[60]: 1.03}  # Yahoo prints a bad close, Stooq does not
    rep = run(SESSIONS[61])
    bad = [r for r in rep.quality if r.check == "cross_source" and r.status == Status.WARN]
    assert [r.series_id for r in bad] == ["yahoo:SPY:close"] and str(SESSIONS[60]) in bad[0].detail


# ---------------------------------------------------------------------------- ALFRED
def alfred_server(today: date):
    world = {m: [(d, v) for d, v in steps if d <= today] for m, steps in cpi_vintages().items()}
    world = {m: s for m, s in world.items() if s}

    def handler(url: str) -> bytes:
        q = parse_qs(urlparse(url).query)
        rs = q["realtime_start"][0]
        clip = None if rs == "1776-07-04" else date.fromisoformat(rs)
        return fakes.fred_observations(alfred_rows(world, clip=clip))

    return handler


def ingest_cpi(store, bundle, catalog, today: date, full: bool = False):
    prov = {"fred": FredProvider(FixtureClient({r"api\.stlouisfed\.org": alfred_server(today)}), api_key="k")}
    return run_ingest(store, bundle, catalog, prov, CAL, today, full=full, only_series=["fred:CPIAUCSL"])


def test_acceptance_cpi_as_known_on_2008_06_30(bundle, catalog) -> None:
    """Phase 1 acceptance (docs/ARCHITECTURE.md §12): the view returns the value known at the time."""
    store = PointInTimeStore(None)
    ingest_cpi(store, bundle, catalog, date(2009, 12, 31), full=True)
    v = view(store, catalog, bundle, date(2008, 6, 30))
    s = v.series("fred:CPIAUCSL")
    may = cpi_vintages()[date(2008, 5, 1)]
    assert s.index[-1] == pd.Timestamp("2008-05-31")
    assert s.iloc[-1] == may[0][1]  # first release of 2008-06-15 …
    latest = view(store, catalog, bundle, date(2009, 12, 31)).series("fred:CPIAUCSL").loc["2008-05-31"]
    assert latest == may[-1][1] and latest != s.iloc[-1]  # … not today's revised value
    assert view(store, catalog, bundle, date(2008, 6, 14)).series("fred:CPIAUCSL").index[-1] == pd.Timestamp(
        "2008-04-30"
    )
    jan07 = view(store, catalog, bundle, date(2008, 2, 19)).series("fred:CPIAUCSL").loc["2007-01-31"]
    jan07_rev = view(store, catalog, bundle, date(2008, 2, 20)).series("fred:CPIAUCSL").loc["2007-01-31"]
    assert (
        jan07 == cpi_vintages()[date(2007, 1, 1)][0][1]
        and jan07_rev == cpi_vintages()[date(2007, 1, 1)][1][1]
    )
    # history before the archive start is available through the backfill at the lag-model date
    assert v.series("fred:CPIAUCSL").index[0] == pd.Timestamp("2004-01-31")


def test_incremental_alfred_equals_full_ingest(bundle, catalog) -> None:
    inc, full = PointInTimeStore(None), PointInTimeStore(None)
    for today in (
        date(2007, 3, 1),
        date(2007, 11, 1),
        date(2008, 7, 1),
        date(2009, 3, 1),
        date(2009, 12, 31),
    ):
        ingest_cpi(inc, bundle, catalog, today)
    ingest_cpi(full, bundle, catalog, date(2009, 12, 31), full=True)
    for d in pd.date_range("2004-01-31", "2009-12-31", freq="15D"):
        a = view(inc, catalog, bundle, d.date()).series("fred:CPIAUCSL")
        b = view(full, catalog, bundle, d.date()).series("fred:CPIAUCSL")
        pd.testing.assert_series_equal(a, b, obj=f"as of {d.date()}")


def test_quarantine_keeps_bad_rows_out(bundle, catalog) -> None:
    def bad_yahoo(url: str) -> bytes:
        days = SESSIONS[:5]
        return fakes.yahoo_chart("SPY", days, [470.0, 471.0, -1.0, 472.0, 473.0])

    store = PointInTimeStore(None)
    provs = {"yahoo": YahooProvider(FixtureClient({r"finance/chart": bad_yahoo}), today=SESSIONS[5])}
    rep = run_ingest(
        store, bundle, catalog, provs, CAL, SESSIONS[5], full=True, only_series=["yahoo:SPY:close"]
    )
    assert any(r.check == "schema" and r.status == Status.BLOCKING for r in rep.quality)
    assert len(store.series_rows("yahoo:SPY:close")) == 4
    q = store.read_log("quarantine")
    assert len(q) == 1 and q["value"].iloc[0] == -1.0


def test_small_revisions_add_up_to_a_cluster_warning(market) -> None:
    world, _, run = market
    run(SESSIONS[100], full=True)
    for k in range(1, 4):  # three days in a row Yahoo nudges two old closes by 0.1 %
        world.revise = {SESSIONS[90 + 2 * k]: 1.001, SESSIONS[91 + 2 * k]: 1.001}
        rep = run(SESSIONS[100 + k])
    clusters = [r for r in rep.quality if r.check == "revision_cluster"]
    assert [r.series_id for r in clusters] == ["yahoo:SPY:close"]
    assert not any(
        r.check == "revision" and r.status == Status.WARN for r in rep.quality
    )  # each one is small
