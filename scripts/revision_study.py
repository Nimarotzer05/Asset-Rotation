"""Wie stark verändern Datenrevisionen die Makrosignale der Studien? (echte FRED-MD-Vintages)

Vergleicht jede archivierte FRED-MD-Vintage in data/raw/fredmd_vintages mit der neuesten:
  1. welcher Anteil der Werte revidiert wurde und um wie viel (Niveau und Jahresrate);
  2. ob die Regime der Studien (Wachstum × Inflation, Trendrichtung) mit damaligen Daten anders
     ausgefallen wären – über die ganze Historie und am Rand der Vintage, wo Entscheidungen fallen;
  3. das Arbeitsmarktsignal (Sahm) damals vs. heute.

Mit dem vollständigen Archiv (scripts/fetch_fredmd_vintages.py, monatlich seit 1999) wird daraus eine
echte Echtzeit-Auswertung; mit den drei Vintages im Repo ist es eine Stichprobe.

Aufruf: python scripts/revision_study.py   →   output/revisions/REPORT.md
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.data.providers.static import StaticProvider  # noqa: E402

OUT = os.path.join(ROOT, "output", "revisions")
SERIES = {"INDPRO": "Industrieproduktion", "PAYEMS": "Beschäftigung (NFP)", "CPIAUCSL": "CPI",
          "CPIULFSL": "Kern-CPI", "PCEPI": "PCE-Deflator", "RPI": "Realeinkommen", "RETAILx": "Einzelhandel",
          "HOUST": "Baubeginne", "UNRATE": "Arbeitslosenquote"}
EDGE = 24  # Monate am Rand einer Vintage


def regime(ip: pd.Series, cpi: pd.Series, smooth: int = 3) -> pd.DataFrame:
    """Studien-Regime (src/features.py::macro_regime, ohne Lag): Richtung der geglätteten Jahresraten."""
    g = (ip.pct_change(12) * 100).rolling(smooth).mean()
    i = (cpi.pct_change(12) * 100).rolling(smooth).mean()
    out = pd.DataFrame({"growth": np.where(g > g.shift(smooth), "steigend", "fallend"),
                        "inflation": np.where(i > i.shift(smooth), "steigend", "fallend")}, index=ip.index)
    valid = g.shift(smooth).notna() & i.shift(smooth).notna()
    return out[valid]


def sahm(un: pd.Series) -> pd.Series:
    m3 = un.rolling(3).mean()
    return m3 - m3.rolling(12).min()


def table(df: pd.DataFrame, fmt: dict[str, str] | None = None) -> str:
    fmt = fmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join([df.index.name or "", *cols]) + " |", "|" + "---|" * (len(cols) + 1)]
    for idx, row in df.iterrows():
        cells = [fmt.get(c, "{}").format(row[c]) if pd.notna(row[c]) else "–" for c in cols]
        lines.append("| " + " | ".join([str(idx), *cells]) + " |")
    return "\n".join(lines)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    p = StaticProvider(os.path.join(ROOT, "data", "raw"))
    entries = p.vintages()
    panels = dict(p._vintage_panels)
    labels = {pd.Timestamp(e["vintage_date"]): str(e["label"]) for e in entries}
    dates = sorted(panels)
    latest_d = dates[-1]
    latest = panels[latest_d]
    old = dates[:-1]

    # 1. Revisionen je Reihe -------------------------------------------------------------------
    rows = []
    for v in old:
        pv = panels[v]
        last_obs = pv["INDPRO"].dropna().index.max()
        for code, name in SERIES.items():
            a, b = pv[code].dropna(), latest[code].dropna()
            common = a.index.intersection(b.index)
            changed = ((b[common] - a[common]).abs() > 1e-9 * a[common].abs()).mean()
            if code == "UNRATE":
                ga, gb = a, b
                unit = "Pkt"
            else:
                ga, gb = a.pct_change(12) * 100, b.pct_change(12) * 100
                unit = "Pkt Jahresrate"
            d = (gb - ga).reindex(common).dropna()
            edge = d[d.index > last_obs - pd.offsets.MonthEnd(EDGE)]
            rows.append({"Vintage": labels[v], "Reihe": name, "revidiert": changed, "Ø |Δ| gesamt": d.abs().mean(),
                         f"Ø |Δ| letzte {EDGE} M": edge.abs().mean(), "max |Δ| Rand": edge.abs().max(), "Einheit": unit})
    rev = pd.DataFrame(rows).set_index(["Vintage", "Reihe"])

    # 2. Regime damals vs. heute -------------------------------------------------------------
    reg_rows, calls = [], []
    r_now = regime(latest["INDPRO"], latest["CPIAUCSL"])
    for v in old:
        pv = panels[v]
        r_then = regime(pv["INDPRO"], pv["CPIAUCSL"])
        common = r_then.index.intersection(r_now.index)
        last = r_then.index.max()
        edge = common[common > last - pd.offsets.MonthEnd(EDGE)]
        for scope, idx in (("gesamt", common), (f"letzte {EDGE} M", edge)):
            a, b = r_then.loc[idx], r_now.loc[idx]
            reg_rows.append({"Vintage": labels[v], "Zeitraum": scope, "Monate": len(idx),
                             "Wachstum gleich": (a["growth"] == b["growth"]).mean(),
                             "Inflation gleich": (a["inflation"] == b["inflation"]).mean(),
                             "Quadrant gleich": ((a["growth"] == b["growth"]) & (a["inflation"] == b["inflation"])).mean()})
        s_then, s_now = sahm(pv["UNRATE"]), sahm(latest["UNRATE"])
        calls.append({"Vintage": labels[v], "letzter Monat": last.strftime("%Y-%m"),
                      "Regime damals": f"Wachstum {r_then.loc[last, 'growth']}, Inflation {r_then.loc[last, 'inflation']}",
                      "Regime heute": f"Wachstum {r_now.loc[last, 'growth']}, Inflation {r_now.loc[last, 'inflation']}",
                      "Sahm damals": s_then.loc[last], "Sahm heute": s_now.loc[last]})
    regs = pd.DataFrame(reg_rows).set_index(["Vintage", "Zeitraum"])
    call = pd.DataFrame(calls).set_index("Vintage")

    # Rebasierung erkennen (Niveau springt, Raten nicht)
    ip_ratio = (latest["INDPRO"] / panels[old[0]]["INDPRO"]).dropna()
    rebase = ip_ratio.loc[:"2015"].median()

    pct = {c: "{:.0%}" for c in ["revidiert", "Wachstum gleich", "Inflation gleich", "Quadrant gleich"]}
    num = {c: "{:.2f}" for c in ["Ø |Δ| gesamt", f"Ø |Δ| letzte {EDGE} M", "max |Δ| Rand", "Sahm damals", "Sahm heute"]}
    rev_t = rev.reset_index().set_index("Reihe")
    md = [
        "# Revisionen: Was Echtzeitdaten an den Makrosignalen ändern",
        "",
        f"Stichprobe aus {len(dates)} echten FRED-MD-Vintages ({', '.join(labels[d] for d in dates)}), jede mit der "
        f"neuesten ({labels[latest_d]}) verglichen. Quelle und Datierung: `data/raw/fredmd_vintages/vintages.yaml`. "
        "Erzeugt mit `scripts/revision_study.py`.",
        "",
        "## 1. Wie viel wird revidiert?",
        "",
        "Anteil der Monatswerte, die sich bis heute geändert haben, und mittlere Änderung der Jahresrate (bei der "
        f"Arbeitslosenquote: des Niveaus). „Rand“ = die letzten {EDGE} Monate der alten Vintage – die Werte, auf denen "
        "eine Entscheidung damals beruhte.",
        "",
    ]
    for v in old:
        md += [f"**Vintage {labels[v]}**", "", table(rev_t[rev_t["Vintage"] == labels[v]].drop(columns="Vintage"), {**pct, **num}), ""]
    md += [
        f"Die Industrieproduktion wurde zwischendurch umbasiert (Niveau heute im Median {rebase:.3f}× des Werts von "
        f"{labels[old[0]]}): Niveaus über Vintages hinweg sind nicht vergleichbar, Jahresraten schon. Features rechnen "
        "deshalb immer innerhalb eines Datenstands (MarketView), nie über Vintages gemischt.",
        "",
        "## 2. Hätten die Studien-Regime damals anders ausgesehen?",
        "",
        "Regime wie in `src/features.py::macro_regime` (Richtung der 3M-geglätteten Jahresraten von Industrieproduktion "
        "und CPI), einmal mit den damaligen, einmal mit den heutigen Daten.",
        "",
        table(regs.reset_index().set_index("Vintage"), {**pct, "Monate": "{:.0f}"}),
        "",
        "Was ein Live-System am Rand der Vintage gesehen hätte:",
        "",
        table(call, num),
        "",
        "## 3. Folgerung",
        "",
        "Die Studien rechnen mit heutigen, revidierten Daten und einem Monat Verzögerung (Lag-Modell). Über die ganze "
        "Historie stimmen die Regime meist überein; am Rand – dort, wo eine Live-Entscheidung fällt – weichen sie häufiger "
        "ab. Deshalb trennt der Store `static:fredmd:*` (Forschungsparität) und `static:fredmd_rt:*` (Echtzeit) und holt "
        "live echte ALFRED-Vintages. Mit dem vollständigen Archiv (monatlich seit 1999) lässt sich jede Studie einmal mit "
        "Echtzeitdaten wiederholen; die Differenz der Kennzahlen ist der Preis der Revisionen.",
        "",
    ]
    with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    rev.to_csv(os.path.join(OUT, "revisions_by_series.csv"))
    regs.to_csv(os.path.join(OUT, "regime_agreement.csv"))
    print("\n".join(md))


if __name__ == "__main__":
    main()
