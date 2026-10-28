"""P8 (ADR 048): the forecast portfolio rule and the fixed-weight baselines on known numbers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.config.models import load_bundle
from rotationlab.core.types import AssetId, Months, StrategySpec
from rotationlab.engine.core import Engine
from rotationlab.features import feature
from rotationlab.portfolio.book import Book
from rotationlab.portfolio.combine import SingleStrategy
from rotationlab.portfolio.costs import CostModel
from rotationlab.strategies import build_strategy
from rotationlab.strategies.fixed_weights import FixedWeights
from rotationlab.strategies.forecast_portfolio import ForecastPortfolio
from tests.fixtures.toy import Toy, spec

pytestmark = [pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")]

PARAMS = {
    "feature_weights": {
        "mom_3_1": 0.2,
        "mom_6_1": 0.3,
        "mom_12_1": 0.3,
        "trend_10m": 0.2,
        "inv_vol_12m": 0.1,
    },
    "zscore_clip": 3.0,
    "top_n": 2,
    "trend_filter": True,
    "vol_target": 0.10,
    "vol_floor": 0.05,
    "max_exposure": 1.0,
    "cash": "RF",
}


def world(n: int = 30, seed: int = 3) -> Toy:
    """Four risky classes with different drifts and volatilities, 30 months, plus cash."""
    rng = np.random.default_rng(seed)
    w = Toy()
    for a, mu, sd in (("A", 0.02, 0.03), ("B", 0.01, 0.02), ("C", -0.01, 0.04), ("D", 0.0, 0.08)):
        r = rng.normal(mu, sd, n)
        w.monthly(a, list(100 * np.cumprod(1 + r)), start="2000-01-31")
    w.cash("RF", 0.001, n=n, start="2000-01-31")
    return w


def test_sleeve_vol_is_the_volatility_of_the_weighted_returns() -> None:
    w = world()
    f = w.factory()
    v = f.at(date(2002, 6, 30))
    lv = v.total_return(["A", "B"], "ME")
    r = lv.pct_change()
    sleeve = 0.5 * r["A"] + 0.5 * r["B"]
    expected = float(sleeve.iloc[-12:].std(ddof=1) * np.sqrt(12))
    got = float(feature("sleeve_vol_12m").call(v, weights={"A": 0.5, "B": 0.5}))
    assert got == pytest.approx(expected)
    # NaN until twelve returns exist; empty weights give NaN
    assert np.isnan(float(feature("sleeve_vol_12m").call(f.at(date(2000, 12, 31)), weights={"A": 1.0})))
    assert np.isnan(float(feature("sleeve_vol_12m").call(v, weights={})))


def _rule(params: dict | None = None) -> ForecastPortfolio:
    s = spec("forecast_portfolio", ["A", "B", "C", "D", "RF"], {**PARAMS, **(params or {})}, warmup=13)
    return ForecastPortfolio(s, {"kind": "score_dispersion", "floor": 0.5})


def independent_composite(lv: pd.DataFrame, weights: dict[str, float], clip: float) -> pd.Series:
    """The research composite written out by hand from month-end levels (not via the registry): z-scores
    (sample SD, clipped) of 3-1, 6-1, 12-1 momentum, distance to the 10-month mean, inverse 12-month vol."""
    feats = {
        "mom_3_1": lv.shift(1) / lv.shift(4) - 1,
        "mom_6_1": lv.shift(1) / lv.shift(7) - 1,
        "mom_12_1": lv.shift(1) / lv.shift(13) - 1,
        "trend_10m": lv / lv.rolling(10).mean() - 1,
        "inv_vol_12m": 1 / lv.pct_change().rolling(12).std(),
    }
    total = sum(weights.values())
    out = pd.Series(0.0, index=lv.columns)
    for k, w in weights.items():
        row = feats[k].iloc[-1]
        z = ((row - row.mean()) / row.std()).clip(-clip, clip)
        out = out.add(z * w / total, fill_value=0)
    return out


def test_rule_picks_the_two_highest_scores_and_scales_to_the_vol_target() -> None:
    """Against an independent calculation: composite by hand, picks, trend filter, sleeve vol and scale."""
    w = world()
    f = w.factory()
    d = date(2002, 6, 30)
    v = f.at(d)
    strat = _rule()
    p, _ = strat.propose(v, strat.initial_state())
    lv = v.total_return(["A", "B", "C", "D"], "ME")
    assert lv.index[-1] == pd.Timestamp(d)
    score = independent_composite(lv, PARAMS["feature_weights"], 3.0)
    assert np.allclose(strat.composite(v).reindex(score.index).to_numpy(), score.to_numpy(), atol=1e-12)
    picks = list(score.sort_values(ascending=False).index[:2])
    trend = (lv / lv.rolling(10).mean() - 1).iloc[-1]
    kept = [a for a in picks if trend[a] > 0]
    r = lv.pct_change()
    sleeve = sum(0.5 * r[a] for a in kept)
    vol = float(sleeve.iloc[-12:].std(ddof=1) * np.sqrt(12)) if kept else np.nan
    scale = min(0.10 / max(vol, 0.05), 1.0) if kept else 1.0
    assert set(p.weights) == set(kept) and not p.warmup
    for a in kept:
        assert p.weights[AssetId(a)] == pytest.approx(0.5 * scale)
    if kept:
        assert p.signals["scale"] == pytest.approx(scale) and p.signals["sleeve_vol_12m"] == pytest.approx(
            vol
        )
    assert sum(p.weights.values()) <= 1.0 + 1e-12


def test_trend_filter_hands_a_pick_to_cash() -> None:
    """A world where one of the two best scores sits below its 10-month average: with the filter it is in
    cash, without it both picks are held."""
    rng = np.random.default_rng(5)
    w = Toy()
    n = 30
    # A: 25 months up 4 %, then 5 months down 2 % – still a top score on 12-1 momentum and low volatility,
    # but below its 10-month average at the decision; B, C steady; D weak
    a = list(100 * np.cumprod(1 + np.r_[np.full(25, 0.04), np.full(5, -0.02)]))
    w.monthly("A", a, start="2000-01-31")
    for name, mu in (("B", 0.004), ("C", 0.002), ("D", -0.01)):
        w.monthly(name, list(100 * np.cumprod(1 + rng.normal(mu, 0.02, n))), start="2000-01-31")
    w.cash("RF", 0.001, n=n, start="2000-01-31")
    f = w.factory()
    v = f.at(date(2002, 6, 30))
    on, off = _rule(), _rule({"trend_filter": False})
    p_on, _ = on.propose(v, on.initial_state())
    p_off, _ = off.propose(v, off.initial_state())
    assert len(p_off.weights) == 2 and "A" in {str(k) for k in p_off.weights}
    assert p_on.signals["trend:A"] < 0
    assert "A" not in {str(k) for k in p_on.weights} and len(p_on.weights) == 1
    assert p_on.notes[0].startswith("below 10M average, held in cash: A")


def test_vol_floor_and_exposure_cap() -> None:
    w = world()
    f = w.factory()
    v = f.at(date(2002, 6, 30))
    base = _rule({"trend_filter": False})
    p0, _ = base.propose(v, base.initial_state())
    vol = p0.signals["sleeve_vol_12m"]
    # a floor above the realised vol caps the scale at target / floor
    floored = _rule({"trend_filter": False, "vol_floor": 0.5})
    p1, _ = floored.propose(v, floored.initial_state())
    assert p1.signals["scale"] == pytest.approx(min(0.10 / 0.5, 1.0)) and 0.5 > vol
    # a high target would lever up: the cap holds at max_exposure
    lev = _rule({"trend_filter": False, "max_exposure": 1.5, "vol_target": 1.0})
    p2, _ = lev.propose(v, lev.initial_state())
    assert sum(p2.weights.values()) == pytest.approx(1.5)
    unlev = _rule({"trend_filter": False, "vol_target": 1.0})
    p3, _ = unlev.propose(v, unlev.initial_state())
    assert sum(p3.weights.values()) == pytest.approx(1.0)


def test_rule_is_in_warmup_without_scores_and_in_cash_without_a_trend() -> None:
    w = world()
    f = w.factory()
    strat = _rule()
    p, _ = strat.propose(f.at(date(2000, 3, 31)), strat.initial_state())
    assert p.warmup and p.weights == {}  # no feature yet: no score for any class
    p, _ = strat.propose(f.at(date(2000, 6, 30)), strat.initial_state())
    # momentum scores exist (research formula: the available features), the 10-month trend does not: a
    # pick without a trend is not above its average and goes to cash – a signal, not a warm-up (house rule)
    assert not p.warmup and p.weights == {} and p.notes[0].startswith("below 10M average")
    p, _ = strat.propose(f.at(date(2000, 11, 30)), strat.initial_state())
    assert p.warmup and "volatility" in p.notes[0]  # trend known, 12 returns not yet


def test_rule_configuration_is_validated() -> None:
    with pytest.raises(ValueError, match="top_n"):
        _rule({"top_n": 5})
    with pytest.raises(ValueError, match="positive"):
        _rule({"vol_target": 0.0})
    with pytest.raises(ValueError, match="unsupported"):
        _rule({"feature_weights": {"mom_3_1": 1.0, "beta": 1.0}})


def _fixed(params: dict) -> FixedWeights:
    s = spec("fixed_weights", ["A", "B", "C", "D", "RF"], {"cash": "RF", **params}, warmup=1)
    return FixedWeights(s, {"kind": "score_dispersion", "floor": 0.5})


def test_fixed_weights_monthly_and_buy_and_hold() -> None:
    w = world()
    f = w.factory()
    ew = _fixed({"weights": {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}, "rebalance": "monthly"})
    p, _ = ew.propose(f.at(date(2001, 6, 30)), ew.initial_state())
    assert {str(a): x for a, x in p.weights.items()} == {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    bh = _fixed({"weights": {"A": 0.5, "B": 0.5}, "rebalance": "never"})
    st = bh.initial_state()
    p0, st = bh.propose(f.at(date(2001, 1, 31)), st)
    p1, st = bh.propose(f.at(date(2001, 6, 30)), st)
    lv = f.at(date(2001, 6, 30)).total_return(["A", "B"], "ME")
    g = {a: 0.5 * lv[a].loc["2001-06-30"] / lv[a].loc["2001-01-31"] for a in ("A", "B")}
    tot = sum(g.values())
    assert p0.weights[AssetId("A")] == pytest.approx(0.5)
    assert p1.weights[AssetId("A")] == pytest.approx(g["A"] / tot) and sum(
        p1.weights.values()
    ) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="sum to 1"):
        _fixed({"weights": {"A": 0.5}, "rebalance": "never"})
    with pytest.raises(ValueError, match="outside"):
        _fixed({"weights": {"Z": 1.0}})


@pytest.mark.parametrize("execution,averaged", [("next_close", ()), ("next_tradable", ("E",))])
def test_buy_and_hold_of_one_asset_never_trades_again(execution, averaged) -> None:
    """Through the engine: 100 % A, rebalance never → turnover only at the first decision – also on the P8
    path (`next_tradable` with averaged assets in the bundle, where every decision trades in two parts)."""
    w = world()
    w.monthly("E", list(np.linspace(50.0, 60.0, 30)), start="2000-01-31")
    f = w.factory()
    bh = _fixed({"weights": {"A": 1.0}, "rebalance": "never"})
    from rotationlab.core.clock import MonthEndClock

    clock = MonthEndClock(f.cal, date(2000, 3, 31), date(2002, 6, 30))
    book = Book("RF", CostModel(default_bps=10.0, cash_bps=10.0), 100.0)
    res = Engine(f, clock, [bh], SingleStrategy(), book, None, execution, averaged=averaged).run()
    t = res.decisions["turnover"]
    assert t.iloc[0] == pytest.approx(1.0) and (t.iloc[1:].abs() < 1e-12).all()
    assert (res.decisions["cost"].iloc[1:].abs() < 1e-15).all()
    # the equity follows A one to one after the first trade (costs aside)
    lv = f.at(date(2002, 6, 30)).total_return(["A"], "ME")["A"]
    eq = res.decisions["equity"]
    ratio = (eq / lv.reindex(eq.index)).iloc[1:]
    assert ratio.std() < 1e-9


def test_long_history_rule_builds_on_the_bundle_with_the_tradable_treasury() -> None:
    b = load_bundle("configs")
    s = build_strategy(b, "forecast_portfolio", "long_history")
    assert [str(a) for a in s.spec.universe] == ["US_EQ", "UST10_ME", "GOLD", "SILVER", "TBILL"]
    assert s.max_exposure == 1.0 and s.vol_target == 0.10 and s.n == 2 and s.trend_filter
    assert b.strategies["forecast_portfolio"].role == "paper"
    assert "forecast_portfolio" not in b.portfolio.risk_budgets
    assert isinstance(s.spec, StrategySpec) and s.spec.warmup == Months(13)
