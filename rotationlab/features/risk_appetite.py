"""Risk appetite (state), research index of scripts/run_derisk.py.

Mean of expanding z-scores (at least 60 months; VIX 36), each signed so that high = risk-on / complacency:

    + equity momentum 12M          + equity vs its 10-month average
    − credit spread (Baa − Aaa)    − 6-month change of the credit spread
    − VIX (month-end close; from 1990)

The index needs at least three components. `start` cuts the history before computing anything (research:
1970-12, the start of the gold/silver panel; expanding statistics depend on it). `risk_appetite_pct` is the
expanding percentile of the index (from `min_history` values on).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define
from rotationlab.features._panel import (
    expanding_pct,
    expanding_z,
    from_start,
    month_grid,
    series_panel,
    tr_panel,
)

PARAMS: dict[str, Any] = {
    "equity": "US_EQ",
    "baa": "macro:BAA",
    "aaa": "macro:AAA",
    "vix": "macro:VIX",
    "start": "1970-12-31",
    "z_min": 60,
    "vix_z_min": 36,
}


def _panel(
    view: Any,
    _assets: Any,
    equity: str = "US_EQ",
    baa: str = "macro:BAA",
    aaa: str = "macro:AAA",
    vix: str = "macro:VIX",
    start: Any = None,
    **_: Any,
) -> pd.DataFrame:
    eq = tr_panel(view, [equity]).set_axis(["EQ"], axis=1)
    m = series_panel(view, [baa, aaa, vix]).set_axis(["BAA", "AAA", "VIX"], axis=1)
    df = pd.concat([eq, m], axis=1)
    valid = df.dropna(how="all")
    if valid.empty:
        return df
    return from_start(df.reindex(month_grid(valid.index[0], view.date)), start)


def components(panel: pd.DataFrame, z_min: int = 60, vix_z_min: int = 36) -> pd.DataFrame:
    eq, credit = panel["EQ"], panel["BAA"] - panel["AAA"]
    return pd.DataFrame(
        {
            "eq_mom_12m": expanding_z(eq / eq.shift(12) - 1, z_min),
            "eq_trend_10m": expanding_z(eq / eq.rolling(10).mean() - 1, z_min),
            "neg_credit": -expanding_z(credit, z_min),
            "neg_d_credit_6m": -expanding_z(credit.diff(6), z_min),
            "neg_vix": -expanding_z(panel["VIX"], vix_z_min),
        },
        index=panel.index,
    )


def index_series(panel: pd.DataFrame, z_min: int = 60, vix_z_min: int = 36, **_: Any) -> pd.Series:
    c = components(panel, z_min, vix_z_min)
    return c.mean(axis=1, skipna=True).where(c.notna().sum(axis=1) >= 3).rename("risk_appetite")


def _index(panel: pd.DataFrame, **kw: Any) -> pd.Series:
    """Risk-appetite index: mean of expanding z-scores of equity trend/momentum, credit and VIX (high = risk-on)."""
    return index_series(panel, **kw)


def _pct(panel: pd.DataFrame, min_history: int = 60, **kw: Any) -> pd.Series:
    """Expanding percentile of the risk-appetite index."""
    idx = index_series(panel, **kw)
    return expanding_pct(idx.dropna(), min_history).reindex(idx.index).rename("risk_appetite_pct")


INPUTS = ["total_return:equity", "series:macro:BAA", "series:macro:AAA", "series:macro:VIX"]
define("risk_appetite", "state", INPUTS, Months(72), _panel, _index, params=PARAMS)
define("risk_appetite_pct", "state", INPUTS, Months(132), _panel, _pct, params={**PARAMS, "min_history": 60})
