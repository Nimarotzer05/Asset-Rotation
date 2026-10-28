"""Round 4's headline rule, rebuilt from scratch in plain pandas – no engine, no strategy module.

Why this file exists: the result of research round 4 (ADR 060) is "risk parity across four sleeves plus a 12-month
trend filter beats passive risk parity". If that result were an artefact of the framework (a timing bug, a cost
quirk), an independent, much simpler implementation would not reproduce it. This one uses only monthly total-return
levels from the store (the data layer: how those levels are built from raw files is the package's, and is checked
separately by the data gates) and implements every portfolio rule itself in a few dozen readable lines:

  1. sleeves and budgets (ADR 057 b): US industries 1/8, countries 1/8, Treasuries 2/5/10y 1/4, gold+silver 1/4
  2. inside a sleeve: inverse-volatility weights over the instruments with ≥ 24 months of history
  3. across sleeves: risk parity  a_s = budget_s / vol_s
  4. volatility target 10 %: scale k = 0.10 / sqrt(a' C a) with the EWMA covariance of the sleeve returns
  5. caps: equities + metals ≤ 1.0 gross, everything ≤ 1.5 gross (leverage only through the bonds)
  6. trend filter: an instrument whose 12-month return is below cash over the same 12 months is held as cash
  7. trade at month-end, earn the next month; 10 bp per unit traded; negative cash costs T-bill + 30 bp

Deliberate simplifications versus the engine (so exact equality is not expected): monthly instead of daily vols,
basket volatility from realised basket returns, execution at the decision close instead of the next session, one
cost rate for all instruments. Like the engine, the caps act on the unfiltered book and the filter only removes. The comparison at the end reports how close the two get.

Result (2026-10-28, 563 months 1979–2025): Sharpe 0.789 from scratch vs 0.802 in the engine, correlation of monthly
excess returns 0.98; with the filter switched off the same code gives ≈ the passive risk parity of the engine.
Lesson recorded on the way: the first version subtracted a cash *Series* from a *DataFrame* with `-`, which pandas
aligns on columns, not dates – every trend value became NaN, the filter never fired, and the "rebuild" looked like
passive risk parity (Sharpe 0.535). An independent rebuild is only a check if its own bugs are found.

Run: python examples/trend_filter_from_scratch.py   (needs the static store: `rotationlab ingest --full --provider static`)
"""

from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SLEEVES = {  # name: (budget, group, instruments)
    "EQ_US": (0.125, "physical", [f"IND_{i}" for i in "NODUR DURBL MANUF ENRGY HITEC TELCM SHOPS HLTH UTILS OTHER".split()]),
    "EQ_INTL": (0.125, "physical", None),  # the 21 country indices, filled from the configuration below
    "FI": (0.25, "rates", ["UST2_D", "UST5_D", "UST10_D"]),
    "PM": (0.25, "physical", ["GOLD_D", "SILVER"]),
}
CASH, TARGET, COST, BORROW = "TBILL_IY", 0.10, 0.0010, 0.0030


def ewma_vol(r: pd.DataFrame, half_life: int = 12, min_obs: int = 24) -> pd.DataFrame:
    """Annualised exponentially weighted volatility of monthly returns, known at each month-end."""
    v = r.ewm(halflife=half_life, min_periods=min_obs).std() * np.sqrt(12)
    return v.clip(lower=0.02)


def load_levels() -> pd.DataFrame:
    """Monthly total-return levels of every instrument – the only thing taken from the package."""
    from rotationlab.config.models import load_bundle
    from rotationlab.data import make_calendar, open_store
    from rotationlab.engine.modes import research_factory

    b = load_bundle(os.path.join(ROOT, "configs"))
    SLEEVES["EQ_INTL"] = (0.125, "physical", [a for a in b.strategies["sleeve_allocator_v2"].universe if a.startswith("CTRY_")])
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    view = research_factory(b, obs, make_calendar(b), date(1971, 1, 31)).at(date(2025, 12, 31))
    names = [a for _, _, inst in SLEEVES.values() for a in inst] + [CASH]
    return view.total_return(names, "ME")


