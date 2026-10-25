"""US-Aktien-Studie: (A) wie viel Aktien halten? (B) welche Branchen und Faktoren?

Daten (alle in data/raw, siehe data/DATA_SOURCES.md):
  ff_3_factors_monthly.csv     Kenneth French, Markt (Mkt-RF + RF) 1926-07 … 2026-07
  ff_10_industry_portfolios.csv  10 Branchen, value-weighted, 1926-07 … 2026-07
  ff5_mom_monthly.csv.gz       FF5 + Momentum 1963-07 … 2026-08
  shiller_sp500_monthly.csv    Preis, Gewinne, CPI, 10y-Rendite ab 1871 (Gewinne bis 2023-06)
  macro_monthly.csv            FRED-MD-Panel (Kreditspread, Zinskurve, Arbeitslosigkeit, IP, CPI, VIX)

Zeitkonvention: Signal am Monatsende t, Rendite im Monat t+1. Makro um 1 Monat verzögert,
Shiller-Gewinne um 4 Monate (Quartalsberichte), Arbeitslosenquote um 1 Monat.

Aufruf: python scripts/run_equity.py → output/equity/REPORT.md
"""
from __future__ import annotations

import io
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src import analysis, metrics  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "output", "equity")
os.makedirs(OUT, exist_ok=True)
REP: list[str] = []
COST_EQ_BPS = 5      # Index-ETF, je Seite
COST_IND_BPS = 10    # Sektor-ETF, je Seite


def say(*p: str) -> None:
    REP.extend(p)
    REP.append("")


def md(df: pd.DataFrame, fmt: str = "{:.2f}", index: bool = True) -> str:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(x) for x in c) for c in df.columns]
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


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------
def read_french_section(path: str, header_contains: str | None = None) -> pd.DataFrame:
    """Erster Monatsblock einer French-CSV (oder der Block nach `header_contains`)."""
    lines = open(path, encoding="latin-1").read().splitlines()
    start = 0
    if header_contains:
        start = next(i for i, l in enumerate(lines) if header_contains in l) + 1
    # Kopfzeile = erste Zeile, die mit ',' beginnt
    h = next(i for i in range(start, len(lines)) if lines[i].startswith(","))
    rows = [lines[h]]
    for l in lines[h + 1:]:
        if not l.strip() or not l.strip()[:6].isdigit() or len(l.split(",")[0].strip()) != 6:
            break
        rows.append(l)
    df = pd.read_csv(io.StringIO("\n".join(rows)), index_col=0)
    df.index = pd.to_datetime(df.index.astype(str).str.strip(), format="%Y%m") + pd.offsets.MonthEnd(0)
    df.columns = [c.strip() for c in df.columns]
    df = df.apply(pd.to_numeric, errors="coerce").replace([-99.99, -999], np.nan) / 100.0
    return df


def load() -> dict[str, pd.DataFrame | pd.Series]:
    ff3 = read_french_section(os.path.join(RAW, "ff_3_factors_monthly.csv"))
    ind = read_french_section(os.path.join(RAW, "ff_10_industry_portfolios.csv"), "Average Value Weighted Returns -- Monthly")
    f5 = pd.read_csv(os.path.join(RAW, "ff5_mom_monthly.csv.gz"), index_col=0, parse_dates=True) / 100.0
    f5.index = f5.index + pd.offsets.MonthEnd(0)
    sh = pd.read_csv(os.path.join(RAW, "shiller_sp500_monthly.csv"), parse_dates=["Date"]).set_index("Date")
    sh.index = sh.index + pd.offsets.MonthEnd(0)
    sh = sh.replace(0.0, np.nan)
    macro = pd.read_csv(os.path.join(ROOT, "data", "macro_monthly.csv"), index_col=0, parse_dates=True)
    rf = ff3["RF"]
    mkt = ff3["Mkt-RF"] + rf
    return {"ff3": ff3, "ind": ind, "f5": f5, "sh": sh, "macro": macro, "rf": rf, "mkt": mkt}


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def exp_pct(s: pd.Series, min_periods: int = 120) -> pd.Series:
    """Expandierendes Perzentil des aktuellen Werts (nur Vergangenheit inkl. t)."""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if np.isnan(vals[i]):
            continue
        hist = vals[: i + 1]
        hist = hist[~np.isnan(hist)]
        if len(hist) >= min_periods:
            out[i] = (hist < vals[i]).mean() + 0.5 * (hist == vals[i]).mean()
    return pd.Series(out, index=s.index)


def run_exposure(w: pd.Series, r: pd.Series, rf: pd.Series, cost_bps: float) -> pd.Series:
    """Exposure w_t (0..1, Rest T-Bills) gilt für Monat t+1."""
    w = w.reindex(r.index).astype(float)
    held = w.shift(1)
    cost = (w.diff().abs().shift(1).fillna(0)) * cost_bps / 1e4
    return (held * r + (1 - held) * rf - cost).dropna()


