"""Baut aus den Rohquellen in data/raw/ zwei Monatspanels (Monatsende-Index):

  data/assets_monthly.csv  Total-Return-Indizes bzw. Preisniveaus der Anlageklassen (1960/1968–2025)
  data/macro_monthly.csv   Zinsen, Inflation, Makro-Aktivität, Risikoappetit, Dollar (1959–2026)

Alle Quellen sind in data/DATA_SOURCES.md dokumentiert. Nach einem Lauf von
scripts/collect_data.py (eigener Rechner, Internet) werden zusätzlich die
Yahoo-/FRED-Reihen in data/ abgelegt; dieses Skript benötigt sie nicht.

Aufruf:  python scripts/build_dataset.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data")


def me(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Beliebiges Datum → Monatsende desselben Monats."""
    return pd.DatetimeIndex(idx) + MonthEnd(0)


def daily_to_me(s: pd.Series) -> pd.Series:
    """Tagesreihe → letzter Wert des Monats (Monatsende-Stempel)."""
    s = s.dropna().sort_index()
    return s.resample("ME").last()


# --------------------------------------------------------------------------
# 1. FRED-MD (monatliche Makrodatenbank, McCracken & Ng), Vintage 2026-10
# --------------------------------------------------------------------------
def load_fred_md() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(RAW, "fred_md_2026-10.csv"), skiprows=[1])
    df = df.rename(columns={"sasdate": "date"})
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    df = df.set_index("date").sort_index()
    df.index = me(df.index)
    df = df.apply(pd.to_numeric, errors="coerce")
    return df


# --------------------------------------------------------------------------
# 2. Edelmetalle (LBMA Tagesfixing → Monatsende) und World Bank Pink Sheet
# --------------------------------------------------------------------------
def load_lbma(name: str) -> pd.Series:
    df = pd.read_csv(os.path.join(RAW, f"lbma_{name}_daily.csv"), parse_dates=["date"]).set_index("date")
    col = [c for c in df.columns if c.endswith("_usd")][0]
    s = pd.to_numeric(df[col], errors="coerce").replace(0, np.nan)
    return daily_to_me(s).rename(name.upper())


