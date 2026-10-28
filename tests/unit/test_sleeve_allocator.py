"""Sleeve allocator (ADR 054): selection, trend filter, inverse-vol baskets, risk parity, caps and the band –
each on a toy where the answer can be computed by hand."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.types import SeriesKind, StrategyState
from rotationlab.features import feature
from rotationlab.features.price import ewma_vol
from rotationlab.strategies.sleeve_allocator import SleeveAllocator, inverse_vol_weights, select_top_half
from tests.fixtures.toy import Toy, geometric, spec

N = 40  # months: 24 returns for the EWMA + 13 for the momentum window, with room to spare


def world(seed: int = 5) -> Toy:
    """EQ: four instruments with different drifts and volatilities; FI: two with yields; PM: two; cash RF.
    E4 trends down (12-month excess return < 0), everything else up."""
    rng = np.random.default_rng(seed)
    w = Toy()
    for name, drift, vol in [
        ("E1", 0.012, 0.03),
        ("E2", 0.008, 0.06),
        ("E3", 0.004, 0.04),
        ("E4", -0.02, 0.05),
    ]:
        r = rng.normal(drift, vol, N)
        w.monthly(name, list(100 * np.cumprod(1 + r)))
    w.monthly("B1", geometric(100, 0.004, N)).monthly("B2", geometric(100, 0.006, N))
    idx = w.frames[-1]["obs_date"]
    w.series("t:B1:y", pd.Series(3.0, index=idx), SeriesKind.YIELD)
    w.series("t:B2:y", pd.Series(5.0, index=idx), SeriesKind.YIELD)
    w.monthly("P1", geometric(100, 0.01, N)).monthly(
        "P2", list(100 * np.cumprod(1 + rng.normal(0.005, 0.08, N)))
    )
    w.cash("RF", 0.001, n=N)
    return w


PARAMS = {
    "cash": "RF",
    "sleeves": {
        "EQ": {"instruments": ["E1", "E2", "E3", "E4"], "families": {"mom_12_1": 1.0}, "budget": 1 / 3},
        "FI": {
            "instruments": ["B1", "B2"],
            "families": {"mom_12_1": 1.0, "carry_yield": 1.0},
            "budget": 1 / 3,
        },
        "PM": {"instruments": ["P1", "P2"], "families": {"mom_12_1": 1.0}, "budget": 1 / 3},
    },
    "feature_params": {
        "carry_yield": {
            "spec": {"B1": {"kind": "yield", "series": "t:B1:y"}, "B2": {"kind": "yield", "series": "t:B2:y"}}
        }
    },
    "half_life": 12,
    "min_obs": 24,
    "vol_floor": 0.02,
    "vol_target": 0.10,
    "max_exposure": 1.5,
    "max_sleeve": 1.0,
    "band": 0.02,
}
UNIVERSE = ["E1", "E2", "E3", "E4", "B1", "B2", "P1", "P2", "RF"]


def build(**over: object) -> SleeveAllocator:
    return SleeveAllocator(spec("sleeve_allocator", UNIVERSE, {**PARAMS, **over}, warmup=30))


def test_helpers_select_the_top_half_and_normalise_inverse_vol() -> None:
    s = pd.Series({"a": 1.0, "b": 0.5, "c": -0.2, "d": 0.9, "e": 0.0})
    assert select_top_half(s) == ["a", "b", "d"]  # ⌈5/2⌉ = 3, configuration order
    assert select_top_half(pd.Series({"x": 0.3, "y": 0.3})) == [
        "x"
    ]  # a tie goes to configuration order (ADR 054 b)
    # float residues of an exact tie (two families that disagree in a two-instrument sleeve) are still a tie
    assert select_top_half(pd.Series({"x": -1.1e-16, "y": 2.2e-16})) == ["x"]
    assert select_top_half(pd.Series({"x": 0.3, "y": 0.2})) == ["x"]
    w = inverse_vol_weights(pd.Series({"a": 0.10, "b": 0.20}))
    assert w["a"] == pytest.approx(2 / 3) and w["b"] == pytest.approx(1 / 3)


def test_configuration_errors_are_caught() -> None:
    bad = {
        **PARAMS,
        "sleeves": {**PARAMS["sleeves"], "PM": {**PARAMS["sleeves"]["PM"], "instruments": ["P1"]}},
    }
    with pytest.raises(ValueError, match="cover exactly"):
        SleeveAllocator(spec("sleeve_allocator", UNIVERSE, bad))
    bad = {**PARAMS, "sleeves": {**PARAMS["sleeves"], "PM": {**PARAMS["sleeves"]["PM"], "budget": 0.5}}}
    with pytest.raises(ValueError, match="sum to one"):
        SleeveAllocator(spec("sleeve_allocator", UNIVERSE, bad))
    bad = {
        **PARAMS,
        "sleeves": {**PARAMS["sleeves"], "PM": {**PARAMS["sleeves"]["PM"], "families": {"rsi": 1.0}}},
    }
    with pytest.raises(ValueError, match="unsupported families"):
        SleeveAllocator(spec("sleeve_allocator", UNIVERSE, bad))


def test_proposal_follows_the_pre_registered_rule_step_by_step() -> None:
    w = world()
    factory = w.factory()
    d = date(2003, 4, 30)  # 40th month
    v = factory.at(d)
    strat = build()
    prop, state = strat.propose(v, strat.initial_state())
    assert not prop.warmup
    sig, tgt = prop.signals, dict(prop.weights)
    # EQ: top-2 of 4 by 12-1 momentum, then the trend filter; E4 falls and is never held
    score = pd.Series({a: sig[f"score:{a}"] for a in ["E1", "E2", "E3", "E4"]})
    picks = select_top_half(score)
    assert "E4" not in tgt and all(a in tgt for a in picks if sig[f"excess12:{a}"] > 0)
    # inside a sleeve the weights are inverse EWMA vol, normalised; the EWMA is the registered feature
    held = [a for a in picks if a in tgt]
    assert held, "the toy has rising instruments in EQ"
    for a in held:
        assert sig[f"vol:{a}"] == pytest.approx(float(feature("vol_ewma").call(v, [a]).iloc[0]))
    inv = {a: 1 / sig[f"vol:{a}"] for a in held}
    basket = {a: inv[a] / sum(inv.values()) for a in held}
    eq_w = sum(tgt[a] for a in held)
    for a in held:
        assert tgt[a] / eq_w == pytest.approx(basket[a])
    # FI: carry prefers B2 (5 % vs 3 %), momentum too → only B2; PM: P1 or P2 by momentum
    assert "B1" not in tgt and "B2" in tgt
    # across: sleeve weight ∝ budget / basket vol, scaled to the vol target, gross ≤ 1.5
    sw = {k: sig[f"sleeve_weight:{k}"] for k in ("EQ", "FI", "PM") if f"sleeve_weight:{k}" in sig}
    sv = {k: sig[f"sleeve_vol:{k}"] for k in sw}
    for k, w_k in sw.items():
        assert w_k * sv[k] == pytest.approx(sw["FI"] * sv["FI"], rel=1e-9)  # equal risk per sleeve
    assert sig["gross"] == pytest.approx(sum(tgt.values())) and sig["gross"] <= 1.5 + 1e-9
    assert sig["scale"] == pytest.approx(min(0.10 / sig["portfolio_vol"], 1.5)) or max(
        sw.values()
    ) == pytest.approx(1.0)
    # the state carries the targets for the band
    assert dict(state.extra["targets"]) == pytest.approx(tgt)


def test_band_keeps_the_last_target_for_small_moves_and_caps_hold() -> None:
    w = world()
    v = w.factory().at(date(2003, 4, 30))
    strat = build()
    prop, state = strat.propose(v, strat.initial_state())
    # same view again: every target moves by 0 < band → everything stays, and the note says so
    prop2, _ = strat.propose(v, state)
    assert dict(prop2.weights) == pytest.approx(dict(prop.weights))
    assert any("band" in n for n in prop2.notes)
    # a nudged last target within the band is kept, one outside it is replaced
    a = next(iter(prop.weights))
    nudged = {str(k): float(x) for k, x in prop.weights.items()}
    nudged[a] -= 0.01  # downwards, so the gross cap cannot interfere
    prop3, _ = strat.propose(v, StrategyState(state.strategy_id, extra={"targets": nudged}))
    assert prop3.weights[a] == pytest.approx(nudged[a])
    nudged[a] -= 0.05
    prop4, _ = strat.propose(v, StrategyState(state.strategy_id, extra={"targets": nudged}))
    assert prop4.weights[a] == pytest.approx(prop.weights[a])
    # kept targets that add up past the cap are scaled back to it
    big = {k: x * 1.2 for k, x in nudged.items()}
    prop5, _ = strat.propose(v, StrategyState(state.strategy_id, extra={"targets": big}))
    assert sum(prop5.weights.values()) <= 1.5 + 1e-9
    # no leverage: scale ≤ 1 → gross ≤ 1
    p1, _ = build(max_exposure=1.0).propose(v, strat.initial_state())
    assert sum(p1.weights.values()) <= 1.0 + 1e-9
    # a sleeve never exceeds max_sleeve of the book
    p2, _ = build(max_sleeve=0.4).propose(v, strat.initial_state())
    for k in ("EQ", "FI", "PM"):
        if f"sleeve_weight:{k}" in p2.signals:
            assert p2.signals[f"sleeve_weight:{k}"] <= 0.4 + 1e-9


def test_sleeve_without_investable_instrument_leaves_its_budget_in_cash() -> None:
    """Both PM instruments fall for a year: the PM budget stays in cash, EQ and FI keep equal risk among
    themselves but are not inflated to fill the gap (ADR 054 c: no redistribution)."""
    rng = np.random.default_rng(9)
    w = Toy()
    for name, drift, vol in [
        ("E1", 0.012, 0.03),
        ("E2", 0.008, 0.06),
        ("E3", 0.004, 0.04),
        ("E4", 0.006, 0.05),
    ]:
        w.monthly(name, list(100 * np.cumprod(1 + rng.normal(drift, vol, N))))
    w.monthly("B1", geometric(100, 0.004, N)).monthly("B2", geometric(100, 0.006, N))
    idx = w.frames[-1]["obs_date"]
    w.series("t:B1:y", pd.Series(3.0, index=idx), SeriesKind.YIELD)
    w.series("t:B2:y", pd.Series(5.0, index=idx), SeriesKind.YIELD)
    w.monthly("P1", geometric(100, -0.02, N)).monthly("P2", geometric(100, -0.015, N))
    w.cash("RF", 0.001, n=N)
    v = w.factory().at(date(2003, 4, 30))
    strat = build(max_exposure=1.0)
    prop, _ = strat.propose(v, strat.initial_state())
    assert "P1" not in prop.weights and "P2" not in prop.weights
    assert "sleeve_weight:PM" not in prop.signals
    sw = {k: prop.signals[f"sleeve_weight:{k}"] for k in ("EQ", "FI")}
    # before vol scaling the two invested sleeves sum to their budgets (2/3), never to one
    assert sum(sw.values()) / prop.signals["scale"] == pytest.approx(2 / 3)
    assert any("in cash" in n for n in prop.notes)


def test_warmup_until_every_estimator_has_its_history() -> None:
    w = world()
    strat = build()
    early = w.factory().at(date(2001, 12, 31))  # 24th month: 23 returns < min_obs
    prop, _ = strat.propose(early, strat.initial_state())
    assert prop.warmup and prop.weights == {}


def test_ewma_volatility_matches_pandas_and_is_floored() -> None:
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.03, 60))
    v = ewma_vol(r, 12, 24, 0.0)
    ref = r.ewm(halflife=12, min_periods=24, adjust=True).std() * np.sqrt(12)
    assert v.iloc[-1] == pytest.approx(ref.iloc[-1]) and np.isnan(v.iloc[22]) and not np.isnan(v.iloc[23])
    assert ewma_vol(pd.Series(np.zeros(60)), 12, 24, 0.02).iloc[-1] == pytest.approx(0.02)
