"""Sleeve allocator v2 (ADR 057/058): rank weights, availability, risk parity, the vol target on the long book with
the overlay outside it, idle budgets, caps before the trend filter, band, the passive baseline, the daily-data
guard and look-ahead – each on a toy where the answer is known."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.errors import ConfigError
from rotationlab.core.types import SeriesKind, StrategyState
from rotationlab.data.view import StoreViewFactory
from rotationlab.features import feature
from rotationlab.strategies.sleeve_allocator_v2 import (
    SleeveAllocatorV2,
    long_leg_weights,
    long_short_weights,
    rank_offsets,
)
from tests.fixtures.toy import Toy, spec
from tests.lookahead.harness import mutate_future

N_DAYS = 760  # ≈ 35 months of sessions: 24 monthly returns for the EWMA plus the 13-month windows
START = "2000-01-03"


def _walk(rng: np.random.Generator, drift: float, vol: float, n: int) -> list[float]:
    return list(100 * np.cumprod(1 + rng.normal(drift, vol, n)))


def world(seed: int = 7, pm_drift: float = 0.0004) -> Toy:
    rng = np.random.default_rng(seed)
    w = Toy()
    for i, (d, v) in enumerate(
        [
            (0.0008, 0.010),
            (0.0006, 0.012),
            (0.0004, 0.009),
            (0.0002, 0.011),
            (0.0000, 0.010),
            (-0.0008, 0.013),
        ]
    ):
        w.daily(f"US{i}", _walk(rng, d, v, N_DAYS), start=START)
    months = pd.date_range("1999-12-31", periods=36, freq="ME")
    for i, (d, v) in enumerate(
        [(0.012, 0.05), (0.010, 0.06), (0.006, 0.04), (0.004, 0.05), (0.002, 0.07), (-0.010, 0.05)]
    ):
        w.monthly(f"CT{i}", pd.Series(_walk(rng, d, v, len(months)), index=months))
    w.daily("B2Y", _walk(rng, 0.0002, 0.0015, N_DAYS), start=START)
    w.daily("B10Y", _walk(rng, 0.0003, 0.0050, N_DAYS), start=START)
    days = pd.bdate_range(START, periods=N_DAYS)
    for i, (d, v, y) in enumerate(
        [
            (0.0003, 0.006, 5.0),
            (0.0002, 0.006, 4.0),
            (0.0, 0.007, 3.0),
            (-0.0001, 0.006, 2.0),
            (-0.0002, 0.007, 1.0),
            (0.0001, 0.006, 0.5),
        ]
    ):
        w.daily(f"FX{i}", _walk(rng, d, v, N_DAYS), start=START)
        w.series(
            f"t:FX{i}:y",
            pd.Series(y, index=pd.date_range("1999-12-31", periods=36, freq="ME")),
            SeriesKind.YIELD,
        )
    w.daily("G", _walk(rng, pm_drift, 0.010, N_DAYS), start=START)
    w.daily("S", _walk(rng, pm_drift, 0.018, N_DAYS), start=START)
    w.cash("RF", 0.002, n=36, start="1999-12-31")
    _ = days
    return w


SLEEVES = {
    "EQ_US": {
        "instruments": [f"US{i}" for i in range(6)],
        "mode": "long_xs",
        "families": {"mom_12_1": 1.0},
        "vol": "daily",
        "budget": 0.125,
        "group": "physical",
    },
    "EQ_INTL": {
        "instruments": [f"CT{i}" for i in range(6)],
        "mode": "long_xs",
        "families": {"mom_12_1": 1.0},
        "vol": "monthly",
        "budget": 0.125,
        "group": "physical",
    },
    "FI": {
        "instruments": ["B2Y", "B10Y"],
        "mode": "long_ts",
        "vol": "daily",
        "budget": 0.25,
        "group": "rates",
    },
    "FX": {
        "instruments": [f"FX{i}" for i in range(6)],
        "mode": "long_short_xs",
        "families": {"carry_yield": 1.0, "mom_12_1": 1.0},
        "vol": "daily",
        "budget": 0.25,
        "group": "overlay",
    },
    "PM": {"instruments": ["G", "S"], "mode": "long_ts", "vol": "daily", "budget": 0.25, "group": "physical"},
}
PARAMS = {
    "cash": "RF",
    "sleeves": SLEEVES,
    "feature_params": {
        "carry_yield": {"spec": {f"FX{i}": {"kind": "yield", "series": f"t:FX{i}:y"} for i in range(6)}}
    },
    "vol_target": 0.10,
    "caps": {"physical": 1.0, "physical_plus_rates": 1.5, "overlay_gross": 0.5},
    "band": 0.02,
}
UNIVERSE = [a for s in SLEEVES.values() for a in s["instruments"]] + ["RF"]
D = date(2002, 11, 30)  # calendar month-end: the monthly toy series are labelled with it


def build(**over: object) -> SleeveAllocatorV2:
    return SleeveAllocatorV2(spec("sleeve_allocator_v2", UNIVERSE, {**PARAMS, **over}, warmup=26))


def test_rank_helpers() -> None:
    s = pd.Series({f"a{i}": float(i) for i in range(10)})
    off = rank_offsets(s)
    assert off.tolist() == [i - 4.5 for i in range(10)]
    vol = pd.Series(0.1, index=s.index)
    w = long_leg_weights(s, vol)
    assert list(w.index) == [f"a{i}" for i in range(5, 10)]
    assert w.tolist() == pytest.approx([x / 12.5 for x in (0.5, 1.5, 2.5, 3.5, 4.5)])
    w2 = long_leg_weights(s, vol.where(s.index != "a9", 0.2))  # double vol halves the raw weight
    assert w2["a9"] / w2["a8"] == pytest.approx((4.5 / 0.2) / (3.5 / 0.1))
    ls = long_short_weights(pd.Series({"x": 3.0, "y": 1.0, "z": 2.0, "q": 0.0}))
    assert ls.sum() == pytest.approx(0.0) and ls.abs().sum() == pytest.approx(1.0)
    assert ls["x"] > ls["z"] > 0 > ls["y"] > ls["q"]


def test_configuration_errors() -> None:
    bad = {**SLEEVES, "FX": {**SLEEVES["FX"], "group": "physical"}}
    with pytest.raises(ValueError, match="overlay"):
        build(sleeves=bad)
    bad = {**SLEEVES, "PM": {**SLEEVES["PM"], "instruments": ["G"]}}
    with pytest.raises(ValueError, match="cover exactly"):
        build(sleeves=bad)
    bad = {**SLEEVES, "EQ_US": {**SLEEVES["EQ_US"], "families": {}}}
    with pytest.raises(ValueError, match="needs families"):
        build(sleeves=bad)
    with pytest.raises(ValueError, match="physical_plus_rates"):
        build(caps={"physical": 1.0, "physical_plus_rates": 0.5, "overlay_gross": 0.5})
    with pytest.raises(ValueError, match="system limit"):
        build(caps={"physical": 1.0, "physical_plus_rates": 1.5, "overlay_gross": 1.0})


def test_the_rule_step_by_step() -> None:
    v = world().factory().at(D)
    strat = build()
    prop, state = strat.propose(v, strat.initial_state())
    assert not prop.warmup
    sig, w = prop.signals, dict(prop.weights)
    assert sig["sleeves_active"] == 5.0 and all(
        sig[f"available:{k}"] == len(s["instruments"]) for k, s in SLEEVES.items()
    )
    # EQ_US: only the top half by 12-1 momentum, rank-weighted and risk-scaled, minus trend-filtered names
    sc = pd.Series({a: sig[f"score:{a}"] for a in SLEEVES["EQ_US"]["instruments"]})
    top = set(sc.sort_values().index[3:])
    assert set(a for a in SLEEVES["EQ_US"]["instruments"] if a in w) <= top
    # the currency overlay is dollar-neutral before the band and within its gross cap
    fx = {a: w.get(a, 0.0) for a in SLEEVES["FX"]["instruments"]}
    assert (
        sum(fx.values()) == pytest.approx(0.0, abs=1e-12) and sum(abs(x) for x in fx.values()) <= 1.0 + 1e-12
    )
    assert fx["FX0"] > 0 > fx["FX4"]  # highest carry long, low carry short (momentum is flat in the toy)
    # vol target on the unfiltered book; caps hold
    assert sig["k"] == pytest.approx(0.10 / sig["book_vol_unfiltered"])
    assert sig["gross_physical"] <= 1.0 + 1e-12 and sig["gross_physical"] + sig["gross_rates"] <= 1.5 + 1e-12
    assert dict(state.extra["targets"]) == pytest.approx(w)


def test_trend_filter_leaves_the_share_in_cash() -> None:
    """Falling metals: PM is active but filtered to zero; the other sleeves are NOT scaled up to fill it."""
    v = world(pm_drift=-0.0015).factory().at(D)
    on, _ = build().propose(v, StrategyState(build().spec.strategy_id))
    off, _ = build(ts_filter=False).propose(v, StrategyState(build().spec.strategy_id))
    assert on.signals["sleeves_active"] == 5.0 and "G" not in on.weights and "S" not in on.weights
    assert any("PM: 12-month excess return" in n for n in on.notes)
    assert on.signals["cap_rates"] == 1.0  # the bond-leverage cap binds in this toy …
    held = [a for a in ("B2Y", "B10Y") if a in on.weights]  # … bonds the filter keeps (B10Y trends down here)
    assert held  # … equal those without the filter: caps come before the filter (ADR 058, finding 1)
    for a in held:
        assert on.weights[a] == pytest.approx(off.weights[a])
    assert (
        on.signals["gross_rates"] <= off.signals["gross_rates"] + 1e-12
    )  # freed physical room is never refilled
    assert on.signals["k"] == pytest.approx(off.signals["k"])  # the target is set on the unfiltered book


def test_passive_baseline_sees_the_same_instruments() -> None:
    v = world().factory().at(D)
    main, _ = build().propose(v, StrategyState(build().spec.strategy_id))
    sleeves_b1 = {**SLEEVES, "FX": {**SLEEVES["FX"], "budget": 0.0}}
    b1, _ = build(xs_select=False, ts_filter=False, sleeves=sleeves_b1).propose(
        v, StrategyState(build().spec.strategy_id)
    )
    for k in ("EQ_US", "EQ_INTL", "FI", "PM"):
        assert b1.signals[f"available:{k}"] == main.signals[f"available:{k}"]
    assert all(a not in b1.weights for a in SLEEVES["FX"]["instruments"])
    held = [a for a in SLEEVES["EQ_US"]["instruments"] if a in b1.weights]
    assert held == SLEEVES["EQ_US"]["instruments"]  # every instrument, inverse volatility
    inv = pd.Series({a: 1 / feature("vol_ewma_d").call(v, [a]).iloc[0] for a in held})
    got = pd.Series({a: b1.weights[a] for a in held})
    assert (got / got.sum()).to_numpy() == pytest.approx((inv / inv.sum()).to_numpy())


def test_caps_bind_and_band_holds() -> None:
    v = world().factory().at(D)
    tight, _ = build(caps={"physical": 0.3, "physical_plus_rates": 0.5, "overlay_gross": 0.2}).propose(
        v, StrategyState(build().spec.strategy_id)
    )
    s = tight.signals
    assert s["gross_physical"] <= 0.3 + 1e-12 and s["gross_physical"] + s["gross_rates"] <= 0.5 + 1e-12
    assert s["gross_overlay"] <= 0.2 + 1e-12 and s["cap_physical"] + s["cap_rates"] + s["cap_overlay"] >= 1.0
    strat = build()
    first, state = strat.propose(v, strat.initial_state())
    again, _ = strat.propose(v, state)
    assert dict(again.weights) == pytest.approx(dict(first.weights)) and any("band" in n for n in again.notes)
    big = {k: 3 * x for k, x in dict(state.extra["targets"]).items()}  # kept targets beyond every cap
    capped, _ = strat.propose(v, StrategyState(state.strategy_id, extra={"targets": big}))
    assert capped.signals["gross"] <= 2.0 + 1e-9


def test_daily_sleeve_with_monthly_prices_is_a_configuration_error() -> None:
    v = world().factory().at(D)
    bad = {**SLEEVES, "EQ_INTL": {**SLEEVES["EQ_INTL"], "vol": "daily"}}
    with pytest.raises(ConfigError, match="median spacing"):
        build(sleeves=bad).propose(v, StrategyState(build().spec.strategy_id))


def test_warmup_and_no_lookahead() -> None:
    w = world()
    strat = build()
    early, _ = strat.propose(w.factory().at(date(2001, 6, 30)), strat.initial_state())
    assert early.warmup and early.weights == {}
    obs = pd.concat(w.frames, ignore_index=True)

    def factory(o: pd.DataFrame) -> StoreViewFactory:
        return StoreViewFactory(o, w.specs, w.roles, WeekdayCalendar(), chains=w.chains)

    clean = factory(obs)
    state = strat.initial_state()
    for i, d in enumerate([date(2002, 3, 31), date(2002, 6, 30), date(2002, 9, 30), D]):
        p1, s1 = strat.propose(clean.at(d), state)
        p2, s2 = strat.propose(factory(mutate_future(obs, d, seed=i)).at(d), state)
        dump = lambda p: json.dumps(asdict(p), default=str, sort_keys=True)  # noqa: E731
        assert dump(p1) == dump(p2) and s1.to_json() == s2.to_json()
        state = s1


def test_an_exit_always_trades_and_ties_never_follow_float_noise() -> None:
    """Second review of round 3: a name dropped by selection or filter must leave even inside the band, and an
    exact tie (two families that disagree) is resolved by configuration order, not by a 1e-16 residue."""
    from rotationlab.strategies.sleeve_allocator_v2 import rank_offsets

    v = world().factory().at(D)
    strat = build()
    first, state = strat.propose(v, strat.initial_state())
    dropped = next(a for a in SLEEVES["EQ_US"]["instruments"] if a not in first.weights)
    stale = {**dict(state.extra["targets"]), dropped: 0.01}  # an old small position, inside the 2 pp band
    again, _ = strat.propose(v, StrategyState(state.strategy_id, extra={"targets": stale}))
    assert dropped not in again.weights
    # a tie goes to the instrument earlier in the configuration, as in round 3 (ADR 058)
    assert rank_offsets(pd.Series({"x": 2.2e-16, "y": -1.1e-16})).tolist() == [0.5, -0.5]
    assert rank_offsets(pd.Series({"x": 1.0, "y": 1.0, "z": 0.0})).tolist() == [1.0, 0.0, -1.0]
    assert np.isfinite(first.signals["book_vol_predicted"]) and first.signals["book_vol_predicted"] > 0


def test_the_overlay_is_sized_with_the_long_books_target_and_does_not_move_it() -> None:
    """ADR 058 d: σ_book and k come from the long sleeves; the currency overlay is sized with the same k but does
    not enter σ_book, so the long book – and B1 – look the same with or without it."""
    v = world().factory().at(D)
    with_fx, _ = build(ts_filter=False).propose(v, StrategyState(build().spec.strategy_id))
    no_fx = {**SLEEVES, "FX": {**SLEEVES["FX"], "budget": 0.0}}
    without, _ = build(ts_filter=False, sleeves=no_fx).propose(v, StrategyState(build().spec.strategy_id))
    assert with_fx.signals["k"] == pytest.approx(without.signals["k"])
    assert with_fx.signals["book_vol_unfiltered"] == pytest.approx(without.signals["book_vol_unfiltered"])
    for a in [*SLEEVES["EQ_US"]["instruments"], *SLEEVES["FI"]["instruments"], "G", "S"]:
        assert with_fx.weights.get(a, 0.0) == pytest.approx(without.weights.get(a, 0.0))
    fx = sum(abs(with_fx.weights.get(a, 0.0)) for a in SLEEVES["FX"]["instruments"])
    raw = (
        with_fx.signals["k"] * 0.25 / with_fx.signals["sleeve_vol:FX"]
    )  # k · budget / σ, Σ|w| of the basket = 1
    assert fx == pytest.approx(min(raw, 0.5))
    # the overlay alone (no long sleeve has a budget): the target is set on the overlay itself
    alone = {k: {**s, "budget": 0.25 if k == "FX" else 0.0} for k, s in SLEEVES.items()}
    solo, _ = build(sleeves=alone).propose(v, StrategyState(build().spec.strategy_id))
    gross = sum(abs(x) for x in solo.weights.values())
    assert gross == pytest.approx(min(0.10 / solo.signals["sleeve_vol:FX"], 0.5))


def test_an_idle_budget_stays_in_cash() -> None:
    """ADR 058 d: a long sleeve with a budget but no active basket keeps its risk budget in cash – σ_book counts
    budget² as an uncorrelated slot, so k does not hand it to the others (switching the sleeve off does)."""
    v = world().factory().at(D)
    sleeves = {k: dict(s) for k, s in SLEEVES.items()}
    uni = [a for k, s in sleeves.items() if k != "EQ_INTL" for a in s["instruments"]] + ["RF"]
    sleeves["EQ_INTL"] = {**sleeves["EQ_INTL"], "instruments": []}  # never active (ADR 057 h)
    idle = SleeveAllocatorV2(spec("sleeve_allocator_v2", uni, {**PARAMS, "sleeves": sleeves}, warmup=26))
    off_sleeves = {**sleeves, "EQ_INTL": {**sleeves["EQ_INTL"], "budget": 0.0}}
    off = SleeveAllocatorV2(spec("sleeve_allocator_v2", uni, {**PARAMS, "sleeves": off_sleeves}, warmup=26))
    a, _ = idle.propose(v, StrategyState(idle.spec.strategy_id))
    b, _ = off.propose(v, StrategyState(off.spec.strategy_id))
    assert a.signals["active:EQ_INTL"] == 0.0 and a.signals["idle_budget"] == pytest.approx(0.125)
    assert a.signals["book_vol_unfiltered"] ** 2 == pytest.approx(
        b.signals["book_vol_unfiltered"] ** 2 + 0.125**2
    )
    assert a.signals["k"] < b.signals["k"]
