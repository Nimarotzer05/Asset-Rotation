"""Rohstoff-Rotationsmodell: relative Attraktivität von Gold, Silber, Platin, Öl, Gas, Kupfer, Aluminium,
Nickel und Agrarrohstoffen zueinander.

Zwei Signalfamilien, beide ohne Look-ahead:
  1. Relatives Momentum / Trend (Querschnitts-z-Scores)
  2. Gelerntes Makro-Regime: Für jeden Rohstoff wird die historische *relative* Überschussrendite
     (vs. Durchschnitt aller Rohstoffe) im aktuellen Makro-Zustand (Dollar-, Industrieproduktions- und
     Inflationstrend, je steigend/fallend → 8 Zustände) aus der Vergangenheit geschätzt (expanding
     window, geschrumpft gegen 0). Der Zustand ist um einen Monat verzögert.
Die Kombination ist ein z-Score-Composite; Ranking → Top-N bzw. Long/Short.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COMMODITIES = {
    "WB_GOLD_AVG": "Gold",
    "WB_SILVER_AVG": "Silber",
    "WB_PLATINUM": "Platin",
    "WB_OIL": "Rohöl",
    "WB_NATGAS": "Erdgas (US)",
    "WB_COPPER": "Kupfer",
    "WB_ALUMINUM": "Aluminium",
    "WB_NICKEL": "Nickel",
    "WB_AGRI": "Agrar-Index",
}


# ---------------------------------------------------------------------------
# Makro-Zustand
# ---------------------------------------------------------------------------
def macro_state(macro: pd.DataFrame, smooth: int = 3, lag: int = 1) -> pd.DataFrame:
    """Drei binäre Trends → Zustandslabel wie 'USD↓ IP↑ CPI↑'. Um `lag` Monate verzögert."""
    out = pd.DataFrame(index=macro.index)
    specs = {"USD": np.log(macro["USD_IDX"]), "IP": macro["INDPRO_YOY"], "CPI": macro["CPI_YOY"]}
    for k, s in specs.items():
        m = s.rolling(smooth).mean()
        d = np.where(m > m.shift(smooth), "↑", "↓")
        out[k] = pd.Series(d, index=macro.index).where(m.shift(smooth).notna())
    out["state"] = "USD" + out["USD"] + " IP" + out["IP"] + " CPI" + out["CPI"]
    out.loc[out[["USD", "IP", "CPI"]].isna().any(axis=1), "state"] = np.nan
    return out.shift(lag)


def regime_score(rel_ret: pd.DataFrame, state: pd.Series, shrink_k: int = 36, min_obs: int = 12) -> pd.DataFrame:
    """Erwartete relative Rendite je Rohstoff im aktuellen Zustand, geschätzt aus der Vergangenheit.

    Für Datum t werden nur Monate < t verwendet (die Rendite von t ist am Monatsende t bekannt und wird
    *nach* der Bewertung von t in die Statistik aufgenommen). Schätzung = mean * n / (n + shrink_k).
    """
    assets = list(rel_ret.columns)
    sums: dict[str, np.ndarray] = {}
    cnts: dict[str, np.ndarray] = {}
    out = pd.DataFrame(np.nan, index=rel_ret.index, columns=assets)
    for t in rel_ret.index:
        s = state.get(t)
        if isinstance(s, str) and s in sums:
            n = cnts[s]
            mean = np.where(n > 0, sums[s] / np.maximum(n, 1), 0.0)
            score = mean * n / (n + shrink_k)
            score[n < min_obs] = np.nan
            out.loc[t] = score
        r = rel_ret.loc[t].to_numpy(dtype=float)
        if isinstance(s, str):
            if s not in sums:
                sums[s] = np.zeros(len(assets))
                cnts[s] = np.zeros(len(assets))
            ok = ~np.isnan(r)
            sums[s][ok] += r[ok]
            cnts[s][ok] += 1
    return out


def regime_table(rel_ret: pd.DataFrame, state: pd.Series) -> pd.DataFrame:
    """Vollstichproben-Tabelle: annualisierte relative Rendite je Zustand × Rohstoff (für die Heatmap)."""
    df = rel_ret.join(state.rename("state"), how="inner").dropna(subset=["state"])
    g = df.groupby("state")
    tab = g.mean() * 12
    tab["Monate"] = g.size()
    return tab


# ---------------------------------------------------------------------------
# Signale
# ---------------------------------------------------------------------------
def zx(df: pd.DataFrame) -> pd.DataFrame:
    mu, sd = df.mean(axis=1), df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0).clip(-3, 3)


def build_signals(levels: pd.DataFrame, rel_excess: pd.DataFrame, state: pd.Series) -> dict[str, pd.DataFrame]:
    p = levels
    sig = {
        "mom_12m": p.shift(1) / p.shift(13) - 1,
        "mom_6m": p.shift(1) / p.shift(7) - 1,
        "mom_3m": p.shift(1) / p.shift(4) - 1,
        "trend_10m": p / p.rolling(10).mean() - 1,
        "lt_rev_36m": p.shift(12) / p.shift(36) - 1,
    }
    sig["regime"] = regime_score(rel_excess, state)
    z = {k: zx(v) for k, v in sig.items()}
    sig["momentum_combo"] = 0.5 * z["mom_12m"] + 0.3 * z["mom_6m"] + 0.2 * z["trend_10m"]
    sig["combined"] = 0.7 * zx(sig["momentum_combo"]) + 0.3 * z["regime"]
    return sig


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------
def rank_ic(signal: pd.DataFrame, fwd: pd.DataFrame, min_assets: int = 5) -> pd.Series:
    ics = {}
    for t in signal.index:
        if t not in fwd.index:
            continue
        x, y = signal.loc[t], fwd.loc[t]
        m = x.notna() & y.notna()
        if m.sum() >= min_assets:
            ics[t] = x[m].rank().corr(y[m].rank())
    return pd.Series(ics)


def ic_summary(ics: dict[str, pd.Series]) -> pd.DataFrame:
    rows = {}
    for k, s in ics.items():
        rows[k] = {"Monate": len(s), "IC": s.mean(), "t": s.mean() / (s.std() / np.sqrt(len(s))), "IC>0": (s > 0).mean()}
    return pd.DataFrame(rows).T.sort_values("t", ascending=False)


def long_short(signal: pd.DataFrame, fwd: pd.DataFrame, n: int = 3, min_assets: int = 6) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Top-n minus Bottom-n (gleichgewichtet) auf der Vorwärtsrendite; zusätzlich Long- und Short-Bein."""
    ls, lo, sh = {}, {}, {}
    for t in signal.index:
        if t not in fwd.index:
            continue
        x, y = signal.loc[t], fwd.loc[t]
        m = x.notna() & y.notna()
        if m.sum() < min_assets:
            continue
        order = x[m].sort_values(ascending=False).index
        lo[t], sh[t] = y[order[:n]].mean(), y[order[-n:]].mean()
        ls[t] = lo[t] - sh[t]
    return pd.Series(ls), pd.Series(lo), pd.Series(sh)