def stats(r: pd.Series, rf: pd.Series, w: pd.Series | None = None) -> dict:
    r = r.dropna()
    ex = r - rf.reindex(r.index)
    out = {"Rendite p.a.": metrics.ann_return(r), "Vol p.a.": metrics.ann_vol(r), "Sharpe": metrics.sharpe(ex),
           "Max DD": metrics.max_drawdown(r), "Calmar": metrics.calmar(r)}
    if w is not None:
        ww = w.reindex(r.index).shift(1)
        out["Ø Aktienquote"] = float(ww.mean())
        out["Wechsel p.a."] = float((ww.diff().abs() > 0.01).sum() / (len(ww) / 12))
    return out


def nw_horizon(y: pd.Series, x: pd.Series, H: int) -> dict:
    d = pd.DataFrame({"y": y, "x": x}).dropna()
    if len(d) < 60:
        return {"coef": np.nan, "t": np.nan, "R2": np.nan, "n": len(d)}
    z = (d.x - d.x.mean()) / d.x.std()
    res = analysis.ols_newey_west(d.y * 100, z.to_frame("x"), lags=max(6, H + 6))
    return {"coef": res.loc["x", "coef"], "t": res.loc["x", "t_stat"], "R2": res.attrs["r2"], "n": res.attrs["n"]}


# ===========================================================================
# Teil A: Wie viel Aktien?
# ===========================================================================
EARNINGS_LAG = 6   # Shiller-Gewinne sind quartalsweise linear interpoliert: der Monatswert enthält das Ergebnis des
                   # laufenden Quartals, das erst ~7 Wochen nach Quartalsende vorliegt → bis zu 5 Monate Vorlauf. 6 ist sicher.
CPI_LAG = 1        # CPI für Monat t erscheint Mitte t+1.
MACRO_LAG = 1      # INDPRO, UNRATE: Veröffentlichung im Folgemonat.


