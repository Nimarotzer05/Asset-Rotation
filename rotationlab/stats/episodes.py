"""Drawdown episodes (scripts/run_derisk.py §1): when did a level fall more than `threshold` from its peak,
and where was the trough?

An episode starts when the drawdown first falls below `threshold` (peak = the running maximum before it)
and ends when the drawdown recovers above `recovery`; its trough is the lowest point between peak and end.
An episode still open at the end of the data runs to the lowest point so far.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Episode:
    peak: pd.Timestamp
    trough: pd.Timestamp
    depth: float


def drawdown_episodes(level: pd.Series, threshold: float = -0.15, recovery: float = -0.02) -> list[Episode]:
    s = level.dropna()
    if s.empty:
        return []
    idx = pd.DatetimeIndex(s.index)
    v = s.to_numpy(dtype=float)
    dd = v / np.maximum.accumulate(v) - 1
    out: list[Episode] = []
    in_ep, p = False, 0

    def close(p: int, end: int) -> Episode:
        t = p + int(np.argmin(v[p : end + 1]))
        return Episode(idx[p], idx[t], float(v[t] / v[p] - 1))

    for i in range(len(v)):
        if not in_ep and dd[i] < threshold:
            in_ep = True
            p = int(np.argmax(v[: i + 1]))  # first occurrence of the running peak
        if in_ep and dd[i] >= recovery:
            out.append(close(p, i))
            in_ep = False
    if in_ep:
        out.append(close(p, len(v) - 1))
    return out


def change_over(level: pd.Series, episodes: list[Episode], log: bool = False) -> pd.Series:
    """Change of another level from each episode's peak to its trough (log difference if `log`)."""
    s = level.dropna().astype(float)
    vals: dict[str, float] = {}
    for e in episodes:
        a, b = float(s.loc[: e.peak].iloc[-1]), float(s.loc[: e.trough].iloc[-1])
        vals[f"{e.peak:%Y-%m} → {e.trough:%Y-%m}"] = float(np.log(b / a)) if log else b / a - 1
    return pd.Series(vals, dtype=float)
