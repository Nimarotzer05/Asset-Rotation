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
    sleeve_vol_12m std × √12 of the last 12 monthly returns of w'r for given `weights` (state: one number;
                   = sqrt(w' Σ w) with the sample covariance – the vol target of the forecast portfolio, ADR 048)
    value_rev_60m  −(p(t) / p(t−60) − 1): long-term reversal (Asness/Moskowitz/Pedersen 2013; ADR 052 value)
    carry_yield    running income yield per class from a `spec` mapping (ADR 052 carry): equity_dy = implied
                   trailing-12-month dividend yield (TR return minus price return of two series), dividend_dy =
                   trailing-12-month cash dividends over the close (ETFs), yield = a stored yield series / 100,
                   zero = no income (metals); the money-market rate cancels in the cross-section and is left out

    vol_ewma       exponentially weighted standard deviation of the monthly returns (half-life `half_life`
                   months, at least `min_obs` returns, annualised × √12, floored at `floor`) – ADR 054 (c)
    basket_vol_ewma the same for the history of a fixed-weight basket w'r (state: one number) – ADR 054 (c)
    vol_ewma_d     EWMA standard deviation of *daily* returns (centre of mass `com` sessions, at least
                   `min_obs` returns, × √252, floored at `floor`; NaN when the asset's last price is more than
                   `stale_days` calendar days old) – Moskowitz/Ooi/Pedersen 2012, ADR 057
    basket_vol_ewma_d the same for the daily returns of a fixed-weight basket on the dates all members trade
    book_vol_hybrid volatility of a book of baskets: sleeve volatilities given (`vols`), correlations from the
                   EWMA of the baskets' *monthly* returns (half-life `half_life`, ≥ `min_obs` months) –
                   "volatilities fast, correlations slow"; σ = √(x'DRDx + idle) with x the sleeve sizes and
                   `idle` the variance of budgets of inactive sleeves (ADR 057, 058 d)
    carry_yield    a `yield` spec may set `max_age_months`: a monthly rate published with a lag has no value in
                   the decision month, so the latest published value counts while it is at most that many
                   months old (ADR 058 a)

Missing history gives NaN; an asset without a value in the month of D gives NaN (never a stale value).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.types import Months
from rotationlab.features._define import define
from rotationlab.features._panel import _on_grid, tr_panel

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


def _weighted_panel(
    view: Any, assets: Sequence[str] | None, weights: Mapping[str, float] | None = None, **_: Any
) -> pd.DataFrame:
    return tr_panel(view, list(weights or {}))


def _sleeve_vol(
    panel: pd.DataFrame, weights: Mapping[str, float] | None = None, months: int = 12
) -> pd.Series:
    """Annualised standard deviation of the last `months` monthly returns of the sleeve w'r with today's
    weights (= sqrt(w' Σ w) with the sample covariance); NaN until every asset has `months` returns."""
    w = dict(weights or {})
    if not w:
        return pd.Series(dtype=float)
    r = panel.reindex(columns=list(w)).pct_change()
    sleeve = (r * pd.Series(w)).sum(axis=1, min_count=len(w))
    out: pd.Series = sleeve.rolling(months).std() * np.sqrt(12)
    return out


def ewma_vol(
    r: pd.DataFrame | pd.Series, half_life: int, min_obs: int, floor: float
) -> pd.DataFrame | pd.Series:
    """Annualised EWMA standard deviation of monthly returns: pandas `ewm(halflife, adjust=True)` with
    `min_periods = min_obs` (a NaN return is left out of the window); floored at `floor` p.a."""
    out = r.ewm(halflife=half_life, min_periods=min_obs, adjust=True, ignore_na=True).std() * np.sqrt(12)
    clipped: pd.DataFrame | pd.Series = out.clip(lower=floor)
    return clipped


def _vol_ewma(
    panel: pd.DataFrame, half_life: int = 12, min_obs: int = 24, floor: float = 0.02
) -> pd.DataFrame:
    """Annualised EWMA volatility of each asset's monthly returns (ADR 054 c)."""
    out: pd.DataFrame = ewma_vol(panel.pct_change(), half_life, min_obs, floor)  # type: ignore[assignment]
    return out


def _basket_vol_ewma(
    panel: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
    half_life: int = 12,
    min_obs: int = 24,
    floor: float = 0.02,
) -> pd.Series:
    """Annualised EWMA volatility of the history of the basket w'r with today's weights (ADR 054 c); NaN
    until every asset of the basket has `min_obs` returns."""
    w = dict(weights or {})
    if not w:
        return pd.Series(dtype=float)
    r = panel.reindex(columns=list(w)).pct_change()
    basket = (r * pd.Series(w)).sum(axis=1, min_count=len(w))
    out: pd.Series = ewma_vol(basket, half_life, min_obs, floor)  # type: ignore[assignment]
    return out


def _daily_panel(view: Any, assets: Sequence[str] | None, **_: Any) -> pd.DataFrame:
    """Total-return levels at their native (daily) frequency, columns in the order asked for; the view date
    is always the last row (a price older than D shows up as stale there, never as current)."""
    cols = list(assets or [])
    df: pd.DataFrame = view.total_return(cols, None).reindex(columns=cols)
    d = pd.Timestamp(view.date)
    if not len(df.index) or df.index[-1] < d:
        df = df.reindex(df.index.append(pd.DatetimeIndex([d])))
    return df


def _vol_ewma_d(
    panel: pd.DataFrame, com: int = 60, min_obs: int = 120, floor: float = 0.02, stale_days: int = 10
) -> pd.DataFrame:
    """Annualised EWMA volatility of each asset's daily returns on its own observation dates (a holiday of one
    market is not a zero return of another), carried to the panel's dates; NaN once the asset's last price is
    more than `stale_days` calendar days behind the row date."""
    out = pd.DataFrame(index=panel.index, columns=panel.columns, dtype=float)
    for c in panel.columns:
        p = panel[c].dropna()
        if len(p) < 2:
            continue
        r = (p / p.shift(1) - 1.0).iloc[1:]
        v = r.ewm(com=com, min_periods=min_obs, adjust=True).std() * np.sqrt(252.0)
        v = v.clip(lower=floor)
        last = pd.Series(p.index, index=p.index).reindex(panel.index).ffill()
        age = (panel.index.to_series() - last).dt.days
        out[c] = v.reindex(panel.index).ffill().where(age <= stale_days)
    return out


def _daily_weighted_panel(
    view: Any, assets: Sequence[str] | None, weights: Mapping[str, float] | None = None, **_: Any
) -> pd.DataFrame:
    return _daily_panel(view, list(weights or {}))


def _basket_vol_ewma_d(
    panel: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
    com: int = 60,
    min_obs: int = 120,
    floor: float = 0.02,
    stale_days: int = 10,
) -> pd.Series:
    """Annualised EWMA volatility of the daily returns of w'r on the dates where every member has a price (the
    members of one sleeve share a calendar); NaN once the last common date is `stale_days` behind the row."""
    w = dict(weights or {})
    if not w:
        return pd.Series(dtype=float)
    p = panel.reindex(columns=list(w)).dropna(how="any")
    if len(p) < 2:
        return pd.Series(np.nan, index=panel.index)
    r = (p / p.shift(1) - 1.0).iloc[1:]
    basket = (r * pd.Series(w)).sum(axis=1)
    v = (basket.ewm(com=com, min_periods=min_obs, adjust=True).std() * np.sqrt(252.0)).clip(lower=floor)
    last = pd.Series(p.index, index=p.index).reindex(panel.index).ffill()
    age = (panel.index.to_series() - last).dt.days
    out: pd.Series = v.reindex(panel.index).ffill().where(age <= stale_days)
    return out


def _book_panel(
    view: Any,
    assets: Sequence[str] | None,
    baskets: Mapping[str, Mapping[str, float]] | None = None,
    **_: Any,
) -> pd.DataFrame:
    names = sorted({str(a) for b in (baskets or {}).values() for a in b})
    return tr_panel(view, names)


def _book_vol_hybrid(
    panel: pd.DataFrame,
    baskets: Mapping[str, Mapping[str, float]] | None = None,
    sizes: Mapping[str, float] | None = None,
    vols: Mapping[str, float] | None = None,
    half_life: int = 24,
    min_obs: int = 24,
    floor: float = 0.02,
    idle: float = 0.0,
) -> pd.Series:
    """σ_book,t = √(x' D R_t D x + idle): x = sleeve sizes, D = the given sleeve volatilities, R_t = EWMA
    correlation of the baskets' monthly returns up to t (every basket needs `min_obs` returns). `idle` is the
    variance of risk budgets held in cash because their sleeve is inactive (Σ b², counted as uncorrelated): the
    vol target then leaves an idle budget unused instead of handing it to the other sleeves (ADR 058 d)."""
    b = {str(k): dict(v) for k, v in (baskets or {}).items()}
    if not b:
        return pd.Series(dtype=float)
    names = sorted(b)
    r = panel.pct_change(fill_method=None)
    sr = pd.DataFrame(
        {n: (r.reindex(columns=list(b[n])) * pd.Series(b[n])).sum(axis=1, min_count=len(b[n])) for n in names}
    )
    x = np.array([float((sizes or {})[n]) for n in names])
    d = np.array([float((vols or {})[n]) for n in names])
    xd = x * d
    out = pd.Series(np.nan, index=panel.index)
    if len(names) == 1:
        ok = sr[names[0]].notna().astype(int).cumsum() >= min_obs
        out[ok] = float(np.sqrt(float(xd[0]) ** 2 + idle))
        return out.clip(lower=floor)
    corr = sr.ewm(halflife=half_life, min_periods=min_obs, adjust=True).corr()
    grid = pd.MultiIndex.from_product([sr.index, names])
    m = (
        corr.reindex(index=grid, columns=names)
        .to_numpy(dtype=float)
        .reshape(len(sr.index), len(names), len(names))
    )
    known = ~np.isnan(m).any(axis=(1, 2))  # every pairwise correlation exists at t
    q = np.einsum("i,tij,j->t", xd, np.nan_to_num(m), xd)
    out[known] = np.sqrt(np.maximum(q[known], 0.0) + idle)
    return out.clip(lower=floor)


def _value_rev(panel: pd.DataFrame, months: int = 60) -> pd.DataFrame:
    """Long-term reversal: −(p(t)/p(t−months) − 1)."""
    return -(panel / panel.shift(months) - 1)


def _carry_panel(
    view: Any, assets: Sequence[str] | None, spec: Mapping[str, Mapping[str, str]] | None = None, **_: Any
) -> pd.DataFrame:
    """One column per input series named `<asset>|<role>` (tr, px, yield), monthly on the grid."""
    cols: dict[str, pd.Series] = {}
    for a in assets or []:
        s = (spec or {}).get(a)
        if not s:
            continue
        kind = s.get("kind")
        if kind == "equity_dy":
            cols[f"{a}|tr"] = view.series(s["tr"], "ME")
            cols[f"{a}|px"] = view.series(s["px"], "ME")
        elif kind == "dividend_dy":  # ETFs: cash dividends per share (summed per month) over the close
            cols[f"{a}|px"] = view.series(s["close"], "ME")
            div = view.series(s["dividend"])
            cols[f"{a}|div"] = div.resample("ME").sum() if len(div) else div
        elif kind == "yield":
            cols[f"{a}|yield"] = view.series(s["series"], "ME")
    df = pd.DataFrame(cols) if cols else pd.DataFrame()
    return _on_grid(df, view.date) if len(df) else df


def _carry(
    panel: pd.DataFrame, spec: Mapping[str, Mapping[str, str]] | None = None, months: int = 12
) -> pd.DataFrame:
    """Income yield per class: equity_dy = (TR_t/TR_{t−m}) / (P_t/P_{t−m}) − 1; yield = y/100; zero = 0."""
    out: dict[str, pd.Series] = {}
    idx = panel.index
    for a, s in (spec or {}).items():
        kind = s.get("kind")
        if kind == "equity_dy" and f"{a}|tr" in panel and f"{a}|px" in panel:
            tr, px = panel[f"{a}|tr"], panel[f"{a}|px"]
            out[a] = (tr / tr.shift(months)) / (px / px.shift(months)) - 1
        elif kind == "dividend_dy" and f"{a}|px" in panel and f"{a}|div" in panel:
            out[a] = panel[f"{a}|div"].fillna(0.0).rolling(months).sum() / panel[f"{a}|px"]
        elif kind == "yield" and f"{a}|yield" in panel:
            y = panel[f"{a}|yield"]
            age = s.get("max_age_months")
            if (
                age is not None
            ):  # a monthly yield published with a lag: the latest value up to `age` months old
                y = y.ffill(limit=int(age))
            out[a] = y / 100.0
        elif kind == "zero":
            out[a] = pd.Series(0.0, index=idx)
    return pd.DataFrame(out, index=idx)


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
    "sleeve_vol_12m",
    "state",
    TR,
    Months(13),
    _weighted_panel,
    _sleeve_vol,
    params={"weights": {}, "months": 12},
)
define(
    "vol_ewma",
    "cross_section",
    TR,
    Months(0),
    _assets_panel,
    _vol_ewma,
    params={"half_life": 12, "min_obs": 24, "floor": 0.02},
)
define(
    "basket_vol_ewma",
    "state",
    TR,
    Months(0),
    _weighted_panel,
    _basket_vol_ewma,
    params={"weights": {}, "half_life": 12, "min_obs": 24, "floor": 0.02},
)
define(
    "vol_ewma_d",
    "cross_section",
    TR,
    Months(0),
    _daily_panel,
    _vol_ewma_d,
    params={"com": 60, "min_obs": 120, "floor": 0.02, "stale_days": 10},
)
define(
    "basket_vol_ewma_d",
    "state",
    TR,
    Months(0),
    _daily_weighted_panel,
    _basket_vol_ewma_d,
    params={"weights": {}, "com": 60, "min_obs": 120, "floor": 0.02, "stale_days": 10},
)
define(
    "book_vol_hybrid",
    "state",
    TR,
    Months(0),
    _book_panel,
    _book_vol_hybrid,
    params={
        "baskets": {},
        "sizes": {},
        "vols": {},
        "half_life": 24,
        "min_obs": 24,
        "floor": 0.02,
        "idle": 0.0,
    },
)
define("value_rev_60m", "cross_section", TR, Months(60), _assets_panel, _value_rev, params={"months": 60})
define(
    "carry_yield",
    "cross_section",
    ["total_return", "yield"],
    Months(13),
    _carry_panel,
    _carry,
    params={"spec": {}, "months": 12},
)
define(
    "excess_mom_12m",
    "cross_section",
    TR,
    Months(13),
    _with_cash,
    _excess_mom,
    params={"cash": "CASH", "months": 12},
)
