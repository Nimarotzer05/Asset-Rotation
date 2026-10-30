"""ADR 069: two robust rules on data this project has never used.

1. Trend filter, US equities 1886–1926 (41 years before every period studied so far – the first equity study began
   in 1927, all rounds in 1973 or later): equities in the month after a month-end close above the 10-month average
   of month-end total-return levels, otherwise cash. Baseline: buy and hold.
2. Turn of the month: equities from the close before the last trading day to the close of the third trading day of
   the next month, cash otherwise. A: 1885-04 … 1926-12 (before its discovery, untouched); B: 1988-01 … 2025-11
   (after its publication in 1987/88).

Data: `static:usmkt:TR` (daily US equity total return from 1885) and `static:usmkt:RF` (the daily cash index of the
same file – the only cash series before 1926; ADR 069). Rules: rotationlab/forecast/fresh_data.py.

Pre-registered (ADR 069), fixed before the first run:
  criterion 1  trend − buy and hold, paired Sharpe difference (excess over cash), 90 % block bootstrap, interval > 0
  criterion 2  turn-of-month Sharpe (excess over cash), 90 % block bootstrap, interval > 0 – in A and in B separately
  readings     1: confirmed / not confirmed. 2: A and B = exists and survived publication; A only = existed, gone
               after publication; B only = not established before, present after; neither = not confirmed
  costs        criteria before costs (Nima 2026-10-29: fees neglected); reported after 5 bp per switch
  reported     return, volatility, max drawdown, time invested, switches, net figures, mean daily excess return on
               turn-of-month days vs other days, share of the buy-and-hold excess earned on those days, MDE

Writes output/fresh_data/FRESH.md, monthly.csv.

Aufruf: python scripts/fresh_data_check.py
"""

from __future__ import annotations

import math
import os
import sys
import time
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, md_table, register, trials_variance  # noqa: E402
from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import research_factory  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    appraisal_residual,
    deflated_sharpe,
    paired_sharpe_diff,
    sharpe_ci,
)
from rotationlab.forecast.fresh_data import month_end_levels, monthly, trend_filter, turn_of_month  # noqa: E402
from rotationlab.forecast.model import BlockBootstrap  # noqa: E402

OUT_FILE = "output/fresh_data/monthly.csv"
TREND = "Trendfilter 1886–1926"
TOM_A = "Monatswechsel 1885–1926"
TOM_B = "Monatswechsel 1988–2025"
BH, CASH = "Buy & Hold", "cash"
TREND_SPAN = ("1886-01-31", "1926-12-31")
TOM_SPANS = {TOM_A: ("1885-04-30", "1926-12-31"), TOM_B: ("1988-01-31", "2025-11-30")}
COST = 0.0005  # 5 bp per switch, reported only


def perf(r: pd.Series, cash: pd.Series, boot: BlockBootstrap) -> dict[str, object]:
    r = r.dropna()
    c = cash.reindex(r.index)
    lvl = (1 + r).cumprod()
    s = sharpe_ci(r, c, boot, CONF)
    return {
        "Monate": len(r),
        "Rendite p.a.": f"{lvl.iloc[-1] ** (12 / len(r)) - 1:+.1%}",
        "Vol p.a.": f"{r.std(ddof=1) * math.sqrt(12):.1%}",
        "Sharpe ex Cash": f"{s.value:+.3f} [{s.low:+.3f}, {s.high:+.3f}]",
        "Max DD": f"{(lvl / lvl.cummax() - 1).min():.1%}",
    }


