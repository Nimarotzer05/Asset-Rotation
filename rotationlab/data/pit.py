"""Interval index for point-in-time reads.

Every stored row is valid for knowledge dates in ``[vintage_date, next_vintage_date)`` of the same
``obs_date``. The value of a series as of D is therefore the set of rows with

    obs_date <= D  and  vintage_date <= D < valid_to

– exactly one row per obs_date, identical to ``AS_OF_SQL`` / ``as_of_pandas`` (tested), but answered
from numpy arrays: O(log n) for series without revisions and monotone vintages (all market data,
lag-model statistics), one vectorised mask otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_INF = np.iinfo(np.int64).max


@dataclass(frozen=True)
class _SeriesArrays:
    obs: np.ndarray        # int64 ns, sorted ascending (ties: by vintage)
    vintage: np.ndarray    # int64 ns
    valid_to: np.ndarray   # int64 ns, _INF for the latest vintage of an obs_date
    value: np.ndarray      # float64
    simple: bool           # one row per obs_date and vintages non-decreasing → searchsorted path


class PitIndex:
    def __init__(self, observations: pd.DataFrame) -> None:
        self._s: dict[str, _SeriesArrays] = {}
        if observations.empty:
            return
        obs = observations.sort_values(["series_id", "obs_date", "vintage_date"], kind="mergesort")
        sid = obs["series_id"].to_numpy()
        o = obs["obs_date"].to_numpy(dtype="datetime64[ns]").view("int64")
        v = obs["vintage_date"].to_numpy(dtype="datetime64[ns]").view("int64")
        x = obs["value"].to_numpy(dtype="float64")
        bounds = np.flatnonzero(np.r_[True, sid[1:] != sid[:-1], True])
        for a, b in zip(bounds[:-1], bounds[1:], strict=True):
            oo, vv, xx = o[a:b], v[a:b], x[a:b]
            same_next = np.r_[oo[1:] == oo[:-1], False]
            valid_to = np.where(same_next, np.r_[vv[1:], _INF], _INF)
            simple = bool(not same_next.any() and (np.diff(vv) >= 0).all())
            self._s[str(sid[a])] = _SeriesArrays(oo.copy(), vv.copy(), valid_to, xx.copy(), simple)

    def __contains__(self, series_id: str) -> bool:
        return series_id in self._s

    def series_ids(self) -> list[str]:
        return sorted(self._s)

    def as_of(self, series_id: str, d: pd.Timestamp) -> pd.Series:
        a = self._s.get(series_id)
        if a is None:
            return pd.Series(dtype="float64", index=pd.DatetimeIndex([]), name=series_id)
        t = np.int64(pd.Timestamp(d).value)
        if a.simple:
            k = min(int(np.searchsorted(a.obs, t, side="right")), int(np.searchsorted(a.vintage, t, side="right")))
            idx, val = a.obs[:k], a.value[:k]
        else:
            m = (a.obs <= t) & (a.vintage <= t) & (t < a.valid_to)
            idx, val = a.obs[m], a.value[m]
        return pd.Series(val, index=pd.DatetimeIndex(idx.view("datetime64[ns]")), name=series_id)

    def is_simple(self, series_id: str) -> bool:
        a = self._s.get(series_id)
        return a is not None and a.simple

    def prefix_len(self, series_id: str, d: pd.Timestamp) -> int:
        """For a simple series, as_of(d) is the first k rows of its full history; returns k."""
        a = self._s[series_id]
        if not a.simple:
            raise ValueError(f"{series_id} has revisions: no prefix property")
        t = np.int64(pd.Timestamp(d).value)
        return min(int(np.searchsorted(a.obs, t, side="right")), int(np.searchsorted(a.vintage, t, side="right")))

    def full(self, series_id: str) -> pd.Series:
        """Every stored observation of a simple series (its as-of answer at the end of time)."""
        a = self._s[series_id]
        return pd.Series(a.value.copy(), index=pd.DatetimeIndex(a.obs.view("datetime64[ns]")), name=series_id)

    def vintage_as_of(self, series_id: str, d: pd.Timestamp) -> pd.Series:
        """Which vintage date produced each value of `as_of` (diagnostics, revision reports)."""
        a = self._s.get(series_id)
        if a is None:
            return pd.Series(dtype="datetime64[ns]", name=series_id)
        t = np.int64(pd.Timestamp(d).value)
        m = (a.obs <= t) & (a.vintage <= t) & (t < a.valid_to)
        return pd.Series(a.vintage[m].view("datetime64[ns]"), index=pd.DatetimeIndex(a.obs[m].view("datetime64[ns]")),
                         name=series_id)

    def n_rows(self, series_id: str) -> int:
        a = self._s.get(series_id)
        return 0 if a is None else len(a.obs)
