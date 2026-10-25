"""Vollständige Auswertung auf dem Langfrist-Panel (1973–2025).

Erzeugt output/long/ mit CSV-Tabellen, PNG-Grafiken und REPORT.md.

Aufruf:  python scripts/run_analysis.py
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
from src import analysis, backtest, data, features, metrics, signals  # noqa: E402

OUT = os.path.join(ROOT, "output", "long")
os.makedirs(OUT, exist_ok=True)
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

REPORT: list[str] = []


def md(df: pd.DataFrame, floatfmt: str = "{:.3f}", index: bool = True) -> str:
    """Kleiner Markdown-Tabellen-Formatter (ohne tabulate)."""
    df = df.copy()
    cols = list(df.columns)
    if isinstance(df.columns, pd.MultiIndex):
        cols = [" ".join(str(x) for x in c) for c in df.columns]
        df.columns = cols
    head = ([df.index.name or ""] if index else []) + [str(c) for c in cols]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for i, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, (float, np.floating)):
                cells.append("" if np.isnan(v) else floatfmt.format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(([str(i)] if index else []) + cells) + " |")
    return "\n".join(lines)


def say(*parts: str) -> None:
    REPORT.extend(parts)
    REPORT.append("")


def savefig(name: str) -> str:
    path = os.path.join(OUT, name)
    plt.tight_layout()
    plt.savefig(path, dpi=130)
    plt.close()
    return name


def main() -> None:
    assets, macro = data.load_long_history()
    universe = list(C.LONG_UNIVERSE)
    levels = assets[universe].loc[C.LONG_START:]
    cash = assets[C.LONG_CASH].pct_change().loc[C.LONG_START:]
    rets = levels.pct_change()
    excess = rets.sub(cash, axis=0)
    macro = macro.reindex(levels.index)
    mf = features.macro_features(macro)

    say("# Cross-Asset Rotation – Auswertung des Langfrist-Panels",
        f"Stichprobe: {levels.index.min():%Y-%m} bis {levels.index.max():%Y-%m}, {len(levels)} Monate, "
        f"{len(universe)} Anlageklassen + Cash (3M-T-Bill).",
        "Alle Renditen monatlich, Monatsende. Überschussrendite = Rendite − T-Bill. "
        "Datenquellen und Konstruktion: `data/DATA_SOURCES.md`.")

    # ------------------------------------------------------------------ 1. Deskriptiv
    desc = analysis.describe_assets(rets, cash)
    desc.to_csv(os.path.join(OUT, "01_describe.csv"))
    say("## 1. Deskriptive Statistik (1973–2025)", md(desc))
    sub = analysis.subperiod_table(rets, cash, ["1984-12-31", "1999-12-31", "2012-12-31"])
    sub.to_csv(os.path.join(OUT, "01_subperiods.csv"))
    say("### Teilperioden", md(sub))

    corr = rets.corr()
    corr.to_csv(os.path.join(OUT, "02_correlation.csv"))
    say("## 2. Korrelationen der Monatsrenditen", md(corr, "{:.2f}"))
    fig, ax = plt.subplots(figsize=(10, 4))
    for a, b in [("US_EQ", "UST10"), ("US_EQ", "GOLD"), ("GOLD", "SILVER"), ("GOLD", "UST10")]:
        analysis.rolling_correlation(rets, a, b, 36).plot(ax=ax, label=f"{a} – {b}")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("Rollierende 36-Monats-Korrelation")
    ax.legend(ncol=4, fontsize=8)
    f_corr = savefig("fig_rolling_corr.png")
    say(f"![]({f_corr})")

    # ------------------------------------------------------------------ 3. Regimes
    quad = features.macro_regime(macro).reindex(levels.index)
    dirs = features.direction_regimes(macro).reindex(levels.index)
    say("## 3. Renditen je Makro-Regime",
        "Regime = Trendrichtung über 3 Monate (3M-Durchschnitt heute vs. vor 3 Monaten), "
        "um einen Monat verzögert (Publikationslag). Tabellen: annualisierte Überschussrendite; "
        "t-Statistik in Klammern-Tabelle darunter. Vorsicht: Regime sind autokorreliert, t-Werte daher optimistisch.")

    reg_tables = {}
    for name, series in [("Wachstum × Inflation (Quadranten)", quad["regime"])] + [(k, dirs[k]) for k in dirs.columns]:
        tab = analysis.returns_by_regime(excess, series)
        if tab.empty:
            continue
        reg_tables[name] = tab
        piv = analysis.regime_pivot(tab, "ann_excess")
        tpiv = analysis.regime_pivot(tab, "t_stat")
        months = tab.groupby("regime")["months"].max()
        piv.columns = [f"{c} (n={months[c]})" for c in piv.columns]
        tpiv.columns = piv.columns
        say(f"### {name}", md(piv), "t-Statistiken:", md(tpiv, "{:.1f}"))
    pd.concat(reg_tables, names=["regime_def"]).to_csv(os.path.join(OUT, "03_regimes.csv"))

    # Plot Quadranten
    tab = reg_tables["Wachstum × Inflation (Quadranten)"]
    piv = analysis.regime_pivot(tab, "ann_excess")
    order = [c for c in ["high_low", "high_high", "low_high", "low_low"] if c in piv.columns]
    ax = piv[order].T.plot(kind="bar", figsize=(10, 4.5), width=0.8)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_ylabel("Ann. Überschussrendite")
    ax.set_title("Überschussrendite je Wachstum/Inflations-Quadrant (growth_inflation)")
    ax.legend(ncol=4, fontsize=8)
    say(f"![]({savefig('fig_regime_quadrants.png')})")

    # Plot Realzins-Regime für Gold/Silber
    tab = reg_tables["real_yield"]
    piv = analysis.regime_pivot(tab, "ann_excess")
    ax = piv.loc[["GOLD", "SILVER", "US_EQ", "UST10"]].plot(kind="bar", figsize=(8, 4))
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("Überschussrendite: Realzins (10y − CPI yoy) steigend vs. fallend")
    say(f"![]({savefig('fig_regime_realyield.png')})")

    # ------------------------------------------------------------------ 4. Treiber-Regressionen
    say("## 4. Was treibt Gold, Silber & Co.? (OLS, Newey-West t-Werte)",
        "Monatliche Überschussrendite (in %) auf *gleichzeitige* Faktoränderungen (standardisiert, 1 Std.-Abw.). "
        "Koeffizient = %-Punkte Monatsrendite je 1 Std.-Abw. Faktoränderung. "
        "Die prädiktive Variante (Faktor um 1 Monat verzögert) zeigt, ob die Information *vorher* nutzbar ist.")
    dX = pd.DataFrame(
        {
            "Δ Realzins 10y": macro["REAL_GS10"].diff(),
            "Δ log Dollar": np.log(macro["USD_IDX"]).diff(),
            "Δ CPI yoy": macro["CPI_YOY"].diff(),
            "Δ Kreditspread": macro["CREDIT_BAA_AAA"].diff(),
            "Δ Zinskurve": macro["CURVE_10Y3M"].diff(),
            "Δ IP yoy": macro["INDPRO_YOY"].diff(),
        },
        index=levels.index,
    )
    factors = {c: c for c in dX.columns}
    assets_reg = ["GOLD", "SILVER", "US_EQ", "UST10", "WB_ENERGY", "WB_BASEMETALS"]
    tab0, full0 = analysis.driver_regressions(excess, dX, assets_reg, factors, lead=0)
    tab1, _ = analysis.driver_regressions(excess, dX, assets_reg, factors, lead=1)
    coef0 = tab0.pivot(index="factor", columns="asset", values="coef_%/sd").loc[list(factors)]
    t0 = tab0.pivot(index="factor", columns="asset", values="t_stat").loc[list(factors)]
    r2 = tab0.groupby("asset")["r2"].first().reindex(assets_reg)
    coef0.loc["R²"] = r2
    say("### Gleichzeitig (erklärend), 1973–2025", md(coef0, "{:.2f}"), "t-Statistiken:", md(t0, "{:.1f}"))
    t1 = tab1.pivot(index="factor", columns="asset", values="t_stat").loc[list(factors)]
    say("### Prädiktiv (Faktor t−1 → Rendite t)", md(t1, "{:.1f}"))
    tab0.to_csv(os.path.join(OUT, "04_drivers_contemporaneous.csv"), index=False)
    tab1.to_csv(os.path.join(OUT, "04_drivers_predictive.csv"), index=False)

    # VIX-Variante ab 1990
    dXv = dX.copy()
    dXv["Δ log VIX"] = np.log(macro["VIX"]).diff()
    dXv = dXv.loc["1990-01-31":]
    tabv, _ = analysis.driver_regressions(excess.loc["1990-01-31":], dXv, assets_reg, {c: c for c in dXv.columns}, lead=0)
    tv = tabv.pivot(index="factor", columns="asset", values="t_stat").loc[list(dXv.columns)]
    say("### Gleichzeitig inkl. VIX, 1990–2025 (t-Statistiken)", md(tv, "{:.1f}"))

    # 12-Monats-Horizont: Jahresrenditen auf 12M-Faktoränderungen (überlappend, Newey-West 12 Lags)
    dX12 = pd.DataFrame(
        {
            "Δ12 Realzins 10y": macro["REAL_GS10"].diff(12),
            "Δ12 log Dollar": np.log(macro["USD_IDX"]).diff(12),
            "Δ12 CPI yoy": macro["CPI_YOY"].diff(12),
            "Δ12 Kreditspread": macro["CREDIT_BAA_AAA"].diff(12),
            "Δ12 IP yoy": macro["INDPRO_YOY"].diff(12),
        },
        index=levels.index,
    )
    ex12 = (levels / levels.shift(12) - 1).sub(assets[C.LONG_CASH].reindex(levels.index).pct_change(12), axis=0)
    tab12, _ = analysis.driver_regressions(ex12, dX12, assets_reg, {c: c for c in dX12.columns}, lags=12, lead=0)
    c12 = tab12.pivot(index="factor", columns="asset", values="coef_%/sd").loc[list(dX12.columns)]
    t12 = tab12.pivot(index="factor", columns="asset", values="t_stat").loc[list(dX12.columns)]
    c12.loc["R²"] = tab12.groupby("asset")["r2"].first().reindex(c12.columns)
    say("### 12-Monats-Horizont (Jahres-Überschussrendite in % je 1 Std.-Abw. der 12M-Faktoränderung; überlappende Fenster)",
        md(c12, "{:.1f}"), "t-Statistiken (Newey-West, 12 Lags):", md(t12, "{:.1f}"))
    tab12.to_csv(os.path.join(OUT, "04_drivers_12m.csv"), index=False)

    # Korrelation der 12M-Goldrendite mit den Kanälen je Teilperiode
    g12, s12 = levels["GOLD"].pct_change(12), levels["SILVER"].pct_change(12)
    chans = {
        "Δ12 Realzins (ex post)": macro["REAL_GS10"].diff(12),
        "Δ12 Nominalzins 10y": macro["GS10"].diff(12),
        "Δ12 CPI yoy": macro["CPI_YOY"].diff(12),
        "Δ12 log Dollar": np.log(macro["USD_IDX"]).diff(12),
    }
    rows = {}
    for s, e in [("1973", "1989"), ("1990", "2005"), ("2006", "2025"), ("2013", "2025"), ("1973", "2025")]:
        rows[f"{s}–{e}"] = {f"Gold: {k}": g12.loc[s:e].corr(v.loc[s:e]) for k, v in chans.items()} | {
            f"Silber: {k}": s12.loc[s:e].corr(v.loc[s:e]) for k, v in list(chans.items())[:1] + list(chans.items())[3:]}
    chan_tab = pd.DataFrame(rows).T
    chan_tab.to_csv(os.path.join(OUT, "04_gold_channels_by_period.csv"))
    say("### Welcher Kanal wann? Korrelation der 12M-Rendite mit 12M-Faktoränderungen je Teilperiode",
        "Der 'Realzins' (nominal − CPI) vermischt zwei Kanäle: In den 1970/80ern reagierte Gold auf *Inflation*, "
        "seit 2006 auf *Nominalzinsen* und den *Dollar*. Die Dollar-Beziehung ist über alle Perioden stabil negativ.",
        md(chan_tab, "{:.2f}"))

    # Scatter Gold vs Realzinsänderung (12M)
    fig, ax = plt.subplots(figsize=(6, 5))
    x = macro["REAL_GS10"].diff(12)
    y = levels["GOLD"].pct_change(12) * 100
    m = x.notna() & y.notna()
    ax.scatter(x[m], y[m], s=8, alpha=0.5)
    b = np.polyfit(x[m], y[m], 1)
    xs = np.linspace(x[m].min(), x[m].max(), 50)
    ax.plot(xs, np.polyval(b, xs), "r-", label=f"Steigung {b[0]:.1f} %-Pkt Gold je 1 %-Pkt Realzins")
    ax.axhline(0, color="k", lw=0.5)
    ax.axvline(0, color="k", lw=0.5)
    ax.set_xlabel("12M-Änderung Realzins 10y (%-Punkte)")
    ax.set_ylabel("12M-Goldrendite (%)")
    ax.set_title("Gold vs. Realzinsänderung, überlappende 12M-Fenster")
    ax.legend(fontsize=8)
    say(f"![]({savefig('fig_gold_vs_realyield.png')})")

    # ------------------------------------------------------------------ 5. ICs
    feats = features.asset_features(levels)
    fwd = excess.shift(-1)
    ic = analysis.information_coefficients(feats, fwd)
    ic.to_csv(os.path.join(OUT, "05_information_coefficients.csv"))
    say("## 5. Information Coefficients der Asset-Features",
        "Spearman-Rangkorrelation zwischen Feature zum Monatsende t und Überschussrendite im Monat t+1 über die "
        f"{len(universe)} Assets. IC > 0 = Feature ordnet richtig.",
        "**Vorsicht:** Die World-Bank-Rohstoffindizes sind Monats*durchschnitte*. Durchschnittsbildung erzeugt "
        "künstliche positive Autokorrelation (Working-Effekt), die 1-Monats-Features (`rev_1m`, `mom_12m_noskip`) "
        "überzeichnet. Deshalb nutzt das Modell Momentum mit 1-Monats-Skip; die zweite Tabelle wiederholt die Rechnung "
        "nur mit echten Monatsendkursen (Aktien, Treasury, Gold, Silber).",
        md(ic))
    lev_me = levels[C.LONG_UNIVERSE_MONTHEND]
    ic_me = analysis.information_coefficients(features.asset_features(lev_me), excess[C.LONG_UNIVERSE_MONTHEND].shift(-1), min_assets=4)
    ic_me.to_csv(os.path.join(OUT, "05_information_coefficients_monthend_only.csv"))
    say("Nur Monatsend-Assets (4 Assets, daher kleinere ICs erwartbar):", md(ic_me))
    spread = analysis.quantile_spread(feats["mom_12m"], fwd)
    spread.to_csv(os.path.join(OUT, "05_mom12_tercile_spread.csv"))
    say(f"Top-Tercil minus Bottom-Tercil nach 12M-Momentum (6 Assets): {spread.mean() * 12:.1%} p.a., "
        f"Sharpe {metrics.sharpe(spread):.2f}, {len(spread)} Monate.")

    # ------------------------------------------------------------------ 6. Gold/Silber-Ratio
    lr = np.log(macro["GOLD_SILVER_RATIO"]).dropna()
    mr = analysis.mean_reversion_test(lr)
    dev = mf["gs_ratio_dev120"]
    fwd12 = (levels["SILVER"].pct_change(12) - levels["GOLD"].pct_change(12)).shift(-12)
    cond = analysis.conditional_forward_returns(dev, fwd12)
    cond.to_csv(os.path.join(OUT, "06_gold_silver_ratio_quintiles.csv"))
    say("## 6. Gold/Silber-Ratio: Mean Reversion?",
        f"AR(1) auf log(Gold/Silber): φ = {mr['phi']:.3f}, Halbwertszeit ≈ {mr['half_life_months']:.0f} Monate, "
        f"t(ρ−1) = {mr['t_stat_(rho-1)']:.2f} (n={mr['n']}). Zum Vergleich: ADF-kritischer Wert 5 % ≈ −2.87.",
        "Vorwärts-12M-Rendite Silber minus Gold je Quintil der Ratio-Abweichung vom 10-Jahres-Mittel "
        "(Q5 = Ratio ungewöhnlich hoch = Silber billig; Quintile expandierend, ohne Look-ahead):",
        md(cond))
    fig, ax = plt.subplots(figsize=(10, 3.5))
    macro["GOLD_SILVER_RATIO"].plot(ax=ax)
    macro["GOLD_SILVER_RATIO"].rolling(120).mean().plot(ax=ax, ls="--")
    ax.set_title("Gold/Silber-Ratio und 10-Jahres-Mittel")
    say(f"![]({savefig('fig_gold_silver_ratio.png')})")

    # ------------------------------------------------------------------ 7. Backtest
    say("## 7. Rotationsstrategie",
        "Signal: Composite aus z-Scores (Momentum 3/6/12M, Trend, inverse Vol) → Top-3, inverse-Vol-gewichtet, "
        f"Trendfilter (unter 10M-Schnitt → Cash), {C.TRANSACTION_COST_BPS} bp Kosten auf Turnover. "
        "Varianten: ohne/mit Regime-Tilts, Walk-forward (Parameter jährlich auf Vergangenheit gewählt).")

    def build(params: dict, lv: pd.DataFrame = levels):
        ft = features.asset_features(lv)
        score = signals.composite_score(ft, params["weights"], quad.reindex(lv.index), params.get("tilts"))
        w = signals.build_weights(score, lv, top_n=params["top_n"], trend_filter=params["trend_filter"])
        return backtest.run_backtest(w, lv, cash, cost_bps=C.TRANSACTION_COST_BPS), w

    base = {"weights": C.FEATURE_WEIGHTS, "tilts": None, "top_n": C.TOP_N, "trend_filter": C.TREND_FILTER}
    bt_plain, w_plain = build(base)
    bt_reg, w_reg = build({**base, "tilts": C.REGIME_TILTS})
    bt_nofilter, _ = build({**base, "trend_filter": False})
    grid = [{**base, "top_n": n, "trend_filter": tf} for n in (2, 3, 4) for tf in (True, False)]
    oos, chosen = backtest.walk_forward(lambda p, lv: build(p, lv)[0], levels, grid, min_train_months=120,
                                        refit_every=12, cash_returns=cash)
    # Robustheit: nur Assets mit echten Monatsendkursen, Top-2
    lev_me = levels[C.LONG_UNIVERSE_MONTHEND]
    bt_me, _ = build({**base, "top_n": 2}, lev_me)

    ew = rets.mean(axis=1)
    bal = 0.6 * rets["US_EQ"] + 0.4 * rets["UST10"]
    start = bt_plain["net"].first_valid_index()
    series = {
        "Rotation (in-sample)": bt_plain["net"],
        "Rotation + Regime-Tilts": bt_reg["net"],
        "Rotation ohne Trendfilter": bt_nofilter["net"],
        "Rotation walk-forward (OOS)": oos,
        "Rotation nur Monatsend-Assets (Top-2)": bt_me["net"],
        f"Equal Weight ({len(universe)} Assets)": ew.loc[start:],
        "60/40 Aktien/Anleihen": bal.loc[start:],
        "US-Aktien": rets["US_EQ"].loc[start:],
        "Gold": rets["GOLD"].loc[start:],
        "T-Bills": cash.loc[start:],
    }
    summ = metrics.summary_table(series, {"Rotation (in-sample)": bt_plain["turnover"], "Rotation + Regime-Tilts": bt_reg["turnover"]}, cash=cash)
    summ.to_csv(os.path.join(OUT, "07_backtest_summary.csv"))
    say(f"### Kennzahlen ({start:%Y-%m} – {levels.index.max():%Y-%m})",
        "Sharpe auf Überschussrendite über T-Bills (wichtig: T-Bills brachten 1973–2025 im Schnitt 4.5 % p.a.).",
        md(summ))

    dec = analysis.by_decade(bt_plain["net"], {"EW": ew, "60/40": bal, "OOS": oos, "T-Bills": cash})
    dec.to_csv(os.path.join(OUT, "07_by_decade.csv"))
    say("### Annualisierte Rendite je Jahrzehnt", md(dec))

    chosen.to_csv(os.path.join(OUT, "07_walk_forward_params.csv"), index=False)
    wf_counts = chosen.groupby(["top_n", "trend_filter"]).size().rename("Jahre gewählt").reset_index()
    say("### Walk-forward: wie oft welche Parameter gewählt wurden",
        f"Erstes Trainingsfenster 120 Monate, Neuwahl jährlich, Kriterium Sharpe (ex Cash) auf allen bisherigen Daten; "
        f"OOS-Periode {oos.index.min():%Y-%m} bis {oos.index.max():%Y-%m}.",
        md(wf_counts, "{:.0f}", index=False))

    # Durchschnittliche Gewichte
    avg_w = w_plain.loc[start:].mean().rename("avg_weight")
    say("### Durchschnittliche Allokation (in-sample)", md(avg_w.to_frame(), "{:.1%}"))
    w_plain.to_csv(os.path.join(OUT, "07_weights.csv"))

    eq = pd.DataFrame({k: v for k, v in series.items() if k in ("Rotation (in-sample)", "Rotation walk-forward (OOS)", f"Equal Weight ({len(universe)} Assets)", "60/40 Aktien/Anleihen", "US-Aktien")})
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    cum = (1 + eq.fillna(0)).cumprod()
    cum.plot(ax=axes[0], logy=True)
    axes[0].set_title("Kumulierte Nettorendite (log)")
    (cum / cum.cummax() - 1).plot(ax=axes[1], legend=False)
    axes[1].set_title("Drawdown")
    say(f"![]({savefig('fig_equity.png')})")

    ax = w_plain.loc[start:].plot.area(figsize=(10, 3.5), lw=0, alpha=0.9)
    ax.set_title("Allokation über die Zeit (Rotation in-sample)")
    ax.legend(ncol=8, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    say(f"![]({savefig('fig_weights.png')})")

    # ------------------------------------------------------------------ 8. Sensitivität
    def build_sens(p: dict):
        key = f"mom_{p['lookback']}m" if p["lookback"] != 12 else "mom_12m"
        ft = features.asset_features(levels)
        score = signals.composite_score(ft, {key: 1.0}, None, None)
        w = signals.build_weights(score, levels, top_n=p["top_n"], trend_filter=p["trend_filter"])
        return backtest.run_backtest(w, levels, cash, cost_bps=C.TRANSACTION_COST_BPS)

    sens = analysis.sensitivity_grid(build_sens, [1, 2, 3, 4], [3, 6, 12], cash=cash)
    sens_nf = analysis.sensitivity_grid(build_sens, [1, 2, 3, 4], [3, 6, 12], trend_filter=False, cash=cash)
    sens.to_csv(os.path.join(OUT, "08_sensitivity_trendfilter.csv"))
    sens_nf.to_csv(os.path.join(OUT, "08_sensitivity_notrendfilter.csv"))
    say("## 8. Parameter-Sensitivität (Sharpe ex Cash, netto, in-sample, reines Momentum mit 1M-Skip)",
        "Mit Trendfilter:", md(sens, "{:.2f}"), "Ohne Trendfilter:", md(sens_nf, "{:.2f}"))
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    for ax, s, t in [(axes[0], sens, "mit Trendfilter"), (axes[1], sens_nf, "ohne Trendfilter")]:
        im = ax.imshow(s.values.astype(float), cmap="RdYlGn", vmin=0, vmax=0.8)
        ax.set_xticks(range(len(s.columns)), s.columns)
        ax.set_yticks(range(len(s.index)), s.index)
        for i in range(s.shape[0]):
            for j in range(s.shape[1]):
                ax.text(j, i, f"{s.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
        ax.set_title(f"Sharpe {t}")
    say(f"![]({savefig('fig_sensitivity.png')})")

    # ------------------------------------------------------------------ 9. Datenabdeckung
    cov = pd.read_csv(os.path.join(ROOT, "data", "coverage.csv"))
    say("## 9. Datenabdeckung", md(cov, index=False))

    with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(REPORT))
    print("\n".join(REPORT))
    print(f"\n→ {OUT}/REPORT.md")


if __name__ == "__main__":
    main()
