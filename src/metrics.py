"""Performance-Kennzahlen für monatliche Renditereihen."""
from __future__ import annotations

import numpy as np
import pandas as pd

PERIODS = 12


def ann_return(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return np.nan
    return float((1 + r).prod() ** (PERIODS / len(r)) - 1)


def ann_vol(r: pd.Series) -> float:
    return float(r.dropna().std() * np.sqrt(PERIODS))


def sharpe(r: pd.Series, rf: float = 0.0) -> float:
    r = r.dropna()
    sd = r.std()
    if sd == 0 or np.isnan(sd):
        return np.nan
    return float((r.mean() - rf / PERIODS) / sd * np.sqrt(PERIODS))


def max_drawdown(r: pd.Series) -> float:
    eq = (1 + r.dropna()).cumprod()
    return float((eq / eq.cummax() - 1).min())


def calmar(r: pd.Series) -> float:
    mdd = max_drawdown(r)
    return np.nan if mdd == 0 else ann_return(r) / abs(mdd)


def summary(r: pd.Series, turnover: pd.Series | None = None, cash: pd.Series | None = None) -> dict:
    """Kennzahlen; mit `cash` wird der Sharpe auf Überschussrenditen (r − Cash) berechnet."""
    ex = r - cash.reindex(r.index).fillna(0) if cash is not None else r
    out = {
        "Ann. Return": ann_return(r),
        "Ann. Vol": ann_vol(r),
        "Sharpe" + (" (ex Cash)" if cash is not None else ""): sharpe(ex),
        "Max Drawdown": max_drawdown(r),
        "Calmar": calmar(r),
        "Hit Rate": float((r.dropna() > 0).mean()),
    }
    if turnover is not None:
        out["Ann. Turnover"] = float(turnover.mean() * PERIODS)
    return out


def summary_table(series: dict[str, pd.Series], turnovers: dict[str, pd.Series] | None = None,
                  cash: pd.Series | None = None) -> pd.DataFrame:
    turnovers = turnovers or {}
    return pd.DataFrame({k: summary(v, turnovers.get(k), cash) for k, v in series.items()}).T


def by_regime(r: pd.Series, regime: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"r": r, "regime": regime.reindex(r.index)}).dropna()
    g = df.groupby("regime")["r"]
    return pd.DataFrame(
        {"Months": g.size(), "Ann. Return": g.apply(ann_return), "Sharpe": g.apply(sharpe)}
    )
