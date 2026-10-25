"""Feste Ratio-Regel: Gold/Silber-Ratio ≤ ENTRY → long Gold / short Silber (dollar-neutral), halten bis Ratio ≥ EXIT.

Tägliche LBMA-Fixings 1968–2026. Jeder Trade einzeln: Dauer, Ertrag, grösster Zwischenverlust.
Ertrag dollar-neutral = log(Ratio_exit / Ratio_entry) ≈ Gold-Rendite minus Silber-Rendite.

Aufruf: python scripts/run_ratio_rule.py → output/gold_silver/RATIO_RULE.md
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "output", "gold_silver")
os.makedirs(OUT, exist_ok=True)


def load_daily() -> pd.Series:
    out = {}
    for n in ("gold", "silver"):
        df = pd.read_csv(os.path.join(RAW, f"lbma_{n}_daily.csv"), parse_dates=["date"]).set_index("date")
        col = [c for c in df.columns if c.endswith("_usd")][0]
        out[n] = pd.to_numeric(df[col], errors="coerce").replace(0, np.nan)
    df = pd.DataFrame(out).dropna()
    return df["gold"] / df["silver"]


def trades(ratio: pd.Series, entry: float, exit_: float) -> pd.DataFrame:
    rows, pos, e_date, e_val = [], False, None, None
    for d, v in ratio.items():
        if not pos and v <= entry:
            pos, e_date, e_val = True, d, v
        elif pos and v >= exit_:
            seg = ratio.loc[e_date:d]
            rows.append({"Einstieg": e_date.date(), "Ratio Einstieg": e_val, "Ausstieg": d.date(), "Ratio Ausstieg": v,
                         "Dauer (Monate)": (d - e_date).days / 30.44, "Ertrag (log)": np.log(v / e_val),
                         "Tiefste Ratio": seg.min(), "Max. Zwischenverlust": np.log(seg.min() / e_val), "offen": False})
            pos = False
    if pos:
        seg = ratio.loc[e_date:]
        v = ratio.iloc[-1]
        rows.append({"Einstieg": e_date.date(), "Ratio Einstieg": e_val, "Ausstieg": ratio.index[-1].date(), "Ratio Ausstieg": v,
                     "Dauer (Monate)": (ratio.index[-1] - e_date).days / 30.44, "Ertrag (log)": np.log(v / e_val),
                     "Tiefste Ratio": seg.min(), "Max. Zwischenverlust": np.log(seg.min() / e_val), "offen": True})
    return pd.DataFrame(rows)


def md(df: pd.DataFrame, fmt: str = "{:.2f}") -> str:
    head = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt.format(v) if isinstance(v, (float, np.floating)) else str(v) for v in row) + " |")
    return "\n".join(lines)


def main() -> None:
    ratio = load_daily()
    rep = [f"# Feste Ratio-Regel: Gold/Silber-Ratio ≤ Einstieg → long Gold / short Silber bis Ausstieg",
           f"Tägliche LBMA-Fixings {ratio.index[0]:%Y-%m-%d} bis {ratio.index[-1]:%Y-%m-%d}. Ertrag dollar-neutral (gleicher Betrag long Gold und short Silber), "
           "vor Kosten, Leihgebühr und Finanzierung. Max. Zwischenverlust = wie weit die Ratio nach dem Einstieg noch fiel (log)."]

    t = trades(ratio, 50, 75)
    t.to_csv(os.path.join(OUT, "ratio_rule_50_75.csv"), index=False)
    rep += ["", "## Regel 50 → 75, alle Trades", md(t)]

    grid = []
    for entry in (40, 45, 50, 55):
        for exit_ in (65, 70, 75, 80):
            if exit_ <= entry:
                continue
            tt = trades(ratio, entry, exit_)
            closed = tt[~tt["offen"]]
            grid.append({"Einstieg ≤": entry, "Ausstieg ≥": exit_, "Trades": len(tt), "davon offen": int(tt["offen"].sum()),
                         "Gewinner (geschlossen)": f"{(closed['Ertrag (log)'] > 0).sum()}/{len(closed)}",
                         "Ø Dauer (Monate)": closed["Dauer (Monate)"].mean(), "längste Dauer": tt["Dauer (Monate)"].max(),
                         "Ø Ertrag geschl.": closed["Ertrag (log)"].mean(),
                         "Ertrag p.a. investiert": closed["Ertrag (log)"].sum() / max(closed["Dauer (Monate)"].sum() / 12, 1e-9),
                         "schlimmster Zwischenverlust": tt["Max. Zwischenverlust"].min(),
                         "Jahre investiert / gesamt": f"{tt['Dauer (Monate)'].sum() / 12:.0f} / {(ratio.index[-1] - ratio.index[0]).days / 365.25:.0f}"})
    g = pd.DataFrame(grid)
    g.to_csv(os.path.join(OUT, "ratio_rule_grid.csv"), index=False)
    rep += ["", "## Sensitivität Einstieg × Ausstieg", md(g)]

    # Wie oft lag die Ratio je Jahrzehnt unter 50?
    dec = ratio.groupby((ratio.index.year // 10) * 10).agg(["min", "median", "max", lambda s: (s <= 50).mean()])
    dec.columns = ["Min", "Median", "Max", "Anteil Tage ≤ 50"]
    dec.insert(0, "Jahrzehnt", [f"{d}er" for d in dec.index])
    rep += ["", "## Ratio je Jahrzehnt (das Niveau wandert)", md(dec)]

    with open(os.path.join(OUT, "RATIO_RULE.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))


if __name__ == "__main__":
    main()
