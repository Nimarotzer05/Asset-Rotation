"""Precious metals satellite: gold/silver ratio mean reversion plus a crash hedge, dollar-neutral.

Position p ∈ [−1, 1]: +p long gold, −p short silver (equal notional; the spread is self-financing).

1. Mean reversion (scripts/run_gold_silver.py §4; ADR 013): signal = clip(−z60 / 2, −1, 1), z60 = z-score of
   log(gold/silver) against its last 60 months; held in overlapping 6-month tranches (the position is the
   mean of the last six monthly signals, so every decision is held six months). 1976–2026: Sharpe 0.22.
2. Crash hedge (scripts/run_derisk.py; ADR 018): long gold / short silver gained in all 8 equity
   drawdowns > 15 % since 1971. Always-on base share, raised to the full sleeve when insurance is cheap:
   hedge = base + (1 − base) · [z60 < cheap] · ramp(risk-appetite percentile from 50 % to `full_at`).
   Low ratio and high risk appetite was the cell with the best 12-month gold-over-silver record (79 %).

p = clip(mr + hedge, −1, 1). Stop: the ratio moves 15 % against the position from entry → close (checked
daily by the risk layer, Phase 3; the rule carries the entry ratio as reference).

Confidence: |z60| / 2, capped at 1 (`abs_z`).
"""

from __future__ import annotations

import math
from typing import Any

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import AssetId, Proposal, StopRule, StrategyState
from rotationlab.strategies.base import BaseStrategy


@registry.strategy
class PreciousMetals(BaseStrategy):
    strategy_id = "precious_metals"
    horizon_months = 6

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        p = self.params
        self.trade = dict(p.get("trade", {"gold": "GLD", "silver": "SLV"}))
        self.signal_assets = dict(p.get("signal", {"gold": "XAU", "silver": "XAG"}))
        self.mr = dict(p.get("mean_reversion", {}))
        self.hedge = dict(p.get("hedge", {}))
        self.ra = dict(p.get("risk_appetite", {}))
        if int(self.mr.get("z_window_months", 60)) != 60 or int(self.mr.get("z_min_periods", 30)) != 30:
            raise ValueError("precious_metals: the ratio z-score is the registered 60-month (min 30) feature")

    def _ratio_feature(self, name: str, view: MarketView) -> float:
        return float(
            self.feature(name, view, gold=self.signal_assets["gold"], silver=self.signal_assets["silver"])
        )

    def _hedge(self, view: MarketView, z: float) -> tuple[float, float]:
        if not self.hedge.get("enabled", True):
            return 0.0, math.nan
        base = float(self.hedge.get("base", 0.25))
        pct = float(
            self.feature(
                "risk_appetite_pct",
                view,
                equity=self.ra.get("equity", "US_EQ"),
                start=self.ra.get("start"),
                min_history=int(self.ra.get("min_history_months", 60)),
            )
        )
        full_at = float(self.hedge.get("risk_appetite_full_at_pct", 0.8))
        ramp = 0.0 if math.isnan(pct) else min(max((pct - 0.5) / (full_at - 0.5), 0.0), 1.0)
        cheap = (not math.isnan(z)) and z < float(self.hedge.get("ratio_z_cheap_below", -1.0))
        return base + (1 - base) * (ramp if cheap else 0.0), pct

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        z = self._ratio_feature("gs_ratio_z60", view)
        ratio = self._ratio_feature("gs_ratio", view)
        scale = float(self.mr.get("position_scale", 2.0))
        signal = 0.0 if math.isnan(z) else min(max(-z / scale, -1.0), 1.0)
        n = int(self.mr.get("tranche_months", 6))
        g, s = AssetId(self.trade["gold"]), AssetId(self.trade["silver"])
        tranches = (*state.tranches, {g: signal, s: -signal})[-n:]
        mr_pos = sum(t.get(g, 0.0) for t in tranches) / len(tranches)
        hedge, pct = self._hedge(view, z)
        pos = min(max(mr_pos + hedge, -1.0), 1.0)

        entries: dict[str, Any] = dict(state.entries)
        prev_sign = math.copysign(1.0, entries["position"]) if entries.get("position") else 0.0
        sign = math.copysign(1.0, pos) if pos else 0.0
        if sign != prev_sign and not math.isnan(ratio):
            entries["ratio_entry"] = ratio
        entries["position"] = pos
        stops = tuple(
            StopRule(
                kind=r["kind"],
                scope=(g, s),
                threshold=float(r["threshold"]),
                action=r["action"],
                reference=entries.get("ratio_entry"),
            )
            for r in self.stop_rules
            if pos
        )
        new_state = StrategyState(
            state.strategy_id, positions={g: pos, s: -pos}, entries=entries, tranches=tranches
        )
        signals = {
            "gs_ratio": ratio,
            "gs_ratio_z60": z,
            "mr_signal": signal,
            "mr_position": mr_pos,
            "hedge": hedge,
            "risk_appetite_pct": pct,
            "position": pos,
        }
        if math.isnan(z) and not hedge:
            return self.proposal(
                view, {}, 0.0, signals, ("warmup: ratio z-score history too short",), warmup=True
            ), new_state
        full_at = float(self.confidence_rule.get("params", {}).get("full_at", 2.0))
        strength = 0.0 if math.isnan(z) else abs(z) / full_at
        return self.proposal(view, {g: pos, s: -pos}, strength, signals, stops=stops), new_state
