"""Forecast portfolio (ADR 048, step P8): the pre-registered rule on the forecast's ranking.

    1. ranking   the composite of the forecast model (ADR 043: z-scores of 3-1, 6-1, 12-1 momentum, distance
                 to the 10-month average, inverse volatility; weights 0.2/0.3/0.3/0.2/0.1; clipped at ±3)
                 over the ranked classes – the same formula as `rotationlab.forecast.model`, computed here
                 pointwise through the registry (ADR 036: panel ≡ pointwise, tested against the forecast)
    2. picks     the `top_n` (2) highest scores, equal-weighted on the risky sleeve
    3. trend     a pick below its 10-month average hands its share to cash (`trend_filter`)
    4. vol       the sleeve is scaled by min(vol_target / σ, max_exposure); σ = annualised standard deviation
                 of the last 12 monthly returns of the sleeve with today's weights (`sleeve_vol_12m`), floored
                 at `vol_floor`; `max_exposure` 1.0 = no leverage (the pre-registered rule; 1.5 is a named
                 sensitivity, ADR 048 f)

Role `paper`: outside the risk budgets of the frozen portfolio system. Nothing adapts; every parameter is
fixed in `configs/strategies/forecast_portfolio.yaml` before the first run. Confidence: score dispersion of
the picks (the house rule), unused by the paper track.
"""

from __future__ import annotations

import math

import pandas as pd

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import Proposal, StrategyState
from rotationlab.strategies.base import (
    BaseStrategy,
    check_window,
    dispersion_strength,
    weighted_composite,
    zscore,
)

FEATURES = (
    "mom_3_1",
    "mom_6_1",
    "mom_12_1",
    "mom_12",
    "trend_10m",
    "inv_vol_12m",
    "value_rev_60m",
    "carry_yield",
)


def top_picks(score: pd.Series, n: int) -> list[str]:
    """The n highest scores, ties broken by position like the forecast's `ranks_of` (rank method 'first')."""
    r = score.rank(ascending=False, method="first")
    return [str(a) for a in sorted((a for a in score.index if r[a] <= n), key=lambda a: float(r[a]))]


@registry.strategy
class ForecastPortfolio(BaseStrategy):
    strategy_id = "forecast_portfolio"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        p = self.params
        check_window("trend_window_months", p.get("trend_window_months"), 10)
        check_window("vol_window_months", p.get("vol_window_months"), 12)
        self.weights = dict(p["feature_weights"])
        unknown = set(self.weights) - set(FEATURES)
        if unknown:
            raise ValueError(f"forecast_portfolio: unsupported features {sorted(unknown)}")
        self.clip = float(p.get("zscore_clip", 3.0))
        self.feature_params = {k: dict(v) for k, v in dict(p.get("feature_params", {})).items()}
        self.n = int(p.get("top_n", 2))
        self.trend_filter = bool(p.get("trend_filter", True))
        self.vol_target = float(p.get("vol_target", 0.10))
        self.vol_floor = float(p.get("vol_floor", 0.05))
        self.max_exposure = float(p.get("max_exposure", 1.0))
        if self.n < 1 or self.n > len(self.assets):
            raise ValueError(f"forecast_portfolio: top_n must be between 1 and {len(self.assets)}")
        if not (self.vol_target > 0 and self.vol_floor > 0 and self.max_exposure > 0):
            raise ValueError("forecast_portfolio: vol_target, vol_floor and max_exposure must be positive")

    def composite(self, view: MarketView) -> pd.Series:
        """The forecast's score at D (ranked classes only)."""
        assets = list(self.assets)
        z = {
            k: zscore(self.feature(k, view, assets, **self.feature_params.get(k, {})), self.clip)
            for k in self.weights
        }
        return weighted_composite(z, self.weights).rename("composite")

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        score = self.composite(view)
        if score.notna().sum() < len(self.assets):
            return self.warmup_proposal(view, "not every ranked class has a score"), state
        picks = top_picks(score, self.n)
        sleeve = pd.Series(1.0 / self.n, index=picks)  # equal-weighted risky sleeve
        trend = self.feature("trend_10m", view, picks)
        notes: list[str] = []
        if self.trend_filter:
            keep = trend > 0  # NaN trend → not above its average → cash (as in multi_asset_rotation)
            dropped = [a for a in picks if not bool(keep[a])]
            if dropped:
                notes.append(f"below 10M average, held in cash: {', '.join(dropped)}")
            sleeve = sleeve[[a for a in picks if bool(keep[a])]]
        signals = {f"score:{a}": float(v) for a, v in score.items()}
        signals.update({f"trend:{a}": float(v) for a, v in trend.items()})
        scale = 1.0
        if len(sleeve):
            vol = float(self.feature("sleeve_vol_12m", view, weights=sleeve.to_dict()))
            if math.isnan(vol):
                return self.warmup_proposal(view, "no 12-month volatility for the sleeve"), state
            scale = min(self.vol_target / max(vol, self.vol_floor), self.max_exposure)
            signals["sleeve_vol_12m"] = vol
            signals["scale"] = scale
            if scale < 1.0:
                notes.append(f"sleeve vol {vol:.1%} > target {self.vol_target:.0%}: scaled to {scale:.2f}")
        w: dict[str, float] = {str(a): float(x) * scale for a, x in sleeve.items()}
        strength = dispersion_strength(
            score, picks, float(self.confidence_rule.get("params", {}).get("scale", 1.0))
        )
        return self.proposal(view, w, strength, signals, tuple(notes)), state


@registry.strategy
class ForecastPortfolioV2(ForecastPortfolio):
    """The same rule on the round-2 forecast (configs/forecast_v2.yaml, ADR 052): five classes, three families.
    A strategy id of its own keeps the two paper rules, their goldens and their journals apart."""

    strategy_id = "forecast_portfolio_v2"
