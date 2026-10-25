"""Feature-Berechnung. Alle Features zum Zeitpunkt t verwenden nur Daten bis t (kein Look-ahead).

Zwei Gruppen:
  asset_features()  – pro Asset (Querschnitt): Momentum, Trend, Volatilität, relative Stärke
  macro_features()  – Zeitreihen-Features aus dem Makro-Panel: Realzins, Dollar, Inflation,
                      Kreditspread, VIX, Zinskurve, Gold/Silber-Ratio (Niveau, Änderung, z-Score)
  macro_regime()    – Wachstum × Inflation Quadranten (Trendrichtung), um 1 Monat verzögert
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Asset-Features (Querschnitt)
# ---------------------------------------------------------------------------
def asset_features(monthly_prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Gibt dict feature_name → DataFrame (Datum × Asset) zurück."""
    p = monthly_prices
    feats = {}
    # Momentum mit 1-Monats-Skip (klassisch 12-1), reduziert Short-Term-Reversal
    for h in (3, 6, 12):
        feats[f"mom_{h}m"] = p.shift(1) / p.shift(h + 1) - 1
    # Momentum ohne Skip (für Vergleich)
    feats["mom_12m_noskip"] = p / p.shift(12) - 1
    # Abstand zum 10-Monats-Durchschnitt (Trend)
    feats["trend_10m"] = p / p.rolling(10).mean() - 1
    # Inverse realisierte Volatilität (12M), hoch = ruhiges Asset
    rets = p.pct_change()
    feats["inv_vol"] = 1 / rets.rolling(12).std().replace(0, np.nan)
    # Relative Stärke: Momentum vs. Querschnittsmittel
    feats["rel_mom_6m"] = feats["mom_6m"].sub(feats["mom_6m"].mean(axis=1), axis=0)
    # Kurzfrist-Reversal (letzter Monat), erwartetes Vorzeichen negativ
    feats["rev_1m"] = rets
    # 36-Monats-Umkehr (DeBondt/Thaler): Rendite der Monate t-36..t-12
    feats["lt_rev_36m"] = p.shift(12) / p.shift(36) - 1
    return feats


# ---------------------------------------------------------------------------
# Makro-Features (Zeitreihe)
# ---------------------------------------------------------------------------
def _z(s: pd.Series, window: int = 60, min_periods: int = 36) -> pd.Series:
    """Rollierender z-Score (nur Vergangenheit)."""
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - mu) / sd.replace(0, np.nan)