def load_worldbank() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monatsdurchschnittspreise (nominal USD) und Indizes (2010=100)."""
    path = os.path.join(RAW, "wb_commodity_prices_monthly.xlsx")
    x = pd.ExcelFile(path)

    p = x.parse("Monthly Prices", header=None)
    names = p.iloc[4].tolist()
    data = p.iloc[6:].copy()
    data.columns = ["date"] + names[1:]
    data["date"] = pd.to_datetime(data["date"].astype(str), format="%YM%m")
    data = data.set_index("date")
    data.index = me(data.index)
    data = data.apply(pd.to_numeric, errors="coerce")
    prices = data[
        ["Crude oil, average", "Crude oil, WTI", "Copper", "Aluminum", "Nickel", "Gold", "Silver", "Platinum", "Natural gas, US"]
    ].rename(
        columns={
            "Crude oil, average": "WB_OIL",
            "Crude oil, WTI": "WB_WTI",
            "Copper": "WB_COPPER",
            "Aluminum": "WB_ALUMINUM",
            "Nickel": "WB_NICKEL",
            "Gold": "WB_GOLD_AVG",
            "Silver": "WB_SILVER_AVG",
            "Platinum": "WB_PLATINUM",
            "Natural gas, US": "WB_NATGAS",
        }
    )

    i = x.parse("Monthly Indices", header=None)
    idx = i.iloc[9:, [0, 1, 2, 3, 4, 13, 14, 15, 16]].copy()
    idx.columns = ["date", "WB_TOTAL", "WB_ENERGY", "WB_NONENERGY", "WB_AGRI", "WB_FERT", "WB_METALS", "WB_BASEMETALS", "WB_PRECIOUS"]
    idx["date"] = pd.to_datetime(idx["date"].astype(str), format="%YM%m")
    idx = idx.set_index("date")
    idx.index = me(idx.index)
    idx = idx.apply(pd.to_numeric, errors="coerce")
    return prices, idx


# --------------------------------------------------------------------------
# 3. US-Aktien Total Return (täglich, 1885–2025) → Monatsende
# --------------------------------------------------------------------------
def load_us_equity() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(RAW, "us_market_data_daily.csv"), parse_dates=["Date"]).set_index("Date")
    out = pd.DataFrame(
        {
            "US_EQ": daily_to_me(df["Adjusted Close"]),  # inkl. Dividenden, SPY-ähnlich
            "US_EQ_PRICE": daily_to_me(df["Close"]),
        }
    )
    return out


def load_shiller() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(RAW, "shiller_sp500_monthly.csv"), parse_dates=["Date"]).set_index("Date")
    df.index = me(df.index)
    df = df.replace(0.0, np.nan)
    return df.rename(columns={"SP500": "SHILLER_SP500_AVG", "Dividend": "SHILLER_DIV", "Earnings": "SHILLER_EPS", "PE10": "SHILLER_CAPE", "Long Interest Rate": "SHILLER_GS10"})[
        ["SHILLER_SP500_AVG", "SHILLER_DIV", "SHILLER_EPS", "SHILLER_CAPE", "SHILLER_GS10"]
    ]


# --------------------------------------------------------------------------
# 4. Synthetische Treasury-Total-Returns aus Constant-Maturity-Renditen
# --------------------------------------------------------------------------
def bond_total_return(yields_pct: pd.Series, maturity_years: float, freq: int = 2) -> pd.Series:
    """Monatlicher Total Return einer Par-Anleihe mit Laufzeit `maturity_years`.

    Standardansatz (vgl. Swinkels 2019, 'Treasury Bond Return Data Starting in 1962'):
    Am Monatsanfang wird eine Par-Anleihe mit Kupon = aktueller Rendite gekauft,
    nach einem Monat zur neuen Rendite bewertet (Restlaufzeit T − 1/12) und
    der anteilige Kupon vereinnahmt.
    """
    y = yields_pct.astype(float) / 100.0
    y_prev = y.shift(1)
    c = y_prev  # Kupon = Rendite bei Kauf
    T = maturity_years - 1.0 / 12.0
    n = int(round(T * freq))
    # Preis einer Anleihe (Nominal 1) mit Kupon c, Rendite y, n Perioden, halbjährliche Zahlung
    per = y / freq
    price = (c / freq) * (1 - (1 + per) ** (-n)) / per + (1 + per) ** (-n)
    tr = price + c / 12.0 - 1.0  # Kursänderung + ein Monat Kuponabgrenzung
    return tr


# --------------------------------------------------------------------------
# 5. Risiko- und Dollar-Reihen (täglich → Monatsende)
# --------------------------------------------------------------------------
def load_vix() -> pd.Series:
    df = pd.read_csv(os.path.join(RAW, "vix_daily.csv"), parse_dates=["DATE"]).set_index("DATE")
    return daily_to_me(df["CLOSE"]).rename("VIX")


def load_hy_oas() -> pd.Series:
    df = pd.read_csv(os.path.join(RAW, "hy_oas_daily_1996_2021.csv"), parse_dates=["DATE"]).set_index("DATE")
    return daily_to_me(pd.to_numeric(df["BAMLH0A0HYM2"], errors="coerce")).rename("HY_OAS")


def load_dollar() -> pd.DataFrame:
    major = pd.read_csv(os.path.join(RAW, "fred_usd_major_index.csv"), parse_dates=["observation_date"]).set_index("observation_date")["DTWEXM"]
    broad = pd.read_csv(os.path.join(RAW, "fred_usd_broad_index.csv"), parse_dates=["observation_date"]).set_index("observation_date")["DTWEXBGS"]
    major = daily_to_me(pd.to_numeric(major, errors="coerce"))
    broad = daily_to_me(pd.to_numeric(broad, errors="coerce"))
    # Verkettung: Major-Index bis zum ersten gemeinsamen Monat, danach Broad-Index skaliert
    link = major.index.intersection(broad.index).min()
    scale = major.loc[link] / broad.loc[link]
    usd = pd.concat([major.loc[:link], (broad * scale).loc[link + pd.Timedelta(days=1):]])
    return pd.DataFrame({"USD_IDX": usd, "USD_MAJOR": major, "USD_BROAD": broad})


# --------------------------------------------------------------------------
# Zusammenbau
# --------------------------------------------------------------------------
def build() -> None:
    fred = load_fred_md()
    gold = load_lbma("gold")
    silver = load_lbma("silver")
    wb_prices, wb_idx = load_worldbank()
    eq = load_us_equity()
    shiller = load_shiller()
    vix = load_vix()
    hy = load_hy_oas()
    usd = load_dollar()

    # ---------------- Asset-Panel ----------------
    a = pd.DataFrame(index=pd.date_range("1959-01-31", "2026-09-30", freq="ME"))
    a["US_EQ"] = eq["US_EQ"]
    a["GOLD"] = gold
    a["SILVER"] = silver
    # Vor dem LBMA-Start (1968) World-Bank-Monatsdurchschnitt (Goldpreis fix 35$)
    a["GOLD"] = a["GOLD"].fillna(wb_prices["WB_GOLD_AVG"].where(wb_prices.index < gold.index.min()))
    tb = fred["TB3MS"]
    a["TBILL"] = (1 + tb.shift(1) / 1200.0).cumprod() * 100.0  # Index aus Vormonatsrendite
    a["UST10"] = (1 + bond_total_return(fred["GS10"], 10.0)).cumprod() * 100.0
    a["UST5"] = (1 + bond_total_return(fred["GS5"], 5.0)).cumprod() * 100.0
    a["UST1"] = (1 + bond_total_return(fred["GS1"], 1.0)).cumprod() * 100.0
    for col in ["WB_ENERGY", "WB_BASEMETALS", "WB_METALS", "WB_AGRI", "WB_NONENERGY", "WB_TOTAL", "WB_PRECIOUS"]:
        a[col] = wb_idx[col]
    for col in ["WB_OIL", "WB_WTI", "WB_COPPER", "WB_ALUMINUM", "WB_NICKEL", "WB_NATGAS", "WB_PLATINUM", "WB_GOLD_AVG", "WB_SILVER_AVG"]:
        a[col] = wb_prices[col]
    a["SHILLER_SP500_AVG"] = shiller["SHILLER_SP500_AVG"]
    a.index.name = "date"
    a = a.loc["1959-12-31":"2025-12-31"]
    a.to_csv(os.path.join(OUT, "assets_monthly.csv"), float_format="%.6f")

    # ---------------- Makro-Panel ----------------
    keep = {
        # Aktivität / Arbeitsmarkt
        "INDPRO": "INDPRO", "CUMFNS": "CAPUTIL", "PAYEMS": "PAYEMS", "UNRATE": "UNRATE", "CLAIMSx": "CLAIMS",
        "HOUST": "HOUST", "PERMIT": "PERMIT", "AMDMNOx": "DURGOODS_ORD", "ACOGNO": "CONSGOODS_ORD",
        "RETAILx": "RETAIL", "RPI": "REAL_INCOME", "AWHMAN": "HOURS_MFG", "UMCSENTx": "UMCSENT",
        # Preise
        "CPIAUCSL": "CPI", "CPIULFSL": "CPI_CORE", "PCEPI": "PCE", "PPICMM": "PPI_METALS", "OILPRICEx": "OIL_FRED",
        # Geld / Kredit
        "M2SL": "M2", "BUSLOANS": "BUSLOANS",
        # Zinsen
        "FEDFUNDS": "FEDFUNDS", "TB3MS": "TB3M", "TB6MS": "TB6M", "GS1": "GS1", "GS5": "GS5", "GS10": "GS10",
        "AAA": "AAA", "BAA": "BAA",
        # Dollar / FX
        "TWEXAFEGSMTHx": "USD_TW_AVG", "EXSZUSx": "USDCHF", "EXJPUSx": "USDJPY", "EXUSUKx": "GBPUSD",
        # Aktienbewertung / Vol
        "S&P div yield": "SP_DIVYIELD", "S&P PE ratio": "SP_PE", "VIXCLSx": "VIX_AVG",
    }
    m = fred[list(keep)].rename(columns=keep)
    m["VIX"] = vix
    m["HY_OAS"] = hy
    m = m.join(usd[["USD_IDX"]])
    m["SHILLER_CAPE"] = shiller["SHILLER_CAPE"]
    m["SHILLER_EPS"] = shiller["SHILLER_EPS"]
    # Abgeleitete Grössen
    m["CPI_YOY"] = m["CPI"].pct_change(12) * 100
    m["CPI_CORE_YOY"] = m["CPI_CORE"].pct_change(12) * 100
    m["CPI_3M_ANN"] = ((m["CPI"] / m["CPI"].shift(3)) ** 4 - 1) * 100
    m["PCE_YOY"] = m["PCE"].pct_change(12) * 100
    m["INDPRO_YOY"] = m["INDPRO"].pct_change(12) * 100
    m["INDPRO_3M_ANN"] = ((m["INDPRO"] / m["INDPRO"].shift(3)) ** 4 - 1) * 100
    m["PAYEMS_YOY"] = m["PAYEMS"].pct_change(12) * 100
    m["UNRATE_CHG12"] = m["UNRATE"].diff(12)
    m["M2_YOY"] = m["M2"].pct_change(12) * 100
    m["REAL_GS10"] = m["GS10"] - m["CPI_YOY"]          # Ex-post-Realzins (lange Historie)
    m["REAL_FF"] = m["FEDFUNDS"] - m["CPI_YOY"]
    m["CURVE_10Y3M"] = m["GS10"] - m["TB3M"]
    m["CURVE_10Y1Y"] = m["GS10"] - m["GS1"]
    m["CREDIT_BAA_AAA"] = m["BAA"] - m["AAA"]
    m["CREDIT_BAA_GS10"] = m["BAA"] - m["GS10"]
    m["GOLD_SILVER_RATIO"] = a["GOLD"] / a["SILVER"]
    m.index.name = "date"
    m = m.loc["1959-01-31":]
    m.to_csv(os.path.join(OUT, "macro_monthly.csv"), float_format="%.6f")

    # ---------------- Abdeckungsübersicht ----------------
    cov = []
    for name, df in [("assets_monthly", a), ("macro_monthly", m)]:
        for c in df.columns:
            s = df[c].dropna()
            cov.append({"file": name, "series": c, "start": s.index.min().date() if len(s) else None,
                        "end": s.index.max().date() if len(s) else None, "n": len(s)})
    pd.DataFrame(cov).to_csv(os.path.join(OUT, "coverage.csv"), index=False)
    print(pd.DataFrame(cov).to_string(index=False))


if __name__ == "__main__":
    build()
