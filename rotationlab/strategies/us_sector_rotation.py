"""US sector rotation: the three strongest sectors, equal weight, the whole sleeve in cash when the market
is below its 10-month average.

Research (scripts/run_equity.py, part B3; ADR 017): rank composite over the sectors – 12-1 momentum 50 %,
6-1 momentum 30 %, distance to the 10-month average 20 % (ranks, not z-scores; a sector missing any of
the three is not ranked) – top 3 equally weighted, gated by the market's own trend. French 10 industries
1928–2026: Sharpe 0.591, max drawdown −46 % (market 0.44, −84 %). Fewer than `min_assets` ranked sectors
(the first year of the data, or the ETF universe before 1998) → all cash.

Confidence: how far the picks' composite stands above the average, in cross-sectional SDs.
"""

from __future__ import annotations

import math

import pandas as pd

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import Proposal, StrategyState
from rotationlab.strategies.base import BaseStrategy, check_window, dispersion_strength, top_n

FEATURES = ("mom_12_1", "mom_6_1", "trend_10m")


@registry.strategy
class UsSectorRotation(BaseStrategy):
    strategy_id = "us_sector_rotation"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        check_window("trend_window_months", self.params.get("trend_window_months"), 10)
        self.weights = dict(
            self.params.get("feature_weights", {"mom_12_1": 0.5, "mom_6_1": 0.3, "trend_10m": 0.2})
        )
        unknown = set(self.weights) - set(FEATURES)
        if unknown:
            raise ValueError(f"us_sector_rotation: unsupported features {sorted(unknown)}")
        self.n = int(self.params.get("top_n", 3))
        self.min_assets = int(self.params.get("min_assets", 8))
        self.gate = bool(self.params.get("market_trend_gate", True))
        self.market = str(self.params.get("market", "SPY"))

    def composite(self, view: MarketView) -> pd.Series:
        assets = list(self.assets)
        ranks = {k: self.feature(k, view, assets).rank() for k in self.weights}
        out: pd.Series | None = None
        for k, w in self.weights.items():
            out = ranks[k] * w if out is None else out + ranks[k] * w
        assert out is not None
        return out.rename("composite")

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        score = self.composite(view)
        ranked = score.dropna()
        if len(ranked) < self.min_assets:
            return self.warmup_proposal(view, f"{len(ranked)} ranked sectors < {self.min_assets}"), state
        picks = top_n(score, self.n)
        g, mkt_trend = 1.0, math.nan
        if self.gate:
            mkt_trend = float(self.feature("trend_10m", view, [self.market])[self.market])
            g = 1.0 if math.isnan(mkt_trend) else float(mkt_trend > 0)
        weights = {a: g / len(picks) for a in picks}
        signals = {f"score:{a}": float(v) for a, v in ranked.items()}
        signals.update({"market_trend_10m": mkt_trend, "gate": g})
        notes = ("market below its 10M average: sleeve in cash",) if g == 0 else ()
        strength = dispersion_strength(
            score, picks, float(self.confidence_rule.get("params", {}).get("scale", 1.0))
        )
        return self.proposal(view, weights, strength, signals, notes), state
