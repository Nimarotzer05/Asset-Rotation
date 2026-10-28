"""Speculative positioning (state): CFTC legacy futures-only report, weekly.

    cot_spec_net_z   z-score of the non-commercial net position as a share of open interest, against the
                     last `window` weeks (at least `min_periods`); high = speculators crowded long

Positions are as of Tuesday and published on Friday (store lag 7D); the value at D is the latest report
public by D. The research panel holds no CFTC history: in backtests before the live store has a few years
of reports the feature is NaN, and nothing trades on it (context only).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define

PARAMS: dict[str, Any] = {
    "net": "cftc:088691:noncomm_net",
    "open_interest": "cftc:088691:open_interest",
    "window": 156,
    "min_periods": 52,
}


def _panel(view: Any, _assets: Any, net: str = "", open_interest: str = "", **_: Any) -> pd.DataFrame:
    return pd.DataFrame({"net": view.series(net), "oi": view.series(open_interest)})


def _z(panel: pd.DataFrame, window: int = 156, min_periods: int = 52, **_: Any) -> pd.Series:
    """z-score of the non-commercial net share of open interest over the last 3 years of weekly reports."""
    if panel.empty:
        return pd.Series(dtype=float, name="cot_spec_net_z")
    share = panel["net"] / panel["oi"].where(panel["oi"] > 0)
    mu = share.rolling(window, min_periods=min_periods).mean()
    sd = share.rolling(window, min_periods=min_periods).std()
    return ((share - mu) / sd).rename("cot_spec_net_z")


define("cot_spec_net_z", "state", ["series:cftc"], Months(36), _panel, _z, params=PARAMS)
