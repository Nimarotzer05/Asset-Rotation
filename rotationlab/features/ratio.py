"""Gold/silver ratio features (state), research formulas of scripts/run_gold_silver.py.

On month-end spot prices G, S (assets `gold`, `silver`; LBMA fix in the research panel, front futures live):

    gs_ratio         G / S
    gs_ratio_z60     z-score of log(G/S) against its last 60 months (at least 30)   high = gold expensive
    gs_ratio_z120    the same over 120 months (at least 60)
    gs_ratio_mom12   12-month change of log(G/S)
    gs_hedge_ratio   σ(r_G) / σ(r_S) over 36 months (at least 24): silver units per gold unit, vol-neutral
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define
from rotationlab.features._panel import from_start, month_grid, rolling_z

PARAMS: dict[str, Any] = {"gold": "XAU", "silver": "XAG", "start": None}


def monthly_last(s: pd.Series, d: Any) -> pd.Series:
    """Last value per calendar month, labelled with the month-end (the running month with `d`)."""
    s = s[s > 0].dropna()
    if s.empty:
        return s
    per = pd.DatetimeIndex(s.index).to_period("M")
    last = s.groupby(per).last()
    labels = pd.PeriodIndex(last.index).to_timestamp(how="end").normalize().as_unit("ns")
    labels = labels.where(labels <= pd.Timestamp(d), pd.Timestamp(d))
    return pd.Series(last.to_numpy(), index=pd.DatetimeIndex(labels), name=s.name)


def _panel(
    view: Any, _assets: Any, gold: str = "XAU", silver: str = "XAG", start: Any = None, **_: Any
) -> pd.DataFrame:
    g = monthly_last(view.asset_series(gold, "close"), view.date)
    s = monthly_last(view.asset_series(silver, "close"), view.date)
    df = pd.DataFrame({"G": g, "S": s}).dropna()  # research: months with both fixes only
    if df.empty:
        return df
    df = df.reindex(month_grid(df.index[0], view.date))
    return from_start(df, start)


def log_ratio(panel: pd.DataFrame) -> pd.Series:
    r = (panel["G"] / panel["S"]).to_numpy(dtype=float)
    return pd.Series(np.log(r), index=panel.index, name="log_ratio")


def _ratio(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """Gold/silver price ratio."""
    return (panel["G"] / panel["S"]).rename("gs_ratio")


def _z60(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """z-score of the log ratio against the last 60 months (min 30): high = gold expensive vs silver."""
    return pd.Series(rolling_z(log_ratio(panel), 60, 30), name="gs_ratio_z60")


def _z120(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """z-score of the log ratio against the last 120 months (min 60)."""
    return pd.Series(rolling_z(log_ratio(panel), 120, 60), name="gs_ratio_z120")


def _mom12(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """12-month change of the log ratio (> 0: gold outperformed silver)."""
    return log_ratio(panel).diff(12).rename("gs_ratio_mom12")


def _hedge(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """Vol-neutral hedge ratio σ_gold / σ_silver over 36 months (min 24)."""
    r = panel.pct_change()
    return (r["G"].rolling(36, min_periods=24).std() / r["S"].rolling(36, min_periods=24).std()).rename(
        "gs_hedge_ratio"
    )


INPUTS = ["close:gold", "close:silver"]
define("gs_ratio", "state", INPUTS, Months(0), _panel, _ratio, params=PARAMS)
define("gs_ratio_z60", "state", INPUTS, Months(60), _panel, _z60, params=PARAMS)
define("gs_ratio_z120", "state", INPUTS, Months(120), _panel, _z120, params=PARAMS)
define("gs_ratio_mom12", "state", INPUTS, Months(12), _panel, _mom12, params=PARAMS)
define("gs_hedge_ratio", "state", INPUTS, Months(37), _panel, _hedge, params=PARAMS)
