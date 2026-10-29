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
