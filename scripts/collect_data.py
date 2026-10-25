"""Lädt die aktuellen Markt- und Makrodaten (Yahoo Finance + FRED) auf dem eigenen Rechner.

Braucht Internet. Schreibt nach data/:
  prices_daily.csv      Adjusted Close der ETFs/Indizes/Futures (Yahoo)
  fred_daily.csv        tägliche FRED-Reihen (Realzins, Breakeven, HY-Spread, ...)
  fred_monthly.csv      monatliche FRED-Reihen (Makro)

Aufruf:  python scripts/collect_data.py [--start 1990-01-01]
Danach:  python run.py --dataset etf
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config as C  # noqa: E402

OUT = os.path.join(ROOT, "data")
os.makedirs(OUT, exist_ok=True)

# Längere Historie als die ETFs: Indizes und Futures (Yahoo)
EXTRA_TICKERS = {
    "^GSPC": "S&P 500 Kursindex (ab 1927)",
    "^TNX": "10y Treasury Yield (ab 1962)",
    "^VIX": "VIX (ab 1990)",
    "GC=F": "Gold Futures (ab 2000)",
    "SI=F": "Silber Futures (ab 2000)",
    "CL=F": "WTI Futures (ab 2000)",
    "HG=F": "Kupfer Futures (ab 2000)",
    "DX-Y.NYB": "Dollar Index DXY (ab 1971)",
    "^SPGSCI": "S&P GSCI (Rohstoffe)",
}


def fetch_yahoo(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf

    frames = []
    for t in tickers:  # einzeln, damit ein fehlender Ticker nicht alles abbricht
        for attempt in range(3):
            try:
                df = yf.download(t, start=start, auto_adjust=True, progress=False)
                if not df.empty:
                    s = df["Close"]
                    s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
                    frames.append(s.rename(t))
                    print(f"  {t:10s} {len(s):6d} Tage  {s.index.min().date()} → {s.index.max().date()}")
                else:
                    print(f"  {t:10s} leer")
                break
            except Exception as e:  # noqa: BLE001
                print(f"  {t}: Versuch {attempt + 1} fehlgeschlagen ({e})")
                time.sleep(2)
    return pd.concat(frames, axis=1).sort_index()


def fetch_fred(series: list[str], start: str) -> pd.DataFrame:
    from pandas_datareader import data as pdr

    frames = []
    for s in series:
        try:
            df = pdr.DataReader(s, "fred", start)
            frames.append(df[s])
            print(f"  {s:16s} {len(df):6d} Obs  {df.index.min().date()} → {df.index.max().date()}")
        except Exception as e:  # noqa: BLE001
            print(f"  {s}: fehlgeschlagen ({e})")
    return pd.concat(frames, axis=1).sort_index()


def main(start: str) -> None:
    print("Yahoo Finance ...")
    prices = fetch_yahoo(list(C.UNIVERSE) + [C.CASH] + list(EXTRA_TICKERS), start)
    prices.to_csv(os.path.join(OUT, "prices_daily.csv"))

    print("FRED (täglich) ...")
    daily = fetch_fred(list(C.FRED_DAILY), start)
    daily.to_csv(os.path.join(OUT, "fred_daily.csv"))

    print("FRED (monatlich) ...")
    monthly = fetch_fred(list(C.FRED_MONTHLY), start)
    monthly.to_csv(os.path.join(OUT, "fred_monthly.csv"))
    print("fertig →", OUT)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1990-01-01")
    main(ap.parse_args().start)
