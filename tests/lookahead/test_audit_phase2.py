"""Look-ahead audit of Phase 2 (docs/AUDIT_phase2_lookahead.md): one test per checklist point.

The Phase-2 harness (`test_modules_lookahead.py`) checks features and modules at month-ends with future
*values* replaced by noise. This file closes the gaps that audit found in that coverage:

* mid-month dates (the running month is a partial month; the daily loop of Phase 3 will ask here),
* future *rows removed* instead of overwritten (a leak through the shape of the store – prefix lengths,
  grid ends – survives a value mutation),
* the engine loop itself: book marks, execution prices, walk-forward choices (never harness-checked).

The invariant is always the same: what is computed at D must be bit-identical with and without the data
that was not knowable at D.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.config.models import CostSpec
from rotationlab.core import registry
from rotationlab.core.clock import MonthEndClock, WeekdayCalendar
from rotationlab.core.types import Frequency, SeriesKind, StrategyState
from rotationlab.data.view import StoreViewFactory, _return_index, asset_roles
from rotationlab.engine.core import Engine, prices_at
from rotationlab.engine.modes import backtest, research_factory
from rotationlab.features import feature
from rotationlab.portfolio.book import Book
from rotationlab.portfolio.combine import SingleStrategy
from rotationlab.portfolio.costs import CostModel
from rotationlab.strategies import build_strategy, build_walkforward, strategy_spec
from rotationlab.strategies.walkforward import WalkForward
from tests.fixtures.toy import Toy, spec
from tests.lookahead.harness import LookaheadHarness
from tests.lookahead.test_modules_lookahead import ASSETS, FEATURE_PARAMS, FEATURE_SERIES

pytestmark = [
    pytest.mark.lookahead,
    pytest.mark.filterwarnings("ignore:overflow encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:divide by zero encountered:RuntimeWarning"),
]

# mid-month dates: stress months and ordinary ones, never a month-end
MID_MONTH = sorted(  # ascending: module state (tranches, walk-forward prev_date) must move forward in time
    [
        date(1979, 1, 10),
        date(1987, 10, 20),
        date(1999, 6, 8),
        date(2008, 9, 15),
        date(2008, 10, 10),
        date(2015, 8, 24),
        date(2020, 3, 16),
    ]
)


def truncate(obs: pd.DataFrame, d: date) -> pd.DataFrame:
    """The store as it could have existed on D: rows observed or published after D are gone."""
    t = pd.Timestamp(d)
    keep = (pd.to_datetime(obs["obs_date"]) <= t) & (pd.to_datetime(obs["vintage_date"]) <= t)
    return obs[keep].reset_index(drop=True)


@pytest.fixture(scope="module")
def reduced(static_store, bundle):
    roles = asset_roles(bundle.universe)
    assets = set(ASSETS) | {"XAU", "XAG", "CASH", "FF_RF"}
    for cfg in bundle.strategies.values():
        assets |= set(cfg.long_history_universe)
    ids = set(FEATURE_SERIES)
    for a in assets:
        for chain in roles[a].values():
            ids |= set(chain)
    obs = static_store.observations()
    return obs[obs["series_id"].isin(ids)].reset_index(drop=True)


@pytest.fixture(scope="module")
def build(catalog, bundle, cal):
    def _build(obs: pd.DataFrame) -> StoreViewFactory:
        return StoreViewFactory(obs, catalog, asset_roles(bundle.universe), cal, chains=bundle.series.chains)

    return _build


def _modules(bundle):
    mods = [build_strategy(bundle, sid, "long_history") for sid in bundle.strategies]
    mods.append(build_strategy(bundle, "precious_metals", "long_history", {"hedge": {"enabled": True}}))
    mods.append(
        build_walkforward(
            bundle, "multi_asset_rotation", "long_history", CostModel(default_bps=7.5).turnover_cost
        )
    )
    return mods


# ---------------------------------------------------------------------------
# Point 1 + 8: mid-month views (partial running month), value mutation
# ---------------------------------------------------------------------------
def test_features_and_modules_pass_the_harness_mid_month(reduced, build, bundle) -> None:
    h = LookaheadHarness(reduced, build, MID_MONTH, ASSETS)
    assert h.check_features(list(registry.features().values()), FEATURE_PARAMS) == []
    assert h.check_strategies(_modules(bundle)) == []


# ---------------------------------------------------------------------------
# Point 1 + 8 + 9: future rows removed (shape of the store), month-ends and mid-month
# ---------------------------------------------------------------------------
def test_features_and_modules_are_invariant_to_removing_future_rows(reduced, build, bundle) -> None:
    dates = [date(1987, 10, 31), date(2008, 9, 30), date(2008, 10, 10), date(2020, 3, 31), date(1999, 6, 8)]
    full = build(reduced)
    metas = list(registry.features().values())
    states = {s.spec.strategy_id: s.initial_state() for s in _modules(bundle)}
    for d in dates:
        cut = build(truncate(reduced, d))
        v_full, v_cut = full.at(d), cut.at(d)
        for m in metas:
            p = FEATURE_PARAMS.get(m.name, {})
            a = m.call(v_full, ASSETS if m.kind == "cross_section" else None, **p)
            b = m.call(v_cut, ASSETS if m.kind == "cross_section" else None, **p)
            if isinstance(a, pd.Series):
                pd.testing.assert_series_equal(a, b, check_exact=True)
            else:
                assert (isinstance(a, float) and np.isnan(a) and np.isnan(b)) or a == b, (m.name, d, a, b)
        for s in _modules(bundle):
            st = states[s.spec.strategy_id]
            p1, s1 = s.propose(v_full, st)
            p2, s2 = s.propose(v_cut, st)
            assert p1 == p2 or _nan_equal(p1, p2), (s.spec.strategy_id, d)
            assert _nan_equal(s1, s2), (s.spec.strategy_id, d)
            states[s.spec.strategy_id] = s1


def _nan_equal(a, b) -> bool:
    import json
    from dataclasses import asdict

    return json.dumps(asdict(a), sort_keys=True, default=str) == json.dumps(
        asdict(b), sort_keys=True, default=str
    )


# ---------------------------------------------------------------------------
# Points 5, 6, 7, 9: the engine loop on a truncated store reproduces the full run up to the cut
# ---------------------------------------------------------------------------
def _same_prefix(full, cut, cut_date: date) -> None:
    """Decisions whose execution day lies on or before the cut must be identical (an execution after the
    cut legitimately trades at a price the truncated store does not have)."""
    done = cut.decisions[cut.decisions["execution"] <= pd.Timestamp(cut_date)]
    n = len(done)
    assert n >= 12
    pd.testing.assert_frame_equal(full.decisions.iloc[:n], done, check_exact=True)
    pd.testing.assert_frame_equal(
        full.weights.reindex(columns=cut.weights.columns).iloc[:n], cut.weights.iloc[:n], check_exact=True
    )
    # the decision at the cut itself (weights) is also identical – only its execution price may differ
    pd.testing.assert_frame_equal(
        full.weights.reindex(columns=cut.weights.columns).iloc[: len(cut.weights)],
        cut.weights,
        check_exact=True,
    )


CUTS = [date(2003, 3, 31), date(2004, 6, 30), date(2005, 9, 30), date(2006, 6, 30), date(2007, 2, 28)]


@pytest.mark.parametrize(
    "sid",
    [
        "us_equity_exposure",
        "us_sector_rotation",
        "multi_asset_rotation",
        "commodity_trend",
        "precious_metals",
        "forecast_portfolio",
    ],
)
def test_engine_run_is_invariant_to_truncating_the_store(reduced, bundle, cal, sid) -> None:
    """One cut tests only the decision *at* the cut for future dependence (the stores agree before it), so
    the store is cut at several dates across the window (second review 2026-10-25)."""
    start, end = date(2001, 12, 31), date(2007, 12, 31)
    gr = bundle.strategies[sid].golden_run
    costs = CostSpec(default_bps=10)
    full_f = research_factory(bundle, reduced, cal, gr.data_from)
    # the decision views are the same under both executions; `same_close` only skips the execution view,
    # so one module covers that path
    executions = ("next_close", "same_close") if sid == "us_equity_exposure" else ("next_close",)
    for execution in executions:
        full = backtest(bundle, full_f, sid, "long_history", start, end, execution, costs)
        for cut_at in CUTS:
            cut_f = research_factory(bundle, truncate(reduced, cut_at), cal, gr.data_from)
            cut = backtest(bundle, cut_f, sid, "long_history", start, cut_at, execution, costs)
            _same_prefix(full, cut, cut_at)


def test_walk_forward_choices_are_invariant_to_truncating_the_store(reduced, bundle, cal) -> None:
    sid = "multi_asset_rotation"
    gr, wf = bundle.strategies[sid].golden_run, bundle.strategies[sid].walkforward
    assert gr is not None and wf is not None
    cut_at, end = date(1983, 6, 30), date(1984, 6, 30)

    def run(obs, until):
        f = research_factory(bundle, obs, cal, gr.data_from)
        cm = CostModel.from_config(gr.costs, bundle.universe)
        strat = build_walkforward(bundle, sid, gr.universe, cm.turnover_cost, gr.params)
        sp = strategy_spec(bundle, sid, gr.universe, gr.params)
        book = Book(str(sp.params["cash"]), cm)
        clock = MonthEndClock(f.cal, gr.start, until)
        return Engine(f, clock, [strat], SingleStrategy(), book, None, "same_close").run()

    full, cut = run(reduced, end), run(truncate(reduced, cut_at), cut_at)
    _same_prefix(full, cut, cut_at)
    choices_full = [c for c in full.states[sid].extra["choices"] if c["date"] <= cut_at.isoformat()]
    assert choices_full == cut.states[sid].extra["choices"]
    assert len(choices_full) >= 1  # the first choice (1982-11-30) lies inside the window
    # the candidates' booked excess returns up to the cut are the same numbers (what the choice is made on)
    ex_full, ex_cut = full.states[sid].extra["excess"], cut.states[sid].extra["excess"]
    for k, v in ex_cut.items():
        assert ex_full[k][: len(v)] == v, k
        assert len(v) >= 100


# ---------------------------------------------------------------------------
# Point 6: next_close prices – a monthly series is priced at its month-end, a daily one at the next close
# ---------------------------------------------------------------------------
def test_next_close_execution_view_reads_no_new_monthly_value() -> None:
    w = Toy().monthly("M", [100.0, 101.0, 102.0, 103.0]).daily("D", [50.0 + i for i in range(90)])
    # a monthly series published with a one-month lag: its month-end value is unknown at D and at E
    w.series(
        "t:L:tr",
        pd.Series([10.0, 11.0, 12.0, 13.0], index=pd.date_range("2000-01-31", periods=4, freq="ME")),
        kind=__import__("rotationlab.core.types", fromlist=["SeriesKind"]).SeriesKind.TOTAL_RETURN,
        lag_days=20,
    )
    w.roles["L"] = {"total_return": ["t:L:tr"]}
    f = w.factory()
    d = date(2000, 2, 29)  # Tuesday; next session 2000-03-01
    e = WeekdayCalendar().next_trading_day(d)
    assert e == date(2000, 3, 1)
    p_d, p_e = prices_at(f.at(d), ["M", "D", "L"]), prices_at(f.at(e), ["M", "D", "L"])
    assert p_e["M"] == p_d["M"] == 101.0  # month-end value, no March value exists yet
    assert p_d["L"] == p_e["L"] == 10.0  # January value: the February value is published 2000-03-20
    s = f.at(e).asset_series("D", "close")
    assert s.index[-1] == pd.Timestamp(e)  # the E close itself is the last known one
    assert p_e["D"] / p_d["D"] == pytest.approx(float(s.iloc[-1] / s.iloc[-2]))  # priced at the E close
    assert p_e["D"] != p_d["D"]


# ---------------------------------------------------------------------------
# Point 7: walk-forward books returns of the *previous* weights, costs of the previous rebalance
# ---------------------------------------------------------------------------
def test_walk_forward_books_previous_weights_times_realised_returns() -> None:
    from tests.unit.test_strategies import Fixed

    levels = [100.0, 110.0, 99.0, 120.0, 130.0]
    w = Toy().monthly("A", levels).cash("RF", 0.01, n=5)
    f = w.factory()
    cand = Fixed(spec("fixed", ["A", "RF"], {"cash": "RF", "hold": "A"}))
    wf = WalkForward(
        spec("w", ["A", "RF"], {"cash": "RF"}),
        {"a": cand},
        refit_every=12,
        min_train=1,
        turnover_cost=lambda a, b: 0.001 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)),
        cash="RF",
    )
    st = wf.initial_state()
    dates = pd.date_range("2000-01-31", periods=5, freq="ME")
    for d in dates:
        _, st = wf.propose(f.at(d.date()), st)
    excess = st.extra["excess"]["a"]
    # first decision: nothing booked; then each month: previous weights (A = 1) × A's return − cost − cash
    assert excess[0] == pytest.approx(levels[1] / levels[0] - 1 - 0.002 - 0.01)  # cost of RF→A (2 legs)
    assert excess[1] == pytest.approx(levels[2] / levels[1] - 1 - 0.0 - 0.01)  # no trade, no cost
    assert excess[2] == pytest.approx(levels[3] / levels[2] - 1 - 0.01)
    assert len(excess) == 4


# ---------------------------------------------------------------------------
# Point 4: the base-100 point of a return index exists only once the first return is known
# ---------------------------------------------------------------------------
def test_return_index_base_appears_with_the_first_return() -> None:
    w = Toy().cash("RF", [0.01, 0.02, 0.03], start="2000-02-29")
    f = w.factory()
    assert f.at(date(2000, 1, 31)).total_return(["RF"], None).empty  # before the first return: nothing
    tr = f.at(date(2000, 2, 29)).total_return(["RF"], None)["RF"]
    assert list(tr.index) == [pd.Timestamp("2000-01-31"), pd.Timestamp("2000-02-29")]
    assert tr.iloc[0] == 100.0 and tr.iloc[1] == pytest.approx(101.0)
    # the reference path agrees with the prefix path
    f.fast = False
    tr_ref = f.at(date(2000, 2, 29)).total_return(["RF"], None)["RF"]
    pd.testing.assert_series_equal(tr, tr_ref, check_exact=True)
    r = pd.Series([0.01], index=pd.to_datetime(["2000-02-29"]))
    assert _return_index(
        r, __import__("rotationlab.core.types", fromlist=["Frequency"]).Frequency.MONTHLY
    ).index[0] == pd.Timestamp("2000-01-31")


# ---------------------------------------------------------------------------
# Point 10: precious metals – the stop reference is the ratio at the entry decision, fixed until the
# position changes sign
# ---------------------------------------------------------------------------
def test_precious_metals_entry_ratio_is_fixed_at_the_sign_change(static_factory, bundle) -> None:
    s = build_strategy(bundle, "precious_metals", "long_history", {"hedge": {"enabled": False}})
    st: StrategyState = s.initial_state()
    seen: list[tuple[date, float, float | None]] = []
    for d in pd.date_range("1976-01-31", "1981-12-31", freq="ME"):
        v = static_factory.at(d.date())
        p, st = s.propose(v, st)
        seen.append((d.date(), p.signals["position"], st.entries.get("ratio_entry")))
    prev_sign, prev_entry = 0.0, None
    flips = 0
    for d, pos, entry in seen:
        sign = np.sign(pos)
        if sign != prev_sign and sign != 0:
            flips += 1
            ratio = float(feature("gs_ratio").call(static_factory.at(d), gold="XAU", silver="XAG"))
            assert entry == ratio, (d, entry, ratio)  # set from the view at D
        elif sign == prev_sign:
            assert entry == prev_entry, d  # unchanged while the sign holds
        prev_sign, prev_entry = sign, entry
    assert flips >= 2


# ---------------------------------------------------------------------------
# Point 1 (characterisation, not a leak): mid-month, the running month is a partial month and rolling
# windows count it as a full observation – the daily loop of Phase 3 must decide how to treat it.
# ---------------------------------------------------------------------------
def test_mid_month_features_see_a_partial_running_month() -> None:
    closes = pd.Series(
        100.0 * np.exp(np.cumsum(np.full(400, 0.001))), index=pd.bdate_range("2000-01-03", periods=400)
    )
    f = Toy().daily("A", closes).factory()
    month_end, mid = date(2001, 5, 31), date(2001, 6, 15)
    tr_end = f.at(month_end).total_return(["A"], "ME")["A"]
    tr_mid = f.at(mid).total_return(["A"], "ME")["A"]
    assert tr_mid.index[-1] == pd.Timestamp(mid) and tr_end.index[-1] == pd.Timestamp(month_end)
    c_mid, c_end = closes.loc[: pd.Timestamp(mid)].iloc[-1], closes.loc[: pd.Timestamp(month_end)].iloc[-1]
    assert tr_mid.iloc[-1] / tr_end.iloc[-1] == pytest.approx(
        c_mid / c_end
    )  # the latest close, not a month-end
    assert len(tr_mid) == len(tr_end) + 1  # the partial month is one more grid row
    # the partial month enters the 12-month volatility as one of the 12 returns
    vol_mid = float(feature("vol_12m").call(f.at(mid), ["A"]).iloc[0])
    r = tr_mid.pct_change().dropna()
    assert vol_mid == pytest.approx(float(r.iloc[-12:].std()))


# ---------------------------------------------------------------------------
# Control: the engine truncation check bites – a module that peeks one month ahead is caught at the cut
# ---------------------------------------------------------------------------
def test_engine_truncation_check_catches_a_peeking_module() -> None:
    from rotationlab.strategies.base import BaseStrategy

    class Peek(BaseStrategy):
        strategy_id = "peek"

        def propose(self, view, state):
            full = view._f._index.full("t:A:tr")  # forbidden: the store beyond the view date
            nxt = full[full.index > pd.Timestamp(view.date)]
            if not len(nxt):
                return self.proposal(view, {}, 1.0, {"up": float("nan")}), state
            up = nxt.iloc[0] > full[full.index <= pd.Timestamp(view.date)].iloc[-1]
            return self.proposal(view, {"A": 1.0 if up else 0.5}, 1.0, {"up": float(up)}), state

    rng = np.random.default_rng(3)
    levels = list(100.0 * np.cumprod(1 + rng.normal(0.005, 0.04, 36)))
    w = Toy().monthly("A", levels).cash("RF", 0.001, n=36)
    obs = pd.concat(w.frames, ignore_index=True)
    cut_at = date(2002, 6, 30)

    def run(frame, until):
        f = StoreViewFactory(frame, w.specs, w.roles, WeekdayCalendar())
        s = Peek(spec("peek", ["A", "RF"], {"cash": "RF"}, warmup=0))
        clock = MonthEndClock(f.cal, date(2000, 6, 30), until)
        return Engine(
            f, clock, [s], SingleStrategy(), Book("RF", CostModel(default_bps=0.0)), None, "same_close"
        ).run()

    full, cut = run(obs, date(2002, 12, 31)), run(truncate(obs, cut_at), cut_at)
    with pytest.raises(AssertionError):
        _same_prefix(full, cut, cut_at)
    # the honest counterpart passes the same check
    from tests.unit.test_strategies import Fixed

    def run_fixed(frame, until):
        f = StoreViewFactory(frame, w.specs, w.roles, WeekdayCalendar())
        s = Fixed(spec("fixed", ["A", "RF"], {"cash": "RF", "hold": "A"}, warmup=0))
        clock = MonthEndClock(f.cal, date(2000, 6, 30), until)
        return Engine(
            f, clock, [s], SingleStrategy(), Book("RF", CostModel(default_bps=0.0)), None, "same_close"
        ).run()

    _same_prefix(run_fixed(obs, date(2002, 12, 31)), run_fixed(truncate(obs, cut_at), cut_at), cut_at)


# ---------------------------------------------------------------------------
# Second review (fresh reader, 2026-10-25): two leaks the audit had missed, now fixed and pinned
# ---------------------------------------------------------------------------
def test_fast_total_return_path_respects_dividend_vintages() -> None:
    """A dividend ingested late (vintage after its ex-date) must not enter the fast total-return level before
    its vintage; the fast path falls back to the vintage-filtering reference path for such series."""
    closes = pd.Series(100.0, index=pd.bdate_range("2000-01-03", periods=60))
    w = Toy().daily("E", closes)
    div = pd.Series([2.0], index=pd.to_datetime(["2000-02-15"]))
    w.series("t:E:div", div, kind=SeriesKind.DIVIDEND, freq=Frequency.DAILY, lag_days=30)  # public 2000-03-16
    w.roles["E"]["dividend"] = ["t:E:div"]
    f = w.factory()
    d = date(2000, 2, 29)
    fast = f.at(d).total_return(["E"], None)["E"]
    f.fast = False
    ref = f.at(d).total_return(["E"], None)["E"]
    pd.testing.assert_series_equal(fast, ref, check_exact=True)
    assert fast.iloc[-1] == 100.0  # no dividend known at D
    f.fast = True
    later = f.at(date(2000, 3, 20)).total_return(["E"], None)["E"]
    assert later.iloc[-1] == pytest.approx(102.0)  # after publication it is in


def test_direction_is_unknown_not_falling_on_missing_data() -> None:
    """`_direction`: NaN > x is False, which once turned a missing month into "falling" for three months."""
    from rotationlab.features.macro import _direction

    s = pd.Series(np.linspace(100.0, 120.0, 24), index=pd.date_range("2000-01-31", periods=24, freq="ME"))
    s.iloc[15] = np.nan
    d = _direction(s, 3)
    assert d.iloc[5:15].eq(1.0).all()  # rising, enough history
    assert (
        d.iloc[15:21].isna().all()
    )  # the gap, the two means containing it, and the comparisons against them
    assert d.iloc[21:].eq(1.0).all()


def test_daily_cash_index_does_not_know_later_special_closings(bundle, catalog, cal) -> None:
    """The month's accrual is spread over its sessions; a closing decided after D (9/11) must not change the
    share accrued by D. At month-end the index equals the monthly one either way."""
    from rotationlab.data.calendar import SPECIAL_CLOSINGS

    y = pd.Series([3.5, 3.4, 3.3], index=pd.to_datetime(["2001-07-31", "2001-08-31", "2001-09-30"]))
    w = Toy().series("t:Y:yield", y, kind=SeriesKind.YIELD, freq=Frequency.MONTHLY)
    w.roles["CASHY"] = {"yield": ["t:Y:yield"]}
    f = StoreViewFactory(pd.concat(w.frames, ignore_index=True), w.specs, w.roles, cal)
    sep4 = f.at(date(2001, 9, 4)).total_return(["CASHY"], None)["CASHY"]
    aug31 = sep4.loc["2001-08-31"]
    n_known = len(cal.trading_days(date(2001, 9, 1), date(2001, 9, 30))) + sum(
        1 for x in SPECIAL_CLOSINGS if x.year == 2001 and x.month == 9
    )
    assert n_known == 19
    assert sep4.iloc[-1] / aug31 == pytest.approx((1 + 3.4 / 1200) ** (1 / 19))
    month_end = f.at(date(2001, 9, 30)).total_return(["CASHY"], None)["CASHY"]
    monthly = f.at(date(2001, 9, 30)).total_return(["CASHY"], "ME")["CASHY"]
    assert month_end.iloc[-1] == pytest.approx(monthly.iloc[-1])


def test_research_factory_cuts_at_the_first_of_the_month(bundle, static_store, cal) -> None:
    obs = static_store.observations()
    obs = obs[obs["series_id"] == "static:french:ff3:RF"]
    for d in (date(1972, 12, 1), date(1972, 12, 15), date(1972, 12, 31)):
        f = research_factory(bundle, obs, cal, d)
        s = f.at(date(1973, 6, 30)).series("static:french:ff3:RF")
        assert s.index[0] == pd.Timestamp("1972-12-31"), d
