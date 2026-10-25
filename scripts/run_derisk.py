"""Gold/Silber als De-Risk-Indikator: Zusammenspiel von Ratio und Risikoappetit.

Risikoappetit-Index (am Monatsende t bekannt), Mittelwert expandierender z-Scores (ohne Look-ahead):
  + Aktien-Momentum 12M (S&P TR)        + Aktien vs. 10M-Schnitt
  − Baa−Aaa-Kreditspread                − Kreditspread-Änderung 6M
  − VIX (ab 1990; davor ausgelassen)
Hoch = Risk-on / Sorglosigkeit, tief = Angst.

Fragen
  1. Hedge: Wie verhält sich der Spread (Gold − Silber, dollar-neutral) in De-Risk-Monaten/-Phasen?
  2. Prognose: Folgt auf hohen Risikoappetit ein Gold-Vorsprung (12M) und ein Aktien-Drawdown?
  3. Kombination: Ratio-z × Risikoappetit (Doppelsortierung, Regression mit Interaktion).
  4. Umgekehrt: Kündigt ein steigender Spread selbst Aktienschwäche an?

Aufruf: python scripts/run_derisk.py → output/gold_silver/DERISK.md
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from run_gold_silver import lbma_monthly, zx  # noqa: E402
from src import analysis, data, metrics  # noqa: E402

OUT = os.path.join(ROOT, "output", "gold_silver")
REP: list[str] = []


def say(*p: str) -> None:
    REP.extend(p)
    REP.append("")


def md(df: pd.DataFrame, fmt: str = "{:.2f}") -> str:
    head = [df.index.name or ""] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for i, row in df.iterrows():
        cells = ["" if (isinstance(v, float) and np.isnan(v)) else (fmt.format(v) if isinstance(v, (float, np.floating)) else str(v)) for v in row]
        lines.append("| " + " | ".join([str(i)] + cells) + " |")
    return "\n".join(lines)


def ez(s: pd.Series, mp: int = 60) -> pd.Series:
    return (s - s.expanding(mp).mean()) / s.expanding(mp).std()


def main() -> None:
    gs = lbma_monthly().loc["1970-12-31":]
    assets, macro = data.load_long_history()
    idx = gs.index
    macro = macro.reindex(idx)
    eq = assets["US_EQ"].reindex(idx)
    cash = assets["TBILL"].pct_change().reindex(idx)
    lr = np.log(gs["GOLD"] / gs["SILVER"])
    spread = lr.diff()                                   # ≈ r_Gold − r_Silber
    req = eq.pct_change()
    z60 = zx(lr, 60)

    comps = pd.DataFrame({
        "Aktien-Mom 12M": ez(eq / eq.shift(12) - 1),
        "Aktien vs 10M": ez(eq / eq.rolling(10).mean() - 1),
        "−Kreditspread": -ez(macro["CREDIT_BAA_AAA"]),
        "−ΔKreditspread 6M": -ez(macro["CREDIT_BAA_AAA"].diff(6)),
        "−VIX": -ez(macro["VIX"], 36),
    }, index=idx)
    risk = comps.mean(axis=1, skipna=True).where(comps.notna().sum(axis=1) >= 3)
    risk.name = "Risikoappetit"

    fwd = {H: lr.shift(-H) - lr for H in (3, 6, 12, 24)}
    eq_dd_next12 = pd.Series([(eq.iloc[i:i + 13] / eq.iloc[i]).min() - 1 if i + 12 < len(eq) else np.nan for i in range(len(eq))], index=idx)
    eq_fwd12 = eq.shift(-12) / eq - 1

    say("# Gold/Silber als De-Risk-Indikator",
        f"Monatsdaten {idx[1]:%Y-%m} bis {idx[-1]:%Y-%m}. Spread = log-Änderung der Gold/Silber-Ratio = Gold minus Silber (dollar-neutral). "
        "Risikoappetit = Durchschnitt expandierender z-Scores aus Aktien-Momentum, Aktientrend, Kreditspread (Niveau und 6M-Änderung, invertiert) und VIX "
        "(invertiert, ab 1990). Hoch = Risk-on/Sorglosigkeit, tief = Angst. Alles ohne Look-ahead.")

    # ---------------- 1. Hedge-Eigenschaft
    bins = pd.cut(req, [-1, -0.10, -0.05, -0.02, 0.02, 0.05, 1], labels=["< −10 %", "−10…−5 %", "−5…−2 %", "−2…+2 %", "+2…+5 %", "> +5 %"])
    h = pd.DataFrame({"r": req, "s": spread, "g": gs["GOLD"].pct_change(), "si": gs["SILVER"].pct_change(), "b": bins}).dropna()
    ht = h.groupby("b", observed=True).agg(Monate=("s", "size"), Aktien=("r", "mean"), Gold=("g", "mean"), Silber=("si", "mean"),
                                          Spread=("s", "mean"), Gold_schlägt_Silber=("s", lambda x: (x > 0).mean()))
    ht.index.name = "Aktienmonat"
    say("## 1. Hedge: Was macht der Spread, wenn Aktien fallen? (gleicher Monat)",
        "Durchschnittliche Monatsrendite je Aktienmonat-Klasse.", md(ht, "{:.3f}"))
    down = h[h.r < -0.05]
    beta_all = np.polyfit(h.r, h.s, 1)[0]
    beta_down = np.polyfit(down.r, down.s, 1)[0]
    say(f"Beta des Spreads auf Aktien: gesamt {beta_all:.2f}, in Monaten mit Aktien < −5 %: {beta_down:.2f} "
        "(negativ = Spread steigt, wenn Aktien fallen = Hedge).")

    # Phasen: grosse Aktien-Drawdowns, Spread vom Hoch bis zum Tief
    dd = eq / eq.cummax() - 1
    episodes = []
    in_ep, peak_d = False, None
    for d in idx:
        if not in_ep and dd.loc[d] < -0.15:
            in_ep = True
            peak_d = eq.loc[:d].idxmax()
        if in_ep and dd.loc[d] >= -0.02:
            trough_d = eq.loc[peak_d:d].idxmin()
            episodes.append((peak_d, trough_d))
            in_ep = False
    if in_ep:
        episodes.append((peak_d, eq.loc[peak_d:].idxmin()))
    ep_rows = {}
    for p, t in episodes:
        ep_rows[f"{p:%Y-%m} → {t:%Y-%m}"] = {"Aktien": eq.loc[t] / eq.loc[p] - 1, "Gold": gs["GOLD"].loc[t] / gs["GOLD"].loc[p] - 1,
                                              "Silber": gs["SILVER"].loc[t] / gs["SILVER"].loc[p] - 1, "Spread (log)": lr.loc[t] - lr.loc[p],
                                              "Ratio Start": np.exp(lr.loc[p]), "Ratio Tief Aktien": np.exp(lr.loc[t])}
    ept = pd.DataFrame(ep_rows).T
    ept.index.name = "Aktien-Drawdown > 15 % (Hoch → Tief)"
    say("### Grosse Aktien-Drawdowns: Gold vs. Silber vom Aktien-Hoch bis zum Aktien-Tief", md(ept, "{:.2f}"),
        f"Spread positiv in {(ept['Spread (log)'] > 0).sum()} von {len(ept)} Episoden, Median {ept['Spread (log)'].median():+.0%}.")

    # ---------------- 2. Prognose durch Risikoappetit
    rq = pd.qcut(risk.rank(method="first"), 5, labels=["Q1 Angst", "Q2", "Q3", "Q4", "Q5 Sorglos"])
    rows = {}
    for q in rq.cat.categories:
        m = rq == q
        rows[q] = {"Monate": int(m.sum()), "Spread 3M": fwd[3][m].mean(), "Spread 12M": fwd[12][m].mean(),
                   "Gold gewinnt 12M": (fwd[12][m] > 0).mean(), "Aktien 12M": eq_fwd12[m].mean(),
                   "P(Aktien-DD > 10 % in 12M)": (eq_dd_next12[m] < -0.10).mean()}
    rt = pd.DataFrame(rows).T
    rt.index.name = "Risikoappetit-Quintil"
    rt.to_csv(os.path.join(OUT, "derisk_quintiles.csv"))
    say("## 2. Kündigt hoher Risikoappetit einen Gold-Vorsprung an?",
        "Quintile des Risikoappetit-Index über die ganze Stichprobe (zur Einteilung; der Index selbst ist ohne Look-ahead).", md(rt, "{:.2f}"))
    reg_rows = {}
    for H in (3, 6, 12, 24):
        d = pd.DataFrame({"y": fwd[H] * 100, "risk": risk}).dropna()
        r = analysis.ols_newey_west(d.y, ((d.risk - d.risk.mean()) / d.risk.std()).to_frame("risk"), lags=H + 6)
        reg_rows[f"{H}M"] = {"%-Pkt je SD Risikoappetit": r.loc["risk", "coef"], "t (NW)": r.loc["risk", "t_stat"], "R²": r.attrs["r2"]}
    say("Regression Spread(t→t+H) auf Risikoappetit(t):", md(pd.DataFrame(reg_rows).T.rename_axis("Horizont")))

    # ---------------- 3. Kombination
    zq = pd.cut(z60, [-10, -1, 1, 10], labels=["Ratio tief (z<−1)", "Ratio normal", "Ratio hoch (z>1)"])
    rq3 = pd.qcut(risk.rank(method="first"), 3, labels=["Angst", "neutral", "Risk-on"])
    ds = pd.DataFrame({"z": zq, "r": rq3, "y": fwd[12], "y24": fwd[24], "dd": eq_dd_next12}).dropna(subset=["z", "r"])
    piv = ds.pivot_table(index="z", columns="r", values="y", aggfunc="mean", observed=False)
    cnt = ds.pivot_table(index="z", columns="r", values="y", aggfunc="count", observed=False)
    win = ds.pivot_table(index="z", columns="r", values="y", aggfunc=lambda x: (x > 0).mean(), observed=False)
    piv.index.name = cnt.index.name = win.index.name = "12M Gold vs Silber (log)"
    say("## 3. Kombination: Ratio-Bewertung × Risikoappetit",
        "Folgende 12-Monats-Spread-Rendite (positiv = Gold schlägt Silber):", md(piv, "{:+.2f}"),
        "Anteil Gold gewinnt:", md(win, "{:.0%}"), "Anzahl Monate:", md(cnt, "{:.0f}"))
    d = pd.DataFrame({"y": fwd[12] * 100, "z": z60, "risk": risk}).dropna()
    X = pd.DataFrame({"Ratio-z": (d.z - d.z.mean()) / d.z.std(), "Risikoappetit": (d.risk - d.risk.mean()) / d.risk.std()})
    X["Interaktion"] = X["Ratio-z"] * X["Risikoappetit"]
    r = analysis.ols_newey_west(d.y, X, lags=18)
    say("Regression 12M-Spread auf Ratio-z, Risikoappetit und Interaktion (Newey-West 18 Lags):",
        md(r[["coef", "t_stat"]].rename(columns={"coef": "%-Pkt je SD", "t_stat": "t"}).rename_axis("Faktor")),
        f"R² = {r.attrs['r2']:.2f}, n = {r.attrs['n']}.")

    # Strategie: long Gold/short Silber nur wenn Ratio tief UND Risk-on; 12M-Tranchen
    ze = lambda s: (s - s.expanding(60).mean()) / s.expanding(60).std()  # noqa: E731
    sig_mr = (-z60 / 2).clip(-1, 1).fillna(0)
    sig_risk = (ze(risk) / 2).clip(-1, 1).fillna(0)        # risk-on → long Gold / short Silber
    sig_combo = ((sig_mr + sig_risk) / 2)
    sig_cond = ((z60 < -1) & (ze(risk) > 0)).astype(float) - ((z60 > 1) & (ze(risk) < 0)).astype(float)
    start = pd.Timestamp("1976-12-31")
    strat = {}
    for name, s in [("Nur Ratio-Bewertung", sig_mr), ("Nur Risikoappetit", sig_risk), ("Ratio + Risikoappetit", sig_combo),
                    ("Bedingt: Ratio tief & Risk-on (bzw. Spiegelbild)", sig_cond)]:
        pos = s.rolling(12, min_periods=1).mean()
        net = (pos.shift(1) * spread - pos.diff().abs().shift(1).fillna(0) * 2 * 10 / 1e4).loc[start:]
        strat[name] = {"Rendite p.a.": net.mean() * 12, "Vol p.a.": metrics.ann_vol(net), "Sharpe": metrics.sharpe(net),
                       "Max DD": metrics.max_drawdown(net), "Korr. zu Aktien": net.corr(req.loc[start:]),
                       "Rendite in Aktien-Monaten < −5 %": net[req.loc[start:] < -0.05].mean(), "Ø |Position|": pos.loc[start:].abs().mean()}
    st = pd.DataFrame(strat).T
    st.index.name = "Strategie (dollar-neutral, 12M-Tranchen, netto)"
    st.to_csv(os.path.join(OUT, "derisk_strategies.csv"))
    say("### Strategien", md(st, "{:.3f}"))

    # ---------------- 4. Spread als Frühwarnung für Aktien
    rows = {}
    for lab, s in [("Spread 3M gestiegen (Gold schlägt Silber)", lr.diff(3)), ("Spread 6M gestiegen", lr.diff(6))]:
        m = s > 0
        rows[lab] = {"Aktien 12M wenn ja": eq_fwd12[m].mean(), "Aktien 12M wenn nein": eq_fwd12[~m & s.notna()].mean(),
                     "P(DD>10 %) wenn ja": (eq_dd_next12[m] < -0.10).mean(), "P(DD>10 %) wenn nein": (eq_dd_next12[~m & s.notna()] < -0.10).mean()}
    d = pd.DataFrame({"y": eq_fwd12 * 100, "x": lr.diff(6)}).dropna()
    r = analysis.ols_newey_west(d.y, ((d.x - d.x.mean()) / d.x.std()).to_frame("x"), lags=18)
    say("## 4. Umgekehrt: Warnt ein steigender Gold/Silber-Spread vor Aktienschwäche?",
        md(pd.DataFrame(rows).T.rename_axis("Signal"), "{:.2f}"),
        f"Regression Aktienrendite 12M auf 6M-Spread-Änderung: {r.loc['x', 'coef']:+.1f} %-Pkt je SD, t = {r.loc['x', 't_stat']:.1f}.")

    # ---------------- Stand heute
    last_r = risk.dropna().index[-1]
    say(f"## Stand (letzte Daten: Ratio {idx[-1]:%Y-%m}, Risikoappetit {last_r:%Y-%m})",
        f"Ratio-z 60M: {z60.iloc[-1]:+.1f} · Risikoappetit-Index: {risk.loc[last_r]:+.2f} "
        f"(Perzentil seit 1971: {(risk.dropna() <= risk.loc[last_r]).mean():.0%}). "
        "Komponenten: " + ", ".join(f"{c} {comps[c].dropna().iloc[-1]:+.1f}" for c in comps.columns))

    # Grafik
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(idx, np.exp(lr), color="k", lw=1)
    axes[0].set_ylabel("Gold/Silber-Ratio")
    for p, t in episodes:
        for ax in axes:
            ax.axvspan(p, t, color="tab:red", alpha=0.12)
    axes[0].set_title("Gold/Silber-Ratio und Risikoappetit (rot = Aktien-Drawdowns > 15 %, Hoch bis Tief)")
    axes[1].plot(risk.index, risk, color="tab:blue", lw=1)
    axes[1].axhline(0, color="k", lw=0.5)
    axes[1].set_ylabel("Risikoappetit (z)")
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "fig_derisk.png"), dpi=130)
    plt.close()
    say("![](fig_derisk.png)")

    with open(os.path.join(OUT, "DERISK.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(REP))
    print("\n".join(REP))


if __name__ == "__main__":
    main()
