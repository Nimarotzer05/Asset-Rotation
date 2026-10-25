"""Strategy base: the shared plumbing of the five modules (docs/ARCHITECTURE.md §5).

A module is constructed from its `StrategySpec` (universe = risky assets + one cash asset, params, warmup),
its confidence rule and its stop rules. `propose(view, state)` reads features through the registry only,
returns a `Proposal` with weights on the module's own capital (the remainder is cash) and the next state.
Modules never see the store, the book or another module; everything they need is in the view.

Helpers here are the research building blocks that more than one module uses (cross-sectional z-scores
and ranks, top-n selection), written so that ties and missing values behave exactly like the studies.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from rotationlab.core.errors import ConfigError
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import (
    AssetId,
    Months,
    Proposal,
    StopRule,
    StrategyId,
    StrategySpec,
    StrategyState,
)
from rotationlab.features import feature


class BaseStrategy:
    strategy_id: ClassVar[str] = "base"
    horizon_months: ClassVar[int] = 1

    def __init__(
        self,
        spec: StrategySpec,
        confidence: Mapping[str, Any] | None = None,
        stops: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.spec = spec
        self.params: Mapping[str, Any] = spec.params
        self.cash = AssetId(str(spec.params.get("cash", "CASH")))
        self.assets: tuple[AssetId, ...] = tuple(a for a in spec.universe if a != self.cash)
        self.confidence_rule = dict(confidence or {"kind": "score_dispersion", "floor": 0.5})
        self.stop_rules = [dict(s) for s in stops]

    # -- protocol ------------------------------------------------------------------
    def warmup(self) -> Months:
        return self.spec.warmup

    def initial_state(self) -> StrategyState:
        return StrategyState(StrategyId(self.spec.strategy_id))

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        raise NotImplementedError

    # -- helpers -------------------------------------------------------------------
    def confidence(self, strength: float) -> float:
        """Map a signal strength in [0, 1] to [floor, 1] (ADR 012)."""
        floor = float(self.confidence_rule.get("floor", 0.5))
        s = 0.0 if not math.isfinite(strength) else min(max(strength, 0.0), 1.0)
        return floor + (1.0 - floor) * s

    def proposal(
        self,
        view: MarketView,
        weights: Mapping[str, float],
        strength: float,
        signals: Mapping[str, float] | None = None,
        notes: Sequence[str] = (),
        stops: Sequence[StopRule] = (),
        warmup: bool = False,
    ) -> Proposal:
        clean = {AssetId(a): float(w) for a, w in weights.items() if abs(w) > 1e-15}
        return Proposal(
            strategy_id=StrategyId(self.spec.strategy_id),
            date=view.date,
            weights=clean,
            confidence=self.confidence(0.0 if warmup else strength),
            horizon_months=self.horizon_months,
            signals={k: float(v) for k, v in (signals or {}).items()},
            stops=tuple(stops),
            notes=tuple(notes),
            warmup=warmup,
        )

    def warmup_proposal(self, view: MarketView, reason: str) -> Proposal:
        return self.proposal(view, {}, 0.0, notes=(f"warmup: {reason}",), warmup=True)

    def feature(self, name: str, view: MarketView, assets: Sequence[str] | None = None, **params: Any) -> Any:
        return feature(name).call(view, assets, **params)


# ---------------------------------------------------------------------------
# research building blocks
# ---------------------------------------------------------------------------
def zscore(x: pd.Series, clip: float = 3.0) -> pd.Series:
    """Cross-sectional z-score over the assets with a value (sample SD), clipped (src/signals.py)."""
    sd = x.std()
    if not np.isfinite(sd) or sd == 0:
        return x * np.nan
    return ((x - x.mean()) / sd).clip(-clip, clip)


def weighted_composite(scores: Mapping[str, pd.Series], weights: Mapping[str, float]) -> pd.Series:
    """Σ w_k/Σw · score_k; an asset missing in one score keeps the sum of the others (research `add(fill=0)`),
    an asset missing in all is NaN."""
    total = sum(weights.values())
    out: pd.Series | None = None
    for name, w in weights.items():
        z = scores[name] * (w / total)
        out = z if out is None else out.add(z, fill_value=0)
    assert out is not None
    return out


def top_n(score: pd.Series, n: int) -> list[str]:
    """The n highest scores, in the order research used (pandas sort, ties as pandas breaks them)."""
    return [str(a) for a in score.dropna().sort_values(ascending=False).index[:n]]


def dispersion_strength(score: pd.Series, picks: Sequence[str], scale: float = 1.0) -> float:
    """How far the picks stand out: (mean score of picks − mean of all) / SD of all, divided by `scale`."""
    s = score.dropna()
    if len(s) < 2 or not picks or s.std() == 0:
        return 0.0
    return float((s[list(picks)].mean() - s.mean()) / s.std() / scale)


def check_window(name: str, value: Any, supported: int) -> None:
    if value is not None and int(value) != supported:
        raise ConfigError(f"{name} = {value}: only {supported} is implemented (the registered feature)")


def deep_merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
