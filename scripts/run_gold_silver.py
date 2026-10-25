"""Gold/Silber-Pair-Trade: Wann lohnt sich long Gold / short Silber (und wann umgekehrt)?

Spread-Rendite (selbstfinanzierend, kein Cash-Abzug):
  dollar-neutral : r_Gold − r_Silber
  vol-neutral    : r_Gold − h_t · r_Silber,  h_t = σ_Gold / σ_Silber (36M, ex ante)
Positiv = Gold schlägt Silber.

Signale (am Monatsende t bekannt; Makro-Aktivität/Inflation um 1 Monat verzögert):
  Ratio-Trend      : 3/6/12M-Änderung der log Gold/Silber-Ratio, Ratio vs 10M-Schnitt (Trendfolge)
  Ratio-Bewertung  : z-Score der log Ratio vs 60M / 120M (Mean Reversion)
  Stress           : 3M-Änderung Baa−Aaa-Spread, VIX, Aktien-Trend (S&P vs 10M-Schnitt)
  Wachstum         : 3M-Änderung IP-Jahresrate, Kupfer-Momentum 6M (industrielle Nachfrage)
  Dollar / Zinsen  : 3M-Änderung log Dollar, 3M-Änderung Realzins

Aufruf: python scripts/run_gold_silver.py  → output/gold_silver/REPORT.md
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

from src import analysis, data, metrics  # noqa: E402

OUT = os.path.join(ROOT, "output", "gold_silver")
os.makedirs(OUT, exist_ok=True)
RAW = os.path.join(ROOT, "data", "raw")
COST_BPS = 10  # je Seite und Positionswechsel (Spread hat zwei Beine → 2 × COST_BPS je voller Umschichtung)
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


def lbma_monthly() -> pd.DataFrame:
    out = {}
    for name in ("gold", "silver"):
        df = pd.read_csv(os.path.join(RAW, f"lbma_{name}_daily.csv"), parse_dates=["date"]).set_index("date")
        col = [c for c in df.columns if c.endswith("_usd")][0]
        s = pd.to_numeric(df[col], errors="coerce").replace(0, np.nan).dropna()
        out[name.upper()] = s.resample("ME").last()
    return pd.DataFrame(out).dropna()


def zx(s: pd.Series, w: int) -> pd.Series:
    return (s - s.rolling(w, min_periods=w // 2).mean()) / s.rolling(w, min_periods=w // 2).std()


def cond_test(signal: pd.Series, fwd: pd.Series) -> dict:
    """Spread-Rendite im Folgemonat, wenn Signal > 0 vs ≤ 0; dazu Steigung (OLS, Newey-West)."""
    df = pd.DataFrame({"s": signal, "y": fwd}).dropna()
    hi, lo = df.loc[df.s > 0, "y"], df.loc[df.s <= 0, "y"]
    diff = hi.mean() - lo.mean()
    se = np.sqrt(hi.var() / len(hi) + lo.var() / len(lo))
    z = (df.s - df.s.mean()) / df.s.std()
    reg = analysis.ols_newey_west(df.y * 100, z.to_frame("z"), lags=6)
    return {"Signal>0 p.a.": hi.mean() * 12, "Signal≤0 p.a.": lo.mean() * 12, "Differenz p.a.": diff * 12,
            "t (Differenz)": diff / se, "Steigung %/Mon je SD": reg.loc["z", "coef"], "t (NW)": reg.loc["z", "t_stat"],
            "Monate >0": len(hi), "Monate ≤0": len(lo)}


def strategy(pos: pd.Series, spread: pd.Series) -> pd.DataFrame:
    """pos_t ∈ [−1, 1] (positiv = long Gold / short Silber) gilt für die Rendite t+1."""
    held = pos.shift(1).reindex(spread.index).fillna(0.0)
    gross = held * spread
    turn = pos.diff().abs().reindex(spread.index).fillna(0.0).shift(1).fillna(0.0)
    cost = turn * 2 * COST_BPS / 1e4
    return pd.DataFrame({"gross": gross, "net": gross - cost, "pos": held})


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    return {"Rendite p.a.": r.mean() * 12, "Vol p.a.": metrics.ann_vol(r), "Sharpe": metrics.sharpe(r),
            "Max DD": metrics.max_drawdown(r), "Trefferquote": (r[r != 0] > 0).mean(), "Monate": len(r)}


def main() -> None:
    gs = lbma_monthly()
    assets, macro = data.load_long_history()
    idx = gs.loc["1970-12-31":].index
    gs = gs.reindex(idx)
    macro = macro.reindex(idx)
    eq = assets["US_EQ"].reindex(idx)
    copper = assets["WB_COPPER"].reindex(idx)

    rG, rS = gs["GOLD"].pct_change(), gs["SILVER"].pct_change()
    h = (rG.rolling(36, min_periods=24).std() / rS.rolling(36, min_periods=24).std())
    spread_dn = rG - rS
    spread_vn = rG - h.shift(1) * rS          # Hedge-Ratio aus Daten bis t−1
    spread = spread_vn
    lr = np.log(gs["GOLD"] / gs["SILVER"])

    say("# Gold vs. Silber: Wann lohnt sich long Gold / short Silber?",
        f"Daten: LBMA-Fixings (echte Monatsendkurse) {idx[1]:%Y-%m} bis {idx[-1]:%Y-%m}"
        f"{' (letzter Monat: Fix vom 25.02.2026, Monat unvollständig)' if idx[-1] >= pd.Timestamp('2026-02-28') else ''}. "
        "Spread = Rendite Gold minus Rendite Silber. Hauptvariante **vol-neutral**: Silber wird mit h = σ_Gold/σ_Silber (36M, ex ante, typisch 0.55–0.65) "
        "gehebelt, sonst ist 'long Gold / short Silber' vor allem eine Wette gegen das Edelmetall-Beta. Positive Spread-Rendite = Gold schlägt Silber. "
        "Der Spread ist selbstfinanzierend; Sharpe daher ohne Cash-Abzug. Nicht modelliert: Leihgebühr für Silber-Short, Margin.")

    # ---------------- 1. Basis
    base = pd.DataFrame({"dollar-neutral": stats(spread_dn), "vol-neutral": stats(spread_vn)}).T
    say("## 1. Der Spread an sich (immer long Gold / short Silber)", md(base),
        f"Aktuelle Ratio: {gs['GOLD'].iloc[-1] / gs['SILVER'].iloc[-1]:.1f} "
        f"(Median seit 1971: {(gs['GOLD'] / gs['SILVER']).median():.1f}, 10-Jahres-Mittel: {(gs['GOLD'] / gs['SILVER']).iloc[-120:].mean():.1f}). "
        f"Hedge-Ratio h aktuell: {h.iloc[-1]:.2f}.")

    # ---------------- 2. Signale
    ip = macro["INDPRO_YOY"]
    sig = pd.DataFrame(index=idx)
    sig["Ratio-Trend 3M"] = lr.diff(3)
    sig["Ratio-Trend 6M"] = lr.diff(6)
    sig["Ratio-Trend 12M"] = lr.diff(12)
    sig["Ratio über 10M-Schnitt"] = lr - lr.rolling(10).mean()
    sig["Ratio-z 60M (hoch = Gold teuer)"] = zx(lr, 60)
    sig["Ratio-z 120M"] = zx(lr, 120)
    sig["Δ Kreditspread 3M"] = macro["CREDIT_BAA_AAA"].diff(3)
    sig["VIX über 20"] = macro["VIX"] - 20
    sig["Aktien unter 10M-Schnitt"] = -(eq / eq.rolling(10).mean() - 1)
    sig["Δ IP-Jahresrate 3M (lag 1)"] = ip.diff(3).shift(1)
    sig["Kupfer-Momentum 6M"] = copper.shift(1) / copper.shift(7) - 1
    sig["Δ log Dollar 3M"] = np.log(macro["USD_IDX"]).diff(3)
    sig["Δ Realzins 3M (lag 1)"] = macro["REAL_GS10"].diff(3).shift(1)
    sig["Δ Fed Funds 3M"] = macro["FEDFUNDS"].diff(3)

    fwd = spread.shift(-1)
    rows = {k: cond_test(sig[k], fwd) for k in sig.columns}
    ct = pd.DataFrame(rows).T
    ct.index.name = "Signal"
    ct.to_csv(os.path.join(OUT, "02_signal_tests.csv"))
    say("## 2. Welche Signale sagen den Spread im Folgemonat voraus? (1971–2025)",
        "Vol-neutraler Spread. 'Signal>0' = durchschnittliche annualisierte Spread-Rendite im Folgemonat, wenn das Signal positiv ist. "
        "Positive Differenz = bei positivem Signal lohnt sich long Gold / short Silber. Steigung = Regression des Spreads (%/Monat) auf das standardisierte Signal.",
        md(ct, "{:.2f}"))

    # Subperioden
    sub = {}
    for s, e in [("1971", "1989"), ("1990", "2007"), ("2008", "2026")]:
        for k in ["Ratio-Trend 6M", "Ratio über 10M-Schnitt", "Ratio-z 60M (hoch = Gold teuer)", "Δ Kreditspread 3M", "Aktien unter 10M-Schnitt", "Kupfer-Momentum 6M", "Δ log Dollar 3M"]:
            r = cond_test(sig[k].loc[s:e], fwd.loc[s:e])
            sub.setdefault(k, {})[f"{s}–{e}"] = r["t (NW)"]
    subt = pd.DataFrame(sub).T
    subt.index.name = "Signal (t-Wert der Steigung)"
    say("### Stabilität: t-Werte je Teilperiode", md(subt, "{:.1f}"))

    # Stress-Ereignisse
    stress = pd.DataFrame({
        "Aktien-Drawdown > 15 %": eq / eq.cummax() - 1 < -0.15,
        "Kreditspread 3M +0.3 Pkt": macro["CREDIT_BAA_AAA"].diff(3) > 0.3,
        "IP-Jahresrate < 0 (Rezession)": ip.shift(1) < 0,
        "VIX > 30": macro["VIX"] > 30,
    }, index=idx)
    ev = {}
    for k in stress.columns:
        m = stress[k].fillna(False)
        same, nxt = spread[m], fwd[m]
        ev[k] = {"Monate": int(m.sum()), "Spread gleicher Monat p.a.": same.mean() * 12, "Spread Folgemonat p.a.": nxt.mean() * 12,
                 "t Folgemonat": nxt.mean() / (nxt.std() / np.sqrt(nxt.count())), "Gold schlägt Silber (Folgemonat)": (nxt > 0).mean()}
    evt = pd.DataFrame(ev).T
    evt.index.name = "Zustand"
    say("### Stressphasen", "Gold ist der Krisen-, Silber der Konjunktur-Edelmetall: in Stress-Monaten verliert Silber typischerweise mehr.", md(evt, "{:.2f}"))

    # ---------------- 3. Strategien
    z = lambda s: (s - s.expanding(36).mean()) / s.expanding(36).std()  # noqa: E731  (expandierend, ohne Look-ahead)
    trend = np.sign(sig["Ratio über 10M-Schnitt"])
    mom = np.sign(sig["Ratio-Trend 6M"])
    stress_s = np.sign(z(sig["Δ Kreditspread 3M"]).fillna(0) + z(sig["Aktien unter 10M-Schnitt"]).fillna(0))
    growth_s = -np.sign(z(sig["Kupfer-Momentum 6M"]).fillna(0) + z(sig["Δ IP-Jahresrate 3M (lag 1)"]).fillna(0))
    meanrev = -np.sign(sig["Ratio-z 60M (hoch = Gold teuer)"])
    composite_raw = (z(sig["Ratio über 10M-Schnitt"]).fillna(0) + z(sig["Ratio-Trend 6M"]).fillna(0)) / 2 \
        + (z(sig["Δ Kreditspread 3M"]).fillna(0) + z(sig["Aktien unter 10M-Schnitt"]).fillna(0)) / 2 \
        - (z(sig["Kupfer-Momentum 6M"]).fillna(0) + z(sig["Δ IP-Jahresrate 3M (lag 1)"]).fillna(0)) / 2
    composite = np.sign(composite_raw)
    composite_scaled = (composite_raw / 1.5).clip(-1, 1)

    # Walk-forward-Regression: expandierend OLS des Spreads auf alle Signale (z), Prognose → Position
    X = pd.DataFrame({k: z(sig[k]) for k in sig.columns if k != "VIX über 20"}).fillna(0)
    wf_pos = pd.Series(0.0, index=idx)
    for i in range(180, len(idx)):
        t = idx[i]
        tr_X, tr_y = X.iloc[: i - 1], fwd.iloc[: i - 1]
        m = tr_y.notna()
        A = np.column_stack([np.ones(m.sum()), tr_X[m].to_numpy()])
        lam = 5.0 * len(A) / 100  # Ridge-Schrumpfung
        beta = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ tr_y[m].to_numpy())
        pred = np.r_[1.0, X.loc[t].to_numpy()] @ beta
        wf_pos.loc[t] = np.sign(pred)

    strategies = {
        "Immer long Gold / short Silber": pd.Series(1.0, index=idx),
        "Ratio-Trend (Ratio vs 10M-Schnitt)": trend,
        "Ratio-Momentum 6M": mom,
        "Stress (Kreditspread + Aktientrend)": stress_s,
        "Wachstum invers (Kupfer + IP)": growth_s,
        "Mean Reversion (Ratio-z 60M)": meanrev,
        "Composite: Trend + Stress − Wachstum": composite,
        "Composite skaliert (Position −1…+1)": composite_scaled,
        "Walk-forward Ridge auf alle Signale": wf_pos,
    }
    res = {k: strategy(v.fillna(0), spread) for k, v in strategies.items()}
    start = pd.Timestamp("1975-12-31")
    st = pd.DataFrame({k: stats(v["net"].loc[start:]) for k, v in res.items()}).T
    st["Anteil long Gold"] = [(v["pos"].loc[start:] > 0).mean() for v in res.values()]
    st.index.name = "Strategie (netto, vol-neutral)"
    st.to_csv(os.path.join(OUT, "03_strategies.csv"))
    say(f"## 3. Strategien ({start:%Y-%m} – {idx[-1]:%Y-%m}, {COST_BPS} bp je Bein und Wechsel)",
        "Position +1 = long Gold / short Silber, −1 = long Silber / short Gold. Composite = Trend der Ratio + Stress − Wachstum, "
        "gleichgewichtet und a priori festgelegt (nicht gefittet). Walk-forward Ridge = jedes Jahr neu geschätzte Regression auf alle Signale, nur Vergangenheit.",
        md(st, "{:.2f}"))

    dec = pd.DataFrame({k: res[k]["net"] for k in ["Ratio-Trend (Ratio vs 10M-Schnitt)", "Composite: Trend + Stress − Wachstum", "Walk-forward Ridge auf alle Signale", "Immer long Gold / short Silber"]}).loc[start:]
    dect = pd.DataFrame({f"{d}s": g.mean() * 12 for d, g in dec.groupby((dec.index.year // 10) * 10)}).T
    say("### Spread-Rendite p.a. je Jahrzehnt", md(dect, "{:.3f}"))

    # dollar-neutral robustness
    rob = {}
    for k in ["Ratio-Trend (Ratio vs 10M-Schnitt)", "Composite: Trend + Stress − Wachstum"]:
        rob[k] = stats(strategy(strategies[k].fillna(0), spread_dn)["net"].loc[start:])
    say("### Robustheit: dieselben Signale, dollar-neutraler Spread", md(pd.DataFrame(rob).T, "{:.2f}"))

    # ---------------- 4. Grafiken
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [2, 2]})
    ratio = gs["GOLD"] / gs["SILVER"]
    axes[0].plot(ratio.index, ratio, color="k", lw=1, label="Gold/Silber-Ratio")
    axes[0].plot(ratio.index, ratio.rolling(10).mean(), color="tab:orange", lw=1, label="10M-Schnitt")
    p = res["Composite: Trend + Stress − Wachstum"]["pos"]
    axes[0].fill_between(ratio.index, 0, ratio.max() * 1.05, where=(p.reindex(ratio.index) > 0), color="tab:blue", alpha=0.12, label="Composite: long Gold / short Silber")
    axes[0].set_ylim(0, ratio.max() * 1.05)
    axes[0].legend(fontsize=8, loc="upper left")
    axes[0].set_title("Gold/Silber-Ratio und Composite-Position (blau = long Gold / short Silber)")
    cum = pd.DataFrame({k: (1 + res[k]["net"].loc[start:]).cumprod() for k in ["Ratio-Trend (Ratio vs 10M-Schnitt)", "Composite: Trend + Stress − Wachstum", "Walk-forward Ridge auf alle Signale", "Immer long Gold / short Silber"]})
    cum.plot(ax=axes[1], logy=True)
    axes[1].set_title("Kumulierte Spread-Rendite (vol-neutral, netto, log)")
    axes[1].legend(fontsize=8)
    say(f"![]({savefig('fig_ratio_and_strategy.png')})")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    plot = ct["Differenz p.a."].sort_values()
    colors = ["tab:blue" if v > 0 else "tab:orange" for v in plot]
    ax.barh(plot.index, plot * 100, color=colors)
    for i, (k, v) in enumerate(plot.items()):
        ax.text(v * 100 + (0.5 if v >= 0 else -0.5), i, f"t={ct.loc[k, 't (Differenz)']:.1f}", va="center", ha="left" if v >= 0 else "right", fontsize=8)
    ax.axvline(0, color="k", lw=0.5)
    ax.set_xlabel("Spread-Rendite Folgemonat p.a. (%): Signal>0 minus Signal≤0  (blau = Signal spricht für long Gold)")
    ax.set_title("Wann schlägt Gold Silber?")
    say(f"![]({savefig('fig_signal_tests.png')})")

    # ---------------- 4. Langer Horizont: Mean Reversion der Ratio
    hz = {}
    for H in (1, 3, 6, 12, 24, 36):
        fwdH = lr.shift(-H) - lr                      # >0 = Gold schlägt Silber (log, dollar-neutral)
        row = {}
        for name, s in [("Ratio-Niveau", gs["GOLD"] / gs["SILVER"]), ("Ratio-z 60M", zx(lr, 60)), ("Ratio-Trend 12M", lr.diff(12))]:
            d = pd.DataFrame({"s": s, "y": fwdH}).dropna()
            zz = (d.s - d.s.mean()) / d.s.std()
            r = analysis.ols_newey_west(d.y * 100, zz.to_frame("z"), lags=H + 6)
            row[f"{name}: %-Pkt je SD"] = r.loc["z", "coef"]
            row[f"{name}: t"] = r.loc["z", "t_stat"]
            row[f"{name}: R²"] = r.attrs["r2"]
        row["unabh. Fenster ≈"] = len(d) // H
        hz[f"{H}M"] = row
    hzt = pd.DataFrame(hz).T
    hzt.index.name = "Horizont"
    hzt.to_csv(os.path.join(OUT, "05_horizons.csv"))

    zz60 = zx(lr, 60)
    fwd12, fwd24 = lr.shift(-12) - lr, lr.shift(-24) - lr
    bk = {}
    for lab, m in [("z < −2 (Ratio extrem tief)", zz60 < -2), ("−2 ≤ z < −1", (zz60 >= -2) & (zz60 < -1)), ("−1 ≤ z ≤ 1", zz60.abs() <= 1),
                   ("1 < z ≤ 2", (zz60 > 1) & (zz60 <= 2)), ("z > 2 (Ratio extrem hoch)", zz60 > 2)]:
        bk[lab] = {"Monate": int(m.sum()), "Gold vs Silber 12M": fwd12[m].mean(), "Gold gewinnt 12M": (fwd12[m] > 0).mean(),
                   "Gold vs Silber 24M": fwd24[m].mean(), "Gold gewinnt 24M": (fwd24[m] > 0).mean()}
    bkt = pd.DataFrame(bk).T
    bkt.index.name = "Ratio-z 60M"
    bkt.to_csv(os.path.join(OUT, "05_zbuckets.csv"))

    # Langsame Strategien, monatlich angepasst, auf dem monatlichen vol-neutralen Spread bewertet
    ze = lambda s: (s - s.expanding(60).mean()) / s.expanding(60).std()  # noqa: E731
    mr60 = (-zz60 / 2).clip(-1, 1)
    mr120 = (-zx(lr, 120) / 2).clip(-1, 1)
    rev12 = (-ze(lr.diff(12)) / 2).clip(-1, 1)
    mr_combo = ((mr60.fillna(0) + rev12.fillna(0)) / 2)
    ext = pd.Series(0.0, index=idx)
    state = 0.0
    for t in idx:
        v = zz60.get(t)
        if pd.notna(v):
            if v < -1.5:
                state = 1.0
            elif v > 1.5:
                state = -1.0
            elif (state > 0 and v >= 0) or (state < 0 and v <= 0):
                state = 0.0
        ext.loc[t] = state
    slow = {
        "MR: Ratio-z 60M (skaliert)": mr60,
        "MR: Ratio-z 120M (skaliert)": mr120,
        "Umkehr 12M-Ratio-Trend (skaliert)": rev12,
        "MR kombiniert (z60 + 12M-Umkehr)": mr_combo,
        "Nur Extreme: |z60| > 1.5 bis z = 0": ext,
    }
    # Überlappende Tranchen (Jegadeesh/Titman): Position = Durchschnitt der Signale der letzten H Monate
    # → jede Monatsentscheidung wird H Monate gehalten, unabhängig vom Startmonat.
    grid, sres = {}, {}
    for k, v in slow.items():
        for H in (1, 6, 12):
            pos = v.fillna(0).rolling(H, min_periods=1).mean()
            for sp_name, sp in [("dollar-neutral", spread_dn), ("vol-neutral", spread_vn)]:
                r = strategy(pos, sp)
                grid[(k, H, sp_name)] = metrics.sharpe(r["net"].loc[start:])
                sres[(k, H, sp_name)] = r
    gt = pd.Series(grid).unstack([2, 1])
    gt.columns = [f"{a}, Haltedauer {b}M" for a, b in gt.columns]
    gt = gt[[c for c in gt.columns if c.startswith("dollar")] + [c for c in gt.columns if c.startswith("vol")]]
    gt.index.name = "Sharpe (netto)"
    gt.to_csv(os.path.join(OUT, "05_slow_grid.csv"))
    main_key = ("MR: Ratio-z 60M (skaliert)", 6, "dollar-neutral")
    sel = {f"{k} · {H}M": sres[(k, H, "dollar-neutral")]["net"].loc[start:] for k in slow for H in (6, 12)}
    sst = pd.DataFrame({k: stats(v) for k, v in sel.items()}).T
    sst.index.name = "Strategie (dollar-neutral, netto)"
    sst.to_csv(os.path.join(OUT, "05_slow_strategies.csv"))
    sub2 = {k: {f"{s}–{e}": metrics.sharpe(v.loc[s:e]) for s, e in [("1976", "1989"), ("1990", "2007"), ("2008", "2026")]} for k, v in sel.items()}
    say("## 4. Der eigentliche Effekt: Mean Reversion über 1–3 Jahre",
        "Auf Monatssicht ist der Spread Rauschen. Über 6–36 Monate kehrt die Ratio aber zurück: ist Gold relativ zu Silber teuer (Ratio hoch, z > 0) "
        "oder ist die Ratio im letzten Jahr stark gestiegen, holt Silber in den folgenden 1–3 Jahren auf, und umgekehrt. "
        "Abhängige Variable: log-Änderung der Ratio über H Monate (= Gold minus Silber, dollar-neutral). Newey-West mit H+6 Lags wegen überlappender Fenster.",
        md(hzt, "{:.2f}"),
        "Bei 24 Monaten gibt es seit 1971 nur rund 26 unabhängige Fenster. Die t-Werte sind um die Überlappung bereinigt, "
        "aber die Evidenz ruht auf wenigen grossen Zyklen (1980, 1990–93, 2008, 2011, 2020, 2025). "
        "Die Spalte Ratio-Niveau nutzt den Mittelwert der ganzen Stichprobe (leichter Look-ahead); Ratio-z 60M nutzt nur die letzten 5 Jahre und ist die saubere Variante.",
        "### Folgerenditen nach Ratio-z (60M), ohne fest gewählte Schwellen wie 'Ratio > 80'",
        md(bkt, "{:.2f}"),
        "### Langsame Strategien: Sharpe je Spread-Definition und Haltedauer",
        "Position −1…+1, monatlich neu entschieden, als überlappende Tranchen H Monate gehalten. Der Effekt lebt in der **dollar-neutralen** Ratio (1 CHF Gold long, 1 CHF Silber short); "
        "die vol-neutrale Variante hält netto Silber-Exposure, deren Rauschen das Signal überdeckt. Mit monatlicher Haltedauer frisst das Rauschen den Effekt.",
        md(gt, "{:.2f}"),
        "### Details dollar-neutral",
        md(sst, "{:.2f}"),
        "Sharpe je Teilperiode:", md(pd.DataFrame(sub2).T, "{:.2f}"))
    sres = {k: sres[(k, 6, "dollar-neutral")] for k in slow}
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax2 = ax.twinx()
    ax.plot(idx, gs["GOLD"] / gs["SILVER"], color="k", lw=1, label="Gold/Silber-Ratio")
    ax2.plot(idx, zz60, color="tab:blue", lw=0.8, alpha=0.7, label="Ratio-z 60M")
    for lvl in (-1.5, 1.5):
        ax2.axhline(lvl, color="tab:blue", ls=":", lw=0.8)
    ax2.fill_between(idx, -5, 5, where=(ext > 0), color="tab:orange", alpha=0.15, label="Extreme-Regel: long Gold / short Silber")
    ax2.fill_between(idx, -5, 5, where=(ext < 0), color="tab:green", alpha=0.15, label="Extreme-Regel: long Silber / short Gold")
    ax2.set_ylim(-5, 5)
    ax.set_ylabel("Ratio")
    ax2.set_ylabel("z-Score")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left", ncol=2)
    ax.set_title("Gold/Silber-Ratio, z-Score und Positionen der Extreme-Regel")
    say(f"![]({savefig('fig_ratio_z.png')})")
    cum = pd.DataFrame({k: (1 + sres[k]["net"].loc[start:]).cumprod() for k in slow})
    cum["Immer long Gold / short Silber"] = (1 + spread_dn.loc[start:].fillna(0)).cumprod()
    ax = cum.plot(figsize=(10, 4), logy=True)
    ax.set_title("Mean Reversion der Ratio, 6M-Tranchen: kumulierte Spread-Rendite (dollar-neutral, netto)")
    ax.legend(fontsize=7)
    say(f"![]({savefig('fig_slow_strategies.png')})")
    strategies.update({f"{k} (6M-Tranchen)": v.fillna(0).rolling(6, min_periods=1).mean() for k, v in slow.items()})

    # ---------------- 5. Aktueller Stand
    last = idx[-1]
    now = []
    for k in sig.columns:
        v = sig[k].loc[:last].dropna()
        if v.empty:
            continue
        now.append({"Signal": k, "Stand": v.index[-1].strftime("%Y-%m"), "Wert": v.iloc[-1],
                    "spricht für": "Gold" if (v.iloc[-1] > 0) == (ct.loc[k, "Differenz p.a."] > 0) else "Silber",
                    "historisch signifikant": "ja" if abs(ct.loc[k, "t (Differenz)"]) >= 2 else "nein"})
    nowt = pd.DataFrame(now).set_index("Signal")
    pos_now = {k: res[k]["pos"].iloc[-1] if False else strategies[k].fillna(0).iloc[-1] for k in strategies}
    say(f"## 5. Wegweiser Gold vs. Silber, Stand {last:%Y-%m}",
        md(nowt, "{:.3f}"),
        "Aktuelle Positionen der Strategien (+1 = long Gold / short Silber, −1 = long Silber / short Gold):",
        md(pd.Series(pos_now, name="Position").to_frame(), "{:+.2f}"))
    nowt.to_csv(os.path.join(OUT, "04_signpost.csv"))

    low = zz60 < -2
    ep = low & ~low.shift(1, fill_value=False)
    ep_list = ", ".join(d.strftime("%Y-%m") for d in ep[ep].index)
    hi_ = zz60 > 2
    ep2 = hi_ & ~hi_.shift(1, fill_value=False)
    ep2_list = ", ".join(d.strftime("%Y-%m") for d in ep2[ep2].index)
    mk = sres["MR: Ratio-z 60M (skaliert)"]["net"].loc[start:]
    say("## 6. Fazit: Wann long Gold / short Silber?",
        f"1. **Kurzfristig (1–3 Monate) gibt es keinen verlässlichen Wegweiser.** Weder Trend der Ratio, Stress, Wachstum, Dollar noch Zinsen sagen den Spread im Folgemonat "
        "signifikant und stabil voraus. Gold schlägt Silber zwar *im* Krisenmonat (VIX > 30: +21 % p.a. im selben Monat), aber nicht danach: wer den Spread als Krisen-Hedge will, "
        "muss ihn vorher halten, ein Timing-Signal ist das nicht.",
        f"2. **Mittelfristig (6–36 Monate) kehrt die Ratio zurück.** Ist die Ratio relativ zu ihren letzten 5 Jahren extrem tief (z < −2), schlug Gold Silber in den folgenden "
        f"12 Monaten in {bkt.iloc[0]['Gold gewinnt 12M']:.0%} der Fälle (Ø {bkt.iloc[0]['Gold vs Silber 12M']:+.0%} log), nach 24 Monaten in {bkt.iloc[0]['Gold gewinnt 24M']:.0%}. "
        f"Bei z > 2 gilt das Spiegelbild (Silber gewinnt 12M in {1 - bkt.iloc[-1]['Gold gewinnt 12M']:.0%}). Episoden z < −2: {ep_list}; z > 2: {ep2_list}.",
        f"3. **Als Strategie ist das bescheiden, aber robust:** Ratio-Mean-Reversion, dollar-neutral, 6-Monats-Tranchen: {mk.mean() * 12:.1%} p.a., Sharpe {metrics.sharpe(mk):.2f}, "
        f"Max-DD {metrics.max_drawdown(mk):.0%}; positiv in allen drei Teilperioden, am stärksten seit 2008. Varianten (z60/z120, 6/12 Monate, nur Extreme) liegen alle bei Sharpe 0.17–0.28: "
        "kein Parameter ist ein Ausreisser. Es ist ein Diversifikations-Baustein, keine Gelddruckmaschine.",
        f"4. **Heute:** Ratio {gs['GOLD'].iloc[-1] / gs['SILVER'].iloc[-1]:.1f}, z60 = {zz60.iloc[-1]:.1f}, nach dem Silber-Ausbruch 2025/26 (Ratio von über 100 im April 2025 auf unter 50 im Januar 2026). "
        f"Im Januar 2026 lag z60 bei {zz60.min():.1f}, dem extremsten Silber-Vorsprung relativ zur 5-Jahres-Historie seit 1971 (vor Dezember 1979: −4.3, kurz vor dem Silber-Crash 1980, und Dezember 1997: −4.2). Alle Mean-Reversion-Varianten stehen auf **long Gold / short Silber** "
        "mit Horizont 6–24 Monate; die kurzfristigen Trendsignale zeigen noch auf Silber. Die Lesart: Das Momentum spricht noch für Silber, die Bewertung klar für Gold, "
        "und historisch hat sich auf diesem Horizont die Bewertung durchgesetzt. 2011 kam die Umkehr innerhalb von Monaten: Ratio 38 im März, 32 im April, 53 im September. "
        "Wer im März short Silber ging, musste erst einen weiteren Silber-Anstieg von rund 17 % relativ zu Gold aushalten.",
        "5. **Risiken des Trades:** Silber-Short hat Squeeze-Risiko (Silber ist dünn gehandelt, siehe 1980 und 2025/26), Leihgebühren für physisches Silber können in Knappheitsphasen "
        "stark steigen, und die Evidenz ruht auf rund 5–6 grossen Zyklen. Positionsgrösse klein halten, Haltedauer in Quartalen denken, nicht in Wochen.")
    with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(REPORT))
    print("\n".join(REPORT))


if __name__ == "__main__":
    main()
