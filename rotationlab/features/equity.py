"""Equity valuation (state features), research formulas of scripts/run_equity.py::signals_a.

    cape(t)  = (P(t) / CPI(t−1)) / mean over 120 months of (E(s) / CPI(s)), s ≤ t−6
    ecy(t)   = 1 / cape(t) − (GS10(t)/100 − infl10(t)),  infl10(t) = (CPI(t−1) / CPI(t−121))^(1/10) − 1
    ecy_pct  = expanding percentile of ecy (from `min_history` months on; history from `pct_start`, research:
               1926-07, the start of the French market index the study aligned everything to)

P, GS10: Shiller monthly averages (public at month-end, 0D). CPI: published mid next month (store lag 1M,
shift 1 here). E: Shiller's quarterly earnings interpolated monthly (store lag 6M, shift 6 here; audit
2026-10-24). Live, the macro chains read the current Shiller workbook first and the frozen copy after.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define
from rotationlab.features._panel import expanding_pct, series_panel

SOURCES = {
    "price": "macro:SP_PRICE",
    "earnings": "macro:SP_EARNINGS",
    "cpi": "macro:SP_CPI",
    "rate": "macro:SP_RATE",
}
PARAMS: dict[str, Any] = {**SOURCES, "cpi_lag": 1, "earnings_lag": 6, "window": 120}
PCT_PARAMS: dict[str, Any] = {**PARAMS, "min_history": 120, "pct_start": None}


def _panel(view: Any, _assets: Any, price: str, earnings: str, cpi: str, rate: str, **_: Any) -> pd.DataFrame:
    p = series_panel(view, [price, earnings, cpi, rate])
    return p.set_axis(["P", "E", "CPI", "RATE"], axis=1)


def cape_series(
    panel: pd.DataFrame, cpi_lag: int = 1, earnings_lag: int = 6, window: int = 120, **_: Any
) -> pd.Series:
    df = panel.replace(0.0, np.nan)
    cpi = df["CPI"].shift(cpi_lag)
    p_real = df["P"] / cpi
    e_real = (df["E"] / df["CPI"]).shift(earnings_lag)
    return (p_real / e_real.rolling(window, min_periods=window).mean()).rename("cape")


def ecy_series(
    panel: pd.DataFrame, cpi_lag: int = 1, earnings_lag: int = 6, window: int = 120, **_: Any
) -> pd.Series:
    cape = cape_series(panel, cpi_lag, earnings_lag, window)
    cpi = panel["CPI"].replace(0.0, np.nan).shift(cpi_lag)
    infl10 = (cpi / cpi.shift(120)) ** (1 / 10) - 1
    real10 = panel["RATE"] / 100 - infl10
    return (1 / cape - real10).rename("ecy")


def _cape(panel: pd.DataFrame, **kw: Any) -> pd.Series:
    """Shiller CAPE: real price over the 10-year average of real earnings (earnings lagged 6 months)."""
    return cape_series(panel, **kw)


def _ecy(panel: pd.DataFrame, **kw: Any) -> pd.Series:
    """Excess CAPE yield: 1/CAPE minus the 10-year real rate (GS10 minus 10-year CPI inflation)."""
    return ecy_series(panel, **kw)


def _ecy_pct(
    panel: pd.DataFrame, min_history: int = 120, pct_start: str | None = None, **kw: Any
) -> pd.Series:
    """Expanding percentile of the excess CAPE yield (high = equities cheap relative to bonds)."""
    e = ecy_series(panel, **kw)
    valid = e.dropna()
    if pct_start is not None:
        valid = valid.loc[pd.Timestamp(pct_start) :]
    return expanding_pct(valid, min_history).reindex(e.index).rename("ecy_pct")


SERIES_INPUTS = [f"series:{s}" for s in SOURCES.values()]
define("cape", "state", SERIES_INPUTS, Months(126), _panel, _cape, params=PARAMS, macro_lag=Months(6))
define(
    "excess_cape_yield", "state", SERIES_INPUTS, Months(126), _panel, _ecy, params=PARAMS, macro_lag=Months(6)
)
define(
    "ecy_percentile",
    "state",
    SERIES_INPUTS,
    Months(246),
    _panel,
    _ecy_pct,
    params=PCT_PARAMS,
    macro_lag=Months(6),
)
