"""Multi-asset rotation: the three most attractive asset classes, inverse-volatility weighted, each only
while it is above its own 10-month average.

Research (src/signals.py, scripts/run_analysis.py §7, config.py FEATURE_WEIGHTS): cross-sectional z-scores
(clipped at ±3) of 3-1, 6-1 and 12-1 momentum, the distance to the 10-month average and inverse volatility,
weighted 0.2/0.3/0.3/0.2/0.1 (normalised); top 3; weights ∝ 1/σ(12 monthly returns) among the picks
(a pick without a volatility estimate drops out and the others are renormalised); a pick below its
10-month average hands its weight to cash. Long-history universe 1973–2025: Sharpe 0.57, max drawdown −24 %.

Confidence: how far the picks' composite stands above the average, in cross-sectional SDs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import Proposal, StrategyState
from rotationlab.strategies.base import (
    BaseStrategy,
    check_window,
    dispersion_strength,
    top_n,
    weighted_composite,
    zscore,
)

FEATURES = ("mom_3_1", "mom_6_1", "mom_12_1", "mom_12", "trend_10m", "inv_vol_12m")


@registry.strategy
class MultiAssetRotation(BaseStrategy):
    strategy_id = "multi_asset_rotation"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        check_window("trend_window_months", self.params.get("trend_window_months"), 10)
        check_window("vol_window_months", self.params.get("vol_window_months"), 12)
        self.weights = dict(self.params["feature_weights"])
        unknown = set(self.weights) - set(FEATURES)
        if unknown:
            raise ValueError(f"multi_asset_rotation: unsupported features {sorted(unknown)}")
        self.clip = float(self.params.get("zscore_clip", 3.0))
        self.n = int(self.params.get("top_n", 3))
        self.trend_filter = bool(self.params.get("trend_filter", True))
        if self.params.get("weighting", "inverse_vol") != "inverse_vol":
            raise ValueError("multi_asset_rotation: only inverse_vol weighting is implemented")

    def composite(self, view: MarketView) -> pd.Series:
        assets = list(self.assets)
        z = {k: zscore(self.feature(k, view, assets), self.clip) for k in self.weights}
        return weighted_composite(z, self.weights).rename("composite")

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        score = self.composite(view)
        if score.dropna().size < self.n:
            return self.warmup_proposal(view, f"fewer than {self.n} assets with a score"), state
        picks = top_n(score, self.n)
        vol = self.feature("vol_12m", view, picks)
        iv = (1 / vol).replace([np.inf, -np.inf], np.nan).dropna()
        if iv.empty:
            return self.warmup_proposal(view, "no volatility estimate for the picks"), state
        w = iv / iv.sum()
        notes: tuple[str, ...] = ()
        trend = self.feature("trend_10m", view, list(w.index))
        if self.trend_filter:
            keep = trend > 0
            dropped = [a for a in w.index if not keep[a]]
            if dropped:
                notes = (f"below 10M average, held in cash: {', '.join(dropped)}",)
            w = w[keep]
        signals = {f"score:{a}": float(v) for a, v in score.dropna().items()}
        signals.update({f"trend:{a}": float(v) for a, v in trend.items()})
        strength = dispersion_strength(
            score, picks, float(self.confidence_rule.get("params", {}).get("scale", 1.0))
        )
        return self.proposal(view, w.to_dict(), strength, signals, notes), state