def top_n_weights(signal: pd.DataFrame, levels: pd.DataFrame, n: int = 3, trend_filter: bool = True, vol_window: int = 12) -> pd.DataFrame:
    rets = levels.pct_change()
    vol = rets.rolling(vol_window).std()
    above = levels > levels.rolling(10).mean()
    w = pd.DataFrame(0.0, index=signal.index, columns=list(levels.columns) + ["CASH"])
    for t in signal.index:
        s = signal.loc[t].dropna()
        if len(s) < n + 2:
            w.loc[t, "CASH"] = 1.0
            continue
        picks = s.sort_values(ascending=False).index[:n]
        iv = (1 / vol.loc[t, picks]).replace([np.inf, -np.inf], np.nan).dropna()
        if iv.empty:
            w.loc[t, "CASH"] = 1.0
            continue
        ww = iv / iv.sum()
        if trend_filter:
            keep = above.loc[t, ww.index]
            w.loc[t, "CASH"] = ww[~keep].sum()
            ww = ww[keep]
        w.loc[t, ww.index] = ww.values
    return w


def tilted_weights(signal: pd.DataFrame, levels: pd.DataFrame, lam: float = 1.0, trend_filter: bool = True,
                   vol_window: int = 12) -> pd.DataFrame:
    """Inverse-Vol-Gewichte über alle Rohstoffe im Aufwärtstrend, multiplikativ nach Score gekippt:
    w_i ∝ (1/vol_i) · exp(lam · score_i). lam = 0 → reines Inverse-Vol + Trendfilter (Benchmark)."""
    rets = levels.pct_change()
    vol = rets.rolling(vol_window).std()
    above = levels > levels.rolling(10).mean()
    w = pd.DataFrame(0.0, index=signal.index, columns=list(levels.columns) + ["CASH"])
    for t in signal.index:
        iv = (1 / vol.loc[t]).replace([np.inf, -np.inf], np.nan)
        sc = signal.loc[t].fillna(0.0) if lam else pd.Series(0.0, index=levels.columns)
        raw = iv * np.exp(lam * sc)
        raw = raw.dropna()
        if raw.empty:
            w.loc[t, "CASH"] = 1.0
            continue
        ww = raw / raw.sum()
        if trend_filter:
            keep = above.loc[t, ww.index]
            w.loc[t, "CASH"] = ww[~keep].sum()
            ww = ww[keep]
        w.loc[t, ww.index] = ww.values
    return w