def main() -> None:
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    out = os.path.join(ROOT, "output", "fresh_data")
    os.makedirs(out, exist_ok=True)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].isin(["static:usmkt:TR", "static:usmkt:RF"])]
    v = research_factory(b, obs, make_calendar(b), date(1885, 1, 31)).at(date(2025, 12, 31))
    d = v.total_return(["US_EQ", "US_RF"], None).dropna()
    boot = BlockBootstrap(2000, 12, 20261025)

    # ---- 1. trend filter --------------------------------------------------------------------------------
    lv_eq, lv_rf = month_end_levels(d["US_EQ"]), month_end_levels(d["US_RF"])
    cash_m = lv_rf.pct_change(fill_method=None)
    bh_m = lv_eq.pct_change(fill_method=None)
    tr = trend_filter(lv_eq, cash_m, 10)
    span = slice(pd.Timestamp(TREND_SPAN[0]), pd.Timestamp(TREND_SPAN[1]))
    trend = tr["ret"].loc[span]
    trend_net = (tr["ret"] - COST * tr["switch"]).loc[span]
    bh = bh_m.loc[span]
    pair = paired_sharpe_diff(trend, bh, cash_m.loc[span], boot, CONF)
    se = (pair.high - pair.low) / (2 * 1.645)
    c1 = pair.low > 0
    t_rows = [
        pd.Series(
            {
                **perf(trend, cash_m, boot),
                "investiert": f"{tr['invested'].loc[span].mean():.0%}",
                "Wechsel p.a.": f"{tr['switch'].loc[span].sum() / len(trend) * 12:.2f}",
            },
            name="Trendfilter 10 M",
        ),
        pd.Series(
            {**perf(trend_net, cash_m, boot), "investiert": "", "Wechsel p.a.": ""},
            name="Trendfilter, nach 5 bp je Wechsel",
        ),
        pd.Series({**perf(bh, cash_m, boot), "investiert": "100%", "Wechsel p.a.": "0"}, name=BH),
    ]
    t_tab = pd.DataFrame(t_rows)
    t_tab.index.name = "1886–1926"

    # ---- 2. turn of the month ---------------------------------------------------------------------------
    tom = turn_of_month(d["US_EQ"], d["US_RF"])
    tom_m = monthly(tom["ret"])
    tom_net_m = monthly(tom["ret"] - COST * tom["switch"])
    eq_m, rf_m = monthly(tom["eq"]), monthly(tom["rf"])
    tom_rows, crit2, extra = [], {}, []
    for name, (a, z) in TOM_SPANS.items():
        sl = slice(pd.Timestamp(a), pd.Timestamp(z))
        dsl = tom.loc[pd.Timestamp(a).replace(day=1) : pd.Timestamp(z)]
        crit2[name] = sharpe_ci(tom_m.loc[sl], rf_m.loc[sl], boot, CONF)
        tom_rows += [
            pd.Series(
                {**perf(tom_m.loc[sl], rf_m, boot), "im Markt": f"{dsl['in_market'].mean():.0%}"}, name=name
            ),
            pd.Series(
                {**perf(tom_net_m.loc[sl], rf_m, boot), "im Markt": ""}, name=f"{name}, nach 5 bp je Wechsel"
            ),
            pd.Series({**perf(eq_m.loc[sl], rf_m, boot), "im Markt": "100%"}, name=f"{BH} {a[:4]}–{z[:4]}"),
        ]
        ex = dsl["eq"] - dsl["rf"]
        on, off = ex[dsl["in_market"] == 1], ex[dsl["in_market"] == 0]
        t_stat = (on.mean() - off.mean()) / math.sqrt(on.var(ddof=1) / len(on) + off.var(ddof=1) / len(off))
        extra.append(
            pd.Series(
                {
                    "Tage am Monatswechsel": len(on),
                    "Ø Überrendite je Tag am Monatswechsel": f"{on.mean():+.3%}",
                    "Ø Überrendite je übriger Tag": f"{off.mean():+.3%}",
                    "t (Welch)": f"{t_stat:+.2f}",
                    "Anteil an der Aktien-Überrendite": f"{on.sum() / ex.sum():.0%}"
                    if ex.sum() > 0
                    else "Gesamt ≤ 0",
                },
                name=name,
            )
        )
    tom_tab = pd.DataFrame(tom_rows)
    tom_tab.index.name = "Monatswechsel"
    ex_tab = pd.DataFrame(extra)
    ex_tab.index.name = "Tage"
    a_ok, b_ok = crit2[TOM_A].low > 0, crit2[TOM_B].low > 0
    reading2 = {
        (True, True): "existiert und hat die Veröffentlichung überlebt",
        (True, False): "existierte vor der Entdeckung, nach der Veröffentlichung nicht mehr belegt",
        (False, True): "vor der Entdeckung nicht belegt, nach der Veröffentlichung vorhanden",
        (False, False): "nicht bestätigt",
    }[(a_ok, b_ok)]

    # ---- files, register ---------------------------------------------------------------------------------
    monthly_df = pd.DataFrame({TREND: trend, BH: bh_m, CASH: cash_m})
    for name, (a, z) in TOM_SPANS.items():
        sl = slice(pd.Timestamp(a), pd.Timestamp(z))
        monthly_df[name] = tom_m.loc[sl]
        monthly_df.loc[sl, BH] = eq_m.loc[sl]
        monthly_df.loc[sl, CASH] = rf_m.loc[sl]
    monthly_df = monthly_df.dropna(subset=[TREND, TOM_A, TOM_B], how="all")
    monthly_df.index.name = "month"
    monthly_df.to_csv(os.path.join(ROOT, OUT_FILE), float_format="%.8f")
    n_trials, _ = register(include_planned=True, own_file=OUT_FILE)
    own = {}
    for col in (TREND, TOM_A, TOM_B):
        sub = monthly_df[[col, BH, CASH]].dropna()
        a_ = appraisal_residual(sub[col], sub[BH], sub[CASH])
        own[col] = float(a_.mean() / a_.std(ddof=1) * math.sqrt(12))
    var = trials_variance(pd.Series(own), own_file=OUT_FILE)
    sub = monthly_df[[TREND, BH, CASH]].dropna()
    _, _, dsr_trend = deflated_sharpe(appraisal_residual(sub[TREND], sub[BH], sub[CASH]), n_trials, var)

    lines = [
        "# Frische Daten: Trendfilter 1886–1926 und Monatswechsel-Effekt (ADR 069)",
        "",
        f"Stand {date.today().isoformat()}. Skript `scripts/fresh_data_check.py`, Regeln `rotationlab/forecast/fresh_data.py`. "
        "Daten: US-Aktien Total Return täglich ab 1885 (`static:usmkt:TR`) und der tägliche Cash-Index derselben Datei "
        "(`static:usmkt:RF`). Kein Zeitraum vor 1927 wurde im Projekt je ausgewertet; 1988–2025 ist für den "
        "Monatswechsel-Effekt neu (nie berechnet), die Aktienreihe selbst aber bekannt. "
        f"90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Kriterien vor Kosten; Kosten 5 bp je "
        f"Wechsel berichtet. Laufzeit {time.perf_counter() - t0:.0f} s.",
        "",
        "## 1. Trendfilter auf 41 unberührten Jahren (1886–1926)",
        "",
        md_table(t_tab),
        "",
        f"Vorab-Kriterium: Trend − Buy & Hold, gepaarte Sharpe-Differenz **{pair.value:+.3f} [{pair.low:+.3f}, {pair.high:+.3f}]** "
        f"→ **{'bestätigt' if c1 else 'nicht bestätigt'}** (Standardfehler ≈ {se:.3f}, kleinste nachweisbare Differenz "
        f"≈ {2.487 * se:.2f}). Deflated Sharpe (Appraisal-Residuum gegen Buy & Hold, N = {n_trials}): {dsr_trend:.3f}.",
        "",
        "## 2. Monatswechsel-Effekt: vor der Entdeckung und nach der Veröffentlichung",
        "",
        md_table(tom_tab),
        "",
        md_table(ex_tab),
        "",
        f"Vorab-Kriterium (Sharpe des Monatswechsels, Intervall > 0): 1885–1926 {crit2[TOM_A].value:+.3f} "
        f"[{crit2[TOM_A].low:+.3f}, {crit2[TOM_A].high:+.3f}] → **{'ja' if a_ok else 'nein'}**; 1988–2025 "
        f"{crit2[TOM_B].value:+.3f} [{crit2[TOM_B].low:+.3f}, {crit2[TOM_B].high:+.3f}] → **{'ja' if b_ok else 'nein'}**. "
        f"Lesart: **{reading2}**.",
        "",
    ]
    with open(os.path.join(out, "FRESH.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
