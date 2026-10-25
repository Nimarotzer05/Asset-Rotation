"""Strategy modules on tiny synthetic markets: each rule of each module, and how modules are built."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.errors import ConfigError
from rotationlab.core.protocols import Strategy
from rotationlab.core.types import Proposal, StrategyId, StrategyState
from rotationlab.strategies import build_strategy, build_walkforward, strategy_spec
from rotationlab.strategies.base import (
    BaseStrategy,
    deep_merge,
    dispersion_strength,
    top_n,
    weighted_composite,
    zscore,
)
from rotationlab.strategies.commodity_trend import CommodityTrend
from rotationlab.strategies.multi_asset_rotation import MultiAssetRotation
from rotationlab.strategies.precious_metals import PreciousMetals
from rotationlab.strategies.us_equity_exposure import UsEquityExposure
from rotationlab.strategies.us_sector_rotation import UsSectorRotation
from rotationlab.strategies.walkforward import WalkForward, grid_points, label, sharpe
from tests.fixtures.toy import Toy, geometric, spec

N = 40
D = date(2003, 4, 30)  # month 40 from 2000-01


def zigzag(trend: float, amp: float, n: int = N, start: float = 100.0) -> list[float]:
    return [start * (1 + trend) ** k * (1 + amp * (-1) ** k) for k in range(n)]


# ---------------------------------------------------------------------------- building blocks
def test_research_building_blocks() -> None:
    x = pd.Series({"A": 1.0, "B": 2.0, "C": np.nan, "D": 30.0})
    z = zscore(x, clip=1.0)
    assert np.isnan(z["C"]) and z.max() == 1.0 and z.min() >= -1.0
    assert zscore(pd.Series({"A": 1.0, "B": 1.0})).isna().all()  # no dispersion → no score
    s = weighted_composite(
        {"a": pd.Series({"A": 1.0, "B": np.nan}), "b": pd.Series({"A": np.nan, "B": 2.0})},
        {"a": 1.0, "b": 3.0},
    )
    assert s.tolist() == [0.25, 1.5]  # missing in one keeps the other
    assert top_n(pd.Series({"A": 1.0, "B": 3.0, "C": np.nan, "D": 2.0}), 2) == ["B", "D"]
    assert dispersion_strength(pd.Series({"A": 0.0, "B": 2.0}), ["B"]) == pytest.approx(1 / np.sqrt(2))
    assert dispersion_strength(pd.Series({"A": 1.0}), ["A"]) == 0.0
    assert deep_merge({"a": {"b": 1, "c": 2}, "d": 1}, {"a": {"b": 5}, "e": 3}) == {
        "a": {"b": 5, "c": 2},
        "d": 1,
        "e": 3,
    }


def test_confidence_maps_strength_to_floor_one() -> None:
    s = BaseStrategy(spec("x", ["A", "CASH"], {"cash": "CASH"}), {"kind": "abs_z", "floor": 0.6})
    assert s.confidence(0.0) == 0.6 and s.confidence(2.0) == 1.0 and s.confidence(float("nan")) == 0.6
    assert s.confidence(0.5) == pytest.approx(0.8)
    assert s.assets == ("A",) and s.cash == "CASH"
    with pytest.raises(NotImplementedError):
        s.propose(None, s.initial_state())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- us_equity_exposure
def _equity(levels: list[float], cash: float = 0.001) -> tuple[UsEquityExposure, object]:
    f = Toy().monthly("MKT", levels).cash("RF", cash, n=len(levels)).factory()
    return UsEquityExposure(spec("us_equity_exposure", ["MKT", "RF"], {"market": "MKT", "cash": "RF"})), f


def test_equity_exposure_votes() -> None:
    s, f = _equity(zigzag(0.01, 0.002))
    p, _ = s.propose(f.at(D), s.initial_state())
    assert p.weights == {"MKT": 1.0} and p.confidence == 1.0 and not p.warmup
    s, f = _equity(zigzag(-0.01, 0.002))
    p, _ = s.propose(f.at(D), s.initial_state())
    assert p.weights == {} and p.confidence == 1.0  # both votes out: all T-bills
    up = geometric(100, 0.01, N - 1)
    crash = [*up, up[-1] * 0.93]  # long uptrend, last month −7 %
    s, f = _equity(crash)
    p, _ = s.propose(f.at(D), s.initial_state())
    assert p.weights == {"MKT": 0.5} and p.confidence == 0.5  # trend broken, momentum still positive
    p, _ = s.propose(f.at(date(2000, 9, 30)), s.initial_state())
    assert p.warmup and p.weights == {}


def test_equity_exposure_rejects_unregistered_windows() -> None:
    with pytest.raises(ConfigError):
        UsEquityExposure(spec("us_equity_exposure", ["MKT", "RF"], {"cash": "RF", "trend_window_months": 12}))


# ---------------------------------------------------------------------------- us_sector_rotation
def _sectors(n: int, trends: list[float], market_trend: float) -> tuple[UsSectorRotation, object]:
    w = Toy()
    names = [f"S{i}" for i in range(n)]
    for name, t in zip(names, trends, strict=True):
        w.monthly(name, zigzag(t, 0.003))
    w.monthly("M", zigzag(market_trend, 0.003)).cash("RF", 0.001, n=N)
    params = {"cash": "RF", "market": "M", "min_assets": 8, "top_n": 3}
    return UsSectorRotation(spec("us_sector_rotation", [*names, "RF"], params)), w.factory()


def test_sector_rotation_picks_the_strongest_and_gates_on_the_market() -> None:
    trends = [0.001 * i for i in range(10)]
    s, f = _sectors(10, trends, 0.01)
    p, _ = s.propose(f.at(D), s.initial_state())
    assert set(p.weights) == {"S7", "S8", "S9"} and all(w == pytest.approx(1 / 3) for w in p.weights.values())
    assert p.signals["gate"] == 1.0 and p.confidence > 0.5
    s, f = _sectors(10, trends, -0.01)
    p, _ = s.propose(f.at(D), s.initial_state())
    assert p.weights == {} and p.signals["gate"] == 0.0 and "sleeve in cash" in p.notes[0]
    s, f = _sectors(7, trends[:7], 0.01)
    p, _ = s.propose(f.at(D), s.initial_state())
    assert p.warmup and "7 ranked sectors < 8" in p.notes[0]


# ---------------------------------------------------------------------------- multi_asset_rotation
def test_multi_asset_trend_filter_and_inverse_vol() -> None:
    w = Toy()
    w.monthly("A", zigzag(0.02, 0.01)).monthly("B", zigzag(0.015, 0.03)).monthly("C", zigzag(0.01, 0.02))
    w.monthly("DN", zigzag(-0.02, 0.01)).monthly("X", zigzag(-0.03, 0.05)).cash("RF", 0.001, n=N)
    params = {"cash": "RF", "top_n": 3, "feature_weights": {"mom_12_1": 1.0, "trend_10m": 1.0}}
    s = MultiAssetRotation(spec("multi_asset_rotation", ["A", "B", "C", "DN", "X", "RF"], params))
    p, _ = s.propose(w.factory().at(D), s.initial_state())
    assert set(p.weights) == {"A", "B", "C"} and sum(p.weights.values()) == pytest.approx(1.0)
    assert p.weights["A"] > p.weights["C"] > p.weights["B"]  # ∝ 1/vol: A calmest, B wildest
    w2 = (
        Toy()
        .monthly("A", zigzag(0.02, 0.01))
        .monthly("B", zigzag(-0.01, 0.01))
        .monthly("C", zigzag(-0.02, 0.01))
    )
    w2.cash("RF", 0.001, n=N)
    s2 = MultiAssetRotation(spec("multi_asset_rotation", ["A", "B", "C", "RF"], params))
    p2, _ = s2.propose(w2.factory().at(D), s2.initial_state())
    assert set(p2.weights) == {"A"} and p2.weights["A"] < 1 and "held in cash" in p2.notes[0]
    with pytest.raises(ValueError, match="unsupported"):
        MultiAssetRotation(spec("m", ["A", "RF"], {"cash": "RF", "feature_weights": {"cape": 1.0}}))


# ---------------------------------------------------------------------------- commodity_trend
def test_commodity_trend_holds_every_uptrend_by_inverse_vol() -> None:
    w = (
        Toy()
        .monthly("U1", zigzag(0.01, 0.01))
        .monthly("U2", zigzag(0.01, 0.02))
        .monthly("D1", zigzag(-0.01, 0.01))
    )
    w.cash("RF", 0.001, n=N)
    s = CommodityTrend(
        spec("commodity_trend", ["U1", "U2", "D1", "RF"], {"cash": "RF"}),
        {"kind": "fraction_in_trend", "floor": 0.5},
    )
    p, _ = s.propose(w.factory().at(D), s.initial_state())
    assert set(p.weights) == {"U1", "U2"} and p.weights["U1"] > p.weights["U2"]
    assert sum(p.weights.values()) < 1  # D1's share sits in cash
    assert p.signals["fraction_in_trend"] == pytest.approx(2 / 3) and p.confidence == pytest.approx(
        0.5 + 0.5 * 2 / 3
    )
    with pytest.raises(ValueError, match="tilt"):
        CommodityTrend(spec("c", ["U1", "RF"], {"cash": "RF", "cross_section_tilt": 1.0}))


# ---------------------------------------------------------------------------- precious_metals
def _metals(ratio_path: list[float], hedge: bool = False, n: int = 90) -> tuple[PreciousMetals, object]:
    idx = pd.bdate_range("2000-01-03", pd.Timestamp("2000-01-31") + pd.offsets.MonthEnd(n - 1))
    month = (idx.year - 2000) * 12 + idx.month - 1
    silver = pd.Series(20.0, index=idx)
    gold = silver * np.asarray(ratio_path)[month]
    w = Toy().daily("G", gold).daily("S", silver).cash("RF", 0.001, n=n)
    params = {
        "cash": "RF",
        "trade": {"gold": "G", "silver": "S"},
        "signal": {"gold": "G", "silver": "S"},
        "hedge": {"enabled": hedge, "base": 0.25},
        "risk_appetite": {"equity": "G"},
    }
    stops = [{"kind": "ratio_drawdown", "threshold": -0.15, "action": "close"}]
    return PreciousMetals(
        spec("precious_metals", ["G", "S", "RF"], params),
        {"kind": "abs_z", "floor": 0.5, "params": {"full_at": 2.0}},
        stops,
    ), w.factory()


def test_gold_silver_tranches_entry_ratio_and_stop() -> None:
    rng = np.random.default_rng(3)
    path = (
        list(50 * np.exp(np.cumsum(rng.normal(0, 0.03, 80)))) + [200.0] * 10
    )  # ratio jumps: gold very expensive
    s, f = _metals(path)
    state = s.initial_state()
    ends = pd.date_range("2000-01-31", periods=90, freq="ME")
    props = []
    for d in ends:
        p, state = s.propose(f.at(d.date()), state)
        props.append(p)
    last = props[-1]
    assert last.weights["S"] == -last.weights["G"] and last.weights["G"] < 0  # short gold, long silver
    assert len(state.tranches) == 6
    assert last.signals["position"] == pytest.approx(np.mean([t["G"] for t in state.tranches]))
    assert state.entries["ratio_entry"] > 0 and last.stops[0].reference == state.entries["ratio_entry"]
    assert last.stops[0].scope == ("G", "S") and last.stops[0].action == "close"
    assert props[0].warmup and props[0].weights == {}
    assert last.horizon_months == 6


def test_gold_silver_hedge_adds_the_base_share() -> None:
    s, f = _metals([50.0] * 90, hedge=True)
    p, _ = s.propose(f.at(date(2007, 6, 30)), s.initial_state())
    assert p.signals["hedge"] == pytest.approx(0.25) and p.weights["G"] == pytest.approx(0.25)
    assert not p.warmup  # the hedge alone is a position


# ---------------------------------------------------------------------------- building from configuration
def test_build_strategies_from_configuration(bundle) -> None:
    for sid in bundle.strategies:
        live = build_strategy(bundle, sid)
        long = build_strategy(bundle, sid, "long_history")
        assert isinstance(live, Strategy) and isinstance(long, Strategy)
        assert live.spec.params["cash"] == "CASH"
        assert str(long.spec.universe[-1]) == long.spec.params["cash"]
    eq = build_strategy(bundle, "us_equity_exposure", "long_history")
    assert eq.spec.params["market"] == "FF_MKT" and eq.spec.params["cash"] == "FF_RF"
    pm = build_strategy(bundle, "precious_metals", "long_history", {"hedge": {"enabled": False}})
    assert pm.spec.params["hedge"] == {
        **bundle.strategies["precious_metals"].params["hedge"],
        "enabled": False,
    }
    with pytest.raises(ConfigError):
        build_strategy(bundle, "nope")
    no_long = bundle.strategies["commodity_trend"].model_copy(update={"long_history_universe": []})
    b2 = bundle.model_copy(update={"strategies": {**bundle.strategies, "commodity_trend": no_long}})
    with pytest.raises(ConfigError, match="no long_history universe"):
        strategy_spec(b2, "commodity_trend", "long_history")
    no_cash = no_long.model_copy(update={"long_history_universe": ["WB_OIL"]})
    b3 = bundle.model_copy(update={"strategies": {**bundle.strategies, "commodity_trend": no_cash}})
    with pytest.raises(ConfigError, match="exactly one cash asset"):
        strategy_spec(b3, "commodity_trend", "long_history")
    with pytest.raises(ConfigError, match="no walkforward"):
        build_walkforward(bundle, "commodity_trend", "long_history", lambda a, b: 0.0)


# ---------------------------------------------------------------------------- walk-forward
class Fixed(BaseStrategy):
    """Always holds one asset fully (or nothing)."""

    strategy_id = "fixed"

    def propose(self, view, state: StrategyState) -> tuple[Proposal, StrategyState]:
        a = self.params["hold"]
        return self.proposal(view, {a: 1.0} if a else {}, 1.0, {"hold": 1.0}), state


def test_walk_forward_trains_then_follows_the_best_candidate() -> None:
    w = Toy().monthly("GOOD", zigzag(0.02, 0.01)).monthly("BAD", zigzag(-0.01, 0.02)).cash("RF", 0.001, n=N)
    f = w.factory()
    cands = {
        name: Fixed(spec("fixed", ["GOOD", "BAD", "RF"], {"cash": "RF", "hold": h}))
        for name, h in (("bad", "BAD"), ("good", "GOOD"), ("cash", None))
    }
    wf = WalkForward(
        spec("fixed", ["GOOD", "BAD", "RF"], {"cash": "RF"}),
        cands,
        refit_every=12,
        min_train=6,
        turnover_cost=lambda a, b: 0.0,
        cash="RF",
    )
    assert wf.warmup().n == 13
    state = wf.initial_state()
    props = []
    for d in pd.date_range("2000-01-31", periods=30, freq="ME"):
        p, state = wf.propose(f.at(d.date()), state)
        props.append(p)
    assert all(p.warmup for p in props[:5]) and not props[5].warmup
    assert props[5].weights == {"GOOD": 1.0} and "walk-forward: good" in props[5].notes[-1]
    choices = state.extra["choices"]
    assert [c["date"] for c in choices] == ["2000-06-30", "2001-06-30", "2002-06-30"]
    assert {c["chosen"] for c in choices} == {"good"}
    assert grid_points({"a": [1, 2], "b": [True]}) == [{"a": 1, "b": True}, {"a": 2, "b": True}]
    assert label({"a": 1, "b": True}) == "a=1,b=True"
    assert sharpe([0.01]) == -np.inf and sharpe([0.01, 0.01]) == -np.inf
    assert isinstance(StrategyId("x"), str)
