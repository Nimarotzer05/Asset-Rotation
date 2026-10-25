"""Price features (cross-sectional): one value per asset at the view date, from monthly total-return levels.

Formulas are the research ones (src/features.py, src/signals.py, scripts/run_equity.py), on the monthly
grid p (month-end labels; the running month is labelled with the view date):

    mom_<h>_1      p(t−1) / p(t−1−h) − 1           h = 3, 6, 12 (one-month skip against short-term reversal)
    mom_12         p(t) / p(t−12) − 1              (no skip)
    trend_10m      p(t) / mean(p(t−9 … t)) − 1     above its 10-month average ⇔ trend_10m > 0
    vol_12m        std of the last 12 monthly returns (sample, ddof 1)
    inv_vol_12m    1 / vol_12m
    drawdown       p(t) / max(p(… t)) − 1
    excess_mom_12m Π(1 + r − r_cash) over 12 months − 1     (param `cash`: asset whose return is subtracted)

Missing history gives NaN; an asset without a value in the month of D gives NaN (never a stale value).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define
from rotationlab.features._panel import tr_panel

TR = ["total_return"]


def _assets_panel(view: Any, assets: Sequence[str] | None, **_: Any) -> pd.DataFrame:
    return tr_panel(view, list(assets or []))


def _with_cash(view: Any, assets: Sequence[str] | None, cash: str = "CASH", **_: Any) -> pd.DataFrame:
    cols = [a for a in (assets or []) if a != cash] + [cash]
    return tr_panel(view, cols)


def momentum(p: pd.DataFrame, months: int, skip: int) -> pd.DataFrame:
    return p.shift(skip) / p.shift(months + skip) - 1


def trend(p: pd.DataFrame, window: int) -> pd.DataFrame:
    return p / p.rolling(window).mean() - 1


def volatility(p: pd.DataFrame, window: int) -> pd.DataFrame:
    return p.pct_change().rolling(window).std()


for _h in (3, 6, 12):

    def _mom(panel: pd.DataFrame, _h: int = _h) -> pd.DataFrame:
        return momentum(panel, _h, 1)

    _mom.__doc__ = f"{_h}-month momentum with a one-month skip: p(t−1)/p(t−{_h + 1}) − 1."
    define(f"mom_{_h}_1", "cross_section", TR, Months(_h + 1), _assets_panel, _mom)


def _mom12(panel: pd.DataFrame) -> pd.DataFrame:
    """12-month momentum without skip: p(t)/p(t−12) − 1."""
    return momentum(panel, 12, 0)


def _trend10(panel: pd.DataFrame) -> pd.DataFrame:
    """Distance to the 10-month average: p(t)/mean(p(t−9…t)) − 1."""
    return trend(panel, 10)


def _vol12(panel: pd.DataFrame) -> pd.DataFrame:
    """Standard deviation of the last 12 monthly returns."""
    return volatility(panel, 12)


def _inv_vol12(panel: pd.DataFrame) -> pd.DataFrame:
    """1 / standard deviation of the last 12 monthly returns (zero volatility gives NaN)."""
    return 1 / volatility(panel, 12).replace(0, np.nan)


def _drawdown(panel: pd.DataFrame) -> pd.DataFrame:
    """Distance to the running maximum of the total-return level."""
    return panel / panel.cummax() - 1


def _excess_mom(panel: pd.DataFrame, cash: str = "CASH", months: int = 12) -> pd.DataFrame:
    """Compounded excess return over the cash asset across the last `months` months."""
    r = panel.pct_change()
    ex = r.drop(columns=[cash]).sub(r[cash], axis=0)
    return (1 + ex).rolling(months).apply(np.prod, raw=True) - 1


define("mom_12", "cross_section", TR, Months(12), _assets_panel, _mom12)
define("trend_10m", "cross_section", TR, Months(10), _assets_panel, _trend10)
define("vol_12m", "cross_section", TR, Months(13), _assets_panel, _vol12)
define("inv_vol_12m", "cross_section", TR, Months(13), _assets_panel, _inv_vol12)
define("drawdown", "cross_section", TR, Months(0), _assets_panel, _drawdown)
define(
    "excess_mom_12m",
    "cross_section",
    TR,
    Months(13),
    _with_cash,
    _excess_mom,
    params={"cash": "CASH", "months": 12},
)
