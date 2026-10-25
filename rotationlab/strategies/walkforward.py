"""WalkForward: parameter choice without hindsight, itself a Strategy (docs/ARCHITECTURE.md §5).

It runs every grid candidate alongside, books each candidate's monthly net return in its state (weights of
the previous decision × asset returns up to this decision, minus the cost of that previous rebalance on
target weights), and proposes what the currently chosen candidate proposes. The first choice is made at
the `min_train`-th decision date, then every `refit_every` decisions, by the highest Sharpe of net excess
returns over cash on all months so far – the procedure of src/backtest.py::walk_forward. Before the first
choice it proposes cash (warm-up).

Because candidates see only the view at D and their own state, the choice at D uses only returns realised
by D; the look-ahead harness checks it like any other strategy.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.protocols import MarketView, Strategy
from rotationlab.core.types import (
    CASH,
    AssetId,
    Months,
    Proposal,
    StrategyId,
    StrategySpec,
    StrategyState,
)

TurnoverCost = Callable[[Mapping[str, float], Mapping[str, float]], float]


def grid_points(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(grid[k] for k in keys))]


def label(point: Mapping[str, Any]) -> str:
    return ",".join(f"{k}={v}" for k, v in point.items())


def _state_to_json(s: StrategyState) -> dict[str, Any]:
    d = asdict(s)
    d["tranches"] = [dict(t) for t in s.tranches]
    return d


def _state_from_json(d: Mapping[str, Any]) -> StrategyState:
    return StrategyState(
        StrategyId(d["strategy_id"]),
        positions=dict(d.get("positions", {})),
        entries=dict(d.get("entries", {})),
        tranches=tuple(dict(t) for t in d.get("tranches", ())),
        extra=dict(d.get("extra", {})),
    )


def sharpe(x: Sequence[float]) -> float:
    a = np.asarray(x, dtype=float)
    if len(a) < 2:
        return -math.inf
    sd = a.std(ddof=1)
    return -math.inf if sd == 0 or not np.isfinite(sd) else float(a.mean() / sd * math.sqrt(12))


class WalkForward:
    """Strategy that delegates to the grid candidate with the best track record so far."""

    def __init__(
        self,
        base_spec: StrategySpec,
        candidates: Mapping[str, Strategy],
        refit_every: int,
        min_train: int,
        turnover_cost: TurnoverCost,
        cash: str,
    ) -> None:
        self.candidates = dict(candidates)
        self.refit_every = int(refit_every)
        self.min_train = int(min_train)
        self.turnover_cost = turnover_cost
        self.cash = AssetId(cash)
        self.spec = StrategySpec(
            strategy_id=StrategyId(base_spec.strategy_id),
            version=base_spec.version,
            role=base_spec.role,
            cadence=base_spec.cadence,
            universe=base_spec.universe,
            warmup=Months(max(min_train, base_spec.warmup.n)),
            params={
                "walkforward": {
                    "candidates": list(self.candidates),
                    "refit_every": refit_every,
                    "min_train": min_train,
                },
                "base": dict(base_spec.params),
            },
        )

    def warmup(self) -> Months:
        return self.spec.warmup

    def initial_state(self) -> StrategyState:
        st = _WF(
            cands={k: _state_to_json(c.initial_state()) for k, c in self.candidates.items()},
            weights={k: {} for k in self.candidates},
            cost=dict.fromkeys(self.candidates, 0.0),
            excess={k: [] for k in self.candidates},
        )
        return StrategyState(self.spec.strategy_id, extra=st.to_extra())

    def _book_returns(self, view: MarketView, st: _WF) -> None:
        if st.prev_date is None:
            return
        assets = sorted({a for w in st.weights.values() for a in w} | {str(self.cash)})
        tr = view.total_return(assets, "ME").ffill()
        before, after = tr.loc[: pd.Timestamp(st.prev_date)], tr.loc[: pd.Timestamp(view.date)]
        if before.empty or after.empty:
            return
        r = (after.iloc[-1] / before.iloc[-1] - 1).fillna(0.0)
        rc = float(r.get(str(self.cash), 0.0))
        for k, w in st.weights.items():
            invested = sum(w.values())
            gross = sum(wi * float(r.get(a, 0.0)) for a, wi in w.items()) + (1 - invested) * rc
            st.excess[k].append(gross - st.cost[k] - rc)

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        st = _WF.from_extra(state.extra)
        self._book_returns(view, st)
        proposals: dict[str, Proposal] = {}
        for k, cand in self.candidates.items():
            p, s = cand.propose(view, _state_from_json(st.cands[k]))
            proposals[k] = p
            st.cands[k] = _state_to_json(s)
            new_w = {str(a): float(w) for a, w in p.weights.items()}
            st.cost[k] = self.turnover_cost(_with_cash(st.weights[k]), _with_cash(new_w))
            st.weights[k] = new_w
        st.n += 1
        st.since += 1
        if (st.chosen is None and st.n >= self.min_train) or (
            st.chosen is not None and st.since >= self.refit_every
        ):
            scores = {k: sharpe(v) for k, v in st.excess.items()}
            chosen = max(scores, key=lambda k: scores[k])  # first candidate wins ties (grid order)
            st.chosen, st.since = chosen, 0
            st.choices.append(
                {"date": view.date.isoformat(), "chosen": chosen, "train_sharpe": scores[chosen]}
            )
        st.prev_date = view.date.isoformat()
        new_state = StrategyState(state.strategy_id, extra=st.to_extra())
        sid = StrategyId(self.spec.strategy_id)
        if st.chosen is None:
            note = f"warmup: walk-forward trains until decision {self.min_train}"
            return Proposal(sid, view.date, {}, 0.5, 1, notes=(note,), warmup=True), new_state
        p = proposals[st.chosen]
        return Proposal(
            sid,
            view.date,
            p.weights,
            p.confidence,
            p.horizon_months,
            signals=p.signals,
            stops=p.stops,
            notes=(*p.notes, f"walk-forward: {st.chosen}"),
            warmup=p.warmup,
        ), new_state


@dataclass
class _WF:
    """Walk-forward state; stored as plain JSON-able data in StrategyState.extra."""

    cands: dict[str, dict[str, Any]]
    weights: dict[str, dict[str, float]]
    cost: dict[str, float]
    excess: dict[str, list[float]]
    prev_date: str | None = None
    n: int = 0
    since: int = 0
    chosen: str | None = None
    choices: list[dict[str, Any]] = field(default_factory=list)

    def to_extra(self) -> dict[str, Any]:
        return {
            "cands": dict(self.cands),
            "weights": {k: dict(v) for k, v in self.weights.items()},
            "cost": dict(self.cost),
            "excess": {k: list(v) for k, v in self.excess.items()},
            "prev_date": self.prev_date,
            "n": self.n,
            "since": self.since,
            "chosen": self.chosen,
            "choices": [dict(c) for c in self.choices],
        }

    @classmethod
    def from_extra(cls, extra: Mapping[str, Any]) -> _WF:
        return cls(
            cands=dict(extra["cands"]),
            weights={k: dict(v) for k, v in extra["weights"].items()},
            cost=dict(extra["cost"]),
            excess={k: list(v) for k, v in extra["excess"].items()},
            prev_date=extra["prev_date"],
            n=int(extra["n"]),
            since=int(extra["since"]),
            chosen=extra["chosen"],
            choices=[dict(c) for c in extra["choices"]],
        )


def _with_cash(w: Mapping[str, float]) -> dict[str, float]:
    out = dict(w)
    out[str(CASH)] = 1.0 - sum(w.values())
    return out