def signals_a(mkt: pd.Series, rf: pd.Series, sh: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    """Alle Exposure-Signale, Wert am Monatsende t aus Daten, die an t bekannt waren. Reine Funktion (Audit-Trunkierungstest)."""
    idx = mkt.index
    tr = (1 + mkt).cumprod()
    ex = mkt - rf
    sig = pd.DataFrame(index=idx)
    sig["trend_10m"] = tr / tr.rolling(10).mean() - 1
    sig["mom_12m_ex"] = (1 + ex).rolling(12).apply(np.prod, raw=True) - 1
    cpi = sh["Consumer Price Index"].shift(CPI_LAG)
    p_real = sh["SP500"] / cpi
    e_real = (sh["Earnings"] / sh["Consumer Price Index"]).shift(EARNINGS_LAG)
    cape = p_real / e_real.rolling(120, min_periods=120).mean()
    sig["cape"] = cape.reindex(idx)
    infl10 = (cpi / cpi.shift(120)) ** (1 / 10) - 1
    real10 = sh["Long Interest Rate"] / 100 - infl10
    sig["ecy"] = (1 / cape - real10).reindex(idx)                     # Excess CAPE Yield (Shiller)
    m = macro.reindex(idx)
    sig["credit_chg_6m"] = m["CREDIT_BAA_AAA"].diff(6)                # Monatsmittel, am Monatsende bekannt
    sig["curve_10y3m"] = m["CURVE_10Y3M"]
    un = m["UNRATE"].shift(MACRO_LAG)
    sig["sahm"] = un.rolling(3).mean() - un.rolling(3).mean().rolling(12).min()
    sig["ip_yoy_lag"] = m["INDPRO_YOY"].shift(MACRO_LAG)
    sig["vix"] = m["VIX"]                                             # Monatsendkurs
    return sig


def part_a(D: dict) -> dict:
    mkt, rf, sh, macro = D["mkt"], D["rf"], D["sh"], D["macro"]
    idx = mkt.index
    tr = (1 + mkt).cumprod()
    ex = mkt - rf
    sig = signals_a(mkt, rf, sh, macro)
    yr = pd.Series(idx.year, index=idx)

    say("# US-Aktien: Wie viel halten, welche Branchen und Faktoren?",
        f"Markt = Kenneth-French-Gesamtmarkt (alle US-Aktien, value-weighted, inkl. Dividenden) {idx[0]:%Y-%m} bis {idx[-1]:%Y-%m}. "
        "Signal am Monatsende t, Rendite im Monat t+1; Cash = 1-Monats-T-Bill. Makrodaten und CPI 1 Monat, Shiller-Gewinne 6 Monate verzögert (quartalsweise Interpolation, siehe docs/AUDIT_equity_study.md).",
        "## Teil A: Wie viel Aktien?")

    # ---- A1: Prognosekraft je Horizont
    fwd = {H: ((1 + ex).rolling(H).apply(np.prod, raw=True) - 1).shift(-H) for H in (1, 12, 60, 120)}
    rows = {}
    for name, label in [("trend_10m", "Trend (Abstand 10M-Schnitt)"), ("mom_12m_ex", "Momentum 12M"), ("cape", "CAPE (hoch = teuer)"),
                        ("ecy", "Excess CAPE Yield"), ("credit_chg_6m", "Δ Kreditspread 6M"), ("curve_10y3m", "Zinskurve 10y−3M"),
                        ("sahm", "Arbeitslosigkeit steigt (Sahm)"), ("vix", "VIX")]:
        row = {}
        for H in (1, 12, 60, 120):
            r = nw_horizon(fwd[H], sig[name], H)
            row[f"{H}M t"] = r["t"]
            row[f"{H}M R²"] = r["R2"]
        row["Start"] = sig[name].first_valid_index().strftime("%Y")
        rows[label] = row
    pt = pd.DataFrame(rows).T
    pt.index.name = "Signal → Überschussrendite"
    pt.to_csv(os.path.join(OUT, "A1_predictive.csv"))
    say("### A1. Was sagt die Aktien-Überschussrendite voraus? (t-Werte Newey-West, R²)",
        "Positiver t-Wert = hohes Signal → höhere Folgerendite. Horizont 1 Monat = Timing, 60/120 Monate = Erwartung für die nächsten 5/10 Jahre.",
        md(pt[["Start", "1M t", "1M R²", "12M t", "12M R²", "60M t", "60M R²", "120M t", "120M R²"]], "{:.2f}"),
        "Lesart: (1) Bewertung ist das einzige Signal mit echter Prognosekraft, und zwar umso mehr, je länger der Horizont: die Excess CAPE Yield erklärt 44 % der Varianz "
        "der 10-Jahres-Überschussrendite, aber nur 2 % des Folgemonats. (2) Trend und Momentum sagen die *durchschnittliche* Monatsrendite nicht voraus (t < 1); "
        "ihr Wert liegt im Vermeiden der grossen Verlustmonate (A5). (3) Steigende Arbeitslosigkeit ist ein *Kauf*-Signal (t = +3.3): wenn der Arbeitsmarkt kippt, "
        "ist der Kurs meist schon gefallen und die Folgerenditen sind hoch. Ein Makro-Risiko-Signal in diese Richtung einzubauen, wäre falsch. "
        "(4) Steigende Kreditspreads haben keine Prognosekraft für den Folgemonat.")

    # ---- A2: Strategien
    above = (sig["trend_10m"] > 0).astype(float).where(sig["trend_10m"].notna())
    mom_on = (sig["mom_12m_ex"] > 0).astype(float).where(sig["mom_12m_ex"].notna())
    credit_ok = (sig["credit_chg_6m"] <= 0.25).astype(float).where(sig["credit_chg_6m"].notna())
    sahm_ok = (sig["sahm"] < 0.5).astype(float).where(sig["sahm"].notna())
    cape_pct = exp_pct(sig["cape"].dropna(), 120).reindex(idx)
    val_scale = (1.0 - 0.5 * cape_pct)            # 1.0 (billig) … 0.5 (teuer)
    w = {
        "Buy & Hold": pd.Series(1.0, index=idx),
        "Trend 10M": above,
        "Momentum 12M": mom_on,
        "Trend ODER Momentum": ((above + mom_on) > 0).astype(float).where(above.notna() & mom_on.notna()),
        "Trend UND Momentum": ((above + mom_on) == 2).astype(float).where(above.notna() & mom_on.notna()),
        "Bewertung (CAPE-Perzentil)": val_scale,
        "Trend × Bewertung": above * val_scale,
        "Composite (Trend, Mom, Kredit, Arbeitsmarkt)": pd.concat([above, mom_on, credit_ok, sahm_ok], axis=1).mean(axis=1, skipna=False),
        "Trend + Kredit (Mittel)": (above + credit_ok) / 2,
        "Trend + Arbeitsmarkt (Mittel)": (above + sahm_ok) / 2,
        "Trend/Momentum-Mittel (0, ½, 1)": (above + mom_on) / 2,
        "Trend/Momentum-Mittel × ECY (0.75–1)": (above + mom_on) / 2 * (0.75 + 0.25 * exp_pct(sig["ecy"].dropna(), 120).reindex(idx)),
    }
    res = {k: run_exposure(v, mkt, rf, COST_EQ_BPS) for k, v in w.items()}
    samples = [("1927-01-31", "2026-07-31", ["Buy & Hold", "Trend 10M", "Momentum 12M", "Trend ODER Momentum", "Trend UND Momentum", "Trend/Momentum-Mittel (0, ½, 1)"]),
               ("1931-01-31", "2023-06-30", ["Buy & Hold", "Trend 10M", "Trend/Momentum-Mittel (0, ½, 1)", "Trend/Momentum-Mittel × ECY (0.75–1)", "Bewertung (CAPE-Perzentil)", "Trend × Bewertung"]),
               ("1962-01-31", "2023-06-30", list(w))]
    tabs = []
    for s, e, keys in samples:
        t = pd.DataFrame({k: stats(res[k].loc[s:e], rf, w[k]) for k in keys}).T
        t.index.name = f"Strategie ({s[:4]}–{e[:4]})"
        tabs.append(t)
        t.to_csv(os.path.join(OUT, f"A2_strategies_{s[:4]}_{e[:4]}.csv"))
    say("### A2. Exposure-Strategien (Aktien oder T-Bills, monatlich, 5 bp je Wechsel)",
        "Drei Stichproben: 1927–2026 nur mit Preissignalen; 1931–2023 mit Bewertung (ECY-Perzentil braucht 10 Jahre Vorlauf, Shiller-Gewinne enden 2023); "
        "1962–2023 mit allen Signalen inkl. Makro.",
        md(tabs[0], "{:.3f}"), md(tabs[1], "{:.3f}"), md(tabs[2], "{:.3f}"),
        "Der Composite mit Kredit und Arbeitsmarkt ist schlechter als Trend allein (Sharpe 0.42 vs 0.51), und die Zerlegung zeigt: beide Makro-Bausteine schaden, "
        "Kredit (0.40) sogar stärker als Arbeitsmarkt (0.44). Der Grund ist mechanisch, nicht ökonomisch: Ein Baustein, der fast immer «investiert bleiben» sagt, "
        "verwässert den Trend-Ausstieg auf 50 % und liefert dafür keine eigene Information über den Folgemonat (A1). "
        "Bewertung allein senkt das Ergebnis (zu früh raus in langen Bullenmärkten, 3–4 Wechsel p.a.); als milde Skalierung (0.75–1) auf dem Trendsignal "
        "senkt sie Volatilität und Drawdown bei kleinem Renditeverzicht. "
        "**Modulkandidat:** Trend/Momentum-Mittel (Exposure 0, ½ oder 1), optional ECY-skaliert.")

    # ---- A3: Sensitivität Trendfenster
    sens = {}
    for n in (6, 8, 10, 12, 15, 18):
        a = (tr > tr.rolling(n).mean()).astype(float).where(tr.rolling(n).mean().notna())
        r = run_exposure(a, mkt, rf, COST_EQ_BPS).loc["1927":]
        sens[f"{n}M"] = {"Sharpe": metrics.sharpe(r - rf.reindex(r.index)), "Max DD": metrics.max_drawdown(r), "Rendite p.a.": metrics.ann_return(r)}
    st = pd.DataFrame(sens).T
    st.index.name = "Trendfenster"
    say("### A3. Robustheit: Trendfenster 6–18 Monate (1927–2026)", md(st, "{:.3f}"),
        f"Buy & Hold zum Vergleich: Sharpe {metrics.sharpe(res['Buy & Hold'].loc['1927':] - rf.loc['1927':]):.3f}, "
        f"Max DD {metrics.max_drawdown(res['Buy & Hold'].loc['1927':]):.3f}.")

    # ---- A4: Crash-Episoden
    eps = [("1929-08", "1932-06"), ("1937-02", "1938-03"), ("1946-05", "1949-06"), ("1968-11", "1970-06"), ("1972-12", "1974-09"),
           ("1987-08", "1987-11"), ("2000-08", "2002-09"), ("2007-10", "2009-02"), ("2020-01", "2020-03"), ("2021-12", "2022-09")]
    crash = {}
    for p, q in eps:
        P, Q = pd.Timestamp(p) + pd.offsets.MonthEnd(0), pd.Timestamp(q) + pd.offsets.MonthEnd(0)
        row = {}
        for k in ["Buy & Hold", "Trend 10M", "Trend ODER Momentum", "Trend/Momentum-Mittel (0, ½, 1)"]:
            r = res[k].loc[P + pd.offsets.MonthEnd(1):Q]
            row[k] = float((1 + r).prod() - 1) if len(r) else np.nan
        crash[f"{p} → {q}"] = row
    ct = pd.DataFrame(crash).T
    ct.index.name = "Crash (Hoch → Tief)"
    ct.to_csv(os.path.join(OUT, "A4_crashes.csv"))
    say("### A4. Grosse Crashes: Rendite vom Markthoch bis zum Tief", md(ct, "{:+.0%}"),
        "Trendfolge spart in langen Baissen den Grossteil (1929–32: −20 % statt −84 %; 2007–09: −4 % statt −50 %). In schnellen Crashes hilft sie wenig, "
        "weil das Monatssignal erst nach dem Fall dreht (1987: −24 % statt −30 %), und in Seitwärtsphasen kostet sie (1946–49: schlechter als Buy & Hold). "
        "Für schnelle Crashes ist der Gold/Silber-Hedge die Ergänzung (8/8 positiv).")

    # ---- A5: Kosten der Absicherung: verpasste Rallys
    whip = {}
    for k in ["Trend 10M", "Trend ODER Momentum", "Trend/Momentum-Mittel (0, ½, 1)"]:
        r, b = res[k].loc["1962":"2023-06"], res["Buy & Hold"].loc["1962":"2023-06"]
        diff = r - b
        up = b > 0.03
        whip[k] = {"Rendite in Monaten Markt > +3 % (Strategie − B&H)": diff[up].mean() * 12,
                   "Rendite in Monaten Markt < −5 % (Strategie − B&H)": diff[b < -0.05].mean() * 12,
                   "Monate investiert": float(w[k].reindex(r.index).shift(1).mean())}
    say("### A5. Was der Schutz kostet", md(pd.DataFrame(whip).T.rename_axis("Strategie, 1962–2023"), "{:.3f}"))

    # ---- A6: Midterm-Zyklus
    nxt12 = fwd[12]
    mt = {}
    for lab, mask in [("Ende Okt. im Midterm-Jahr", (yr % 4 == 2) & (idx.month == 10)), ("Ende Okt. andere Jahre", (yr % 4 != 2) & (idx.month == 10))]:
        x = nxt12[mask].loc["1927":].dropna()
        mt[lab] = {"n": len(x), "Ø 12M Überschuss": x.mean(), "Anteil > 0": (x > 0).mean(), "schlechtestes": x.min()}
    say("### A6. Midterm-Zyklus (Folge-12-Monate ab Ende Oktober, Überschussrendite)", md(pd.DataFrame(mt).T.rename_axis("Start"), "{:.3f}"),
        "Bestätigt das Muster aus der Gold/Silber-Diskussion auf 100 Jahren. Wird nicht ins Modul eingebaut (25 Beobachtungen, Gefahr von Data Mining), aber im Report als Kontext ausgewiesen.")

    # ---- Grafik
    eq = pd.DataFrame({k: (1 + res[k].loc["1927":]).cumprod() for k in ["Buy & Hold", "Trend 10M", "Trend ODER Momentum"]})
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    eq.plot(ax=axes[0], logy=True)
    axes[0].set_title("US-Aktien 1927–2026: Buy & Hold vs. Trendfolge (netto, Rest in T-Bills)")
    (eq / eq.cummax() - 1).plot(ax=axes[1], legend=False)
    axes[1].set_title("Drawdown")
    say(f"![]({savefig('fig_A_exposure.png')})")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    d = pd.DataFrame({"cape": sig["cape"], "fwd10": ((1 + ex).rolling(120).apply(np.prod, raw=True) ** (1 / 10) - 1).shift(-120)}).dropna()
    ax.scatter(d.cape, d.fwd10 * 100, s=6, alpha=0.5)
    b = np.polyfit(np.log(d.cape), d.fwd10 * 100, 1)
    xs = np.linspace(d.cape.min(), d.cape.max(), 50)
    ax.plot(xs, np.polyval(b, np.log(xs)), "r-")
    if pd.notna(sig["cape"].dropna().iloc[-1]):
        ax.axvline(sig["cape"].dropna().iloc[-1], color="k", ls="--", lw=0.8)
        ax.text(sig["cape"].dropna().iloc[-1], ax.get_ylim()[1] * 0.9, f" CAPE {sig['cape'].dropna().index[-1]:%Y-%m}: {sig['cape'].dropna().iloc[-1]:.0f}", fontsize=8)
    ax.set_xlabel("CAPE (Gewinne 4 Monate verzögert)")
    ax.set_ylabel("Überschussrendite p.a. folgende 10 Jahre (%)")
    ax.set_title("Bewertung sagt die nächsten 10 Jahre voraus, nicht den nächsten Monat")
    say(f"![]({savefig('fig_A_cape.png')})")

    return {"sig": sig, "res": res, "w": w, "above": above}


# ===========================================================================
# Teil B: Welche Branchen und Faktoren?
# ===========================================================================
def signals_b(ind: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Branchen-Signale am Monatsende t aus Renditen bis t. Reine Funktion (Audit-Trunkierungstest)."""
    lv = (1 + ind).cumprod()
    return {
        "Momentum 12-1": lv.shift(1) / lv.shift(13) - 1,
        "Momentum 6-1": lv.shift(1) / lv.shift(7) - 1,
        "Momentum 3-1": lv.shift(1) / lv.shift(4) - 1,
        "Letzter Monat (Reversal)": ind,
        "Trend 10M": lv / lv.rolling(10).mean() - 1,
        "Niedrige Vol 36M": -ind.rolling(36).std(),
        "Langfrist-Umkehr 60-12": -(lv.shift(12) / lv.shift(60) - 1),
    }


def part_b(D: dict, A: dict) -> dict:
    ind, rf, mkt, macro, f5 = D["ind"], D["rf"], D["mkt"], D["macro"], D["f5"]
    names = {"NoDur": "Basiskonsum", "Durbl": "Langl. Konsum", "Manuf": "Industrie", "Enrgy": "Energie", "HiTec": "Technologie",
             "Telcm": "Telekom", "Shops": "Handel", "Hlth": "Gesundheit", "Utils": "Versorger", "Other": "Übrige (Fin. u. a.)"}
    say("## Teil B: Welche Branchen und Faktoren?",
        "10 Branchen-Portfolios von Kenneth French (value-weighted, SIC-Zuordnung, 1926–2026). "
        "Live-Abbildung über die Sektor-SPDRs (XLP, XLY, XLI, XLE, XLK, XLC, XLRE/XLY, XLV, XLU, XLF) ab 1998.")
    ex = ind.sub(rf, axis=0)
    lv = (1 + ind).cumprod()
    rel = ex.sub(ex.mean(axis=1), axis=0)

    # ---- B1 deskriptiv
    desc = pd.DataFrame({"Rendite p.a.": ind.apply(metrics.ann_return), "Vol p.a.": ind.apply(metrics.ann_vol),
                         "Sharpe": ex.apply(metrics.sharpe), "Max DD": ind.apply(metrics.max_drawdown),
                         "Beta zum Markt": ind.apply(lambda s: np.cov(s.dropna(), mkt.reindex(s.dropna().index))[0, 1] / mkt.reindex(s.dropna().index).var())})
    desc.index = [names[c] for c in desc.index]
    desc.index.name = "Branche (1926–2026)"
    say("### B1. Die Branchen einzeln", md(desc, "{:.2f}"))

    # ---- B2 Signale + ICs
    sig = signals_b(ind)
    fwd = rel.shift(-1)
    rows, sub = {}, {}
    for k, s in sig.items():
        ic = analysis.information_coefficients({k: s}, fwd, min_assets=8)
        rows[k] = ic.iloc[0].to_dict()
        icser = pd.Series({t: s.loc[t].rank().corr(fwd.loc[t].rank()) for t in s.index if s.loc[t].notna().sum() >= 8 and fwd.loc[t].notna().sum() >= 8})
        for a, b in [("1927", "1962"), ("1963", "1994"), ("1995", "2026")]:
            x = icser.loc[a:b]
            sub.setdefault(k, {})[f"{a}–{b}"] = x.mean() / (x.std() / np.sqrt(len(x)))
    ict = pd.DataFrame(rows).T.rename(columns={"months": "Monate", "mean_IC": "Ø IC", "std_IC": "Std IC", "t_stat": "t", "IC>0": "Anteil IC>0"})
    ict.index.name = "Signal"
    say("### B2. Welche Signale ordnen die Branchen? (Rang-IC gegen relative Folgemonatsrendite)", md(ict, "{:.3f}"),
        "t-Werte je Teilperiode:", md(pd.DataFrame(sub).T.rename_axis("Signal"), "{:.1f}"),
        "Branchen-Momentum (12-1) und Trend sind über 100 Jahre robust (t ≈ 5), aber deutlich schwächer geworden: seit 1995 t = 1.7 bzw. 1.0. "
        "Der 1-Monats-Effekt ist hier *Fortsetzung*, nicht Umkehr (positives IC, Moskowitz & Grinblatt 1999), und seit 1995 verschwunden.")

    # ---- B3 Strategien
    vol = ind.rolling(12).std()

    def topn(score: pd.DataFrame, n: int, invvol: bool, trend_gate: pd.Series | None = None) -> pd.DataFrame:
        W = pd.DataFrame(0.0, index=score.index, columns=list(ind.columns) + ["CASH"])
        for t in score.index:
            s = score.loc[t].dropna()
            if len(s) < 8:
                W.loc[t, "CASH"] = 1.0
                continue
            picks = s.sort_values(ascending=False).index[:n]
            ww = (1 / vol.loc[t, picks]) if invvol else pd.Series(1.0, index=picks)
            ww = ww / ww.sum()
            g = 1.0 if trend_gate is None or pd.isna(trend_gate.get(t)) else float(trend_gate.get(t))
            W.loc[t, picks] = ww.values * g
            W.loc[t, "CASH"] = 1 - g
        return W

    def run_w(W: pd.DataFrame, cost_bps: float = COST_IND_BPS) -> pd.Series:
        R = ind.copy()
        R["CASH"] = rf
        held = W.shift(1)
        gross = (held * R[W.columns]).sum(axis=1, min_count=1)
        turn = W.diff().abs().sum(axis=1).shift(1).fillna(0) / 2
        return (gross - turn * 2 * cost_bps / 1e4).dropna()

    ew = ind.mean(axis=1)
    combo = sig["Momentum 12-1"].rank(axis=1) * 0.5 + sig["Momentum 6-1"].rank(axis=1) * 0.3 + sig["Trend 10M"].rank(axis=1) * 0.2
    strategies = {
        "Markt (Buy & Hold)": mkt,
        "Gleichgewicht 10 Branchen": ew,
        "Top-3 Momentum 12-1": run_w(topn(sig["Momentum 12-1"], 3, False)),
        "Top-3 Momentum 12-1, inverse Vol": run_w(topn(sig["Momentum 12-1"], 3, True)),
        "Top-5 Momentum 12-1": run_w(topn(sig["Momentum 12-1"], 5, False)),
        "Top-3 Composite (12-1, 6-1, Trend)": run_w(topn(combo, 3, False)),
        "Top-3 Composite + Markt-Trendfilter": run_w(topn(combo, 3, False, A["above"])),
    }
    st = {}
    for k, r in strategies.items():
        st[k] = stats(r.loc["1928":"2026-07"], rf)
        rr = r.loc["1928":"2026-07"]
        st[k]["Überrendite vs Markt p.a."] = (rr - mkt.reindex(rr.index)).mean() * 12
        st[k]["Tracking Error"] = (rr - mkt.reindex(rr.index)).std() * np.sqrt(12)
        st[k]["Information Ratio"] = st[k]["Überrendite vs Markt p.a."] / st[k]["Tracking Error"] if st[k]["Tracking Error"] > 0 else np.nan
    stt = pd.DataFrame(st).T
    stt.index.name = "Strategie (1928–2026, 10 bp je Seite)"
    stt.to_csv(os.path.join(OUT, "B3_strategies.csv"))
    say("### B3. Branchen-Rotation (monatlich, long-only)", md(stt, "{:.3f}"))
    ls = cm_ls(sig["Momentum 12-1"], ex.shift(-1))
    dec = {}
    for k in ["Top-3 Composite (12-1, 6-1, Trend)", "Top-3 Momentum 12-1", "Markt (Buy & Hold)"]:
        r = strategies[k].loc["1928":"2026-07"]
        for d, g in r.groupby((r.index.year // 10) * 10):
            dec.setdefault(f"{d}er", {})[k] = metrics.ann_return(g)
    dect = pd.DataFrame(dec).T
    dect["Composite − Markt"] = dect["Top-3 Composite (12-1, 6-1, Trend)"] - dect["Markt (Buy & Hold)"]
    say(f"Long-Short Top-3 minus Bottom-3 nach Momentum 12-1: {ls.mean() * 12:+.1%} p.a., Sharpe {metrics.sharpe(ls):.2f}, "
        f"positiv in {(ls.groupby(ls.index.year).sum() > 0).mean():.0%} der Jahre.",
        "### Rendite p.a. je Jahrzehnt", md(dect, "{:+.3f}"))

    # ---- B4 Regime
    m = macro.reindex(ind.index)
    g = m["INDPRO_YOY"].rolling(3).mean()
    i = m["CPI_YOY"].rolling(3).mean()
    # Label am Monatsende t aus Daten, die an t bekannt sind (IP/CPI: Monat t−1), bewertet mit der relativen Rendite in t+1
    quad = (pd.Series(np.where(g > g.shift(3), "Wachstum↑", "Wachstum↓"), index=ind.index) + " " +
            pd.Series(np.where(i > i.shift(3), "Inflation↑", "Inflation↓"), index=ind.index)).where(g.shift(3).notna() & i.shift(3).notna()).shift(1)
    rec = (m["INDPRO_YOY"].shift(1) < 0).map({True: "IP-Rückgang (Rezession)", False: "IP-Wachstum"}).where(m["INDPRO_YOY"].shift(1).notna())
    curve = pd.Series(np.where(m["CURVE_10Y3M"] < 0, "Kurve invers", "Kurve normal"), index=ind.index).where(m["CURVE_10Y3M"].notna())
    rel_next = rel.shift(-1)
    tabs = []
    for lab, s in [("Wachstum × Inflation", quad), ("Konjunktur", rec), ("Zinskurve", curve)]:
        df = rel_next.join(s.rename("reg")).dropna(subset=["reg"]).loc["1960":]
        t = df.groupby("reg").mean() * 12
        t.columns = [names.get(c, c) for c in t.columns]
        t = t.T
        t.loc["Monate"] = df.groupby("reg").size().astype(float)
        tabs.append((lab, t))
    say("### B4. Relative Branchenrendite im Folgemonat je Makro-Regime (p.a., vs. Durchschnitt der 10 Branchen, 1960–2026)",
        "Regime am Monatsende t aus den dann veröffentlichten Daten (Makro bis t−1), Rendite im Monat t+1. So ist die Tabelle das, was ein Investor hätte nutzen können.",
        *[x for lab, t in tabs for x in (f"**{lab}**", md(t, "{:+.3f}"))],
        "Das Lehrbuch stimmt hier nur halb. Klar ist: Energie gewinnt im Folgemonat nach steigender Inflation (+6.0 % bzw. +4.8 % p.a. relativ) und verliert, "
        "solange die veröffentlichte Industrieproduktion fällt (−8.4 %). Nicht bestätigt: Defensive Sektoren (Basiskonsum, Gesundheit, Versorger) schlagen den "
        "Durchschnitt in diesen Monaten *nicht*; zyklische wie langlebiger Konsum (+13.0 %) und Handel (+8.1 %) tun es, weil der Markt die Erholung vorwegnimmt, "
        "während die Produktionsdaten noch fallen. "
        "Wer nach veröffentlichten Makrodaten in Defensive rotiert, kommt zu spät. Deshalb nutzt das Modul diese Tabelle nicht als Signal, sondern nur als Kontext und für die Szenario-Engine.")

    # ---- B5 Faktoren
    fac = f5.drop(columns=["RF"]).rename(columns={"MKT_RF": "Markt", "SMB": "Size", "HML": "Value", "RMW": "Quality", "CMA": "Investment", "Mom": "Momentum"})
    fdesc = pd.DataFrame({"Prämie p.a.": fac.mean() * 12, "Vol p.a.": fac.std() * np.sqrt(12), "Sharpe": fac.apply(metrics.sharpe),
                          "Max DD": fac.apply(metrics.max_drawdown)})
    fl = (1 + fac).cumprod()
    fsub = {}
    for a, b in [("1963", "1989"), ("1990", "2006"), ("2007", "2026")]:
        fsub[f"Sharpe {a}–{b}"] = fac.loc[a:b].apply(metrics.sharpe)
    fdesc = fdesc.join(pd.DataFrame(fsub))
    fdesc.index.name = "Faktor (long-short, 1963–2026)"
    # Faktor-Momentum (Zeitreihe): Faktor halten, wenn eigene 12M-Rendite > 0 (Ehsani & Linnainmaa 2022)
    lf = fac.drop(columns=["Markt"])
    on = ((1 + lf).rolling(12).apply(np.prod, raw=True) - 1 > 0).astype(float)
    tsfm = (on.shift(1) * lf).sum(axis=1) / on.shift(1).sum(axis=1).replace(0, np.nan)
    eqf = lf.mean(axis=1)
    csfm_w = lf.rolling(12).sum().rank(axis=1, ascending=False) <= 2
    csfm = (csfm_w.shift(1) * lf).sum(axis=1) / 2
    fstrat = pd.DataFrame({k: {"Prämie p.a.": s.loc["1965":].mean() * 12, "Sharpe": metrics.sharpe(s.loc["1965":]), "Max DD": metrics.max_drawdown(s.loc["1965":])}
                           for k, s in [("Alle 5 Faktoren gleichgewichtet", eqf), ("Faktor-Momentum (Zeitreihe)", tsfm), ("Top-2 Faktoren nach 12M", csfm)]}).T
    fstrat.index.name = "Faktor-Rotation (1965–2026, brutto)"
    say("### B5. Faktoren: Prämien und Rotation",
        "Long-short-Faktoren von Fama-French (nicht direkt investierbar; live über Faktor-ETFs wie VLUE, QUAL, MTUM, USMV, IJR, erst ab 2013 mit Historie).",
        md(fdesc, "{:.2f}"), md(fstrat, "{:.3f}"),
        "Value hat seit 2007 keine Prämie mehr geliefert, Quality und Momentum schon. Faktor-Momentum glättet das, ist aber ein Long-short-Konstrukt; "
        "für ein Long-only-System mit ETFs ist es Phase-2-Material mit kurzer Live-Historie.")

    # ---- Grafik
    eqc = pd.DataFrame({k: (1 + strategies[k].loc["1928":"2026-07"]).cumprod() for k in ["Markt (Buy & Hold)", "Gleichgewicht 10 Branchen", "Top-3 Composite (12-1, 6-1, Trend)", "Top-3 Composite + Markt-Trendfilter"]})
    ax = eqc.plot(figsize=(10, 4.5), logy=True)
    ax.set_title("Branchen-Rotation 1928–2026 (netto, log)")
    say(f"![]({savefig('fig_B_industries.png')})")

    # ---- Aktueller Stand
    last = ind.dropna(how="all").index.max()
    now = pd.DataFrame({"Momentum 12-1": sig["Momentum 12-1"].loc[last], "Momentum 6-1": sig["Momentum 6-1"].loc[last],
                        "Trend 10M": sig["Trend 10M"].loc[last], "Composite-Rang": combo.loc[last].rank(ascending=False)})
    now.index = [names[c] for c in now.index]
    now = now.sort_values("Composite-Rang")
    now.index.name = f"Branche, Stand {last:%Y-%m}"
    say(f"### Aktueller Stand Branchen ({last:%Y-%m})", md(now, "{:.3f}"))
    return {"strategies": strategies, "ict": ict, "stt": stt}


def cm_ls(score: pd.DataFrame, fwd: pd.DataFrame, n: int = 3) -> pd.Series:
    out = {}
    for t in score.index:
        if t not in fwd.index:
            continue
        x, y = score.loc[t], fwd.loc[t]
        m = x.notna() & y.notna()
        if m.sum() < 8:
            continue
        o = x[m].sort_values(ascending=False).index
        out[t] = y[o[:n]].mean() - y[o[-n:]].mean()
    return pd.Series(out)


def main() -> None:
    D = load()
    A = part_a(D)
    B = part_b(D, A)
    # Stand Teil A
    sig = A["sig"]
    last = sig["trend_10m"].dropna().index[-1]
    say(f"## Stand Aktien-Exposure ({last:%Y-%m})",
        f"Trend: {'über' if sig['trend_10m'].loc[last] > 0 else 'unter'} 10M-Schnitt ({sig['trend_10m'].loc[last]:+.1%}) · "
        f"Momentum 12M: {sig['mom_12m_ex'].loc[last]:+.1%} · Δ Kreditspread 6M: {sig['credit_chg_6m'].dropna().iloc[-1]:+.2f} · "
        f"Sahm-Indikator: {sig['sahm'].dropna().iloc[-1]:.2f} · letzter CAPE ({sig['cape'].dropna().index[-1]:%Y-%m}): {sig['cape'].dropna().iloc[-1]:.1f} "
        f"(Perzentil seit 1881: {exp_pct(sig['cape'].dropna(), 120).iloc[-1]:.0%}).",
        "Hinweis: CAPE endet mit den Shiller-Gewinnen 2023-06 im Repo; live kommt er in Phase 1 aus einer aktuellen Quelle.")
    with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(REP))
    print("\n".join(REP))


if __name__ == "__main__":
    main()
