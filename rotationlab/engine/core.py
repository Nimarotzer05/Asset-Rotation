"""The engine: one loop for backtest, walk-forward and live (docs/ARCHITECTURE.md §7, ADR 001).

    for D in clock.decision_dates():
        view = views.at(D)
        book.mark(prices as of D)                       # the period ending at D is booked here
        proposals = [s.propose(view, state[s]) …]
        targets = combiner.combine(proposals, view)
        E = D (same_close) | next session (next_close, ADR 011) | next decision date (next_month_close)
        book.rebalance(targets, prices as of E)
        recorder.decision(D, proposals, targets, …)

Prices are total-return levels as of a date (the last value on or before it): a monthly series is priced
at its month-end on the following session, so `next_close` equals `same_close` for monthly-only data and
differs only where daily closes exist. `next_month_close` (ADR 042) trades the targets of D at the next
decision date, after that date's mark: the only execution whose price lies wholly after D for assets valued
at monthly *averages* (World Bank commodities), where `next_close` re-uses the average that made the
signal. `next_tradable` is the honest mix: assets with closing prices trade at the next session, assets valued
at monthly averages (`averaged`, from `price_basis` in universe.yaml) at the next decision date. The daily
risk loop between decisions (stops, drawdown, vol spike,
kill switch) belongs to Phase 3 and plugs in through `risk`.

Determinism: equal data snapshot, configuration and code ⇒ identical results; nothing here is random.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

from rotationlab.core.protocols import Clock, Combiner, MarketView, Recorder, Strategy, ViewFactory
from rotationlab.core.types import CASH, AssetId, Proposal, RiskReport, StrategyState, Targets
from rotationlab.engine import metrics
from rotationlab.portfolio.book import Book

Execution = Literal["same_close", "next_close", "next_month_close", "next_tradable"]
EXECUTION_LAG = {
    "same_close": 1,
    "next_close": 1,
    "next_month_close": 2,
    "next_tradable": 1,
}  # periods from decision to effect


def prices_at(view: MarketView, assets: Sequence[str]) -> dict[str, float]:
    """Total-return level of each asset as of view.date (last value on or before it; missing → absent)."""
    if not assets:
        return {}
    tr = view.total_return(list(assets), None)
    out: dict[str, float] = {}
    for a in assets:
        if a in tr.columns:
            s = tr[a].dropna()
            if len(s) and s.iloc[-1] > 0:
                out[a] = float(s.iloc[-1])
    return out


@dataclass
class RunResult:
    decisions: pd.DataFrame  # one row per decision date: equity, cash level, warmup, turnover, cost
    weights: pd.DataFrame  # target weights per decision date (incl. CASH)
    proposals: list[Proposal]
    states: dict[str, StrategyState]
    record: Mapping[str, Any] = field(default_factory=dict)
    execution_lag: int = 1  # decision at D shapes the return of the period ending `lag` periods later

    @property
    def returns(self) -> pd.Series:
        """Period return of the book, dated at the decision date that ends the period."""
        return self.decisions["equity"].pct_change().iloc[1:].rename("return")

    @property
    def cash_returns(self) -> pd.Series:
        return self.decisions["cash_level"].pct_change().iloc[1:].rename("cash")

    @property
    def active(self) -> pd.Series:
        """True for periods that followed a decision with a signal (not warm-up)."""
        lag = self.execution_lag
        return (~self.decisions["warmup"].shift(lag).fillna(True).astype(bool)).iloc[1:].rename("active")

    @property
    def turnover(self) -> pd.Series:
        return self.decisions["turnover"].shift(1).iloc[1:].rename("turnover")

    def sample(
        self, start: date | None = None, end: date | None = None, count_warmup: bool = True
    ) -> tuple[pd.Series, pd.Series]:
        r, c = self.returns, self.cash_returns
        mask = pd.Series(True, index=r.index)
        if start is not None:
            mask &= r.index >= pd.Timestamp(start)
        if end is not None:
            mask &= r.index <= pd.Timestamp(end)
        if not count_warmup:
            first = self.active[self.active].index.min() if self.active.any() else None
            mask &= (r.index >= first) if first is not None else False
        return r[mask], c[mask]

    def metrics(
        self, start: date | None = None, end: date | None = None, count_warmup: bool = True
    ) -> dict[str, float]:
        r, c = self.sample(start, end, count_warmup)
        return metrics.summary(r, c, self.turnover)


class Engine:
    def __init__(
        self,
        views: ViewFactory,
        clock: Clock,
        strategies: Sequence[Strategy],
        combiner: Combiner,
        book: Book,
        recorder: Recorder | None = None,
        execution: Execution = "next_close",
        risk: Any = None,
        averaged: Sequence[str] = (),
    ) -> None:
        self.views = views
        self.clock = clock
        self.strategies = list(strategies)
        self.combiner = combiner
        self.book = book
        self.recorder = recorder
        self.execution = execution
        self.risk = risk
        self.averaged = frozenset(str(a) for a in averaged)  # assets valued at monthly averages

    def run(self, states: Mapping[str, StrategyState] | None = None) -> RunResult:
        st = {
            s.spec.strategy_id: (states or {}).get(s.spec.strategy_id) or s.initial_state()
            for s in self.strategies
        }
        universe = sorted({str(a) for s in self.strategies for a in s.spec.universe} | {self.book.cash_asset})
        rows: list[dict[str, Any]] = []
        weights: list[dict[str, Any]] = []
        proposals_all: list[Proposal] = []
        pending: Targets | None = None  # next_month_close: targets of the previous decision, not yet traded
        for d in self.clock.decision_dates():
            view = self.views.at(d)
            held = sorted(set(self.book.units) | {self.book.cash_asset})
            self.book.mark(prices_at(view, held), d)
            equity = self.book.equity()
            cash_level = self.book.prices.get(self.book.cash_asset, math.nan)
            trade: dict[str, Any] = {"turnover": 0.0, "cost": 0.0}
            executed: date | None = None
            if pending is not None:  # deferred part of the previous decision trades at this close
                if self.execution == "next_tradable":
                    trade = self._execute_part(pending, view, d, self.averaged)
                else:
                    trade = self._execute(pending, view, d)
                executed, pending = d, None
            proposals = []
            for s in self.strategies:
                p, st[s.spec.strategy_id] = s.propose(view, st[s.spec.strategy_id])
                proposals.append(p)
            targets: Targets = self.combiner.combine(proposals, view)
            if self.execution == "next_month_close":
                pending = targets
            elif self.execution == "next_tradable" and self.averaged:
                e = self.clock.execution_day(d)
                now = self._execute_part(targets, self.views.at(e), e, None)
                trade = {k: trade[k] + now[k] for k in trade}
                executed, pending = e, targets
            else:
                e = d if self.execution == "same_close" else self.clock.execution_day(d)
                trade, executed = self._execute(targets, view if e == d else self.views.at(e), e), e
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "equity": equity,
                    "cash_level": cash_level,
                    "warmup": all(p.warmup for p in proposals),
                    "turnover": trade["turnover"],
                    "cost": trade["cost"],
                    "execution": pd.Timestamp(executed) if executed else pd.NaT,
                }
            )
            weights.append(
                {"date": pd.Timestamp(d), **{str(a): float(w) for a, w in targets.weights.items()}}
            )
            proposals_all.extend(proposals)
            if self.recorder is not None:
                report = RiskReport(
                    d,
                    (),
                    math.nan,
                    sum(abs(w) for a, w in targets.weights.items() if a != CASH),
                    sum(w for a, w in targets.weights.items() if a != CASH),
                )
                self.recorder.decision(d, proposals, targets, report, self.book.snapshot())
        decisions = (
            pd.DataFrame(rows).set_index("date")
            if rows
            else pd.DataFrame(columns=["equity", "cash_level", "warmup", "turnover", "cost", "execution"])
        )
        w = (
            pd.DataFrame(weights)
            .set_index("date")
            .reindex(columns=[*(a for a in universe if a != CASH), CASH])
            .fillna(0.0)
            if weights
            else pd.DataFrame()
        )
        w = w.loc[:, (w != 0).any(axis=0)] if len(w) else w
        if self.recorder is not None:
            self.recorder.finish("ok")
        return RunResult(
            decisions,
            w,
            proposals_all,
            {str(k): v for k, v in st.items()},
            execution_lag=EXECUTION_LAG[self.execution],
        )

    def _execute_part(
        self, targets: Targets, view: MarketView, e: date, only: frozenset[str] | None
    ) -> dict[str, Any]:
        """Trade part of `targets`: the averaged assets (`only` = that set) or every other asset (`only` =
        None); the rest keeps its current (drifted) weight, cash absorbs the difference."""
        held = sorted(set(self.book.units) | {self.book.cash_asset})
        self.book.mark(prices_at(view, held), e)
        current = {str(a): w for a, w in self.book.weights().items() if str(a) != CASH}
        names = {str(a) for a in targets.weights if str(a) != CASH} | set(current)

        def trades_now(a: str) -> bool:
            return (a in self.averaged) if only is not None else (a not in self.averaged)

        mixed = {
            AssetId(a): (
                float(targets.weights.get(AssetId(a), 0.0)) if trades_now(a) else current.get(a, 0.0)
            )
            for a in sorted(names)
        }
        return self._execute(Targets(e, mixed, targets.by_strategy, targets.scale, targets.notes), view, e)

    def _execute(self, targets: Targets, view: MarketView, e: date) -> dict[str, Any]:
        """Rebalance the book to `targets` at the prices of `view` (date `e`); turnover and cost as a share
        of the equity before the trade."""
        needed = sorted(
            {str(a) for a in targets.weights if str(a) != CASH}
            | set(self.book.units)
            | {self.book.cash_asset}
        )
        equity = self.book.equity()
        cost = self.book.rebalance(targets, prices_at(view, needed), e)
        return {"turnover": self.book.trades[-1]["turnover"], "cost": cost / equity if equity else 0.0}


def target_weights(proposal: Proposal) -> dict[AssetId, float]:
    w = {AssetId(a): float(x) for a, x in proposal.weights.items()}
    w[CASH] = 1.0 - sum(w.values())
    return w