def macro_features(macro: pd.DataFrame) -> pd.DataFrame:
    """Niveaus, 3-Monats-Änderungen und rollierende z-Scores der wichtigsten Treiber.

    Erwartet Spalten aus data/macro_monthly.csv. Fehlende Spalten werden übersprungen.
    """
    f = pd.DataFrame(index=macro.index)
    specs = {
        # Name          Quelle            Änderungsfenster
        "real10":       ("REAL_GS10", 3),
        "real10_12":    ("REAL_GS10", 12),
        "nom10":        ("GS10", 3),
        "ff":           ("FEDFUNDS", 3),
        "curve":        ("CURVE_10Y3M", 3),
        "cpi_yoy":      ("CPI_YOY", 3),
        "cpi_core_yoy": ("CPI_CORE_YOY", 3),
        "cpi_3m":       ("CPI_3M_ANN", 1),
        "usd":          ("USD_IDX", 3),
        "usd_12":       ("USD_IDX", 12),
        "credit":       ("CREDIT_BAA_AAA", 3),
        "hy_oas":       ("HY_OAS", 3),
        "vix":          ("VIX", 1),
        "indpro_yoy":   ("INDPRO_YOY", 3),
        "indpro_3m":    ("INDPRO_3M_ANN", 1),
        "payems_yoy":   ("PAYEMS_YOY", 3),
        "unrate":       ("UNRATE", 3),
        "claims":       ("CLAIMS", 3),
        "umcsent":      ("UMCSENT", 3),
        "m2_yoy":       ("M2_YOY", 3),
        "gs_ratio":     ("GOLD_SILVER_RATIO", 1),
        "sp_pe":        ("SP_PE", 3),
        "caputil":      ("CAPUTIL", 3),
    }
    for name, (col, h) in specs.items():
        if col not in macro.columns:
            continue
        s = macro[col].astype(float)
        if col in ("USD_IDX", "CLAIMS", "GOLD_SILVER_RATIO", "SP_PE"):
            chg = np.log(s).diff(h)        # relative Änderung für Niveaugrössen
        else:
            chg = s.diff(h)                # Prozentpunkte für Zinsen/Raten
        f[f"{name}_lvl"] = s
        f[f"{name}_chg"] = chg
        f[f"{name}_z"] = _z(s)
    # Gold/Silber-Ratio: Abstand vom 10-Jahres-Mittel (Mean-Reversion-Signal)
    if "GOLD_SILVER_RATIO" in macro.columns:
        r = np.log(macro["GOLD_SILVER_RATIO"])
        f["gs_ratio_dev120"] = r - r.rolling(120, min_periods=60).mean()
    return f


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------
def macro_regime(macro: pd.DataFrame, growth_col: str | None = None, infl_col: str | None = None,
                 smooth: int = 3, lag: int = 1) -> pd.DataFrame:
    """Wachstum × Inflation Quadranten nach Trendrichtung.

    growth: 3M-Durchschnitt der Industrieproduktions-Jahresrate steigt ("high") oder fällt ("low")
    inflation: 3M-Durchschnitt der CPI-Jahresrate steigt oder fällt
    Trendrichtung (nicht Niveau) ist das übliche Rotationssignal (vgl. Hedgeye/Bridgewater-Quadranten).
    Makrodaten erscheinen ~1 Monat verzögert → Ergebnis um `lag` Monate verschoben.

    Akzeptiert sowohl das Rohformat (INDPRO, CPIAUCSL) als auch das Makro-Panel (INDPRO_YOY, CPI_YOY).
    """
    if growth_col is None:
        growth_col = "INDPRO_YOY" if "INDPRO_YOY" in macro.columns else "INDPRO"
    if infl_col is None:
        infl_col = "CPI_YOY" if "CPI_YOY" in macro.columns else "CPIAUCSL"
    g = macro[growth_col].astype(float)
    i = macro[infl_col].astype(float)
    if growth_col == "INDPRO":
        g = g.pct_change(12) * 100
    if infl_col == "CPIAUCSL":
        i = i.pct_change(12) * 100
    g_s, i_s = g.rolling(smooth).mean(), i.rolling(smooth).mean()
    g_dir = np.where(g_s > g_s.shift(smooth), "high", "low")
    i_dir = np.where(i_s > i_s.shift(smooth), "high", "low")
    out = pd.DataFrame({"growth": g_dir, "inflation": i_dir}, index=macro.index)
    valid = g_s.shift(smooth).notna() & i_s.shift(smooth).notna()
    out.loc[~valid, ["growth", "inflation"]] = "unknown"
    out["regime"] = out["growth"] + "_" + out["inflation"]
    out.loc[~valid, "regime"] = "unknown"
    return out.shift(lag)


def direction_regimes(macro: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
    """Weitere binäre Regimes (steigend/fallend über 3 Monate) für die Auswertung."""
    out = pd.DataFrame(index=macro.index)
    for name, col in [("real_yield", "REAL_GS10"), ("dollar", "USD_IDX"), ("curve", "CURVE_10Y3M"),
                      ("credit", "CREDIT_BAA_AAA"), ("fedfunds", "FEDFUNDS")]:
        if col in macro.columns:
            s = macro[col].rolling(3).mean()
            d = np.where(s > s.shift(3), "rising", "falling")
            d = pd.Series(d, index=macro.index).where(s.shift(3).notna(), "unknown")
            out[name] = d
    if "VIX" in macro.columns:
        v = macro["VIX"]
        out["vix"] = pd.Series(np.where(v > 25, "high", "low"), index=macro.index).where(v.notna(), "unknown")
    if "CPI_YOY" in macro.columns:
        c = macro["CPI_YOY"]
        out["infl_level"] = pd.Series(np.where(c > 4, ">4%", np.where(c > 2, "2-4%", "<2%")), index=macro.index).where(c.notna(), "unknown")
    return out.shift(lag)
