"""Performance metrics on period returns (monthly unless stated), ported from src/metrics.py.

ann_return       geometric: Π(1 + r)^(12/n) − 1
ann_vol          sample SD × √12
sharpe_ex_cash   mean / SD × √12 of r − r_cash (self-financing spreads: their excess return is the spread)
max_drawdown     worst fall of Π(1 + r) from its running peak
calmar           ann_return / |max_drawdown|
hit_rate         share of periods with r > 0
mean_excess_ann  arithmetic mean of r − r_cash × 12 (how the spread studies reported "return p.a.")
turnover_ann     mean one-way turnover per period × 12
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

PERIODS = 12


def ann_return(r: pd.Series) -> float:
    a = r.dropna().to_numpy(dtype=float)
    return float(np.prod(1 + a) ** (PERIODS / len(a)) - 1) if len(a) else math.nan


def ann_vol(r: pd.Series) -> float:
    return float(r.dropna().std() * np.sqrt(PERIODS))


def sharpe(x: pd.Series) -> float:
    x = x.dropna()
    sd = x.std()
    if len(x) < 2 or sd == 0 or not np.isfinite(sd):
        return math.nan
    return float(x.mean() / sd * np.sqrt(PERIODS))


def max_drawdown(r: pd.Series) -> float:
    eq = (1 + r.dropna()).cumprod()
    return float((eq / eq.cummax() - 1).min()) if len(eq) else math.nan


def summary(r: pd.Series, cash: pd.Series, turnover: pd.Series | None = None) -> dict[str, float]:
    ex = r - cash.reindex(r.index).fillna(0.0)
    mdd = max_drawdown(r)
    ar = ann_return(r)
    out = {
        "months": float(r.dropna().size),
        "ann_return": ar,
        "ann_vol": ann_vol(r),
        "sharpe_ex_cash": sharpe(ex),
        "max_drawdown": mdd,
        "calmar": ar / abs(mdd) if mdd else math.nan,
        "hit_rate": float((r.dropna() > 0).mean()) if r.dropna().size else math.nan,
        "mean_excess_ann": float(ex.dropna().mean() * PERIODS),
    }
    if turnover is not None:
        out["turnover_ann"] = float(turnover.reindex(r.index).fillna(0.0).mean() * PERIODS)
    return out


METRICS: dict[str, Callable[[pd.Series, pd.Series], float]] = {
    "ann_return": lambda r, c: ann_return(r),
    "ann_vol": lambda r, c: ann_vol(r),
    "sharpe_ex_cash": lambda r, c: sharpe(r - c.reindex(r.index).fillna(0.0)),
    "max_drawdown": lambda r, c: max_drawdown(r),
    "mean_excess_ann": lambda r, c: float((r - c.reindex(r.index).fillna(0.0)).mean() * PERIODS),
}
