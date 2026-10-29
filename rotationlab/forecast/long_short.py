"""A leveraged long-short rule on a monthly ranking, with explicit accounting (ADR 063 a).

The rule (Nima, 2026-10-29): at each month-end, buy the class ranked first with `leverage` × equity and sell short
the class ranked last with `leverage` × equity, for one month – unless the forecast has not changed, in which
case the position is kept as it is. Gross exposure 2 × 1.5 = 3.0 lies above the engine's limit of 2.0
(core/types.py Proposal), so the rule is accounted here, month by month, in fractions of equity:

    long  L = notional of the long leg / equity        short S = notional of the short leg / equity
    cash  1 − L + S   (own capital plus the short-sale proceeds, which earn the cash rate as a rebate)
    month return  R = L·r_long − S·r_short + (1 − L + S)·r_cash
                      − spread/12 · max(L − 1, 0)      (the part of the long not covered by equity is borrowed)
                      − borrow[short]/12 · S             (lending fee of the shorted instrument)
                      − cost · traded notional           (charged at the decision, i.e. in the month that follows)
    drift   L ← L·(1 + r_long)/(1 + R),  S ← S·(1 + r_short)/(1 + R)

With L = S = 1.5 the excess return over cash is 1.5·(r_long − r_short) − 0.5·spread/12 − 1.5·borrow/12 − costs.

`hold`:
    "per_leg"  (the registered rule) a leg is traded only when its class changes; an unchanged leg keeps its drifted
               size. A changed leg is closed and the new class opened at `leverage` × current equity.
    "reset"    both legs are set back to `leverage` every month (a sensitivity, ADR 063 a).

A month in which equity falls to zero or below is a ruin: the series ends there with −100 %. Margin calls inside
the month are not modelled (monthly data); the drawdown column shows how close the path came.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

Hold = Literal["per_leg", "reset"]


@dataclass(frozen=True)
class Frictions:
    cost_bps: float = 7.5  # per unit of notional traded (one side), the round-1 golden convention
    financing_spread: float = 0.0030  # p.a. over the cash rate on borrowed money (engine convention)
    borrow: Mapping[str, float] = field(default_factory=dict)  # p.a. lending fee per shorted instrument


@dataclass(frozen=True)
class LongShortResult:
    monthly: pd.DataFrame  # labelled with the month the return was earned
    ruin: pd.Timestamp | None


def picks(ranks: pd.DataFrame) -> pd.DataFrame:
    """First and last class per decision month (NaN where a month has no complete ranking)."""
    complete = ranks.notna().all(axis=1)
    out = pd.DataFrame({"long": np.nan, "short": np.nan}, index=ranks.index, dtype=object)
    full = ranks[complete]  # idxmin/idxmax fail on rows without any value (the start of the panel)
    if len(full):
        out.loc[full.index, "long"] = full.idxmin(axis=1)
        out.loc[full.index, "short"] = full.idxmax(axis=1)
    return out


def _leg(held: str | None, size: float, want: str, leverage: float, hold: Hold) -> tuple[str, float, float]:
    """One leg at a decision: (class, size, notional traded). Unchanged class under "per_leg": kept as it is."""
    if want != held:
        return want, leverage, size + leverage  # close the old class, open the new one
    if hold == "reset":
        return want, leverage, abs(leverage - size)
    return want, size, 0.0


def run_long_short(
    choice: pd.DataFrame,
    returns: pd.DataFrame,
    cash: pd.Series,
    leverage: float = 1.5,
    hold: Hold = "per_leg",
    frictions: Frictions | None = None,
) -> LongShortResult:
    """`choice`: per decision month-end the class to hold long and short (columns long, short; NaN = no new
    information, the book is kept). `returns`, `cash`: monthly returns labelled with the month-end they end on.
    Decisions run in order; the return of the month after decision t is labelled t + 1 month."""
    fr = frictions or Frictions()
    cost = fr.cost_bps / 1e4
    months = list(choice.index)
    rows = []
    long_a: str | None = None
    short_a: str | None = None
    lw = sw = 0.0
    equity, peak = 1.0, 1.0
    ruin: pd.Timestamp | None = None
    for t in months:
        nxt = pd.Timestamp(t) + pd.offsets.MonthEnd(1)
        if nxt not in returns.index or nxt not in cash.index:
            continue
        want_l, want_s = choice.at[t, "long"], choice.at[t, "short"]
        traded = 0.0
        if isinstance(want_l, str) and isinstance(want_s, str):
            long_a, lw, tl = _leg(long_a, lw, want_l, leverage, hold)
            short_a, sw, ts = _leg(short_a, sw, want_s, leverage, hold)
            traded = tl + ts
        if long_a is None or short_a is None:
            continue
        legs = returns.loc[nxt, [long_a, short_a]].to_numpy(dtype=float)
        rl, rs = float(legs[0]), float(legs[1])
        rc = float(cash.reindex([nxt]).to_numpy(dtype=float)[0])
        if any(np.isnan(v) for v in (rl, rs, rc)):
            raise ValueError(f"long_short: missing return in {nxt:%Y-%m} for {long_a}/{short_a}/cash")
        fin = fr.financing_spread / 12 * max(lw - 1.0, 0.0)
        bor = fr.borrow.get(short_a, 0.0) / 12 * sw
        tc = cost * traded
        r = lw * rl - sw * rs + (1.0 - lw + sw) * rc - fin - bor - tc
        gross_l, gross_s = lw, sw
        if 1.0 + r <= 0.0:
            ruin = nxt
            r = -1.0
        equity *= 1.0 + r
        peak = max(peak, equity)
        rows.append(
            {
                "month": nxt,
                "ret": r,
                "cash": rc,
                "long": long_a,
                "short": short_a,
                "long_size": gross_l,
                "short_size": gross_s,
                "traded": traded,
                "cost": tc,
                "financing": fin,
                "borrow": bor,
                "drawdown": equity / peak - 1.0,
            }
        )
        if ruin is not None:
            break
        lw = lw * (1.0 + rl) / (1.0 + r)
        sw = sw * (1.0 + rs) / (1.0 + r)
    df = pd.DataFrame(rows).set_index("month") if rows else pd.DataFrame()
    return LongShortResult(df, ruin)


# ---------------------------------------------------------------------------
# ADR 065: close and reopen every month, 20 % stop on daily closes
# ---------------------------------------------------------------------------
def _last_at(s: pd.Series, t: pd.Timestamp) -> float:
    """The last value of `s` on or before t (NaN if none)."""
    x = s.loc[:t].dropna()
    return float(x.iloc[-1]) if len(x) else float("nan")


def run_long_short_stop(
    choice: pd.DataFrame,
    daily: pd.DataFrame,
    cash: pd.Series,
    leverage: float = 1.5,
    stop: float | None = 0.20,
    frictions: Frictions | None = None,
) -> LongShortResult:
    """ADR 065 (Nima, 2026-10-29): at every month-end close both legs and open them again – rank 1 long and the
    last rank short, each `leverage` × equity – paying costs on the full sale and the full purchase, also when the
    class stays the same. During the month every daily close is checked: if the long has fallen `stop` (20 %) below
    its entry close, or the short has risen `stop` above its entry close, **both** legs are closed at that close
    and the book stays in cash until the month-end. A gap through the stop is filled at the close that shows it
    (worse than −20 %); intraday prices are not modelled. `stop=None` = the same rule without stop.

    Per month, in fractions of the equity at the decision (L = S = leverage, r_l / r_s = return of each leg from
    the entry close to the exit close, f = share of the month's trading days held):

        R = L·r_l − S·r_s + r_cash·(f + (1 − f)·(1 + L·r_l − S·r_s)) − spread/12·max(L − 1, 0)·f − borrow/12·S·f
            − cost·(L + S)  − cost·(L·(1 + r_l) + S·(1 + r_s))

    `daily`: total-return or price levels of the traded classes on trading days; `cash`: monthly cash returns
    labelled with the month-end. A month without a complete ranking holds cash."""
    fr = frictions or Frictions()
    rows = []
    equity, peak = 1.0, 1.0
    ruin: pd.Timestamp | None = None
    thr = stop if stop is not None else float("inf")
    for t0 in choice.index:
        t = pd.Timestamp(t0)
        nxt = t + pd.offsets.MonthEnd(1)
        if nxt not in cash.index:
            continue
        rc = float(cash.reindex([nxt]).to_numpy(dtype=float)[0])
        la, sa = choice.at[t, "long"], choice.at[t, "short"]
        row: dict[str, object] = {"month": nxt, "cash": rc, "long": la, "short": sa}
        if not (isinstance(la, str) and isinstance(sa, str)):
            r = rc
            row.update(
                ret=r,
                stopped=False,
                stop_leg=None,
                exit_day=None,
                held=0.0,
                cost=0.0,
                r_long=0.0,
                r_short=0.0,
            )
        else:
            row.update(_stop_month(daily, t, nxt, la, sa, rc, leverage, thr, fr))
        if float(row["ret"]) <= -1.0:  # type: ignore[arg-type]
            row["ret"] = -1.0
            ruin = nxt
        equity *= 1.0 + float(row["ret"])  # type: ignore[arg-type]
        peak = max(peak, equity)
        row["drawdown"] = equity / peak - 1.0
        rows.append(row)
        if ruin is not None:
            break
    df = pd.DataFrame(rows).set_index("month") if rows else pd.DataFrame()
    return LongShortResult(df, ruin)


def _stop_month(
    daily: pd.DataFrame,
    t: pd.Timestamp,
    nxt: pd.Timestamp,
    la: str,
    sa: str,
    rc: float,
    leverage: float,
    thr: float,
    fr: Frictions,
) -> dict[str, object]:
    """One month of `run_long_short_stop`: entry at the close on or before t, daily closes in (t, nxt]."""
    p_l0, p_s0 = _last_at(daily[la], t), _last_at(daily[sa], t)
    window = daily.loc[(daily.index > t) & (daily.index <= nxt), [la, sa]]
    path = pd.concat([daily[[la, sa]].loc[:t].ffill().iloc[[-1]], window]).ffill().iloc[1:]
    if np.isnan(p_l0) or np.isnan(p_s0) or path.empty or path.isna().any().any():
        raise ValueError(f"long_short_stop: missing daily price in {nxt:%Y-%m} for {la}/{sa}")
    rl_path = path[la].to_numpy(dtype=float) / p_l0 - 1.0
    rs_path = path[sa].to_numpy(dtype=float) / p_s0 - 1.0
    eps = 1e-12  # a close exactly at the stop triggers it (80/100 − 1 is −0.19999999999999996)
    long_hit, short_hit = rl_path <= -thr + eps, rs_path >= thr - eps
    hit = np.flatnonzero(long_hit | short_hit)
    k = int(hit[0]) if len(hit) else len(path) - 1
    rl, rs = float(rl_path[k]), float(rs_path[k])
    f = (k + 1) / len(path)
    pnl = leverage * rl - leverage * rs
    c = fr.cost_bps / 1e4
    fin = fr.financing_spread / 12 * max(leverage - 1.0, 0.0) * f
    bor = fr.borrow.get(sa, 0.0) / 12 * leverage * f
    cost = c * 2 * leverage + c * (leverage * (1 + rl) + leverage * (1 + rs))
    leg = None
    if len(hit):
        leg = "both" if long_hit[k] and short_hit[k] else "long" if long_hit[k] else "short"
    return {
        "ret": pnl + rc * (f + (1 - f) * (1 + pnl)) - fin - bor - cost,
        "stopped": bool(len(hit)),
        "stop_leg": leg,
        "exit_day": path.index[k],
        "held": f,
        "cost": cost,
        "financing": fin,
        "borrow": bor,
        "r_long": rl,
        "r_short": rs,
    }


# ---------------------------------------------------------------------------
# ADR 067: fixed dollar legs, no fees, stop on the dollar loss of a leg
# ---------------------------------------------------------------------------
def run_dollar_long_short(
    choice: pd.DataFrame,
    daily: pd.DataFrame,
    notional: float = 1500.0,
    stop_loss: float | None = 200.0,
) -> pd.DataFrame:
    """ADR 067 (Nima, 2026-10-29 09:15): every month $1000 per leg at 1.5× – `notional` $1500 long rank 1 and
    $1500 short the last rank – opened at the decision close. If one leg's loss reaches `stop_loss` ($200, i.e. a
    13.3 % price move against it) at a daily close, both legs are closed at that close until the month-end. Next
    month again $1000 per leg: no compounding, no fees, no borrow, no financing, no interest – the dollar P&L of
    each month is simply added. A gap through the stop is filled at the close that shows it. `stop_loss=None` =
    the same rule without stop. A month without a complete ranking has no position (P&L 0)."""
    rows = []
    thr = stop_loss if stop_loss is not None else float("inf")
    eps = 1e-9  # a loss of exactly $200 triggers the stop
    for t0 in choice.index:
        t = pd.Timestamp(t0)
        nxt = t + pd.offsets.MonthEnd(1)
        la, sa = choice.at[t0, "long"], choice.at[t0, "short"]
        if not (isinstance(la, str) and isinstance(sa, str)):
            rows.append({"month": nxt, "pnl": 0.0, "pnl_long": 0.0, "pnl_short": 0.0, "stopped": False})
            continue
        window = daily.loc[(daily.index > t) & (daily.index <= nxt), [la, sa]]
        if window.empty:
            continue  # the month after the last decision is not in the data
        p_l0, p_s0 = _last_at(daily[la], t), _last_at(daily[sa], t)
        path = pd.concat([daily[[la, sa]].loc[:t].ffill().iloc[[-1]], window]).ffill().iloc[1:]
        if np.isnan(p_l0) or np.isnan(p_s0) or path.isna().any().any():
            raise ValueError(f"dollar_long_short: missing daily price in {nxt:%Y-%m} for {la}/{sa}")
        pl = notional * (path[la].to_numpy(dtype=float) / p_l0 - 1.0)
        ps = -notional * (path[sa].to_numpy(dtype=float) / p_s0 - 1.0)
        hit = np.flatnonzero((pl <= -thr + eps) | (ps <= -thr + eps))
        k = int(hit[0]) if len(hit) else len(path) - 1
        leg = None
        if len(hit):
            leg = (
                "both"
                if pl[k] <= -thr + eps and ps[k] <= -thr + eps
                else "long"
                if pl[k] <= -thr + eps
                else "short"
            )
        rows.append(
            {
                "month": nxt,
                "long": la,
                "short": sa,
                "pnl": float(pl[k] + ps[k]),
                "pnl_long": float(pl[k]),
                "pnl_short": float(ps[k]),
                "stopped": bool(len(hit)),
                "stop_leg": leg,
                "exit_day": path.index[k],
            }
        )
    return pd.DataFrame(rows).set_index("month")
