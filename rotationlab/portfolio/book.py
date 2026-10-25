"""Book: positions, cash, marks and the equity curve; the same class in backtest and live (§6).

Holdings are units of each asset's total-return index (dividends and coupons are in the price), so marking
is units × level. Cash is held in units of the run's cash asset (T-bill index; `CASH` in production) and
appears in weights under the key `CASH`. Shorts are negative units; their proceeds sit in cash.

`rebalance(targets, prices, when)`: marks at `prices`, trades from the drifted weights to the target
weights, pays costs out of equity, and records turnover. Weights of the targets that are not CASH must
have a price; the remainder of the targets is cash.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any

from rotationlab.core.errors import DataError
from rotationlab.core.types import CASH, AssetId, RiskAction, Targets
from rotationlab.portfolio.costs import CostModel


class Book:
    def __init__(self, cash_asset: str, costs: CostModel, capital: float = 100.0) -> None:
        self.cash_asset = str(cash_asset)
        self.costs = costs
        self.units: dict[str, float] = {}
        self.cash_units: float | None = None
        self.cash_value = float(capital)  # until the cash asset has a price
        self.prices: dict[str, float] = {}
        self.last_mark: date | None = None
        self.history: list[tuple[date, float]] = []
        self.trades: list[dict[str, Any]] = []
        self._peak = float(capital)

    # -- valuation -----------------------------------------------------------------
    def _cash(self) -> float:
        if self.cash_units is None:
            return self.cash_value
        return self.cash_units * self.prices[self.cash_asset]

    def equity(self) -> float:
        return float(sum(u * self.prices[a] for a, u in self.units.items()) + self._cash())

    def weights(self) -> Mapping[AssetId, float]:
        e = self.equity()
        w = {AssetId(a): u * self.prices[a] / e for a, u in self.units.items() if u}
        w[CASH] = self._cash() / e
        return w

    def drawdown(self) -> float:
        return self.equity() / self._peak - 1

    # -- marking ---------------------------------------------------------------------
    def mark(self, prices: Mapping[AssetId, float] | Mapping[str, float], when: date) -> None:
        for a, p in prices.items():
            if p is not None and math.isfinite(p) and p > 0:
                self.prices[str(a)] = float(p)
        if self.cash_units is None and self.cash_asset in self.prices:
            self.cash_units = self.cash_value / self.prices[self.cash_asset]
        missing = [a for a in self.units if a not in self.prices]
        if missing:
            raise DataError(f"book: no price for held asset(s) {missing} at {when}")
        if self.last_mark is not None and when > self.last_mark:
            days = (when - self.last_mark).days
            carry = self.costs.carry(self.weights(), days) * self.equity()
            if carry:
                self._pay(carry)
        if self.last_mark is None or when >= self.last_mark:
            self.last_mark = when
        e = self.equity()
        self._peak = max(self._peak, e)
        if self.history and self.history[-1][0] == when:
            self.history[-1] = (when, e)
        else:
            self.history.append((when, e))

    def _pay(self, amount: float) -> None:
        if self.cash_units is None:
            self.cash_value -= amount
        else:
            self.cash_units -= amount / self.prices[self.cash_asset]

    # -- trading ---------------------------------------------------------------------
    def rebalance(
        self, targets: Targets, prices: Mapping[AssetId, float] | Mapping[str, float], when: date
    ) -> float:
        self.mark(prices, when)
        target = {str(a): float(w) for a, w in targets.weights.items() if str(a) != CASH and abs(w) > 1e-15}
        for a in target:
            if a not in self.prices:
                raise DataError(f"book: cannot trade {a} at {when}: no price")
        target[str(CASH)] = 1.0 - sum(target.values())
        before = {str(a): w for a, w in self.weights().items()}
        trades = {a: target.get(a, 0.0) - before.get(a, 0.0) for a in set(target) | set(before)}
        e = self.equity()
        cost = self.costs.cost(trades) * e
        e_after = e - cost
        self.units = {a: w * e_after / self.prices[a] for a, w in target.items() if a != CASH}
        if self.cash_units is None:
            self.cash_value = target[CASH] * e_after
        else:
            self.cash_units = target[CASH] * e_after / self.prices[self.cash_asset]
        turnover = sum(abs(dw) for dw in trades.values()) / 2  # one-way, cash leg included
        self.trades.append(
            {"date": when, "turnover": turnover, "cost": cost / e if e else 0.0, "equity": e_after}
        )
        if self.history and self.history[-1][0] == when:
            self.history[-1] = (when, e_after)
        return cost

    def apply(
        self, action: RiskAction, prices: Mapping[AssetId, float] | Mapping[str, float], when: date
    ) -> None:
        """Risk action (Phase 3): close / halve / scale the positions in scope (all if scope is empty)."""
        self.mark(prices, when)
        factor = {"close": 0.0, "halve": 0.5}.get(action.action, action.factor)
        w = {str(a): x for a, x in self.weights().items() if str(a) != CASH}
        scope = {str(a) for a in action.scope} or set(w)
        new = {a: (x * factor if a in scope else x) for a, x in w.items()}
        self.rebalance(
            Targets(when, {AssetId(a): x for a, x in new.items()}, {}, 1.0, (action.rule,)), {}, when
        )

    def snapshot(self) -> Mapping[str, Any]:
        return {
            "date": self.last_mark.isoformat() if self.last_mark else None,
            "equity": self.equity(),
            "weights": {str(a): float(w) for a, w in self.weights().items()},
            "drawdown": self.drawdown(),
        }