def trend_check(levels: pd.DataFrame, excess: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    """Zeitreihen-Test je Rohstoff: Überschussrendite im Folgemonat, wenn über vs. unter dem 10M-Schnitt."""
    above = levels > levels.rolling(10).mean()
    fwd = excess.shift(-1)
    rows = {}
    for a in levels.columns:
        up, dn = fwd[a][above[a]].dropna(), fwd[a][~above[a] & levels[a].notna()].dropna()
        if len(up) < 24 or len(dn) < 24:
            continue
        diff = up.mean() - dn.mean()
        se = np.sqrt(up.var() / len(up) + dn.var() / len(dn))
        rows[names.get(a, a)] = {"über Trend p.a.": up.mean() * 12, "unter Trend p.a.": dn.mean() * 12,
                                 "Differenz p.a.": diff * 12, "t": diff / se, "Monate über": len(up), "Monate unter": len(dn)}
    return pd.DataFrame(rows).T


def signpost(levels: pd.DataFrame, sig: dict[str, pd.DataFrame], state: pd.Series, names: dict[str, str],
             weights: pd.DataFrame | None = None) -> tuple[pd.DataFrame, str]:
    """Aktueller Wegweiser: Trend-Ampel je Rohstoff, relative Signale, Composite-Rang, Modellgewicht."""
    t = sig["combined"].dropna(how="all").index.max()
    above = levels > levels.rolling(10).mean()
    rows = []
    for a in levels.columns:
        rows.append({
            "Rohstoff": names.get(a, a),
            "Trend": "aufwärts" if above.loc[t, a] else "abwärts",
            "Momentum 12M": sig["mom_12m"].loc[t, a],
            "Momentum 6M": sig["mom_6m"].loc[t, a],
            "Abstand 10M-Schnitt": sig["trend_10m"].loc[t, a],
            "Regime-Erwartung p.a.": sig["regime"].loc[t, a] * 12 if pd.notna(sig["regime"].loc[t, a]) else np.nan,
            "Score": sig["combined"].loc[t, a],
            "Modellgewicht": weights.loc[t, a] if weights is not None else np.nan,
        })
    tab = pd.DataFrame(rows).sort_values("Score", ascending=False).reset_index(drop=True)
    tab.index = tab.index + 1
    tab.index.name = "Rang"
    return tab, f"{t:%Y-%m} · Makro-Zustand: {state.get(t)}"
