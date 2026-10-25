"""Datenzugriff.

Drei Datensätze:
  load_long_history()  – data/assets_monthly.csv + data/macro_monthly.csv (1959–2025, offline, gebaut
                         von scripts/build_dataset.py aus öffentlichen Quellen, siehe data/DATA_SOURCES.md)
  load_etf_dataset()   – data/prices_daily.csv + fred_*.csv aus scripts/collect_data.py (Yahoo/FRED, Internet)
  synthetic_*()        – Zufallsdaten für Smoke-Tests
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Langfrist-Panel (offline)
# ---------------------------------------------------------------------------
def load_long_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    assets = pd.read_csv(os.path.join(DATA_DIR, "assets_monthly.csv"), index_col=0, parse_dates=True)
    macro = pd.read_csv(os.path.join(DATA_DIR, "macro_monthly.csv"), index_col=0, parse_dates=True)
    return assets, macro


# ---------------------------------------------------------------------------
# ETF-Datensatz (nach scripts/collect_data.py)
# ---------------------------------------------------------------------------
def load_etf_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monatsendpreise (Spalten = Ticker) und Monats-Makropanel im selben Spaltenschema wie
    das Langfrist-Panel (CPI_YOY, INDPRO_YOY, REAL_GS10, USD_IDX, VIX, HY_OAS, ...)."""
    p = pd.read_csv(os.path.join(DATA_DIR, "prices_daily.csv"), index_col=0, parse_dates=True)
    monthly = p.resample("ME").last()
    fd = pd.read_csv(os.path.join(DATA_DIR, "fred_daily.csv"), index_col=0, parse_dates=True).resample("ME").last()
    fm = pd.read_csv(os.path.join(DATA_DIR, "fred_monthly.csv"), index_col=0, parse_dates=True)
    fm.index = fm.index + pd.offsets.MonthEnd(0)
    m = pd.DataFrame(index=monthly.index)
    m["CPI"] = fm.get("CPIAUCSL")
    m["CPI_YOY"] = m["CPI"].pct_change(12) * 100
    m["CPI_3M_ANN"] = ((m["CPI"] / m["CPI"].shift(3)) ** 4 - 1) * 100
    m["INDPRO"] = fm.get("INDPRO")
    m["INDPRO_YOY"] = m["INDPRO"].pct_change(12) * 100
    m["INDPRO_3M_ANN"] = ((m["INDPRO"] / m["INDPRO"].shift(3)) ** 4 - 1) * 100
    m["PAYEMS_YOY"] = fm["PAYEMS"].pct_change(12) * 100 if "PAYEMS" in fm else np.nan
    m["UNRATE"] = fm.get("UNRATE")
    m["FEDFUNDS"] = fm.get("FEDFUNDS")
    m["TB3M"] = fm.get("TB3MS")
    m["GS10"] = fd.get("DGS10")
    m["GS2"] = fd.get("DGS2")
    m["REAL_GS10"] = m["GS10"] - m["CPI_YOY"]
    m["TIPS_REAL10"] = fd.get("DFII10")        # Markt-Realzins (ab 2003)
    m["BREAKEVEN10"] = fd.get("T10YIE")
    m["CURVE_10Y3M"] = m["GS10"] - m["TB3M"]
    m["CURVE_10Y2Y"] = fd.get("T10Y2Y")
    m["CREDIT_BAA_AAA"] = fm["BAA"] - fm["AAA"] if "BAA" in fm and "AAA" in fm else np.nan
    m["HY_OAS"] = fd.get("BAMLH0A0HYM2")
    m["IG_OAS"] = fd.get("BAMLC0A0CM")
    m["VIX"] = fd.get("VIXCLS")
    m["USD_IDX"] = fd.get("DTWEXBGS")
    m["NFCI"] = fd.get("NFCI")
    m["UMCSENT"] = fm.get("UMCSENT")
    m["MICH_INFL_EXP"] = fm.get("MICH")
    m["M2_YOY"] = fm["M2SL"].pct_change(12) * 100 if "M2SL" in fm else np.nan
    if "GLD" in monthly and "SLV" in monthly:
        m["GOLD_SILVER_RATIO"] = monthly["GLD"] / monthly["SLV"]
    return monthly, m


def load_prices(tickers: list[str], start: str, use_cache: bool = True) -> pd.DataFrame:
    """Adjusted-Close-Preise, täglich (Yahoo), mit CSV-Cache."""
    path = os.path.join(DATA_DIR, "prices_daily.csv")
    if use_cache and os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if set(tickers).issubset(df.columns):
            return df[tickers]
    import yfinance as yf

    raw = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    df = raw.dropna(how="all")
    df.to_csv(path)
    return df[tickers]


def to_monthly(prices: pd.DataFrame) -> pd.DataFrame:
    """Tagespreise → Monatsendpreise."""
    return prices.resample("ME").last()


# ---------------------------------------------------------------------------
# Synthetische Daten für Smoke-Tests ohne Internet
# ---------------------------------------------------------------------------
def synthetic_prices(tickers: list[str], start: str, years: int = 20, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=years * 252)
    n, k = len(idx), len(tickers)
    drift = np.zeros((n, k))
    for j in range(k):
        d = 0.0
        for i in range(n):
            d = 0.98 * d + rng.normal(0, 0.0004)
            drift[i, j] = d
    vol = rng.uniform(0.10, 0.30, size=k) / np.sqrt(252)
    rets = drift + rng.normal(0, 1, size=(n, k)) * vol
    prices = 100 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=idx, columns=tickers)


def synthetic_macro(index: pd.DatetimeIndex, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    m = index.to_series().resample("ME").last().index
    n = len(m)
    indpro = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.008, n)))
    cpi = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.003, n)))
    df = pd.DataFrame({"INDPRO": indpro, "CPI": cpi}, index=m)
    df["INDPRO_YOY"] = df["INDPRO"].pct_change(12) * 100
    df["CPI_YOY"] = df["CPI"].pct_change(12) * 100
    df["GS10"] = 4 + np.cumsum(rng.normal(0, 0.1, n))
    df["REAL_GS10"] = df["GS10"] - df["CPI_YOY"]
    df["USD_IDX"] = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return df
