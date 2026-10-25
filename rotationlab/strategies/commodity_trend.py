"""Commodity trend: every commodity in an uptrend, inverse-volatility weighted; the rest in cash.

Research (src/commodity_model.py::tilted_weights with λ = 0, scripts/run_commodities.py variant C; ADR 014):
weights ∝ 1/σ(12 monthly returns) over all commodities with a volatility estimate; a commodity below its
10-month average hands its weight to cash. No cross-sectional tilt: every tilt the study tried lowered the
Sharpe (0.74 → 0.50) and the walk-forward kept the untilted variant in all 44 years. World Bank monthly
averages 1973–2025: Sharpe 0.74, max drawdown −17 %.

Confidence: the share of commodities in an uptrend.
"""

from __future__ import annotations

import numpy as np

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import Proposal, StrategyState
from rotationlab.strategies.base import BaseStrategy, check_window


@registry.strategy
class CommodityTrend(BaseStrategy):
    strategy_id = "commodity_trend"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        check_window("trend_window_months", self.params.get("trend_window_months"), 10)
        check_window("vol_window_months", self.params.get("vol_window_months"), 12)
        if float(self.params.get("cross_section_tilt", 0.0)) != 0.0:
            raise ValueError("commodity_trend: a cross-sectional tilt is not part of v1 (ADR 014)")

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        assets = list(self.assets)
        vol = self.feature("vol_12m", view, assets)
        iv = (1 / vol).replace([np.inf, -np.inf], np.nan).dropna()
        if iv.empty:
            return self.warmup_proposal(view, "no volatility estimate yet"), state
        w = iv / iv.sum()
        trend = self.feature("trend_10m", view, list(w.index))
        keep = trend > 0
        signals = {f"trend:{a}": float(v) for a, v in trend.items()}
        signals["fraction_in_trend"] = float(keep.mean())
        return self.proposal(view, w[keep].to_dict(), float(keep.mean()), signals), state
