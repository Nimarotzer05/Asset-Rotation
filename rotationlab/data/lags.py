"""Publication lags: when did a value become public?

Two units, because two kinds of statistics exist:

* ``"<n>D"`` – n calendar days after ``obs_date``. Market data is ``"0D"`` (the close is public at
  the close); daily rates published the next morning are ``"1D"``; weekly releases ``"7D"``.
* ``"<n>M"`` – the calendar month-end n months after the observation month. This is the unit of
  monthly statistics that appear "some time during the following month(s)". With decisions taken
  at calendar month-ends it reproduces exactly the research convention ``series.shift(n)`` on a
  month-end index, independent of the day within the month on which the release happened.

Lags are deliberately conservative: a too-long lag only delays information, a too-short lag
creates look-ahead. Because decisions happen at month-ends, any lag that keeps a release inside
the same month costs nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

_LAG_RE = re.compile(r"^(\d+)([DM])$")


@dataclass(frozen=True)
class Lag:
    n: int
    unit: str  # "D" | "M"

    @classmethod
    def parse(cls, text: str) -> Lag:
        m = _LAG_RE.match(text.strip().upper())
        if not m:
            raise ValueError(f"invalid lag '{text}': expected '<n>D' or '<n>M'")
        return cls(int(m.group(1)), m.group(2))

    def __str__(self) -> str:
        return f"{self.n}{self.unit}"

    def apply(self, obs: date) -> date:
        """Vintage date for one observation date."""
        if self.unit == "D":
            return obs + timedelta(days=self.n)
        return (pd.Timestamp(obs) + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(self.n)).date()

    def apply_index(self, obs: pd.DatetimeIndex | pd.Series) -> pd.DatetimeIndex:
        """Vectorised `apply` (used when a provider emits thousands of rows)."""
        idx = pd.DatetimeIndex(obs)
        if self.unit == "D":
            return idx + pd.Timedelta(days=self.n)
        month_end = idx + pd.offsets.MonthEnd(0)
        if self.n == 0:
            return month_end
        # MonthEnd(n) on a month-end timestamp moves exactly n month-ends forward
        return month_end + pd.offsets.MonthEnd(self.n)

    def max_days(self) -> int:
        """Upper bound in days (staleness thresholds)."""
        return self.n if self.unit == "D" else 31 * (self.n + 1)


def validate_vintages(obs: np.ndarray, vintage: np.ndarray) -> None:
    """Every vintage must be on or after its observation date."""
    bad = vintage < obs
    if bad.any():
        i = int(np.argmax(bad))
        raise ValueError(f"vintage {vintage[i]} precedes obs_date {obs[i]}")
