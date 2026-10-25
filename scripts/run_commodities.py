"""Rohstoff-Rotation: Signale testen, Backtest, aktueller Wegweiser.

Erzeugt output/commodities/ mit REPORT.md, Tabellen (CSV) und Grafiken (PNG).
Aufruf:  python scripts/run_commodities.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import config as C  # noqa: E402
from src import backtest, commodity_model as cm, data, metrics  # noqa: E402

OUT = os.path.join(ROOT, "output", "commodities")
os.makedirs(OUT, exist_ok=True)
START = "1972-12-31"
COST_BPS = 20  # Rohstoffe: etwas höher als bei ETFs auf Aktien/Anleihen

REPORT: list[str] = []


def say(*parts: str) -> None:
    REPORT.extend(parts)
    REPORT.append("")


def md(df: pd.DataFrame, fmt: str = "{:.3f}", index: bool = True) -> str:
    head = ([df.index.name or ""] if index else []) + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for i, row in df.iterrows():
        cells = ["" if (isinstance(v, float) and np.isnan(v)) else (fmt.format(v) if isinstance(v, (float, np.floating)) else str(v)) for v in row]
        lines.append("| " + " | ".join(([str(i)] if index else []) + cells) + " |")
    return "\n".join(lines)


def savefig(name: str) -> str:
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, name), dpi=130)
    plt.close()
    return name


def main() -> None:
    assets, macro = data.load_long_history()
    names = cm.COMMODITIES
    levels = assets[list(names)].loc[START:]
    cash = assets[C.LONG_CASH].pct_change().loc[START:]
    rets = levels.pct_change()
    excess = rets.sub(cash, axis=0)
    rel_excess = excess.sub(excess.mean(axis=1), axis=0)          # relativ zum Rohstoff-Durchschnitt
    macro = macro.reindex(levels.index)
    st = cm.macro_state(macro)
    state = st["state"]

    sig = cm.build_signals(levels, rel_excess, state)
    fwd_rel = rel_excess.shift(-1)

    say("# Rohstoff-Rotation: Wegweiser-Modell",
        f"Universum: {', '.join(names.values())}. Stichprobe {levels.index.min():%Y-%m} bis {levels.index.max():%Y-%m}; "
        "Rohstoffe treten ein, sobald Daten vorliegen (Erdgas/Aluminium/Nickel ab 1982). Alle Preise sind World-Bank-Monatsdurchschnitte, "
        "damit der Querschnitt zeitlich konsistent ist (LBMA-Monatsendkurse für Gold/Silber nur als Robustheitscheck). Alle Renditen monatlich; 'relativ' = Überschussrendite minus Durchschnitt aller "
        "verfügbaren Rohstoffe im selben Monat. Die Frage ist also nie 'steigt Öl?', sondern 'schlägt Öl die anderen Rohstoffe?'.")

    # ---------------- 1. Deskriptiv
    desc = pd.DataFrame({
        "Start": [rets[c].first_valid_index().strftime("%Y-%m") for c in rets.columns],
        "Rendite p.a.": rets.apply(metrics.ann_return),
        "Vol p.a.": rets.apply(metrics.ann_vol),
        "Sharpe ex Cash": excess.apply(metrics.sharpe),
        "Max DD": rets.apply(metrics.max_drawdown),
    }, index=rets.columns)
    desc.index = [names[c] for c in desc.index]
    desc.to_csv(os.path.join(OUT, "01_describe.csv"))
    say("## 1. Die Rohstoffe einzeln", md(desc))
    corr = rets.corr()
    corr.index = corr.columns = [names[c] for c in corr.columns]
    say("### Korrelation der Monatsrenditen", md(corr, "{:.2f}"))

    # ---------------- 2. Regime-Tabelle (Vollstichprobe, zur Illustration)
    rt = cm.regime_table(rel_excess, state)
    rt.columns = [names.get(c, c) for c in rt.columns]
    rt = rt.sort_values("Monate", ascending=False)
    rt.to_csv(os.path.join(OUT, "02_regime_table.csv"))
    say("## 2. Welcher Rohstoff in welchem Makro-Zustand? (relative Rendite p.a., Vollstichprobe)",
        "Zustand = Trendrichtung über 3 Monate von Dollar (USD), Industrieproduktion (IP) und Inflation (CPI), um einen Monat verzögert. "
        "Positive Zahl = Rohstoff schlug den Rohstoff-Durchschnitt in diesem Zustand. Das Modell selbst nutzt diese Tabelle nur "
        "expanding (jeweils aus der Vergangenheit geschätzt und geschrumpft), die Vollstichprobe hier dient der Anschauung.",
        md(rt, "{:.3f}"))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    hm = rt.drop(columns="Monate")
    im = ax.imshow(hm.values.astype(float) * 100, cmap="RdBu", vmin=-15, vmax=15, aspect="auto")
    ax.set_xticks(range(hm.shape[1]), hm.columns, rotation=30, ha="right")
    ax.set_yticks(range(hm.shape[0]), [f"{i} (n={int(rt.loc[i, 'Monate'])})" for i in hm.index])
    for i in range(hm.shape[0]):
        for j in range(hm.shape[1]):
            ax.text(j, i, f"{hm.values[i, j] * 100:+.1f}", ha="center", va="center", fontsize=8)
    plt.colorbar(im, ax=ax, label="relative Rendite p.a. (%)")
    ax.set_title("Relative Rohstoffrendite je Makro-Zustand (Dollar / Industrieproduktion / Inflation)")
    say(f"![]({savefig('fig_regime_heatmap.png')})")

    # ---------------- 3. Signalqualität
    ics = {k: cm.rank_ic(v, fwd_rel) for k, v in sig.items()}
    ict = cm.ic_summary(ics)
    fwd3 = (levels.shift(-3) / levels - 1)
    fwd3 = fwd3.sub(fwd3.mean(axis=1), axis=0)
    ics3 = {k: cm.rank_ic(v, fwd3) for k, v in sig.items()}
    ict3 = cm.ic_summary(ics3)
    ict["IC 3M"], ict["t 3M"] = ict3["IC"], ict3["t"]
    ict.to_csv(os.path.join(OUT, "03_ics.csv"))
    say("## 3. Signalqualität",
        "### 3a. Querschnitt: Rang-IC gegen relative Rendite im Folgemonat bzw. in den Folge-3-Monaten",
        "Frage: Sagt das Signal voraus, *welcher* Rohstoff die anderen schlägt? Zum Vergleich: im Multi-Asset-Modell lag der 12M-Momentum-IC bei 0.07–0.10 (t ≈ 3.5).",
        md(ict))
    tc = cm.trend_check(levels, excess, names)
    tc.to_csv(os.path.join(OUT, "03_trend_check.csv"))
    lb = assets[["GOLD", "SILVER"]].loc[START:]
    tc_lb = cm.trend_check(lb, lb.pct_change().sub(cash, axis=0), {"GOLD": "Gold (LBMA Monatsende)", "SILVER": "Silber (LBMA Monatsende)"})
    say("### 3b. Zeitreihe: Lohnt es sich, einen Rohstoff überhaupt zu halten?",
        "Frage: Ist der Rohstoff über seinem 10-Monats-Schnitt, verdient er im Folgemonat mehr als darunter? "
        "Das ist Time-Series-Momentum (Moskowitz, Ooi & Pedersen 2012) und bei Rohstoffen die robustere Signalart. "
        "Monatsdurchschnitte überzeichnen den Effekt leicht; die LBMA-Monatsendkurse unten zeigen, dass er für Gold und Silber auch ohne Durchschnittsbildung besteht.",
        md(tc), md(tc_lb))
    rows = {}
    for k in ["mom_12m", "momentum_combo", "regime", "combined"]:
        ls, lo, sh = cm.long_short(sig[k], excess.shift(-1), n=3)
        rows[k] = {"Long-Short p.a.": ls.mean() * 12, "LS Sharpe": metrics.sharpe(ls), "Long-Bein p.a. (ex Cash)": lo.mean() * 12,
                   "Short-Bein p.a. (ex Cash)": sh.mean() * 12, "Monate": len(ls)}
    lst = pd.DataFrame(rows).T
    lst.to_csv(os.path.join(OUT, "03_long_short.csv"))
    say("### Top-3 minus Bottom-3 (gleichgewichtet, brutto)", md(lst))

    # Teilperioden-Stabilität des kombinierten Signals
    sub = {}
    for s, e in [("1973", "1989"), ("1990", "2005"), ("2006", "2025")]:
        for k in ["momentum_combo", "regime", "combined"]:
            x = ics[k].loc[s:e]
            sub[(f"{s}–{e}", k)] = {"IC": x.mean(), "t": x.mean() / (x.std() / np.sqrt(len(x))), "Monate": len(x)}
    subt = pd.DataFrame(sub).T
    subt.index = [f"{a} · {b}" for a, b in subt.index]
    say("### Stabilität über Teilperioden", md(subt))

    # ---------------- 4. Backtest long-only
    ew = rets.mean(axis=1)
    results, weights = {}, {}
    for k in ["momentum_combo", "regime", "combined"]:
        for n in (2, 3, 4):
            w = cm.top_n_weights(sig[k], levels, n=n, trend_filter=True)
            bt = backtest.run_backtest(w, levels, cash, cost_bps=COST_BPS)
            results[(k, n)] = bt
            weights[(k, n)] = w
    for lam in (0.0, 0.5, 1.0):
        w = cm.tilted_weights(sig["combined"], levels, lam=lam, trend_filter=True)
        results[("tilt", lam)] = backtest.run_backtest(w, levels, cash, cost_bps=COST_BPS)
        weights[("tilt", lam)] = w
    above = levels > levels.rolling(10).mean()
    w_ew = above.astype(float) / levels.notna().sum(axis=1).to_numpy()[:, None]
    w_ew["CASH"] = 1 - w_ew.sum(axis=1)
    results[("ew_tf", 0)] = backtest.run_backtest(w_ew, levels, cash, cost_bps=COST_BPS)
    start = results[("combined", 3)]["net"].first_valid_index()
    # Walk-forward über Kandidaten (Signale sind kausal → nur die Auswahl ist zu testen)
    cands = {f"{k} Top-{n}" if k not in ("tilt", "ew_tf") else f"{k} λ={n}": v["net"] for (k, n), v in results.items()}
    cdf = pd.DataFrame(cands)
    oos, chosen = pd.Series(dtype=float), []
    idx = cdf.index
    t = 120
    while t < len(idx):
        hist = cdf.iloc[:t].sub(cash.reindex(idx[:t]), axis=0)
        best = hist.apply(metrics.sharpe).idxmax()
        end = min(t + 12, len(idx))
        oos = pd.concat([oos, cdf[best].iloc[t:end]])
        chosen.append(best)
        t = end
    series = {
        "A  Equal Weight, immer investiert": ew.loc[start:],
        "B  Equal Weight + Trendfilter": results[("ew_tf", 0)]["net"],
        "C  Inverse Vol + Trendfilter (λ=0)": results[("tilt", 0.0)]["net"],
        "D  C + Score-Tilt λ=0.5": results[("tilt", 0.5)]["net"],
        "E  C + Score-Tilt λ=1.0": results[("tilt", 1.0)]["net"],
        "F  Momentum Top-3": results[("momentum_combo", 3)]["net"],
        "G  Regime Top-3": results[("regime", 3)]["net"],
        "H  Kombiniert Top-3": results[("combined", 3)]["net"],
        "I  Kombiniert Top-4": results[("combined", 4)]["net"],
        "J  Walk-forward über alle Kandidaten": oos,
        "Gold": rets["WB_GOLD_AVG"].loc[start:],
        "Rohöl": rets["WB_OIL"].loc[start:],
    }
    summ = metrics.summary_table(series, {"E  C + Score-Tilt λ=1.0": results[("tilt", 1.0)]["turnover"], "H  Kombiniert Top-3": results[("combined", 3)]["turnover"]}, cash=cash)
    summ.to_csv(os.path.join(OUT, "04_backtest.csv"))
    say(f"## 4. Backtest long-only ({start:%Y-%m} – {levels.index.max():%Y-%m}, {COST_BPS} bp Kosten, Trendfilter → T-Bills)",
        "Die Zeilen bauen aufeinander auf: A→B isoliert den Trendfilter, B→C die Volatilitätsgewichtung, C→D/E den Mehrwert des "
        "relativen Scores (Momentum + Regime), F–I die harte Top-N-Auswahl. Sharpe auf Überschussrendite über T-Bills.",
        md(summ))
    wf = pd.Series(chosen).value_counts().rename("Jahre gewählt").to_frame()
    say("Walk-forward: gewählte Kandidaten", md(wf, "{:.0f}"))
    dec = pd.DataFrame({"InvVol+Trend+Tilt": series["E  C + Score-Tilt λ=1.0"], "Kombiniert Top-3": series["H  Kombiniert Top-3"], "Equal Weight": ew, "Gold": rets["WB_GOLD_AVG"]}).loc[start:]
    dec["decade"] = (dec.index.year // 10) * 10
    dect = pd.DataFrame({d: g.drop(columns="decade").apply(metrics.ann_return) for d, g in dec.groupby("decade")}).T
    dect.index = [f"{d}s" for d in dect.index]
    say("### Rendite p.a. je Jahrzehnt", md(dect))

    eq = pd.DataFrame({k: series[k] for k in ["A  Equal Weight, immer investiert", "C  Inverse Vol + Trendfilter (λ=0)", "E  C + Score-Tilt λ=1.0", "H  Kombiniert Top-3", "J  Walk-forward über alle Kandidaten", "Gold"]})
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    cum = (1 + eq.fillna(0)).cumprod()
    cum.plot(ax=axes[0], logy=True)
    axes[0].set_title("Rohstoff-Rotation: kumulierte Nettorendite (log)")
    (cum / cum.cummax() - 1).plot(ax=axes[1], legend=False)
    axes[1].set_title("Drawdown")
    say(f"![]({savefig('fig_equity.png')})")
    w3 = weights[("tilt", 1.0)].loc[start:]
    w3.columns = [names.get(c, c) for c in w3.columns]
    ax = w3.plot.area(figsize=(10, 3.5), lw=0, alpha=0.9)
    ax.set_title("Allokation Inverse Vol + Trendfilter + Score-Tilt (λ=1)")
    ax.legend(ncol=5, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    say(f"![]({savefig('fig_weights.png')})")
    w3.to_csv(os.path.join(OUT, "04_weights_tilt.csv"))

    # ---------------- 5. Wegweiser
    tab, asof = cm.signpost(levels, sig, state, names, weights[("tilt", 0.0)])
    tab.to_csv(os.path.join(OUT, "05_signpost.csv"))
    say(f"## 5. Wegweiser, Stand {asof}",
        "Zwei Ebenen. **Trend** (Zeitreihe): aufwärts = halten, abwärts = Cash; das ist die verlässliche Ebene. "
        "**Score** (Querschnitt) = 0.7 × Momentum-Composite (z) + 0.3 × Regime-Erwartung (z); er kippt die Gewichte innerhalb der Aufwärtstrend-Rohstoffe "
        "und ist die unsichere Ebene (siehe ICs). Regime-Erwartung = aus der Vergangenheit geschätzte relative Rendite p.a. im aktuellen Makro-Zustand. "
        "Modellgewicht = Variante C (inverse Volatilität, nur Aufwärtstrends, Rest T-Bills), weil der Score im Backtest keinen Mehrwert zeigt: "
        "die Rangfolge ist Information, keine Handlungsanweisung.",
        md(tab, "{:.3f}"),
        f"Cash-Anteil (T-Bills) des Modells: {weights[('tilt', 0.0)].loc[levels.index.max(), 'CASH']:.0%}.")
    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["tab:green" if i < 3 else ("tab:red" if i >= len(tab) - 3 else "tab:gray") for i in range(len(tab))]
    ax.barh(tab["Rohstoff"][::-1], tab["Score"][::-1], color=colors[::-1])
    ax.axvline(0, color="k", lw=0.5)
    ax.set_title(f"Wegweiser: Composite-Score je Rohstoff, {asof}")
    say(f"![]({savefig('fig_signpost.png')})")

    # Historie des Rankings (letzte 24 Monate) als Tabelle
    rank_hist = sig["combined"].rank(axis=1, ascending=False).loc[levels.index.max() - pd.DateOffset(months=23):]
    rank_hist.columns = [names.get(c, c) for c in rank_hist.columns]
    rank_hist.index = rank_hist.index.strftime("%Y-%m")
    rank_hist.to_csv(os.path.join(OUT, "05_rank_history.csv"))
    say("### Rangfolge der letzten 24 Monate (1 = attraktivster Rohstoff)", md(rank_hist, "{:.0f}"))

    say("## 6. Fazit",
        "1. **Wann halten** lässt sich beantworten: Jeder Rohstoff ausser US-Erdgas verdient über seinem 10-Monats-Schnitt 10–18 % p.a. mehr als darunter (t = 1.9–4.3). "
        "Ein Portfolio, das nur Rohstoffe im Aufwärtstrend hält und sie nach inverser Volatilität gewichtet, erreicht Sharpe 0.74 bei −17 % Max-Drawdown "
        "gegenüber 0.28 und −51 % für dauerhaft gleichgewichtete Rohstoffe.",
        "2. **Welcher zuerst** lässt sich mit Spotpreisen und Makrotrends *nicht* verlässlich beantworten: Querschnitts-ICs von Momentum und Regime liegen bei 0.00–0.02, "
        "Long-Short-Portfolios bringen nichts, und jede Kippung der Gewichte nach Score senkt den Sharpe (0.74 → 0.50). Der Walk-forward wählt in allen 44 Jahren die ungekippte Variante.",
        "3. Was in der Literatur die Rangfolge innerhalb von Rohstoffen erklärt, fehlt in diesen Daten: Terminkurve/Roll-Rendite (Backwardation = Knappheit; Gorton, Hayashi & Rouwenhorst 2013), "
        "Lagerbestände und Hedging-Positionierung (CFTC). Der nächste Ausbauschritt ist deshalb nicht ein besseres Makromodell, sondern Futures-Daten mit Terminkurve.",
        "4. Für Gold und Silber konkret: Silber schlägt Gold nicht vorhersagbar; beide folgen demselben Trend- und Dollarregime, Silber mit doppelter Amplitude. "
        "Wer Silber übergewichtet, kauft Hebel auf Gold, keine eigenständige Prognose.")
    with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(REPORT))
    print("\n".join(REPORT))


if __name__ == "__main__":
    main()
