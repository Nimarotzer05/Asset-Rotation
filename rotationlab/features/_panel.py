"""Panels and small statistics shared by the feature modules.

Every feature is computed the same way: build an *as-of panel* (what the view knows at D, on a complete
monthly grid that ends with the month containing D), run a vectorised formula over it, read the last row.
The pointwise value at D is therefore the D-row of the panel variant, by construction (ADR 036), and the
panel variant run once on the final store reproduces every pointwise value of an unrevised, unlagged
input bit for bit (rolling windows only ever see a prefix of the same data).

Lags inside a feature (``shift``) never stand in for publication lags – the store already hides what was
unknown at D. They reconstruct the research timing of *past* rows (CPI of t−1 deflates the price of t)
and are only allowed when the store's lag for that series is at least as long (the harness proves it:
a shift shorter than the lag reads a NaN at D, never a future value).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from rotationlab.core.protocols import MarketView


def month_grid(first: pd.Timestamp, d: date | pd.Timestamp) -> pd.DatetimeIndex:
    """Calendar month-ends from the month of `first` to the month of `d`; the last label is capped at `d`
    (the running month is labelled with `d`, exactly like MarketView's monthly resampling)."""
    d64 = np.datetime64(pd.Timestamp(d).normalize().date(), "D")
    m0 = np.datetime64(pd.Timestamp(first).date(), "M")
    m1 = d64.astype("datetime64[M]")
    if m0 > m1:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    one = np.timedelta64(1, "M")
    ends = (np.arange(m0, m1 + one, one) + one).astype("datetime64[D]") - np.timedelta64(1, "D")
    ends[-1] = min(ends[-1], d64)
    return pd.DatetimeIndex(ends.astype("datetime64[ns]"))


def _on_grid(df: pd.DataFrame, d: date) -> pd.DataFrame:
    valid = df.dropna(how="all")
    if valid.empty:
        return df.iloc[:0]
    return df.reindex(month_grid(valid.index[0], d))


def tr_panel(view: MarketView, assets: Sequence[str]) -> pd.DataFrame:
    """Monthly total-return levels (columns = assets) on the complete grid up to the month of view.date."""
    df = view.total_return(list(assets), "ME")
    df = df.reindex(columns=list(assets))
    return _on_grid(df, view.date)


def series_panel(view: MarketView, series_ids: Sequence[str]) -> pd.DataFrame:
    """Monthly as-of values (last per month) of stored series or macro chains, on the complete grid."""
    cols = {s: view.series(s, "ME") for s in series_ids}
    df = pd.DataFrame(cols).reindex(columns=list(series_ids))
    return _on_grid(df, view.date)


def from_start(df: pd.DataFrame, start: str | date | None) -> pd.DataFrame:
    """Drop rows before `start` (features whose expanding statistics follow a research sample start)."""
    return df if start is None else df.loc[pd.Timestamp(start) :]


def rolling_z(s: pd.Series | pd.DataFrame, window: int, min_periods: int) -> pd.Series | pd.DataFrame:
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - mu) / sd


def expanding_z(s: pd.Series, min_periods: int) -> pd.Series:
    return (s - s.expanding(min_periods).mean()) / s.expanding(min_periods).std()


def expanding_pct(s: pd.Series, min_periods: int) -> pd.Series:
    """Expanding percentile of each value among all values up to and including it (ties count half)."""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    hist: list[float] = []
    for i, v in enumerate(vals):
        if np.isnan(v):
            continue
        hist.append(v)
        if len(hist) >= min_periods:
            h = np.asarray(hist)
            out[i] = (h < v).mean() + 0.5 * (h == v).mean()
    return pd.Series(out, index=s.index, name=s.name)


def last_row(df: pd.DataFrame, name: str) -> pd.Series:
    """Cross-sectional value at the view date: the last grid row (NaN for every asset if the grid is empty)."""
    if df.empty:
        return pd.Series(np.nan, index=df.columns, name=name, dtype=float)
    return df.iloc[-1].rename(name).astype(float)


def last_value(s: pd.Series) -> float | str:
    """State value at the view date: a float, or a label for categorical states (NaN without data)."""
    if not len(s):
        return float("nan")
    v = s.iloc[-1]
    if isinstance(v, str):
        return v
    return float(v) if v is not None else float("nan")
