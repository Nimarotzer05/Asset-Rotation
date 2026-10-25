"""Transaction and carry costs (docs/ARCHITECTURE.md §6).

Costs are fractions of equity: trading a weight change Δw in asset i costs |Δw| · bps_i / 10 000; the cash
leg (key `CASH`) costs `cash_bps` (0 in production; some studies charged it, see the golden runs). Shorts
pay `borrow_bps` p.a. on their absolute weight, accrued per calendar day.
"""

from __future__ import annotations

from collections.abc import Mapping

from rotationlab.config.models import CostSpec, UniverseConfig
from rotationlab.core.types import CASH, AssetId


class CostModel:
    def __init__(
        self,
        bps: Mapping[str, float] | None = None,
        default_bps: float = 10.0,
        cash_bps: float = 0.0,
        borrow_bps: Mapping[str, float] | None = None,
    ) -> None:
        self._bps = dict(bps or {})
        self.default_bps = float(default_bps)
        self.cash_bps = float(cash_bps)
        self._borrow = dict(borrow_bps or {})

    @classmethod
    def from_config(cls, spec: CostSpec, universe: UniverseConfig) -> CostModel:
        """`default_bps=None`: each asset's cost_bps from universe.yaml; otherwise one rate for all."""
        if spec.default_bps is None:
            bps = {a: c.cost_bps for a, c in universe.assets.items()}
            default = 10.0
        else:
            bps, default = {}, float(spec.default_bps)
        bps.update(spec.per_asset)
        borrow = {a: c.borrow_bps for a, c in universe.assets.items() if c.borrow_bps}
        return cls(bps, default, spec.cash_bps, borrow)

    def bps(self, asset: str) -> float:
        if asset == CASH:
            return self.cash_bps
        return float(self._bps.get(asset, self.default_bps))

    def cost(
        self,
        trades: Mapping[AssetId, float] | Mapping[str, float],
        prices: Mapping[AssetId, float] | None = None,
    ) -> float:
        return float(sum(abs(dw) * self.bps(str(a)) for a, dw in trades.items()) / 1e4)

    def carry(self, weights: Mapping[AssetId, float] | Mapping[str, float], days: int) -> float:
        return float(
            sum(-w * self._borrow.get(str(a), 0.0) for a, w in weights.items() if w < 0) / 1e4 * days / 365
        )

    def turnover_cost(self, before: Mapping[str, float], after: Mapping[str, float]) -> float:
        """Cost of moving from one weight vector to another (both including the CASH key)."""
        keys = set(before) | set(after)
        return self.cost({k: after.get(k, 0.0) - before.get(k, 0.0) for k in keys})
