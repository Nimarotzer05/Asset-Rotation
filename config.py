"""Zentrale Konfiguration: Universen, Datenreihen, Modellparameter, Kosten."""

# ---------------------------------------------------------------------------
# A) ETF-Universum (ab ~2004, Yahoo Finance; braucht scripts/collect_data.py)
# ---------------------------------------------------------------------------
UNIVERSE = {
    "SPY": "US-Aktien (S&P 500)",
    "EFA": "Aktien entwickelte Märkte ex-US",
    "EEM": "Aktien Schwellenländer",
    "TLT": "US-Staatsanleihen 20y+",
    "IEF": "US-Staatsanleihen 7-10y",
    "TIP": "Inflationsgeschützte Anleihen",
    "GLD": "Gold",
    "SLV": "Silber",
    "DBC": "Breiter Rohstoffkorb",
    "VNQ": "US-REITs",
}
CASH = "BIL"  # T-Bill-ETF als Cash-Proxy

# ---------------------------------------------------------------------------
# B) Langfrist-Universum (1968–2025, aus data/assets_monthly.csv; offline nutzbar)
#    Total-Return-Indizes für Aktien/Anleihen/Cash, Spotpreise für Metalle/Rohstoffe.
# ---------------------------------------------------------------------------
LONG_UNIVERSE = {
    "US_EQ": "US-Aktien Total Return (S&P 500 inkl. Dividenden)",
    "UST10": "10y US-Treasury Total Return (synthetisch aus GS10)",
    "GOLD": "Gold, LBMA PM-Fix, Monatsende",
    "SILVER": "Silber, LBMA Fix, Monatsende",
    "WB_ENERGY": "World-Bank-Energieindex (Spot, Monatsdurchschnitt)",
    "WB_BASEMETALS": "World-Bank-Basismetallindex ex Eisenerz (Spot, Monatsdurchschnitt)",
}
# Robustheits-Universum: nur echte Monatsendkurse (keine Monatsdurchschnitte)
LONG_UNIVERSE_MONTHEND = ["US_EQ", "UST10", "GOLD", "SILVER"]
LONG_CASH = "TBILL"
LONG_START = "1972-12-31"  # nach Bretton Woods; Dollar-Index ab 1973

# ---------------------------------------------------------------------------
# FRED-Reihen für scripts/collect_data.py (eigener Rechner)
# ---------------------------------------------------------------------------
FRED_DAILY = {
    "DGS2": "2y Treasury",
    "DGS10": "10y Treasury",
    "DFII10": "10y TIPS-Realzins",
    "T10YIE": "10y Breakeven-Inflation",
    "T10Y2Y": "Zinskurve 10y–2y",
    "BAMLH0A0HYM2": "High-Yield OAS",
    "BAMLC0A0CM": "Investment-Grade OAS",
    "VIXCLS": "VIX",
    "DTWEXBGS": "Handelsgewichteter Dollar (broad)",
    "NFCI": "Chicago Fed Financial Conditions (wöchentlich)",
    "DCOILWTICO": "WTI Spot",
}
FRED_MONTHLY = {
    "INDPRO": "Industrieproduktion",
    "PAYEMS": "Beschäftigung (Nonfarm)",
    "UNRATE": "Arbeitslosenquote",
    "CPIAUCSL": "CPI",
    "CPILFESL": "Kern-CPI",
    "PCEPILFE": "Kern-PCE",
    "FEDFUNDS": "Fed Funds",
    "TB3MS": "3M T-Bill",
    "GS2": "2y CMT (monatlich)",
    "GS10": "10y CMT (monatlich)",
    "BAA": "Moody's Baa",
    "AAA": "Moody's Aaa",
    "UMCSENT": "Konsumentenstimmung Michigan",
    "MICH": "Inflationserwartung 1y Michigan",
    "M2SL": "M2",
    "HOUST": "Baubeginne",
    "ICSA": "Erstanträge Arbeitslosenhilfe (wöchentlich)",
}
# Rückwärtskompatibel (altes Skript)
FRED_SERIES = {k: v for k, v in FRED_MONTHLY.items() if k in ("INDPRO", "CPIAUCSL")} | {
    "DFII10": FRED_DAILY["DFII10"],
    "DTWEXBGS": FRED_DAILY["DTWEXBGS"],
}

START = "2004-01-01"

# ---------------------------------------------------------------------------
# Signal: Gewichte der Asset-Features im Composite-Score (werden normiert)
# ---------------------------------------------------------------------------
FEATURE_WEIGHTS = {
    "mom_3m": 0.20,
    "mom_6m": 0.30,
    "mom_12m": 0.30,
    "trend_10m": 0.20,
    "inv_vol": 0.10,
}

# Regime-Tilts (Bonus auf den z-Score). Quadranten: (Wachstum, Inflation) jeweils
# "high" = Trend steigt, "low" = Trend fällt. Für beide Universen definiert.
REGIME_TILTS = {
    ("high", "low"):  {"SPY": 0.3, "EEM": 0.2, "VNQ": 0.2,            "US_EQ": 0.3, "WB_BASEMETALS": 0.2},
    ("high", "high"): {"DBC": 0.3, "SLV": 0.2, "TIP": 0.2, "EEM": 0.1, "WB_ENERGY": 0.3, "WB_BASEMETALS": 0.2, "SILVER": 0.2},
    ("low", "high"):  {"GLD": 0.4, "SLV": 0.2, "TIP": 0.2, "DBC": 0.1, "GOLD": 0.4, "SILVER": 0.2, "WB_ENERGY": 0.1},
    ("low", "low"):   {"TLT": 0.4, "IEF": 0.3, "GLD": 0.1,            "UST10": 0.4, "GOLD": 0.1},
}

# Makro-Tilts (datengetriebene Alternative zu den Quadranten): Vorzeichen der
# erwarteten Wirkung einer *Änderung* des Faktors auf das Asset, siehe analysis.py
MACRO_FACTORS = ["REAL_GS10", "USD_IDX", "CPI_YOY", "VIX", "CREDIT_BAA_AAA", "CURVE_10Y3M"]

TOP_N = 3
TRANSACTION_COST_BPS = 15
TREND_FILTER = True  # Assets unter 10M-Schnitt werden durch Cash ersetzt
