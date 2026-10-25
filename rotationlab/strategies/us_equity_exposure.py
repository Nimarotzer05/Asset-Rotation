"""US equity exposure: how much of the module sits in the market, the rest in T-bills.

Research (scripts/run_equity.py, part A; output/equity/REPORT.md A2; ADR 015/016): two binary votes on the
market's total return – above its 10-month average, and 12-month return above T-bills – averaged to an
exposure of 0, ½ or 1. Sharpe 0.573, max drawdown −41 % over 1927–2026 (buy & hold 0.45, −84 %).

Optional valuation scaling (off in v1): exposure × (floor + (1 − floor) · percentile of the excess CAPE
yield), 0.75–1; research 1931–2023 Sharpe 0.587 vs 0.563 without (A2), but it needs Shiller earnings.

Confidence: both votes agree → 1, split → the floor.
"""

from __future__ import annotations

import math

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import Proposal, StrategyState
from rotationlab.strategies.base import BaseStrategy, check_window


@registry.strategy
class UsEquityExposure(BaseStrategy):
    strategy_id = "us_equity_exposure"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        check_window("trend_window_months", self.params.get("trend_window_months"), 10)
        self.market = str(self.params.get("market", self.assets[0]))
        self.momentum_months = int(self.params.get("momentum_months", 12))
        self.valuation = dict(self.params.get("valuation_scaling", {}) or {})

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        m = self.market
        trend = float(self.feature("trend_10m", view, [m])[m])
        mom = float(self.feature("excess_mom_12m", view, [m], cash=self.cash, months=self.momentum_months)[m])
        if math.isnan(trend) or math.isnan(mom):
            return self.warmup_proposal(view, "trend or momentum history too short"), state
        votes = [1.0 if trend > 0 else 0.0, 1.0 if mom > 0 else 0.0]
        exposure = sum(votes) / len(votes)
        signals = {"trend_10m": trend, "excess_mom_12m": mom, "votes": exposure}
        if self.valuation.get("enabled"):
            pct = float(
                self.feature(
                    "ecy_percentile",
                    view,
                    min_history=int(self.valuation.get("min_history_months", 120)),
                    pct_start=self.valuation.get("pct_start"),
                )
            )
            if math.isnan(pct):
                return self.warmup_proposal(view, "valuation history too short"), state
            floor = float(self.valuation.get("floor", 0.75))
            exposure *= floor + (1 - floor) * pct
            signals["ecy_percentile"] = pct
        signals["exposure"] = exposure
        agreement = abs(sum(votes) / len(votes) - 0.5) * 2
        return self.proposal(view, {m: exposure}, agreement, signals), state
