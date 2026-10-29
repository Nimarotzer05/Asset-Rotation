"""Macro regime and driver features (state), research formulas of src/features.py and src/commodity_model.py.

Regime (src/features.py::macro_regime): growth = year-on-year rate of industrial production, inflation = of
CPI; each smoothed over 3 months and compared with its value 3 months earlier ("high" = rising, "low" =
falling); the quadrant joins both. Commodity state (src/commodity_model.py::macro_state): the same three-
month directions for the log dollar index, the IP rate and the CPI rate (8 states).

Activity and price statistics are published the month after (store lag 1M); `lag` (default 1, the research
shift) reads the value of the previous month, which the store has by D. Market-rate averages (GS10, Baa,
Aaa, T-bill, Fed funds) are public at month-end (0D). The research dollar index carries no publication
lag in the store either, but the studies lagged the whole commodity state by a month: `usd_lag` keeps that.

Drivers are 3-month changes: real 10y yield (GS10 − CPI rate), log dollar, CPI rate, credit spread
(Baa − Aaa), curve (GS10 − 3M bill), Fed funds; plus levels used by reports and the risk-appetite index, and
the real policy rate (Fed funds − CPI rate; ADR 063, round 5's Fed category).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define
from rotationlab.features._panel import series_panel

SOURCES = {
    "indpro": "macro:INDPRO",
    "cpi": "macro:CPI",
    "gs10": "macro:GS10",
    "baa": "macro:BAA",
    "aaa": "macro:AAA",
    "tb3ms": "macro:TB3MS",
    "fedfunds": "macro:FEDFUNDS",
    "unrate": "macro:UNRATE",
    "usd": "static:USD_IDX",
}
COLS = list(SOURCES)


def _panel(view: Any, _assets: Any, **kw: Any) -> pd.DataFrame:
    ids = [kw.get(k, v) for k, v in SOURCES.items()]
    return series_panel(view, ids).set_axis(COLS, axis=1)


def _log(s: pd.Series) -> pd.Series:
    return pd.Series(np.log(s.to_numpy(dtype=float)), index=s.index, name=s.name)


def _labels(parts: list[tuple[str, pd.Series, dict[float, str]]], sep: str) -> pd.Series:
    """Join categorical directions into one label per row; NaN where any part is missing."""
    idx = parts[0][1].index
    cols = [s.reindex(idx).to_numpy(dtype=float) for _, s, _ in parts]
    out: list[str | None] = []
    for i in range(len(idx)):
        vals = [c[i] for c in cols]
        if any(np.isnan(v) for v in vals):
            out.append(None)
        else:
            out.append(sep.join(f"{p}{m[v]}" for (p, _, m), v in zip(parts, vals, strict=True)))
    return pd.Series(out, index=idx, dtype=object)


def _yoy(s: pd.Series) -> pd.Series:
    return s.pct_change(12, fill_method=None) * 100


def _direction(s: pd.Series, smooth: int) -> pd.Series:
    """+1 rising, −1 falling (smoothed level vs `smooth` months earlier), NaN without enough history."""
    m = s.rolling(smooth).mean()
    d = pd.Series(np.where(m > m.shift(smooth), 1.0, -1.0), index=s.index)
    # NaN on either side is "unknown", not "falling" (NaN > x is False; second review 2026-10-25)
    return d.where(m.notna() & m.shift(smooth).notna())


def growth_direction(panel: pd.DataFrame, smooth: int = 3, lag: int = 1) -> pd.Series:
    return _direction(_yoy(panel["indpro"]), smooth).shift(lag)


def inflation_direction(panel: pd.DataFrame, smooth: int = 3, lag: int = 1) -> pd.Series:
    return _direction(_yoy(panel["cpi"]), smooth).shift(lag)


def _growth(panel: pd.DataFrame, smooth: int = 3, lag: int = 1, **_: Any) -> pd.Series:
    """Growth direction: +1 if the smoothed IP year-on-year rate rises over 3 months, −1 if it falls."""
    return growth_direction(panel, smooth, lag).rename("growth_dir")


def _inflation(panel: pd.DataFrame, smooth: int = 3, lag: int = 1, **_: Any) -> pd.Series:
    """Inflation direction: +1 if the smoothed CPI year-on-year rate rises over 3 months, −1 if it falls."""
    return inflation_direction(panel, smooth, lag).rename("inflation_dir")


def _quadrant(panel: pd.DataFrame, smooth: int = 3, lag: int = 1, **_: Any) -> pd.Series:
    """Growth × inflation quadrant ("high_low" = growth rising, inflation falling; "unknown" without data)."""
    g = growth_direction(panel, smooth, lag)
    i = inflation_direction(panel, smooth, lag)
    lab = {1.0: "high", -1.0: "low"}
    out = _labels([("", g, lab), ("", i, lab)], "_")
    return out.where(out.notna(), "unknown").rename("quadrant")


def _commodity_state(
    panel: pd.DataFrame, smooth: int = 3, lag: int = 1, usd_lag: int = 1, **_: Any
) -> pd.Series:
    """Commodity macro state: directions of log dollar, IP rate and CPI rate, e.g. "USD↓ IP↑ CPI↑"."""
    arrow = {1.0: "↑", -1.0: "↓"}
    usd = _direction(_log(panel["usd"]), smooth).shift(usd_lag)
    ip = _direction(_yoy(panel["indpro"]), smooth).shift(lag)
    cpi = _direction(_yoy(panel["cpi"]), smooth).shift(lag)
    return _labels([("USD", usd, arrow), ("IP", ip, arrow), ("CPI", cpi, arrow)], " ").rename(
        "commodity_state"
    )


def _sahm(panel: pd.DataFrame, lag: int = 1, **_: Any) -> pd.Series:
    """Sahm indicator: 3-month average unemployment rate minus its 12-month low (≥ 0.5 = recession signal)."""
    un = panel["unrate"].shift(lag)
    m3 = un.rolling(3).mean()
    return (m3 - m3.rolling(12).min()).rename("sahm")


def real_yield(panel: pd.DataFrame, lag: int = 1) -> pd.Series:
    """Ex-post real 10y yield: GS10 minus the CPI year-on-year rate (both of the same month)."""
    return panel["gs10"] - _yoy(panel["cpi"])


def _d_real(panel: pd.DataFrame, lag: int = 1, **_: Any) -> pd.Series:
    """3-month change of the ex-post real 10y yield, read one month back (CPI timing)."""
    return real_yield(panel).diff(3).shift(lag).rename("d_real_yield_3m")


def _d_usd(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """3-month change of the log dollar index."""
    return _log(panel["usd"]).diff(3).rename("d_log_usd_3m")


def _d_cpi(panel: pd.DataFrame, lag: int = 1, **_: Any) -> pd.Series:
    """3-month change of the CPI year-on-year rate (percentage points), read one month back."""
    return _yoy(panel["cpi"]).diff(3).shift(lag).rename("d_cpi_yoy_3m")


def _credit(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """Credit spread Baa − Aaa (percentage points, monthly averages)."""
    return (panel["baa"] - panel["aaa"]).rename("credit_spread")


def _d_credit(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """3-month change of the Baa − Aaa spread."""
    return (panel["baa"] - panel["aaa"]).diff(3).rename("d_credit_3m")


def _d_curve(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """3-month change of the curve GS10 − 3M T-bill."""
    return (panel["gs10"] - panel["tb3ms"]).diff(3).rename("d_curve_3m")


def _d_ff(panel: pd.DataFrame, **_: Any) -> pd.Series:
    """3-month change of the Fed funds rate."""
    return panel["fedfunds"].diff(3).rename("d_fedfunds_3m")


def _real_policy(panel: pd.DataFrame, lag: int = 1, **_: Any) -> pd.Series:
    """Real policy rate (ADR 063): Fed funds of the month minus the CPI year-on-year rate read one month back
    (the latest CPI known at the month-end) – the stance of monetary policy, restrictive when high."""
    return (panel["fedfunds"] - _yoy(panel["cpi"]).shift(lag)).rename("real_policy_rate")


def _fred_daily(name: str, series_id: str) -> None:
    def _panel_one(view: Any, _assets: Any, series: str = series_id, **_: Any) -> pd.DataFrame:
        return series_panel(view, [series]).set_axis(["x"], axis=1)

    def _level(panel: pd.DataFrame, **_: Any) -> pd.Series:
        return panel["x"].rename(name)

    _level.__doc__ = f"Month-end level of {series_id} (live FRED series; empty in the research panel)."
    define(
        name, "state", [f"series:{series_id}"], Months(0), _panel_one, _level, params={"series": series_id}
    )


MACRO_INPUTS = [f"series:{s}" for s in SOURCES.values()]
REG = {**SOURCES, "smooth": 3, "lag": 1}
define("growth_dir", "state", MACRO_INPUTS, Months(19), _panel, _growth, params=REG, macro_lag=Months(1))
define(
    "inflation_dir", "state", MACRO_INPUTS, Months(19), _panel, _inflation, params=REG, macro_lag=Months(1)
)
define("quadrant", "state", MACRO_INPUTS, Months(19), _panel, _quadrant, params=REG, macro_lag=Months(1))
define(
    "commodity_state",
    "state",
    MACRO_INPUTS,
    Months(19),
    _panel,
    _commodity_state,
    params={**REG, "usd_lag": 1},
    macro_lag=Months(1),
)
define(
    "sahm",
    "state",
    MACRO_INPUTS,
    Months(15),
    _panel,
    _sahm,
    params={**SOURCES, "lag": 1},
    macro_lag=Months(1),
)
define(
    "d_real_yield_3m",
    "state",
    MACRO_INPUTS,
    Months(16),
    _panel,
    _d_real,
    params={**SOURCES, "lag": 1},
    macro_lag=Months(1),
)
define("d_log_usd_3m", "state", MACRO_INPUTS, Months(3), _panel, _d_usd, params=SOURCES)
define(
    "d_cpi_yoy_3m",
    "state",
    MACRO_INPUTS,
    Months(16),
    _panel,
    _d_cpi,
    params={**SOURCES, "lag": 1},
    macro_lag=Months(1),
)
define("credit_spread", "state", MACRO_INPUTS, Months(0), _panel, _credit, params=SOURCES)
define("d_credit_3m", "state", MACRO_INPUTS, Months(3), _panel, _d_credit, params=SOURCES)
define("d_curve_3m", "state", MACRO_INPUTS, Months(3), _panel, _d_curve, params=SOURCES)
define("d_fedfunds_3m", "state", MACRO_INPUTS, Months(3), _panel, _d_ff, params=SOURCES)
define(
    "real_policy_rate",
    "state",
    MACRO_INPUTS,
    Months(13),
    _panel,
    _real_policy,
    params={**SOURCES, "lag": 1},
    macro_lag=Months(1),
)
_fred_daily("tips_real_10y", "fred:DFII10")
_fred_daily("breakeven_10y", "fred:T10YIE")
