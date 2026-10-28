"""Fixed-weight baselines through the same engine as the strategies (ADR 048 b).

    weights     target weight per asset (the rest is cash); `rebalance: monthly` restores them at every
                decision, `rebalance: never` lets them drift from the first decision on (buy and hold)

Buy and hold needs the engine to re-propose the *drifted* weights: the module keeps the total-return
levels of its first decision in its state and proposes w_0 · L_t / L_0 (fully invested: the weights must
sum to 1, so no cash leg drifts unseen). With one asset at 100 % this is exact (always 1.0, no trade after
the first); with several assets the proposal is the drift at the decision close, so an execution at a
later session trades the drift between the two closes – a few basis points, not a rebalancing.

Role `paper`: a baseline, not a strategy; no confidence, no stops, no warm-up beyond the first price. The
module reads total-return levels through the view (a level is not a feature); the look-ahead harness
covers it like every registered module.
"""

from __future__ import annotations

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import Proposal, StrategyState
from rotationlab.strategies.base import BaseStrategy


@registry.strategy
class FixedWeights(BaseStrategy):
    strategy_id = "fixed_weights"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        w = {str(a): float(x) for a, x in dict(self.params["weights"]).items()}
        unknown = set(w) - {str(a) for a in self.assets}
        if unknown:
            raise ValueError(f"fixed_weights: weights for assets outside the universe {sorted(unknown)}")
        if any(x < 0 for x in w.values()) or sum(w.values()) > 1.0 + 1e-12:
            raise ValueError("fixed_weights: weights must be non-negative and sum to at most 1")
        self.weights = w
        self.rebalance = str(self.params.get("rebalance", "monthly"))
        if self.rebalance not in ("monthly", "never"):
            raise ValueError("fixed_weights: rebalance must be 'monthly' or 'never'")
        if self.rebalance == "never" and abs(sum(w.values()) - 1.0) > 1e-12:
            raise ValueError("fixed_weights: 'never' (buy and hold) needs weights that sum to 1")

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        levels = view.total_return(list(self.weights), "ME")
        last = levels.iloc[-1] if len(levels) else None
        if last is None or last.reindex(list(self.weights)).isna().any():
            return self.warmup_proposal(view, "no price for every asset yet"), state
        if self.rebalance == "monthly":
            return self.proposal(view, self.weights, 1.0), state
        extra = dict(state.extra)
        if "levels" not in extra:
            extra["levels"] = {a: float(last[a]) for a in self.weights}
        base = extra["levels"]
        grown = {a: w * float(last[a]) / float(base[a]) for a, w in self.weights.items()}
        total = sum(grown.values())
        w = {a: g / total for a, g in grown.items()} if total > 0 else dict(self.weights)
        new_state = StrategyState(
            state.strategy_id, positions=state.positions, entries=state.entries, extra=extra
        )
        return self.proposal(view, w, 1.0), new_state
