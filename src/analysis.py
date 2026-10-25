"""Statistische Auswertung: deskriptive Statistik, Regime-Renditen, Treiber-Regressionen,
Information Coefficients, Mean-Reversion-Tests, Parameter-Sensitivität.

Keine externen Abhängigkeiten ausser pandas/numpy (OLS mit Newey-West-Standardfehlern selbst implementiert).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import metrics

PERIODS = 12


# ---------------------------------------------------------------------------
# Deskriptive Statistik
# ---------------------------------------------------------------------------
def describe_assets(returns: pd.DataFrame, cash: pd.Series | None = None) -> pd.DataFrame:
    rows = {}
    for c in returns.columns:
        r = returns[c].dropna()
        ex = (r - cash.reindex(r.index).fillna(0)) if cash is not None else r
        rows[c] = {
            "Start": r.index.min().strftime("%Y-%m"),
            "Ann. Return": metrics.ann_return(r),
            "Ann. Vol": metrics.ann_vol(r),
            "Sharpe (ex Cash)": metrics.sharpe(ex),
            "Max Drawdown": metrics.max_drawdown(r),
            "Skew": float(r.skew()),
            "Worst Month": float(r.min()),
            "Best Month": float(r.max()),
            "% Months > 0": float((r > 0).mean()),
        }
    return pd.DataFrame(rows).T


def subperiod_table(returns: pd.DataFrame, cash: pd.Series, breaks: list[str]) -> pd.DataFrame:
    """Annualisierte Rendite / Sharpe je Teilperiode."""
    out = {}
    edges = [returns.index.min()] + [pd.Timestamp(b) for b in breaks] + [returns.index.max()]
    for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        seg = returns.loc[a:b]
        if k > 0:
            seg = seg.loc[a + pd.Timedelta(days=1):]  # Grenzmonat nicht doppelt zählen
        lab = f"{seg.dropna(how='all').index.min().year}–{b.year}"
        out[(lab, "Ann. Return")] = seg.apply(metrics.ann_return)
        out[(lab, "Sharpe")] = seg.sub(cash.reindex(seg.index), axis=0).apply(metrics.sharpe)
    return pd.DataFrame(out)


def rolling_correlation(returns: pd.DataFrame, a: str, b: str, window: int = 36) -> pd.Series:
    return returns[a].rolling(window).corr(returns[b])


# ---------------------------------------------------------------------------
# Renditen je Regime
# ---------------------------------------------------------------------------
def returns_by_regime(excess: pd.DataFrame, regime: pd.Series, min_months: int = 12) -> pd.DataFrame:
    """Annualisierte Überschussrendite (über Cash), Sharpe und t-Statistik je Regime und Asset.

    excess: monatliche Überschussrenditen (Datum × Asset); regime: Label je Datum (bereits verzögert).
    """
    df = excess.join(regime.rename("regime"), how="inner").dropna(subset=["regime"])
    df = df[df["regime"] != "unknown"]
    rows = []
    for reg, g in df.groupby("regime"):
        if len(g) < min_months:
            continue
        for c in excess.columns:
            r = g[c].dropna()
            if len(r) < min_months:
                continue
            t = r.mean() / (r.std() / np.sqrt(len(r))) if r.std() > 0 else np.nan
            rows.append({"regime": reg, "asset": c, "months": len(r), "ann_excess": r.mean() * PERIODS,
                         "sharpe": metrics.sharpe(r), "t_stat": t, "hit_rate": (r > 0).mean()})
    return pd.DataFrame(rows)


def regime_pivot(tab: pd.DataFrame, value: str = "ann_excess") -> pd.DataFrame:
    return tab.pivot(index="asset", columns="regime", values=value)


# ---------------------------------------------------------------------------
# OLS mit Newey-West (HAC) Standardfehlern
# ---------------------------------------------------------------------------
def ols_newey_west(y: pd.Series, X: pd.DataFrame, lags: int = 6) -> pd.DataFrame:
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    yv = df["y"].to_numpy(dtype=float)
    Xv = np.column_stack([np.ones(len(df)), df[X.columns].to_numpy(dtype=float)])
    n, k = Xv.shape
    XtX_inv = np.linalg.pinv(Xv.T @ Xv)
    beta = XtX_inv @ Xv.T @ yv
    e = yv - Xv @ beta
    S = (Xv * e[:, None]).T @ (Xv * e[:, None])
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = (Xv[l:] * e[l:, None]).T @ (Xv[:-l] * e[:-l, None])
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / ((yv - yv.mean()) @ (yv - yv.mean()))
    out = pd.DataFrame({"coef": beta, "se_NW": se, "t_stat": beta / se}, index=["const"] + list(X.columns))
    out.attrs["r2"] = float(r2)
    out.attrs["n"] = int(n)
    return out


def driver_regressions(excess: pd.DataFrame, macro_feats: pd.DataFrame, assets: list[str],
                       factors: dict[str, str], lags: int = 6, lead: int = 0) -> tuple[pd.DataFrame, dict]:
    """Regression der monatlichen Überschussrendite jedes Assets auf Faktoränderungen.

    factors: Anzeigename → Spalte in macro_feats (bereits als Änderung). Mit lead=1 werden die
    Faktoren um einen Monat verzögert (prädiktive Variante); lead=0 = gleichzeitig (erklärend).
    Standardisierte Koeffizienten (Faktor in Std.-Abw., Rendite in %/Monat) für Vergleichbarkeit.
    """
    X = macro_feats[list(factors.values())].copy()
    X.columns = list(factors.keys())
    X = (X - X.mean()) / X.std()
    if lead:
        X = X.shift(lead)
    rows, full = [], {}
    for a in assets:
        res = ols_newey_west(excess[a] * 100, X, lags=lags)
        full[a] = res
        for f in factors:
            rows.append({"asset": a, "factor": f, "coef_%/sd": res.loc[f, "coef"], "t_stat": res.loc[f, "t_stat"],
                         "r2": res.attrs["r2"], "n": res.attrs["n"]})
    return pd.DataFrame(rows), full


# ---------------------------------------------------------------------------
# Information Coefficient (Querschnitt)
# ---------------------------------------------------------------------------
def information_coefficients(feats: dict[str, pd.DataFrame], fwd_excess: pd.DataFrame, min_assets: int = 4) -> pd.DataFrame:
    """Monatlicher Spearman-Rang-IC zwischen Feature_t und Überschussrendite_{t+1} über Assets."""
    rows = []
    for name, f in feats.items():
        ics = []
        for t in f.index:
            if t not in fwd_excess.index:
                continue
            x, y = f.loc[t], fwd_excess.loc[t]
            m = x.notna() & y.notna()
            if m.sum() < min_assets:
                continue
            ics.append(x[m].rank().corr(y[m].rank()))
        ics = pd.Series(ics)
        if ics.empty:
            continue
        rows.append({"feature": name, "months": len(ics), "mean_IC": ics.mean(), "std_IC": ics.std(),
                     "t_stat": ics.mean() / (ics.std() / np.sqrt(len(ics))), "IC>0": (ics > 0).mean()})
    return pd.DataFrame(rows).set_index("feature").sort_values("t_stat", ascending=False)


def quantile_spread(feature: pd.DataFrame, fwd_excess: pd.DataFrame, q: int = 3) -> pd.Series:
    """Rendite Top-Tercil minus Bottom-Tercil pro Monat (Long-Short-Portfolio des Features)."""
    out = {}
    for t in feature.index:
        if t not in fwd_excess.index:
            continue
        x, y = feature.loc[t], fwd_excess.loc[t]
        m = x.notna() & y.notna()
        if m.sum() < 4:
            continue
        rk = x[m].rank(pct=True)
        top, bot = y[m][rk > 1 - 1 / q], y[m][rk <= 1 / q]
        if len(top) and len(bot):
            out[t] = top.mean() - bot.mean()
    return pd.Series(out)


# ---------------------------------------------------------------------------
# Gold/Silber-Ratio: Mean Reversion
# ---------------------------------------------------------------------------
def mean_reversion_test(log_ratio: pd.Series) -> dict:
    """AR(1) auf der log-Ratio → Halbwertszeit; Dickey-Fuller-ähnliche t-Statistik (ohne kritische Werte)."""
    s = log_ratio.dropna()
    d = s.diff().dropna()
    lag = s.shift(1).dropna().reindex(d.index)
    X = pd.DataFrame({"lag": lag})
    res = ols_newey_west(d, X, lags=6)
    phi = 1 + res.loc["lag", "coef"]
    half_life = -np.log(2) / np.log(phi) if 0 < phi < 1 else np.inf
    return {"phi": phi, "half_life_months": half_life, "t_stat_(rho-1)": res.loc["lag", "t_stat"], "n": res.attrs["n"]}


def conditional_forward_returns(signal: pd.Series, fwd: pd.Series, q: int = 5) -> pd.DataFrame:
    """Durchschnittliche Vorwärtsrendite je Signal-Quintil (Quintile rollierend, nur Vergangenheit)."""
    df = pd.DataFrame({"sig": signal, "fwd": fwd}).dropna()
    # Quintile aus expandierendem Fenster, damit kein Look-ahead
    ranks = df["sig"].expanding(min_periods=60).apply(lambda x: (x.rank(pct=True)).iloc[-1], raw=False)
    df["q"] = pd.cut(ranks, bins=np.linspace(0, 1, q + 1), labels=[f"Q{i}" for i in range(1, q + 1)], include_lowest=True)
    g = df.dropna().groupby("q", observed=True)["fwd"]
    return pd.DataFrame({"n": g.size(), "mean_fwd": g.mean(), "median_fwd": g.median(), "hit": g.apply(lambda x: (x > 0).mean())})


# ---------------------------------------------------------------------------
# Parameter-Sensitivität
# ---------------------------------------------------------------------------
def sensitivity_grid(build_fn, top_ns: list[int], lookbacks: list[int], trend_filter: bool = True,
                     cash: pd.Series | None = None) -> pd.DataFrame:
    """Sharpe (netto, ex Cash, in-sample) über Top-N × Momentum-Lookback. build_fn(params) → Backtest-DataFrame."""
    out = pd.DataFrame(index=[f"Top-{n}" for n in top_ns], columns=[f"mom {lb}M" for lb in lookbacks], dtype=float)
    for n in top_ns:
        for lb in lookbacks:
            bt = build_fn({"top_n": n, "lookback": lb, "trend_filter": trend_filter})
            net = bt["net"] - cash.reindex(bt.index).fillna(0) if cash is not None else bt["net"]
            out.loc[f"Top-{n}", f"mom {lb}M"] = metrics.sharpe(net)
    return out


def by_decade(r: pd.Series, bench: dict[str, pd.Series]) -> pd.DataFrame:
    df = pd.DataFrame({"Strategie": r, **bench}).dropna(how="all")
    df["decade"] = (df.index.year // 10) * 10
    rows = {}
    for dec, g in df.groupby("decade"):
        rows[f"{dec}s"] = {c: metrics.ann_return(g[c]) for c in df.columns if c != "decade"} | {"months": len(g)}
    return pd.DataFrame(rows).T
