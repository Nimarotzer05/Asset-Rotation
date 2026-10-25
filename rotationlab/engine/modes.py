"""Building runs from configuration: module backtests, walk-forward and the golden runs.

    backtest(bundle, factory, "us_equity_exposure", universe="long_history", start=…, end=…)
    golden(bundle, observations, "multi_asset_rotation")          # reproduce the research figures
    walkforward_golden(bundle, observations, "multi_asset_rotation")

A golden run is the module, the research universe, the research sample and the research cost convention
(`golden_run` in the strategy YAML); `execution` defaults to the research convention (`same_close`) and can
be set to `next_close` to see what the production timing (ADR 011) costs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

from rotationlab.config.models import Bundle, CostSpec, GoldenRun
from rotationlab.core.clock import MonthEndClock
from rotationlab.core.protocols import TradingCalendar
from rotationlab.core.types import Mode
from rotationlab.data.catalog import build_catalog
from rotationlab.data.view import StoreViewFactory, asset_roles
from rotationlab.engine.core import Engine, Execution, RunResult
from rotationlab.engine.recorder import RunRecorder
from rotationlab.portfolio.book import Book
from rotationlab.portfolio.combine import SingleStrategy
from rotationlab.portfolio.costs import CostModel
from rotationlab.strategies import build_strategy, build_walkforward, strategy_spec

Universe = Literal["live", "long_history"]


def research_factory(
    bundle: Bundle,
    observations: pd.DataFrame,
    calendar: TradingCalendar,
    data_from: date | None = None,
    snapshot: str | None = None,
) -> StoreViewFactory:
    """A view factory over `observations`, optionally cut at the month of `data_from` (the research panel's
    first month: rolling windows and expanding statistics restart there, as in the studies)."""
    obs = observations
    if data_from is not None:
        first = pd.Timestamp(data_from).normalize() - pd.offsets.MonthBegin(1)
        obs = obs[pd.to_datetime(obs["obs_date"]) >= first]
    return StoreViewFactory(
        obs,
        build_catalog(bundle),
        asset_roles(bundle.universe),
        calendar,
        snapshot=snapshot,
        chains=bundle.series.chains,
    )


def backtest(
    bundle: Bundle,
    factory: StoreViewFactory,
    sid: str,
    universe: Universe = "live",
    start: date | None = None,
    end: date | None = None,
    execution: Execution = "next_close",
    costs: CostSpec | None = None,
    overrides: Mapping[str, Any] | None = None,
    recorder: RunRecorder | None = None,
    capital: float = 100.0,
) -> RunResult:
    strat = build_strategy(bundle, sid, universe, overrides)
    cash = str(strat.spec.params["cash"])
    cost_model = CostModel.from_config(costs or CostSpec(), bundle.universe)
    clock = MonthEndClock(factory.cal, start or date(1900, 1, 31), end or date.today())
    book = Book(cash, cost_model, capital)
    return Engine(factory, clock, [strat], SingleStrategy(), book, recorder, execution).run()


@dataclass
class GoldenReport:
    strategy: str
    execution: str
    measured: dict[str, float]
    expected: dict[str, float]
    tolerance: dict[str, float]
    result: RunResult
    extra: dict[str, Any] = field(default_factory=dict)

    def failures(self) -> list[str]:
        out = []
        for k, exp in self.expected.items():
            if k not in self.measured:
                continue
            tol = self.tolerance.get(k, 0.0)
            if not abs(self.measured[k] - exp) <= tol + 1e-12:
                out.append(f"{self.strategy}.{k}: {self.measured[k]:.4f} vs {exp:.4f} ± {tol}")
        return out

    def table(self) -> pd.DataFrame:
        rows = [
            {
                "metric": k,
                "research": v,
                "engine": self.measured.get(k),
                "tolerance": self.tolerance.get(k),
                "diff": (self.measured.get(k, float("nan")) - v),
            }
            for k, v in self.expected.items()
            if k in self.measured
        ]
        return pd.DataFrame(rows).set_index("metric")


def golden(
    bundle: Bundle,
    observations: pd.DataFrame,
    sid: str,
    calendar: TradingCalendar,
    execution: Execution | None = None,
    run: GoldenRun | None = None,
) -> GoldenReport:
    cfg = bundle.strategies[sid]
    gr = run or cfg.golden_run
    if gr is None:
        raise ValueError(f"strategy {sid} has no golden_run")
    ex: Execution = execution or gr.execution
    factory = research_factory(bundle, observations, calendar, gr.data_from)
    res = backtest(bundle, factory, sid, gr.universe, gr.start, gr.end, ex, gr.costs, gr.params)
    m = res.metrics(gr.sample[0], gr.sample[1], gr.count_warmup)
    return GoldenReport(sid, ex, m, dict(cfg.golden), dict(cfg.golden_tolerance), res)


def walkforward_golden(
    bundle: Bundle,
    observations: pd.DataFrame,
    sid: str,
    calendar: TradingCalendar,
    execution: Execution | None = None,
) -> GoldenReport:
    cfg = bundle.strategies[sid]
    gr, wf = cfg.golden_run, cfg.walkforward
    if gr is None or wf is None:
        raise ValueError(f"strategy {sid} needs golden_run and walkforward")
    ex: Execution = execution or gr.execution
    factory = research_factory(bundle, observations, calendar, gr.data_from)
    cost_model = CostModel.from_config(gr.costs, bundle.universe)
    strat = build_walkforward(bundle, sid, gr.universe, cost_model.turnover_cost, gr.params)
    spec = strategy_spec(bundle, sid, gr.universe, gr.params)
    clock = MonthEndClock(factory.cal, gr.start, gr.end)
    res = Engine(
        factory, clock, [strat], SingleStrategy(), Book(str(spec.params["cash"]), cost_model), None, ex
    ).run()
    sample = wf.golden_sample or gr.sample
    m = res.metrics(sample[0], sample[1], True)
    choices = res.states[sid].extra["choices"]
    return GoldenReport(
        f"{sid} (walk-forward)", ex, m, dict(wf.golden), dict(wf.golden_tolerance), res, {"choices": choices}
    )


def recorder_for(
    bundle: Bundle, factory: StoreViewFactory, mode: Mode, start: date, end: date, label: str
) -> RunRecorder:
    return RunRecorder(mode, bundle.hash(), factory.data_snapshot(), start, end, label)
