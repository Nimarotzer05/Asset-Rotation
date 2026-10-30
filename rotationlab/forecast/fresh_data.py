"""ADR 069: two robust rules tested on data no study of this project has touched.

1. Trend filter on US equities 1885–1926 – the one result that held up (round 4, the first equity study 1927–2026),
   on 41 earlier years: hold equities in the month after a month-end at which the total-return level is above its
   10-month average (the month-end levels, the current one included), otherwise cash.
2. Turn of the month – equities only from the last trading day of a month to the third trading day of the next
   (Ariel 1987, Lakonishok & Smidt 1988), cash otherwise; before its discovery (1885–1926, untouched) and after its
   publication (1988–2025).

Both functions take levels and return the strategy's returns before costs plus what is needed to charge them; the
switches are counted so that a cost per switch can be applied by the caller.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def month_end_levels(daily: pd.Series) -> pd.Series:
    """The last close of every calendar month, labelled with the calendar month-end."""
    s = daily.dropna()
    out = s.groupby(pd.DatetimeIndex(s.index).to_period("M")).last()
    out.index = pd.PeriodIndex(out.index).to_timestamp("M")
    return out


def trend_filter(levels: pd.Series, cash: pd.Series, window: int = 10) -> pd.DataFrame:
    """Monthly trend filter. `levels`: month-end total-return levels; `cash`: monthly cash returns (same labels).
    Row t+1 holds the return earned in month t+1 on the decision taken at the close of month t:
    invested = level(t) > mean(level(t−window+1 … t)). Columns: ret, invested, switch (1 when the position changed
    at that decision, the first decision counts as a switch if it invests)."""
    sig = levels / levels.rolling(window).mean() - 1.0
    eq = levels.pct_change(fill_method=None)
    inv = (sig > 0).astype(float).where(sig.notna())
    held = inv.shift(1)
    ret = held * eq + (1.0 - held) * cash.reindex(levels.index)
    switch = held.diff().abs()
    valid = held.dropna()
    if len(valid):
        switch.loc[valid.index[0]] = valid.iloc[0]
    return pd.DataFrame({"ret": ret, "invested": held, "switch": switch}).dropna(subset=["ret"])


def turn_of_month_days(index: pd.DatetimeIndex, before: int = 1, after: int = 3) -> pd.Series:
    """True on the last `before` trading days of every month and the first `after` trading days of every month
    (trading days = the dates of `index`). A month cut off at either end of `index` is treated as if it started or
    ended there – callers evaluate complete months only."""
    idx = pd.DatetimeIndex(index).sort_values()
    per = idx.to_period("M")
    pos = pd.Series(np.arange(len(idx)), index=idx)
    first_pos = pos.groupby(per).transform("min").to_numpy()
    last_pos = pos.groupby(per).transform("max").to_numpy()
    k = np.arange(len(idx))
    flag = (k - first_pos < after) | (last_pos - k < before)
    return pd.Series(flag, index=idx)


def turn_of_month(equity: pd.Series, cash: pd.Series, before: int = 1, after: int = 3) -> pd.DataFrame:
    """Daily turn-of-the-month rule. `equity`, `cash`: daily total-return levels on the same trading days. The
    return of day d (close d−1 to close d) is the equity return on turn-of-month days and the cash return on all
    other days – i.e. buy at the close before the last trading day, sell at the close of the third trading day.
    Columns: ret, in_market, eq (equity return), rf (cash return), switch (1 on each entry and each exit)."""
    df = pd.DataFrame({"eq": equity, "rf": cash}).dropna()
    r = df.pct_change(fill_method=None).iloc[1:]
    tom = turn_of_month_days(pd.DatetimeIndex(df.index), before, after).reindex(r.index)
    ret = np.where(tom, r["eq"], r["rf"])
    inm = tom.astype(float)
    switch = inm.diff().abs().fillna(inm)
    return pd.DataFrame(
        {"ret": ret, "in_market": inm, "eq": r["eq"], "rf": r["rf"], "switch": switch}, index=r.index
    )


def monthly(daily_ret: pd.Series) -> pd.Series:
    """Compound daily returns to calendar months (labelled with the month-end)."""
    g = (1.0 + daily_ret).groupby(pd.DatetimeIndex(daily_ret.index).to_period("M")).prod() - 1.0
    g.index = pd.PeriodIndex(g.index).to_timestamp("M")
    return g
