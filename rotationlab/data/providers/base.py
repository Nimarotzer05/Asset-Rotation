"""Provider base: the frame contract and the shared vintage logic.

A provider turns one `SeriesSpec` into a frame with columns ``obs_date, vintage_date, value``:

* ``obs_date`` is the END of the period (providers that stamp period starts normalise here);
* ``vintage_date`` is either a real publication date (ALFRED ``realtime_start``) or
  ``Lag.apply(obs_date)`` from the spec;
* ``value`` is finite; missing values are dropped, never stored as NaN.

The store decides what is new, what is a revision and what is unchanged; providers stay stateless
apart from an optional download cache shared by several series of the same file.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

from rotationlab.core.types import Frequency, Observation, SeriesSpec
from rotationlab.data.lags import Lag

FRAME_COLUMNS = ["obs_date", "vintage_date", "value"]


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame({"obs_date": pd.Series(dtype="datetime64[ns]"),
                         "vintage_date": pd.Series(dtype="datetime64[ns]"),
                         "value": pd.Series(dtype="float64")})


def period_end(idx: pd.DatetimeIndex, freq: Frequency) -> pd.DatetimeIndex:
    """Normalise period stamps to the end of the period (monthly → calendar month-end)."""
    idx = pd.DatetimeIndex(idx).normalize()
    if freq == Frequency.MONTHLY:
        return idx + pd.offsets.MonthEnd(0)
    if freq == Frequency.QUARTERLY:
        return idx + pd.offsets.QuarterEnd(0)
    return idx


def frame_from_series(s: pd.Series, spec: SeriesSpec, since: date | None = None,
                      normalise: bool = True) -> pd.DataFrame:
    """Values indexed by date → provider frame with lag-model vintages."""
    s = pd.to_numeric(s, errors="coerce")
    s = s[np.isfinite(s.to_numpy(dtype=float))]
    if s.empty:
        return empty_frame()
    idx = period_end(pd.DatetimeIndex(s.index), spec.frequency) if normalise else pd.DatetimeIndex(s.index)
    out = pd.DataFrame({"obs_date": idx, "value": s.to_numpy(dtype=float)})
    out = out.drop_duplicates("obs_date", keep="last").sort_values("obs_date")
    if since is not None:
        out = out[out["obs_date"] >= pd.Timestamp(since)]
    out["vintage_date"] = Lag.parse(spec.lag).apply_index(out["obs_date"])
    return out.loc[:, FRAME_COLUMNS].reset_index(drop=True)


class BaseProvider:
    """Implements `fetch` (Observation objects) on top of `fetch_frame`."""

    name = "base"

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def fetch(self, spec: SeriesSpec, since: date | None) -> Iterable[Observation]:
        f = self.fetch_frame(spec, since)
        for o, v, x in zip(f["obs_date"], f["vintage_date"], f["value"], strict=True):
            yield Observation(spec.series_id, o.date(), v.date(), float(x))


def lagged_vintage(obs_date: date, spec: SeriesSpec) -> date:
    return Lag.parse(spec.lag).apply(obs_date)


def make_observation(spec: SeriesSpec, obs_date: date, value: float, vintage: date | None = None) -> Observation:
    return Observation(
        series_id=spec.series_id,
        obs_date=obs_date,
        vintage_date=vintage if vintage is not None else lagged_vintage(obs_date, spec),
        value=float(value),
    )
