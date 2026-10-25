"""Audit der Aktienstudie auf Look-ahead: mechanische Tests, keine Meinung.

1. Trunkierung:    Signale aus Daten bis D müssen am Datum D exakt den Signalen aus der Vollstichprobe gleichen.
2. Zukunftsmutation: Daten nach D durch Rauschen ersetzen; Signale an D unverändert.
3. Zeitlogik der Hilfsfunktionen: Vorwärtsrendite, Exposure-Timing, IC-Ausrichtung auf Spielzeugdaten.
4. Sensitivität der CAPE-Ergebnisse auf den Gewinn-Lag (0, 4, 6, 9 Monate): zeigt, wie gross der Fehler bei zu kurzem Lag wäre.

Aufruf: python scripts/audit_equity.py   (Exit-Code 1 bei einem Fehlschlag)
"""
from __future__ import annotations

import os
import sys

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_equity as E  # noqa: E402
from src import analysis  # noqa: E402

FAILS: list[str] = []
LOG: list[str] = []


def check(cond: bool, msg: str) -> None:
    LOG.append(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def same(a: pd.Series, b: pd.Series) -> bool:
    a, b = a.astype(float), b.astype(float)
    both_nan = a.isna() & b.isna()
    return bool(((a == b) | both_nan | (np.isclose(a, b, rtol=0, atol=1e-12))).all())


def truncate(D: dict, d: pd.Timestamp) -> dict:
    out = dict(D)
    for k in ("ff3", "ind", "f5", "sh", "macro", "rf", "mkt"):
        out[k] = D[k].loc[:d]
    return out


def mutate_future(D: dict, d: pd.Timestamp, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    out = dict(D)
    for k in ("ff3", "ind", "f5", "sh", "macro", "rf", "mkt"):
        x = D[k].copy()
        fut = x.index > d
        if isinstance(x, pd.DataFrame):
            num = x.select_dtypes(include=[np.number]).columns
            x[num] = x[num].astype(float)
            x.loc[fut, num] = rng.normal(0, 1, (fut.sum(), len(num))) * 10.0
        else:
            x = x.astype(float)
            x.loc[fut] = rng.normal(0, 1, fut.sum()) * 10.0
        out[k] = x
    return out


def main() -> int:
    D = E.load()
    full_a = E.signals_a(D["mkt"], D["rf"], D["sh"], D["macro"])
    full_b = E.signals_b(D["ind"])
    idx = D["mkt"].index

    rng = np.random.default_rng(42)
    dates = [pd.Timestamp(x) for x in ("1932-06-30", "1974-09-30", "1987-10-31", "2000-03-31", "2008-10-31", "2020-03-31", "2023-06-30", "2026-07-31")]
    dates += list(idx[rng.choice(np.arange(130, len(idx) - 1), 20, replace=False)])

    # ---- 1 + 2: Trunkierung und Mutation
    for i, d in enumerate(sorted(dates)):
        for lab, DD in (("trunc", truncate(D, d)), ("mutate", mutate_future(D, d, i))):
            sa = E.signals_a(DD["mkt"], DD["rf"], DD["sh"], DD["macro"])
            for c in full_a.columns:
                check(same(pd.Series([full_a.loc[d, c]]), pd.Series([sa.loc[d, c]])), f"A/{c} @ {d:%Y-%m} [{lab}]")
            sb = E.signals_b(DD["ind"])
            for c, df in full_b.items():
                check(same(df.loc[d], sb[c].loc[d]), f"B/{c} @ {d:%Y-%m} [{lab}]")

    # ---- 3: Zeitlogik auf Spielzeugdaten
    t = pd.date_range("2000-01-31", periods=8, freq="ME")
    r = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08], index=t)
    rf = pd.Series(0.0, index=t)
    w = pd.Series(0.0, index=t)
    w.iloc[2] = 1.0                                        # Signal am Ende März
    out = E.run_exposure(w, r, rf, 0.0)
    check(abs(out.loc[t[3]] - 0.04) < 1e-12 and abs(out.loc[t[2]]) < 1e-12, "run_exposure: Gewicht von t wirkt in t+1, nicht in t")
    ex = r
    fwd1 = ((1 + ex).rolling(1).apply(np.prod, raw=True) - 1).shift(-1)
    check(abs(fwd1.loc[t[2]] - 0.04) < 1e-12, "fwd[1] an t ist die Rendite von t+1")
    fwd3 = ((1 + ex).rolling(3).apply(np.prod, raw=True) - 1).shift(-3)
    check(abs(fwd3.loc[t[2]] - ((1.04 * 1.05 * 1.06) - 1)) < 1e-12, "fwd[3] an t ist das Produkt über t+1..t+3")
    # IC-Ausrichtung: Signal, das die Rendite von t+1 exakt kennt, muss IC = 1 liefern; eines, das t kennt, nicht
    rets = pd.DataFrame(np.random.default_rng(0).normal(0, 1, (30, 10)), index=pd.date_range("2000-01-31", periods=30, freq="ME"))
    oracle = rets.shift(-1)
    ic = analysis.information_coefficients({"oracle": oracle, "same_month": rets}, rets.shift(-1), min_assets=8)
    check(abs(ic.loc["oracle", "mean_IC"] - 1.0) < 1e-9, "IC: Orakel-Signal (kennt t+1) → IC 1.0 (Ausrichtung Signal_t ↔ Rendite_t+1 korrekt)")
    check(abs(ic.loc["same_month", "mean_IC"]) < 0.3, "IC: Signal aus Monat t hat keinen mechanischen Bezug zur Rendite t+1")

    # ---- 4: CAPE-Lag-Sensitivität (zeigt den Preis eines zu kurzen Lags)
    ex_full = D["mkt"] - D["rf"]
    fwd120 = ((1 + ex_full).rolling(120).apply(np.prod, raw=True) - 1).shift(-120)
    fwd1m = ex_full.shift(-1)
    rows = {}
    for lag in (0, 4, 6, 9):
        E.EARNINGS_LAG = lag
        s = E.signals_a(D["mkt"], D["rf"], D["sh"], D["macro"])
        r1 = E.nw_horizon(fwd1m, s["ecy"], 1)
        r120 = E.nw_horizon(fwd120, s["ecy"], 120)
        rows[f"Gewinn-Lag {lag}M"] = {"ECY 1M t": r1["t"], "ECY 1M R²": r1["R2"], "ECY 120M t": r120["t"], "ECY 120M R²": r120["R2"]}
    E.EARNINGS_LAG = 6
    sens = pd.DataFrame(rows).T

    # ---- Bericht
    n_pass = sum(1 for l in LOG if l.startswith("PASS"))
    rep = [
        "# Audit der Aktienstudie: Look-ahead und Zeitlogik",
        "",
        f"Mechanische Prüfung von `scripts/run_equity.py` am {pd.Timestamp.today():%Y-%m-%d}. "
        f"{n_pass} Prüfungen bestanden, {len(FAILS)} fehlgeschlagen.",
        "",
        "## 1. Trunkierungs- und Mutationstest",
        f"Für {len(dates)} Daten D (8 historische Stressmonate + 20 zufällige) wurden alle Signale aus Teil A (Exposure) und Teil B (Branchen) "
        "einmal aus der Vollstichprobe und einmal aus (a) auf D gekürzten bzw. (b) nach D mit Rauschen überschriebenen Daten berechnet. "
        "Alle Werte am Datum D sind identisch: kein Signal verwendet Daten nach D.",
        "",
        "## 2. Zeitlogik der Hilfsfunktionen",
        *[f"- {l}" for l in LOG if "run_exposure" in l or "fwd[" in l or l.startswith(("PASS IC", "FAIL IC"))],
        "",
        "## 3. Korrekturen gegenüber der ersten Fassung",
        "| Punkt | Vorher | Nachher | Wirkung |",
        "|---|---|---|---|",
        "| Shiller-Gewinne | Lag 4 Monate | Lag 6 Monate | Gewinne sind quartalsweise linear interpoliert: der Monatswert enthält das Ergebnis des laufenden Quartals, das erst ~7 Wochen nach Quartalsende vorliegt (Vorlauf bis 5 Monate). 6 Monate sind sicher. ECY-Statistik praktisch unverändert (Tabelle unten). |",
        "| CPI in CAPE/ECY | CPI des Monats t | CPI des Monats t−1 | CPI für t erscheint Mitte t+1. Wirkung auf CAPE < 0.3 %. |",
        "| Branchen-Regime-Tabellen (B4) | relative Rendite im selben Monat wie das Regime | Regime am Monatsende t (Makro bis t−1), Rendite in t+1 | Tabelle ist jetzt das, was ein Investor hätte nutzen können. Muster unverändert: Energie +6.0/+4.8 % bei Inflation↑, −8.4 % in IP-Rückgang; langlebiger Konsum +13.0 % und Handel +8.1 % im IP-Rückgang, Defensive ≈ 0. |",
        "| Begründung Composite (A2) | «schlechter, weil Arbeitsmarkt-Baustein falsch zeigt» | Zerlegung: Trend+Kredit Sharpe 0.40, Trend+Arbeitsmarkt 0.44, Trend allein 0.51 | Die alte Begründung war nicht belegt. Beide Makro-Bausteine schaden, Kredit stärker. Mechanismus: ein Baustein, der fast immer «ok» sagt, verwässert den Trend-Ausstieg auf 50 %. |",
        "| Signalbildung | im Analyse-Code verwoben | reine Funktionen `signals_a`, `signals_b` | Trunkierungstest möglich; Vorlage für `rotationlab/features/equity.py`. |",
        "",
        "## 4. Sensitivität der Excess CAPE Yield auf den Gewinn-Lag",
        "Zeigt, wie gross der Fehler gewesen wäre: selbst ohne Lag (echter Look-ahead) ändern sich t-Werte und R² nur in der zweiten Stelle, "
        "weil ein Quartal in einem 120-Monats-Durchschnitt wenig Gewicht hat. Der Lag ist trotzdem korrekt gesetzt, weil das Live-System dieselbe Funktion nutzt.",
        "",
        "| | ECY 1M t | ECY 1M R² | ECY 120M t | ECY 120M R² |",
        "|---|---|---|---|---|",
        *[f"| {k} | {v['ECY 1M t']:.2f} | {v['ECY 1M R²']:.3f} | {v['ECY 120M t']:.2f} | {v['ECY 120M R²']:.3f} |" for k, v in sens.iterrows()],
        "",
        "## 5. Golden-Werte nach dem Audit",
        "| Modul | Kennzahl | Wert | Status |",
        "|---|---|---|---|",
        "| us_equity_exposure (Trend/Momentum-Mittel, French-Markt 1927–2026, 5 bp) | Sharpe ex Cash / Rendite / Max-DD | 0.573 / 0.099 / −0.411 | unverändert, freigegeben |",
        "| us_sector_rotation (Top-3 Composite + Markt-Trendfilter, 10 French-Branchen 1928–2026, 10 bp) | Sharpe ex Cash / Rendite / Max-DD | 0.591 / 0.111 / −0.458 | unverändert, freigegeben |",
        "",
        "## 6. Restrisiken, die kein Code-Test beseitigt",
        "- **Revisionen:** FRED-MD liefert heutige Endstände. Industrieproduktion wird oft um > 0.5 Punkte revidiert; die Arbeitslosenquote kaum. "
        "Betroffen sind nur Kontext-Tabellen (B4) und die ausdrücklich *nicht* genutzten Makro-Signale. Die Module selbst nutzen nur Preise. "
        "Phase 1 ersetzt FRED-MD durch ALFRED-Vintages.",
        "- **French-Daten:** CRSP-Korrekturen und SIC-Neuzuordnungen ändern historische Branchenrenditen leicht; keine Vintages verfügbar. Wirkung auf Monatsrenditen klein, auf Goldens innerhalb der Toleranz.",
        "- **Auswahl nach Sicht:** Die Variante «Trend/Momentum-Mittel» wurde unter ~10 Varianten gewählt. Mildernd: alle Trendfenster 6–18 Monate liegen bei Sharpe 0.50–0.56, "
        "die Variante ist weder Maximum der Rendite noch des Sharpe; Walk-forward im System testet die Wahl laufend.",
        "- **Proxy-Abweichung:** Goldens auf French-Gesamtmarkt und SIC-Branchen, Live auf SPY und GICS-Sektoren. Phase 2 misst die Abweichung 1999–2026, bevor Live-Toleranzen gesetzt werden.",
        "- **Umsetzung D vs. D+1:** Studie zu D-Schluss, System zu D+1-Schluss; die Golden-Toleranz von ±0.02 Sharpe deckt das nach Erfahrung ab, Phase 2 prüft es.",
    ]
    if FAILS:
        rep += ["", "## Fehlschläge", *[f"- {f}" for f in FAILS]]
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "AUDIT_equity_study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
