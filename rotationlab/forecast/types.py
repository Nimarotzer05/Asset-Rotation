"""The forecast object (ADR 043): what the system says at a month-end, kept exactly as it was said.

A `Forecast` is one horizon at one decision date. It carries everything needed to reproduce and to judge it
later: the decision date, the data snapshot it was computed from, the model id, version and parameters, and
per asset class the score, rank, expected relative excess return with its band and the absolute trend.

    ranked class      probability of the event `params.probability.target` over the horizon – `top_half`:
                      the class ends among the upper half of the ranked classes (the main output, ADR 044,
                      target chosen in ADR 045 b) –, score, rank (1 = most attractive), expected relative
                      excess return and band (decision 3)
    trend-only class  trend only (decision 2: commodities are not ranked against each other)

Relative excess return = the class's return minus the mean return of the ranked classes over the horizon
(the cash rate cancels). `expected` is the mean relative return that the class's rank earned in the past
months known at D, `band` the bootstrap interval of that *mean* – not a prediction interval for the coming
month, whose spread is far wider. Status (ADR 044, descriptive only, ADR 045 c):

    signal            at least one class is given a probability further than the margin from 50 %
    no_clear_signal   every probability lies within the margin of 50 %: nothing distinguishable from noise
    warmup            not enough history for a ranking or for the probabilities yet

Ranking and portfolio stay separate: `weights` is an optional derived output, never an input. The object
is immutable (frozen dataclasses, read-only mappings) and serialises to canonical JSON, so a forecast in the
journal is byte-for-byte what was computed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Literal

Status = Literal["signal", "no_clear_signal", "warmup"]
Trend = Literal["up", "down"]
STATUSES: tuple[str, ...] = ("signal", "no_clear_signal", "warmup")
SCHEMA_VERSION = 1


def freeze(x: Any) -> Any:
    """Deep read-only copy: dicts → MappingProxyType, lists → tuples."""
    if isinstance(x, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in x.items()})
    if isinstance(x, list | tuple):
        return tuple(freeze(v) for v in x)
    return x


def thaw(x: Any) -> Any:
    """Plain JSON-able copy of a frozen value (dates as ISO strings)."""
    if isinstance(x, Mapping):
        return {str(k): thaw(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [thaw(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


def _finite_or_none(v: float | None, name: str) -> None:
    if v is not None and not math.isfinite(v):
        raise ValueError(f"{name} must be finite or None, got {v}")


@dataclass(frozen=True)
class ClassForecast:
    asset: str
    ranked: bool
    trend: Trend | None  # above / below its 10-month average; None without enough history
    trend_value: float | None = None  # distance to the 10-month average (trend_10m)
    score: float | None = None
    rank: int | None = None
    expected: float | None = None  # expected relative excess return over the horizon (fraction)
    band: tuple[float, float] | None = None  # (low, high) of the expected value
    probability: float | None = None  # P(relative excess return > 0) over the horizon

    def __post_init__(self) -> None:
        for name in ("trend_value", "score", "expected", "probability"):
            _finite_or_none(getattr(self, name), f"{self.asset}.{name}")
        if self.probability is not None and not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"{self.asset}: probability must lie in [0, 1]")
        if not self.ranked and self.probability is not None:
            raise ValueError(f"{self.asset}: a trend-only class has no probability")
        if self.trend is not None and self.trend not in ("up", "down"):
            raise ValueError(f"{self.asset}: trend must be 'up', 'down' or None")
        if not self.ranked and (self.score is not None or self.rank is not None or self.expected is not None):
            raise ValueError(f"{self.asset}: a trend-only class has no score, rank or expectation")
        if self.rank is not None and self.rank < 1:
            raise ValueError(f"{self.asset}: rank starts at 1")
        if (self.expected is None) != (self.band is None):
            raise ValueError(f"{self.asset}: expectation and band come together")
        if self.band is not None:
            lo, hi = self.band
            _finite_or_none(lo, f"{self.asset}.band")
            _finite_or_none(hi, f"{self.asset}.band")
            if not lo <= self.expected <= hi:  # type: ignore[operator]
                raise ValueError(f"{self.asset}: band {self.band} does not contain {self.expected}")
            object.__setattr__(self, "band", (float(lo), float(hi)))


@dataclass(frozen=True)
class Forecast:
    decision_date: date
    horizon_months: int
    status: Status
    model_id: str
    model_version: int
    params: Mapping[str, Any]
    data_snapshot: str  # store snapshot the view was built on; with decision_date it fixes the data
    classes: tuple[ClassForecast, ...]
    calibration_months: int = 0  # outcome months behind the expectations (per rank, the minimum)
    notes: tuple[str, ...] = ()
    weights: Mapping[str, float] | None = None  # derived output only (ADR 043), never an input
    created_at: str | None = None  # wall-clock stamp, set when written to the journal
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if self.horizon_months < 1:
            raise ValueError("horizon_months must be at least 1")
        object.__setattr__(self, "params", freeze(dict(self.params)))
        object.__setattr__(self, "classes", tuple(self.classes))
        object.__setattr__(self, "notes", tuple(self.notes))
        if self.weights is not None:
            object.__setattr__(self, "weights", freeze({k: float(v) for k, v in self.weights.items()}))
        names = [c.asset for c in self.classes]
        if len(set(names)) != len(names):
            raise ValueError("each asset class appears once")
        ranked = [c for c in self.classes if c.ranked]
        ranks = sorted(c.rank for c in ranked if c.rank is not None)
        if self.status == "warmup":
            if ranks and ranks != list(range(1, len(ranks) + 1)):
                raise ValueError("ranks must be 1..n")
        else:
            if ranks != list(range(1, len(ranked) + 1)):
                raise ValueError(f"a forecast with status {self.status} ranks every ranked class 1..n")
            if any(c.expected is None for c in ranked):
                raise ValueError(f"a forecast with status {self.status} has an expectation for every rank")
            if any(c.probability is None for c in ranked):
                raise ValueError(f"a forecast with status {self.status} has a probability for every rank")

    # -- reading -----------------------------------------------------------------
    def probabilities(self) -> dict[str, float]:
        return {c.asset: c.probability for c in self.classes if c.probability is not None}

    def ranking(self) -> list[str]:
        """Ranked classes, most attractive first."""
        ranked = [c for c in self.classes if c.rank is not None]
        return [c.asset for c in sorted(ranked, key=lambda c: c.rank or 0)]

    def by_asset(self) -> dict[str, ClassForecast]:
        return {c.asset: c for c in self.classes}

    # -- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_date": self.decision_date.isoformat(),
            "horizon_months": self.horizon_months,
            "status": self.status,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "params": thaw(self.params),
            "data_snapshot": self.data_snapshot,
            "calibration_months": self.calibration_months,
            "classes": [
                {
                    "asset": c.asset,
                    "ranked": c.ranked,
                    "trend": c.trend,
                    "trend_value": c.trend_value,
                    "score": c.score,
                    "rank": c.rank,
                    "expected": c.expected,
                    "band": list(c.band) if c.band is not None else None,
                    "probability": c.probability,
                }
                for c in self.classes
            ],
            "notes": list(self.notes),
            "weights": thaw(self.weights) if self.weights is not None else None,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Canonical JSON: sorted keys, no whitespace variation – equal forecasts give equal bytes."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Forecast:
        if int(d.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError(f"unknown forecast schema version {d.get('schema_version')}")
        classes = tuple(
            ClassForecast(
                asset=c["asset"],
                ranked=bool(c["ranked"]),
                trend=c["trend"],
                trend_value=c["trend_value"],
                score=c["score"],
                rank=c["rank"],
                expected=c["expected"],
                band=tuple(c["band"]) if c["band"] is not None else None,
                probability=c.get("probability"),
            )
            for c in d["classes"]
        )
        return cls(
            decision_date=date.fromisoformat(d["decision_date"]),
            horizon_months=int(d["horizon_months"]),
            status=d["status"],
            model_id=d["model_id"],
            model_version=int(d["model_version"]),
            params=d["params"],
            data_snapshot=d["data_snapshot"],
            classes=classes,
            calibration_months=int(d["calibration_months"]),
            notes=tuple(d.get("notes", ())),
            weights=d.get("weights"),
            created_at=d.get("created_at"),
        )

    @classmethod
    def from_json(cls, text: str) -> Forecast:
        return cls.from_dict(json.loads(text))

    def stamped(self, created_at: str) -> Forecast:
        """A copy with the wall-clock stamp of the moment it is written (journal)."""
        return Forecast(**{**self.__dict__, "created_at": created_at})

    def with_notes(self, *notes: str) -> Forecast:
        """A copy with notes appended (the live run records late data this way)."""
        return Forecast(**{**self.__dict__, "notes": (*self.notes, *notes)})

    def with_weights(self, weights: Mapping[str, float] | None) -> Forecast:
        """A copy carrying derived portfolio weights (the paper rule of ADR 048) – an output, never an input."""
        return Forecast(**{**self.__dict__, "weights": None if weights is None else dict(weights)})


def ranked_assets(classes: Sequence[ClassForecast]) -> list[str]:
    return [c.asset for c in classes if c.ranked]


__all__ = ["ClassForecast", "Forecast", "Status", "Trend", "freeze", "ranked_assets", "thaw"]
