"""Core value types shared by every layer.

Everything here is immutable and serialisable (JSON) so that proposals, targets, states and
run records can be stored verbatim and replayed. No pandas objects cross module boundaries
except inside `MarketView` (see data/view.py); here we use plain mappings keyed by AssetId.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, NewType

AssetId = NewType("AssetId", str)  # e.g. "SPY", "GOLD" (long-history), "GC=F"
SeriesId = NewType("SeriesId", str)  # e.g. "fred:CPIAUCSL", "yahoo:SPY:close"
StrategyId = NewType("StrategyId", str)
RunId = NewType("RunId", str)

CASH = AssetId("CASH")


class Mode(StrEnum):
    BACKTEST = "backtest"
    WALKFORWARD = "walkforward"
    LIVE = "live"


class Cadence(StrEnum):
    MONTHLY = "monthly"  # decisions at month-end
    WEEKLY = "weekly"
    DAILY = "daily"  # reserved for risk checks, never for signals


class Role(StrEnum):
    CORE = "core"  # receives a risk budget
    SATELLITE = "satellite"  # receives a (smaller) risk budget, usually long-short
    OVERLAY = "overlay"  # sized relative to core exposure, additive hedge
    PAPER = "paper"  # research/paper module outside the risk budgets (forecast portfolio, baselines; ADR 048)


class SeriesKind(StrEnum):
    PRICE = "price"  # close (split-adjusted, not dividend-adjusted)
    DIVIDEND = "dividend"  # cash amount on the ex-date, same split basis as PRICE
    SPLIT = "split"  # split factor on the ex-date (2.0 = 2-for-1)
    TOTAL_RETURN = "total_return"  # index level incl. distributions
    RETURN = "return"  # simple period return in decimals (French portfolios, RF)
    YIELD = "yield"  # percent p.a. (rates, spreads)
    INDEX = "index"  # level without distributions (VIX, DXY, commodity index)
    MACRO = "macro"  # revised statistic (vintages matter)
    POSITIONING = "positioning"  # CFTC

    @property
    def is_level(self) -> bool:
        """Levels are spliced by ratio, rates and returns by value."""
        return self in (SeriesKind.PRICE, SeriesKind.TOTAL_RETURN, SeriesKind.INDEX)


class Frequency(StrEnum):
    DAILY = "D"
    WEEKLY = "W"
    MONTHLY = "M"
    QUARTERLY = "Q"


@dataclass(frozen=True)
class Months:
    """A duration in months; used for lookbacks, warmups and horizons."""

    n: int

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError("Months must be non-negative")


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeriesSpec:
    """Everything the data layer needs to know about one stored series.

    Date convention: `obs_date` is the END of the period the value refers to (a monthly value for
    September carries 2026-09-30, whatever the provider stamps). `lag` says when it became public:
    "0D" market data, "<n>D" n calendar days after obs_date, "<n>M" the calendar month-end n months
    after the observation month. `vintages="alfred"` means real publication dates come from ALFRED
    and `lag` only covers history older than the first archived vintage.
    """

    series_id: SeriesId
    provider: str  # "yahoo" | "stooq" | "fred" | "french" | "cftc" | "static"
    provider_code: str  # ticker / FRED code / file column
    kind: SeriesKind
    frequency: Frequency
    unit: str = ""
    asset_id: AssetId | None = None
    lag: str = "0D"
    vintages: str = "none"  # "none" | "alfred"
    required: bool = False  # staleness of a required series blocks live decisions
    revision_tolerance: float = 1e-9  # relative change below which a refetch is not a revision
    name: str = ""
    params: tuple[tuple[str, str], ...] = ()  # provider-specific options, hashable


@dataclass(frozen=True)
class Observation:
    """One value with both dates: what it is for, and when it became known."""

    series_id: SeriesId
    obs_date: date
    vintage_date: date
    value: float

    def __post_init__(self) -> None:
        if self.vintage_date < self.obs_date:
            raise ValueError(
                f"{self.series_id}: vintage_date {self.vintage_date} precedes obs_date {self.obs_date}"
            )


@dataclass(frozen=True)
class AssetSpec:
    asset_id: AssetId
    name: str
    asset_class: str  # equity | bond | precious | energy | base_metal | agri | cash
    instrument: str  # etf | spot | future | index
    tradable: bool
    cost_bps: float  # per side
    borrow_bps: float = 0.0  # p.a., shorts only
    proxy_of: AssetId | None = (
        None  # long-history series this instrument stands in for (golden tests, analogs)
    )


# ---------------------------------------------------------------------------
# Strategy layer
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StopRule:
    kind: str  # ratio_drawdown | asset_trend_break | portfolio_drawdown | max_holding
    scope: tuple[AssetId, ...]
    threshold: float
    action: str  # close | halve | flag
    reference: float | None = None  # e.g. entry ratio level the rule is measured against


@dataclass(frozen=True)
class Proposal:
    strategy_id: StrategyId
    date: date
    weights: Mapping[AssetId, float]  # on the module's own capital; long-only sums <= 1, cash = remainder
    confidence: float  # 0..1
    horizon_months: int
    signals: Mapping[str, float] = field(default_factory=dict)
    stops: tuple[StopRule, ...] = ()
    notes: tuple[str, ...] = ()
    warmup: bool = False  # not enough history for a signal yet: weights are empty (all cash)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must lie in [0, 1]")
        gross = sum(abs(w) for w in self.weights.values())
        if gross > 2.0 + 1e-9:
            raise ValueError(f"gross exposure {gross:.3f} exceeds 2.0")
        for a, w in self.weights.items():
            if math.isnan(w):
                raise ValueError(f"weight for {a} is NaN")

    @property
    def net(self) -> float:
        return float(sum(self.weights.values()))

    @property
    def gross(self) -> float:
        return float(sum(abs(w) for w in self.weights.values()))


@dataclass(frozen=True)
class StrategyState:
    """Serialisable module state carried from one decision date to the next."""

    strategy_id: StrategyId
    positions: Mapping[AssetId, float] = field(default_factory=dict)
    entries: Mapping[str, float] = field(default_factory=dict)  # e.g. {"ratio_entry": 49.6}
    tranches: tuple[Mapping[AssetId, float], ...] = ()  # open tranche weights (oldest first)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True)


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: StrategyId
    version: int
    role: Role
    cadence: Cadence
    universe: tuple[AssetId, ...]
    warmup: Months
    params: Mapping[str, Any]

    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), default=str, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Portfolio / risk layer
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Targets:
    date: date
    weights: Mapping[AssetId, float]  # final portfolio weights incl. CASH, gross <= max_gross
    by_strategy: Mapping[StrategyId, Mapping[AssetId, float]]
    scale: float  # vol-target scaling applied
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskAction:
    date: date
    rule: str
    action: str  # close | halve | scale | halt | flag
    scope: tuple[AssetId, ...]
    detail: str
    factor: float = 1.0  # multiplicative exposure change for scale/halve


@dataclass(frozen=True)
class RiskReport:
    date: date
    actions: tuple[RiskAction, ...]
    ex_ante_vol: float
    gross: float
    net: float
    halted: bool = False  # kill switch active


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RunRecord:
    run_id: RunId
    mode: Mode
    started_at: str  # ISO timestamp
    git_sha: str
    config_hash: str
    data_snapshot: str  # max ingested_at in the store
    start: date
    end: date
    seed: int | None = None
    status: str = "running"


@dataclass(frozen=True)
class JournalEntry:
    decision_date: date
    asset_id: AssetId
    target_weight: float
    prev_weight: float
    ref_price: float | None
    ref_price_date: date | None
    strategy_breakdown: Mapping[StrategyId, float]
    note: str = ""
    config_version: str = ""
    realized_return: float | None = None  # filled at the next decision date


def weights_from(seq: Sequence[tuple[AssetId, float]]) -> dict[AssetId, float]:
    """Helper: build a weight mapping, dropping zeros."""
    return {a: float(w) for a, w in seq if abs(w) > 1e-12}
