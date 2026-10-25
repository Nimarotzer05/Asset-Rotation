"""Combiners: proposals → portfolio targets.

Phase 2 needs two simple ones; the risk-budget combiner (EWMA covariances, vol target, confidence scaling,
ADR 006/012) is Phase 3.

* `SingleStrategy`: one module runs alone (goldens, module backtests); its weights are the targets.
* `CapitalWeights`: fixed capital shares per module (a transparent baseline for combined backtests).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from rotationlab.core.errors import ConfigError
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import CASH, AssetId, Proposal, StrategyId, Targets


class SingleStrategy:
    def combine(self, proposals: Sequence[Proposal], view: MarketView) -> Targets:
        if len(proposals) != 1:
            raise ConfigError(f"SingleStrategy combiner needs exactly one proposal, got {len(proposals)}")
        p = proposals[0]
        w = {AssetId(a): float(x) for a, x in p.weights.items()}
        w[CASH] = 1.0 - sum(w.values())
        return Targets(view.date, w, {p.strategy_id: dict(p.weights)}, 1.0, p.notes)


class CapitalWeights:
    def __init__(self, shares: Mapping[str, float]) -> None:
        total = sum(shares.values())
        if total <= 0:
            raise ConfigError("CapitalWeights: shares must be positive")
        self.shares = {k: v / total for k, v in shares.items()}

    def combine(self, proposals: Sequence[Proposal], view: MarketView) -> Targets:
        w: dict[AssetId, float] = {}
        by: dict[StrategyId, Mapping[AssetId, float]] = {}
        for p in proposals:
            s = self.shares.get(str(p.strategy_id), 0.0)
            by[p.strategy_id] = {a: x * s for a, x in p.weights.items()}
            for a, x in p.weights.items():
                w[AssetId(a)] = w.get(AssetId(a), 0.0) + x * s
        w[CASH] = 1.0 - sum(w.values())
        return Targets(view.date, w, by, 1.0)
