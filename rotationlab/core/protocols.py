"""Contracts between layers.

Each layer depends only on the protocols of the layer directly below it. Implementations live
in their own packages; nothing imports a concrete class across layers. Tests in
tests/test_contracts.py assert that every registered implementation satisfies these protocols.
"""

from __future__ import annotations

import datetime as _dt  # MarketView has an attribute called `date`
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from rotationlab.core.types import (
    AssetId,
    Months,
    Observation,
    Proposal,
    RiskAction,
    RiskReport,
    SeriesId,
    SeriesSpec,
    StrategySpec,
    StrategyState,
    Targets,
)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
@runtime_checkable
class Provider(Protocol):
    """Fetches one series. Stateless and idempotent: the store decides what is new.

    `fetch_frame` returns columns obs_date (period end), vintage_date, value (finite). Frames whose
    vintages are real publication dates carry ``frame.attrs["real_vintages"] = True``.
    """

    name: str

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame: ...
    def fetch(self, spec: SeriesSpec, since: date | None) -> Iterable[Observation]: ...


@runtime_checkable
class TradingCalendar(Protocol):
    def is_trading_day(self, d: date) -> bool: ...
    def trading_days(self, start: date, end: date) -> Sequence[date]: ...
    def month_ends(
        self, start: date, end: date
    ) -> Sequence[date]: ...  # calendar month-ends = decision dates
    def next_trading_day(self, d: date) -> date: ...
    def previous_trading_day(self, d: date) -> date: ...


@runtime_checkable
class MarketView(Protocol):
    """Immutable, point-in-time read view of the store at `date`.

    Guarantees (enforced by tests in tests/unit/test_view.py and the look-ahead harness):
      1. No returned index exceeds `date`.
      2. Every value has vintage_date <= `date`.
      3. Two views with equal `date` and equal data snapshot return bit-identical frames.
    """

    date: date

    def close(self, assets: Sequence[AssetId | str], lookback_days: int | None = None) -> pd.DataFrame: ...
    def total_return(self, assets: Sequence[AssetId | str], freq: str | None = "ME") -> pd.DataFrame: ...
    def series(self, series_id: SeriesId | str, freq: str | None = None) -> pd.Series: ...
    def panel(self, series_ids: Sequence[SeriesId | str], freq: str | None = "ME") -> pd.DataFrame: ...
    def last_obs(self, series_id: SeriesId | str) -> _dt.date | None: ...
    def calendar(self) -> TradingCalendar: ...
    def asset_series(self, asset: AssetId | str, role: str) -> pd.Series: ...


@runtime_checkable
class ViewFactory(Protocol):
    def at(self, d: date) -> MarketView: ...
    def precompute(self, dates: Sequence[date]) -> None: ...
    def data_snapshot(self) -> str: ...


# ---------------------------------------------------------------------------
# Feature layer
# ---------------------------------------------------------------------------
@runtime_checkable
class CrossSectionFeature(Protocol):
    """One value per asset at view.date."""

    name: str
    lookback: Months

    def __call__(self, view: MarketView, assets: Sequence[AssetId]) -> pd.Series: ...


@runtime_checkable
class StateFeature(Protocol):
    """State of the world at view.date: scalar, label or small series."""

    name: str
    lookback: Months

    def __call__(self, view: MarketView) -> float | str | pd.Series: ...


# ---------------------------------------------------------------------------
# Strategy layer
# ---------------------------------------------------------------------------
@runtime_checkable
class Strategy(Protocol):
    spec: StrategySpec

    def warmup(self) -> Months: ...
    def initial_state(self) -> StrategyState: ...
    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]: ...


# ---------------------------------------------------------------------------
# Portfolio / risk layer
# ---------------------------------------------------------------------------
@runtime_checkable
class Book(Protocol):
    """Positions, cash, marks, equity curve. Same class in backtest and live."""

    def weights(self) -> Mapping[AssetId, float]: ...
    def equity(self) -> float: ...
    def drawdown(self) -> float: ...
    def rebalance(
        self, targets: Targets, prices: Mapping[AssetId, float], when: date
    ) -> float: ...  # returns cost
    def mark(self, prices: Mapping[AssetId, float], when: date) -> None: ...
    def apply(self, action: RiskAction, prices: Mapping[AssetId, float], when: date) -> None: ...
    def snapshot(self) -> Mapping[str, Any]: ...


@runtime_checkable
class Combiner(Protocol):
    def combine(self, proposals: Sequence[Proposal], view: MarketView) -> Targets: ...


@runtime_checkable
class RiskRule(Protocol):
    name: str

    def check(self, book: Book, view: MarketView, proposals: Sequence[Proposal]) -> RiskAction | None: ...


@runtime_checkable
class RiskLayer(Protocol):
    def apply(self, targets: Targets, view: MarketView, book: Book) -> tuple[Targets, RiskReport]: ...
    def daily(self, book: Book, view: MarketView, proposals: Sequence[Proposal]) -> RiskAction | None: ...


@runtime_checkable
class CostModel(Protocol):
    def cost(self, trades: Mapping[AssetId, float], prices: Mapping[AssetId, float]) -> float: ...
    def carry(self, weights: Mapping[AssetId, float], days: int) -> float: ...  # borrow for shorts


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
@runtime_checkable
class Clock(Protocol):
    def decision_dates(self) -> Sequence[date]: ...
    def next_decision(self, d: date) -> date | None: ...
    def execution_day(self, d: date) -> date: ...
    def trading_days(self, start: date, end: date) -> Sequence[date]: ...
    def next_trading_day(self, d: date) -> date: ...


@runtime_checkable
class Recorder(Protocol):
    def decision(
        self,
        d: date,
        proposals: Sequence[Proposal],
        targets: Targets,
        risk: RiskReport,
        book_snapshot: Mapping[str, Any],
    ) -> None: ...
    def risk_event(self, d: date, action: RiskAction) -> None: ...
    def finish(self, status: str) -> None: ...


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
@runtime_checkable
class ScenarioMethod(Protocol):
    name: str

    def evaluate(
        self, scenario: Mapping[str, Any], targets: Targets, view: MarketView
    ) -> Mapping[str, Any]: ...


# ---------------------------------------------------------------------------
# Execution (reserved, not built in v1)
# ---------------------------------------------------------------------------
@runtime_checkable
class Executor(Protocol):
    def submit(self, targets: Targets) -> Mapping[str, Any]: ...