def run(levels: pd.DataFrame, trend_filter: bool = True) -> pd.Series:
    r = levels.pct_change(fill_method=None)
    cash = r[CASH]
    inst_vol = ewma_vol(r.drop(columns=CASH))
    growth_12m = (1 + r.drop(columns=CASH)).rolling(12).apply(np.prod, raw=True)
    cash_12m = (1 + cash).rolling(12).apply(np.prod, raw=True)
    excess_12m = growth_12m.sub(cash_12m, axis=0)  # axis=0: align on dates (a plain '-' aligns on columns)

    # sleeve baskets: inverse-vol weights inside each sleeve (unfiltered – the filter decides what is held)
    baskets, basket_ret = {}, {}
    for s, (_, _, inst) in SLEEVES.items():
        iv = 1 / inst_vol[inst]
        w = iv.div(iv.sum(axis=1), axis=0)  # NaN where an instrument has < 24 months: it is not available
        baskets[s] = w
        basket_ret[s] = (w.shift(1) * r[inst]).sum(axis=1, min_count=1)  # basket held over the next month
    br = pd.DataFrame(basket_ret)
    sleeve_vol = ewma_vol(br)
    cov = br.ewm(halflife=24, min_periods=24).cov()

    rows = {}
    for d in r.index:
        if d not in cov.index.get_level_values(0) or sleeve_vol.loc[d].isna().any():
            continue
        a = pd.Series({s: SLEEVES[s][0] for s in SLEEVES}) / sleeve_vol.loc[d]  # risk parity across sleeves
        c = cov.loc[d].loc[list(SLEEVES), list(SLEEVES)] * 12
        if c.isna().any().any():
            continue
        k = TARGET / np.sqrt(float(a @ c @ a))  # one scale for the whole book: the vol target
        w = pd.concat([baskets[s].loc[d] * a[s] * k for s in SLEEVES])
        phys = w[[x for s, (_, g, inst) in SLEEVES.items() if g == "physical" for x in inst]].sum()
        if phys > 1.0:  # caps: physical ≤ 1.0, then everything ≤ 1.5
            w[[x for s, (_, g, inst) in SLEEVES.items() if g == "physical" for x in inst]] *= 1.0 / phys
        if w.sum() > 1.5:
            fi = SLEEVES["FI"][2]
            w[fi] *= max(0.0, (1.5 - w.drop(fi).sum()) / w[fi].sum())
        if trend_filter:
            w[excess_12m.loc[d].reindex(w.index) <= 0] = 0.0  # trend filter: those shares stay in cash
        rows[d] = w.fillna(0.0)
    W = pd.DataFrame(rows).T.sort_index()

    nxt = r.shift(-1).reindex(W.index)
    held_cash = 1 - W.sum(axis=1)
    gross = (W * nxt[W.columns].fillna(0.0)).sum(axis=1) + held_cash * nxt[CASH]
    gross -= np.minimum(held_cash, 0).abs() * BORROW / 12  # financing of leverage
    turnover = W.diff().abs().sum(axis=1).fillna(W.abs().sum(axis=1))
    net = gross - turnover * COST
    return net.shift(1).dropna()  # label each return with the month it was earned


def sharpe(x: pd.Series, cash: pd.Series) -> float:
    e = (x - cash.reindex(x.index)).dropna()
    return float(e.mean() / e.std(ddof=1) * np.sqrt(12))


def main() -> None:
    levels = load_levels()
    mine, unfiltered = run(levels), run(levels, trend_filter=False)
    ref = pd.read_csv(os.path.join(ROOT, "output", "allocator_v2", "walkforward_monthly.csv"), index_col=0, parse_dates=True)
    months = ref.index.intersection(mine.index)
    cash = ref["cash"].loc[months]
    engine = ref["ohne Querschnitt"].loc[months]
    b1 = ref["B1 passive Risikoparität"].loc[months]
    m = mine.loc[months]
    print(f"months compared: {len(months)} ({months[0].date()} … {months[-1].date()})")
    print(f"Sharpe ex cash  from scratch {sharpe(m, cash):.3f} | engine (same rule) {sharpe(engine, cash):.3f} | passive risk parity {sharpe(b1, cash):.3f}")
    print(f"correlation of monthly excess returns, from scratch vs engine: {(m - cash).corr(engine - cash):.3f}")
    print(f"annual return / vol from scratch: {m.mean() * 12:.1%} / {m.std() * np.sqrt(12):.1%}")
    u = unfiltered.loc[months]
    print(f"same code with the trend filter switched off: Sharpe {sharpe(u, cash):.3f} (engine's passive risk parity {sharpe(b1, cash):.3f})")


if __name__ == "__main__":
    main()
