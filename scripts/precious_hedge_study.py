"""Precious metals satellite: what does the crash-hedge component add to the gold/silver mean reversion?

Runs the module through the engine (research panel, 1975-12 – 2026-02, 10 bp per leg, research timing) in
six variants and writes output/precious/HEDGE_VARIANTS.md + .csv. Context: ADR 018 combined the MR with an
always-on hedge share; the combination had never been backtested before Phase 2 (ADR 040).

Aufruf: python scripts/precious_hedge_study.py
"""

from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.config.models import CostSpec, load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import backtest, research_factory  # noqa: E402
from rotationlab.stats import drawdown_episodes  # noqa: E402

OUT = os.path.join(ROOT, "output", "precious")
START, END, SAMPLE = date(1970, 12, 31), date(2026, 2, 28), (date(1975, 12, 31), date(2026, 2, 28))
VARIANTS = {
    "MR allein (Golden)": {"hedge": {"enabled": False}},
    "MR + Basis 0.25 + bedingt (Konfiguration v1)": {},
    "MR + Basis 0.10 + bedingt": {"hedge": {"base": 0.10}},
    "MR + nur bedingt (Basis 0)": {"hedge": {"base": 0.0}},
    "Nur Hedge: Basis 0.25 + bedingt": {"mean_reversion": {"position_scale": 1e12}},
    "Nur Hedge bedingt (Basis 0)": {"mean_reversion": {"position_scale": 1e12}, "hedge": {"base": 0.0}},
}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    b = load_bundle(os.path.join(ROOT, "configs"))
    store = open_store(b, ROOT)
    obs = store.observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, make_calendar(b), START)
    eq = f.at(END).total_return(["US_EQ"], "ME")["US_EQ"]
    eqr = eq.pct_change()
    eps = [e for e in drawdown_episodes(eq.loc["1970-12-31":]) if e.peak >= pd.Timestamp(SAMPLE[0])]
    rows = {}
    for name, ov in VARIANTS.items():
        res = backtest(b, f, "precious_metals", "long_history", START, END, "same_close", CostSpec(default_bps=10), ov)
        r, c = res.sample(*SAMPLE)
        ex = r - c
        crash = [float((1 + ex.loc[e.peak + pd.Timedelta(days=1) : e.trough]).prod() - 1) for e in eps]
        bad = eqr.reindex(ex.index) < -0.05
        cum = (1 + ex).cumprod()
        rows[name] = {
            "Sharpe": ex.mean() / ex.std() * np.sqrt(12),
            "Rendite p.a. (arithm.)": ex.mean() * 12,
            "Vol p.a.": ex.std() * np.sqrt(12),
            "Max DD": float((cum / cum.cummax() - 1).min()),
            "Crashs positiv": f"{sum(x > 0 for x in crash)}/{len(crash)}",
            "Ø Crash": float(np.mean(crash)),
            "Aktienmonate < −5 % p.a.": float(ex[bad].mean() * 12),
            "Korrelation Aktien": float(ex.corr(eqr.reindex(ex.index))),
        }
    t = pd.DataFrame(rows).T
    t.index.name = "Variante"
    t.to_csv(os.path.join(OUT, "hedge_variants.csv"))
    lines = ["| " + " | ".join([t.index.name, *t.columns]) + " |", "|" + "---|" * (len(t.columns) + 1)]
    for i, row in t.iterrows():
        cells = [f"{v:.3f}" if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join([str(i), *cells]) + " |")
    text = "\n".join([
        "# Edelmetall-Satellit: Was bringt der Crash-Hedge?",
        "",
        f"Engine-Läufe auf dem Forschungspanel (LBMA-Fix, ab 1970-12), Stichprobe {SAMPLE[0]:%Y-%m} – {SAMPLE[1]:%Y-%m}, "
        "10 bp je Bein, Umsetzung zum Entscheidungsschluss. Überschussrendite = Spread (selbstfinanzierend). "
        f"Crashs = Aktien-Drawdowns > 15 % mit Hoch ab {SAMPLE[0]:%Y} ({len(eps)} Episoden).",
        "",
        *lines,
        "",
        "Lesart: Der Hedge-Anteil (immer long Gold / short Silber) hat seit 1976 im Mittel Geld gekostet; als Zusatz zur "
        "Mean Reversion halbiert er deren Sharpe und vertieft den Drawdown. Dafür dreht er die Korrelation zu Aktien leicht "
        "ins Negative und bringt mehr in schlechten Aktienmonaten. Ob sich das im Portfolio lohnt, entscheidet der "
        "Risikobudget-Combiner (Phase 3); bis dahin bleibt Konfiguration v1 (ADR 040).",
    ])
    with open(os.path.join(OUT, "HEDGE_VARIANTS.md"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(t.to_string(float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
