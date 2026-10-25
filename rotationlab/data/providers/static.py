"""Static provider: the frozen research history in ``data/raw`` as point-in-time series.

This is the port of ``scripts/build_dataset.py`` and the loaders of ``scripts/run_equity.py``.
It produces two kinds of series:

* raw source columns under a namespace (``static:fredmd:INDPRO``, ``static:shiller:Earnings``,
  ``static:lbma:GOLD`` …), stored as delivered (daily stays daily);
* real-time FRED-MD (``static:fredmd_rt:INDPRO`` …) from the archived monthly vintages in
  ``data/raw/fredmd_vintages`` (``vintages.yaml``): every value carries the date of the first vintage
  file that showed it – one row per change, so 300 monthly vintages stay a few million rows. Kept apart
  from ``static:fredmd:*`` (one vintage, lag model, research parity) so the two never mix;
* the few research constructs that are not a plain column (``static:GOLD`` with the World Bank
  fill before 1968, synthetic Treasury total returns ``static:UST10``, ``static:TBILL``,
  ``static:USD_IDX``, French portfolios ``static:FF_*``) – same formulas as the research code, so
  the golden panel can be rebuilt from the store bit for bit (tests/golden/test_store_parity.py).

Vintage rule (ADR 022): a value is dated when a *live* system could have had the same information.
Returns and averages of public market prices (French portfolios, World Bank monthly averages,
FRED-MD monthly average yields, Shiller monthly average price, dollar indices) are public at
``obs_date`` because the live system observes the underlying prices in real time → ``0D``.
Statistics only their publisher knows (activity, labour, prices, money; S&P earnings and dividends;
ICE spreads) carry a publication lag. FRED-MD lags follow the research convention (``1M`` =
``shift(1)`` on the month-end panel), ``2M`` for releases that arrive more than ~4 weeks after the
month, ``6M`` for Shiller's interpolated earnings and dividends (audit 2026-10-24).

The catalog is code, not file content, so ``rotationlab validate`` needs no I/O.
"""
from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import AssetId, Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series

# ---------------------------------------------------------------------------
# FRED-MD (McCracken & Ng), vintage 2026-10: 126 series, monthly
# ---------------------------------------------------------------------------
FREDMD_CODES: tuple[str, ...] = (
    "RPI", "W875RX1", "DPCERA3M086SBEA", "CMRMTSPLx", "RETAILx", "INDPRO", "IPFPNSS", "IPFINAL", "IPCONGD",
    "IPDCONGD", "IPNCONGD", "IPBUSEQ", "IPMAT", "IPDMAT", "IPNMAT", "IPMANSICS", "IPB51222S", "IPFUELS", "CUMFNS",
    "HWI", "HWIURATIO", "CLF16OV", "CE16OV", "UNRATE", "UEMPMEAN", "UEMPLT5", "UEMP5TO14", "UEMP15OV",
    "UEMP15T26", "UEMP27OV", "CLAIMSx", "PAYEMS", "USGOOD", "CES1021000001", "USCONS", "MANEMP", "DMANEMP",
    "NDMANEMP", "SRVPRD", "USTPU", "USWTRADE", "USTRADE", "USFIRE", "USGOVT", "CES0600000007", "AWOTMAN",
    "AWHMAN", "HOUST", "HOUSTNE", "HOUSTMW", "HOUSTS", "HOUSTW", "PERMIT", "PERMITNE", "PERMITMW", "PERMITS",
    "PERMITW", "ACOGNO", "AMDMNOx", "ANDENOx", "AMDMUOx", "BUSINVx", "ISRATIOx", "M1SL", "M2SL", "M2REAL",
    "BOGMBASE", "TOTRESNS", "NONBORRES", "BUSLOANS", "REALLN", "NONREVSL", "CONSPI", "S&P 500", "S&P div yield",
    "S&P PE ratio", "FEDFUNDS", "CP3Mx", "TB3MS", "TB6MS", "GS1", "GS5", "GS10", "AAA", "BAA", "COMPAPFFx",
    "TB3SMFFM", "TB6SMFFM", "T1YFFM", "T5YFFM", "T10YFFM", "AAAFFM", "BAAFFM", "TWEXAFEGSMTHx", "EXSZUSx",
    "EXJPUSx", "EXUSUKx", "EXCAUSx", "WPSFD49207", "WPSFD49502", "WPSID61", "WPSID62", "OILPRICEx", "PPICMM",
    "CPIAUCSL", "CPIAPPSL", "CPITRNSL", "CPIMEDSL", "CUSR0000SAC", "CUSR0000SAD", "CUSR0000SAS", "CPIULFSL",
    "CUSR0000SA0L2", "CUSR0000SA0L5", "PCEPI", "DDURRG3M086SBEA", "DNDGRG3M086SBEA", "DSERRG3M086SBEA",
    "CES0600000008", "CES2000000008", "CES3000000008", "UMCSENTx", "DTCOLNVHFNM", "DTCTHFNM", "INVEST", "VIXCLSx",
)
_FREDMD_ID = {"S&P 500": "SP500", "S&P div yield": "SP_DIVYIELD", "S&P PE ratio": "SP_PE"}
_FREDMD_YIELD = {"FEDFUNDS", "CP3Mx", "TB3MS", "TB6MS", "GS1", "GS5", "GS10", "AAA", "BAA", "COMPAPFFx",
                 "TB3SMFFM", "TB6SMFFM", "T1YFFM", "T5YFFM", "T10YFFM", "AAAFFM", "BAAFFM"}
_FREDMD_MARKET_INDEX = {"S&P 500", "TWEXAFEGSMTHx", "EXSZUSx", "EXJPUSx", "EXUSUKx", "EXCAUSx", "VIXCLSx"}
_FREDMD_MARKET_PRICE = {"OILPRICEx"}
# Releases later than ~4 weeks after the reference month (personal income and outlays, M3 full report,
# business inventories, consumer credit, real manufacturing and trade sales; the help-wanted index is
# built from JOLTS, out ~5 weeks after the month – empty at the last month of every archived vintage,
# Fable review 2026-10-24).
_FREDMD_SLOW = {"RPI", "W875RX1", "DPCERA3M086SBEA", "CMRMTSPLx", "BUSINVx", "ISRATIOx", "NONREVSL", "CONSPI",
                "DTCOLNVHFNM", "DTCTHFNM", "ACOGNO", "AMDMNOx", "ANDENOx", "AMDMUOx", "PCEPI",
                "DDURRG3M086SBEA", "DNDGRG3M086SBEA", "DSERRG3M086SBEA", "HWI", "HWIURATIO"}
_FREDMD_EARNINGS_BASED = {"S&P div yield", "S&P PE ratio"}  # Shiller's interpolated dividends/earnings


def fredmd_series_id(code: str) -> SeriesId:
    return SeriesId(f"static:fredmd:{_FREDMD_ID.get(code, code)}")


def _fredmd_lag_kind(code: str) -> tuple[str, SeriesKind]:
    if code in _FREDMD_YIELD:
        return "0D", SeriesKind.YIELD
    if code in _FREDMD_MARKET_INDEX:
        return "0D", SeriesKind.INDEX
    if code in _FREDMD_MARKET_PRICE:
        return "0D", SeriesKind.PRICE
    if code in _FREDMD_EARNINGS_BASED:
        return "6M", SeriesKind.MACRO
    if code in _FREDMD_SLOW:
        return "2M", SeriesKind.MACRO
    return "1M", SeriesKind.MACRO


# ---------------------------------------------------------------------------
# Other groups
# ---------------------------------------------------------------------------
FRENCH_INDUSTRIES = ("NoDur", "Durbl", "Manuf", "Enrgy", "HiTec", "Telcm", "Shops", "Hlth", "Utils", "Other")
FF5_COLUMNS = ("MKT_RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF")
SHILLER_COLUMNS = {  # column -> (lag, kind)
    "SP500": ("0D", SeriesKind.INDEX),
    "Dividend": ("6M", SeriesKind.MACRO),
    "Earnings": ("6M", SeriesKind.MACRO),
    "Consumer Price Index": ("1M", SeriesKind.MACRO),
    "Long Interest Rate": ("0D", SeriesKind.YIELD),
    "PE10": ("6M", SeriesKind.MACRO),
}
WB_PRICES = {  # pink sheet column -> id
    "Crude oil, average": "WB_OIL", "Crude oil, WTI": "WB_WTI", "Copper": "WB_COPPER", "Aluminum": "WB_ALUMINUM",
    "Nickel": "WB_NICKEL", "Gold": "WB_GOLD_AVG", "Silver": "WB_SILVER_AVG", "Platinum": "WB_PLATINUM",
    "Natural gas, US": "WB_NATGAS",
}
WB_INDICES = ("WB_TOTAL", "WB_ENERGY", "WB_NONENERGY", "WB_AGRI", "WB_FERT", "WB_METALS", "WB_BASEMETALS", "WB_PRECIOUS")


@dataclass(frozen=True)
class _Entry:
    spec: SeriesSpec
    group: str
    column: str


def _shiller_slug(col: str) -> str:
    return col.replace(" ", "_")


def _build_catalog() -> dict[SeriesId, _Entry]:
    out: dict[SeriesId, _Entry] = {}

    def add(sid: str, group: str, column: str, kind: SeriesKind, freq: Frequency, lag: str = "0D",
            name: str = "", unit: str = "", asset: str | None = None) -> None:
        spec = SeriesSpec(series_id=SeriesId(sid), provider="static", provider_code=f"{group}:{column}", kind=kind,
                          frequency=freq, unit=unit, asset_id=AssetId(asset) if asset else None, lag=lag,
                          name=name or column)
        out[spec.series_id] = _Entry(spec, group, column)

    M, D = Frequency.MONTHLY, Frequency.DAILY
    for code in FREDMD_CODES:
        lag, kind = _fredmd_lag_kind(code)
        add(fredmd_series_id(code), "fredmd", code, kind, M, lag, name=f"FRED-MD {code}")
    for code in FREDMD_CODES:
        _, kind = _fredmd_lag_kind(code)
        sid = f"static:fredmd_rt:{_FREDMD_ID.get(code, code)}"
        spec = SeriesSpec(series_id=SeriesId(sid), provider="static", provider_code=f"fredmd_rt:{code}", kind=kind,
                          frequency=M, lag=_fredmd_lag_kind(code)[0], vintages="archive",
                          name=f"FRED-MD {code}, real time from archived vintages")
        out[spec.series_id] = _Entry(spec, "fredmd_rt", code)
    for col in ("Mkt-RF", "SMB", "HML", "RF"):
        add(f"static:french:ff3:{col.replace('-', '_').upper()}", "ff3", col, SeriesKind.RETURN, M, name=f"French FF3 {col}")
    for col in FF5_COLUMNS:
        add(f"static:french:ff5:{col.upper()}", "ff5", col, SeriesKind.RETURN, M, name=f"French FF5+Mom {col}")
    for col, (lag, kind) in SHILLER_COLUMNS.items():
        add(f"static:shiller:{_shiller_slug(col)}", "shiller", col, kind, M, lag, name=f"Shiller {col}")
    add("static:lbma:GOLD", "lbma", "GOLD", SeriesKind.PRICE, D, name="LBMA gold PM fix USD", unit="USD/oz")
    add("static:lbma:SILVER", "lbma", "SILVER", SeriesKind.PRICE, D, name="LBMA silver fix USD", unit="USD/oz")
    add("static:usmkt:TR", "usmkt", "Adjusted Close", SeriesKind.TOTAL_RETURN, D, name="US equities total return (S&P, dividends reinvested)")
    add("static:usmkt:CLOSE", "usmkt", "Close", SeriesKind.INDEX, D, name="US equities price index")
    add("static:cboe:VIX", "vix", "CLOSE", SeriesKind.INDEX, D, name="CBOE VIX close")
    add("static:ice:HY_OAS", "hyoas", "BAMLH0A0HYM2", SeriesKind.YIELD, D, "1D", name="ICE BofA US HY OAS", unit="pct")
    add("static:fred:DTWEXM", "usd", "DTWEXM", SeriesKind.INDEX, D, name="Trade-weighted dollar, major currencies")
    add("static:fred:DTWEXBGS", "usd", "DTWEXBGS", SeriesKind.INDEX, D, name="Trade-weighted dollar, broad")
    for col, sid in WB_PRICES.items():
        add(f"static:{sid}", "wb_prices", col, SeriesKind.PRICE, M, name=f"World Bank {col} (monthly average)")
    for sid in WB_INDICES:
        add(f"static:{sid}", "wb_indices", sid, SeriesKind.INDEX, M, name=f"World Bank index {sid} (2010=100, monthly average)")
    # research constructs
    add("static:GOLD", "constructs", "GOLD", SeriesKind.PRICE, M, name="Gold: LBMA month-end, World Bank average before 1968-04")
    add("static:TBILL", "constructs", "TBILL", SeriesKind.TOTAL_RETURN, M, name="T-bill index from TB3MS (month t earns TB3MS(t-1)/12)")
    for m in (10, 5, 1):
        add(f"static:UST{m}", "constructs", f"UST{m}", SeriesKind.TOTAL_RETURN, M, name=f"Synthetic {m}y Treasury total return (par bond, GS{m})")
    add("static:USD_IDX", "constructs", "USD_IDX", SeriesKind.INDEX, M, name="Dollar index: major currencies, broad from first overlap (chained)")
    add("static:FF_MKT", "constructs", "FF_MKT", SeriesKind.RETURN, M, name="US total market return (French Mkt-RF + RF)", asset="FF_MKT")
    for ind in FRENCH_INDUSTRIES:
        add(f"static:FF_{ind.upper()}", "ind10", ind, SeriesKind.RETURN, M, name=f"French industry {ind} (value-weighted)",
            asset=f"FF_{ind.upper()}")
    return out


STATIC_CATALOG: dict[SeriesId, _Entry] = _build_catalog()


def static_specs() -> dict[SeriesId, SeriesSpec]:
    return {sid: e.spec for sid, e in STATIC_CATALOG.items()}


# ---------------------------------------------------------------------------
# Loaders (ported from scripts/build_dataset.py, scripts/run_equity.py)
# ---------------------------------------------------------------------------
def _me(idx: pd.Index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx) + pd.offsets.MonthEnd(0)


def _daily_to_me(s: pd.Series) -> pd.Series:
    return s.dropna().sort_index().resample("ME").last()


def read_french_section(text: str, header_contains: str | None = None) -> pd.DataFrame:
    """First monthly block of a Kenneth French CSV (or the block after `header_contains`), in decimals."""
    lines = text.splitlines()
    start = 0
    if header_contains:
        start = next(i for i, ln in enumerate(lines) if header_contains in ln) + 1
    h = next(i for i in range(start, len(lines)) if lines[i].startswith(","))
    rows = [lines[h]]
    for ln in lines[h + 1:]:
        if not ln.strip() or not ln.strip()[:6].isdigit() or len(ln.split(",")[0].strip()) != 6:
            break
        rows.append(ln)
    df = pd.read_csv(io.StringIO("\n".join(rows)), index_col=0)
    df.index = pd.to_datetime(df.index.astype(str).str.strip(), format="%Y%m") + pd.offsets.MonthEnd(0)
    df = df.rename(columns=lambda c: str(c).strip())
    out: pd.DataFrame = df.apply(pd.to_numeric, errors="coerce").replace([-99.99, -999], np.nan) / 100.0
    return out


def bond_total_return(yields_pct: pd.Series, maturity_years: float, freq: int = 2) -> pd.Series:
    """Monthly total return of a par bond bought at the start of the month (Swinkels 2019)."""
    y = yields_pct.astype(float) / 100.0
    c = y.shift(1)
    n = int(round((maturity_years - 1.0 / 12.0) * freq))
    per = y / freq
    price = (c / freq) * (1 - (1 + per) ** (-n)) / per + (1 + per) ** (-n)
    return price + c / 12.0 - 1.0


class StaticProvider(BaseProvider):
    """Reads `raw_path`; one cached frame per source group."""

    name = "static"

    FILES = {
        "fredmd": "fred_md_2026-10.csv",
        "ff3": "ff_3_factors_monthly.csv",
        "ind10": "ff_10_industry_portfolios.csv",
        "ff5": "ff5_mom_monthly.csv.gz",
        "shiller": "shiller_sp500_monthly.csv",
        "lbma": ("lbma_gold_daily.csv", "lbma_silver_daily.csv"),
        "usmkt": "us_market_data_daily.csv",
        "vix": "vix_daily.csv",
        "hyoas": "hy_oas_daily_1996_2021.csv",
        "usd": ("fred_usd_major_index.csv", "fred_usd_broad_index.csv"),
        "wb_prices": "wb_commodity_prices_monthly.xlsx",
        "wb_indices": "wb_commodity_prices_monthly.xlsx",
    }
    VINTAGE_DIR = "fredmd_vintages"

    def __init__(self, raw_path: str | os.PathLike[str]) -> None:
        self.raw = Path(raw_path)
        self._cache: dict[str, pd.DataFrame] = {}

    # -- interface ---------------------------------------------------------
    def catalog(self) -> dict[SeriesId, SeriesSpec]:
        return static_specs()

    def fingerprint(self) -> str:
        """Hash of all raw files (incl. the vintage archive): unchanged files → nothing to ingest."""
        h = hashlib.sha256()
        names = sorted(self._all_files())
        vdir = self.raw / self.VINTAGE_DIR
        if vdir.exists():
            names += sorted(f"{self.VINTAGE_DIR}/{p.name}" for p in vdir.iterdir() if p.is_file())
        for name in names:
            p = self.raw / name
            h.update(name.encode())
            h.update(p.read_bytes() if p.exists() else b"<missing>")
        return h.hexdigest()[:16]

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        entry = STATIC_CATALOG.get(spec.series_id)
        if entry is None:
            raise DataError(f"static provider has no series {spec.series_id}")
        if entry.group == "fredmd_rt":
            return self._realtime_frame(entry.column, since)
        frame = self._group(entry.group)
        if entry.column not in frame.columns:
            raise DataError(f"{spec.series_id}: column '{entry.column}' missing in group {entry.group}")
        s = frame[entry.column]
        if s.dropna().empty:
            return empty_frame()
        # catalog spec carries the lag; config may not override static semantics
        return frame_from_series(s, entry.spec, since, normalise=entry.spec.frequency != Frequency.DAILY)

    # -- real-time FRED-MD -----------------------------------------------------
    def vintages(self) -> list[dict[str, object]]:
        """Entries of vintages.yaml with existing files, oldest first."""
        import yaml

        mf = self.raw / self.VINTAGE_DIR / "vintages.yaml"
        if not mf.exists():
            return []
        entries = yaml.safe_load(mf.read_text()).get("vintages", []) or []
        out: list[dict[str, object]] = []
        for e in entries:
            if not (self.raw / self.VINTAGE_DIR / str(e["file"])).exists():
                raise DataError(f"vintages.yaml lists missing file {e['file']}")
            out.append({**e, "vintage_date": pd.Timestamp(str(e["vintage_date"]))})
        return sorted(out, key=lambda e: pd.Timestamp(str(e["vintage_date"])))

    @cached_property
    def _vintage_panels(self) -> list[tuple[pd.Timestamp, pd.DataFrame]]:
        panels = []
        for e in self.vintages():
            df = pd.read_csv(self.raw / self.VINTAGE_DIR / str(e["file"]), skiprows=[1])
            df = df.dropna(subset=["sasdate"])
            df.index = _me(pd.DatetimeIndex(pd.to_datetime(df.pop("sasdate"), format="%m/%d/%Y")))
            panels.append((pd.Timestamp(str(e["vintage_date"])), df.apply(pd.to_numeric, errors="coerce")))
        return panels

    def _realtime_frame(self, code: str, since: date | None) -> pd.DataFrame:
        """One row per (obs_date, first vintage showing this value)."""
        cols = {v: p[code] for v, p in self._vintage_panels if code in p.columns}
        if not cols:
            out = empty_frame()
            out.attrs["real_vintages"] = True
            return out
        wide = pd.DataFrame(cols).sort_index()                       # obs × vintage date
        prev = wide.ffill(axis=1).shift(1, axis=1)
        changed = wide.notna() & (prev.isna() | ((wide - prev).abs() > 1e-12 * prev.abs().clip(lower=1e-12)))
        stacked = cast(pd.Series, wide.where(changed).stack().dropna())
        long = stacked.reset_index()
        long = long.set_axis(["obs_date", "vintage_date", "value"], axis=1)
        long["vintage_date"] = long[["vintage_date", "obs_date"]].max(axis=1)
        if since is not None:
            long = long[long["vintage_date"] >= pd.Timestamp(since)]
        out = long.sort_values(["obs_date", "vintage_date"]).reset_index(drop=True)
        out.attrs["real_vintages"] = True
        return out

    # -- groups --------------------------------------------------------------
    def _all_files(self) -> set[str]:
        out: set[str] = set()
        for v in self.FILES.values():
            out.update((v,) if isinstance(v, str) else v)
        return out

    def _path(self, name: str) -> Path:
        p = self.raw / name
        if not p.exists():
            raise DataError(f"raw file missing: {p}")
        return p

    def _group(self, group: str) -> pd.DataFrame:
        if group not in self._cache:
            loader: Callable[[], pd.DataFrame] = getattr(self, f"_load_{group}")
            self._cache[group] = loader()
        return self._cache[group]

    def _load_fredmd(self) -> pd.DataFrame:
        df = pd.read_csv(self._path("fred_md_2026-10.csv"), skiprows=[1])
        df = df.rename(columns={"sasdate": "date"})
        df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
        df = df.set_index("date").sort_index()
        df.index = _me(df.index)
        out: pd.DataFrame = df.apply(pd.to_numeric, errors="coerce")
        return out

    def _load_ff3(self) -> pd.DataFrame:
        return read_french_section(self._path("ff_3_factors_monthly.csv").read_text(encoding="latin-1"))

    def _load_ind10(self) -> pd.DataFrame:
        return read_french_section(self._path("ff_10_industry_portfolios.csv").read_text(encoding="latin-1"),
                                   "Average Value Weighted Returns -- Monthly")

    def _load_ff5(self) -> pd.DataFrame:
        f5 = pd.read_csv(self._path("ff5_mom_monthly.csv.gz"), index_col=0, parse_dates=True) / 100.0
        f5.index = _me(f5.index)
        return f5

    def _load_shiller(self) -> pd.DataFrame:
        sh = pd.read_csv(self._path("shiller_sp500_monthly.csv"), parse_dates=["Date"]).set_index("Date")
        sh.index = _me(sh.index)
        return sh.replace(0.0, np.nan)  # the mirror zero-fills months without data

    def _load_lbma(self) -> pd.DataFrame:
        out = {}
        for metal in ("gold", "silver"):
            df = pd.read_csv(self._path(f"lbma_{metal}_daily.csv"), parse_dates=["date"]).set_index("date")
            col = next(c for c in df.columns if c.endswith("_usd"))
            out[metal.upper()] = pd.to_numeric(df[col], errors="coerce").replace(0, np.nan)
        return pd.DataFrame(out).sort_index()

    def _load_usmkt(self) -> pd.DataFrame:
        df = pd.read_csv(self._path("us_market_data_daily.csv"), parse_dates=["Date"]).set_index("Date")
        return df[["Close", "Adjusted Close"]].sort_index()

    def _load_vix(self) -> pd.DataFrame:
        df = pd.read_csv(self._path("vix_daily.csv"), parse_dates=["DATE"]).set_index("DATE")
        out: pd.DataFrame = df[["CLOSE"]].apply(pd.to_numeric, errors="coerce").sort_index()
        return out

    def _load_hyoas(self) -> pd.DataFrame:
        df = pd.read_csv(self._path("hy_oas_daily_1996_2021.csv"), parse_dates=["DATE"]).set_index("DATE")
        out: pd.DataFrame = df[["BAMLH0A0HYM2"]].apply(pd.to_numeric, errors="coerce").sort_index()
        return out

    def _load_usd(self) -> pd.DataFrame:
        major = pd.read_csv(self._path("fred_usd_major_index.csv"), parse_dates=["observation_date"]).set_index("observation_date")["DTWEXM"]
        broad = pd.read_csv(self._path("fred_usd_broad_index.csv"), parse_dates=["observation_date"]).set_index("observation_date")["DTWEXBGS"]
        return pd.DataFrame({"DTWEXM": pd.to_numeric(major, errors="coerce"),
                             "DTWEXBGS": pd.to_numeric(broad, errors="coerce")}).sort_index()

    @cached_property
    def _wb(self) -> dict[str, pd.DataFrame]:
        with pd.ExcelFile(self._path("wb_commodity_prices_monthly.xlsx")) as x:
            return {name: x.parse(name, header=None) for name in ("Monthly Prices", "Monthly Indices")}

    def _load_wb_prices(self) -> pd.DataFrame:
        p = self._wb["Monthly Prices"]
        names = p.iloc[4].tolist()
        data = p.iloc[6:].copy().set_axis(["date", *names[1:]], axis=1)
        data["date"] = pd.to_datetime(data["date"].astype(str), format="%YM%m")
        data = data.set_index("date")
        data.index = _me(data.index)
        out: pd.DataFrame = data[list(WB_PRICES)].apply(pd.to_numeric, errors="coerce")
        return out

    def _load_wb_indices(self) -> pd.DataFrame:
        i = self._wb["Monthly Indices"]
        idx = i.iloc[9:, [0, 1, 2, 3, 4, 13, 14, 15, 16]].copy().set_axis(
            ["date", "WB_TOTAL", "WB_ENERGY", "WB_NONENERGY", "WB_AGRI", "WB_FERT", "WB_METALS", "WB_BASEMETALS",
             "WB_PRECIOUS"], axis=1)
        idx["date"] = pd.to_datetime(idx["date"].astype(str), format="%YM%m")
        idx = idx.set_index("date")
        idx.index = _me(idx.index)
        out: pd.DataFrame = idx.apply(pd.to_numeric, errors="coerce")
        return out

    def _load_constructs(self) -> pd.DataFrame:
        fred = self._group("fredmd")
        lbma = self._group("lbma")
        wb = self._group("wb_prices")
        ff3 = self._group("ff3")
        usd = self._group("usd")
        out = pd.DataFrame(index=fred.index.union(wb.index))
        # Gold: LBMA month-end; before the first LBMA month the World Bank monthly average ($35 fixed)
        gold_me = _daily_to_me(lbma["GOLD"])
        wb_gold = wb["Gold"].rename("WB_GOLD_AVG")
        gold = gold_me.reindex(out.index.union(gold_me.index))
        gold = gold.fillna(wb_gold.where(wb_gold.index < gold_me.index.min()))
        tb = fred["TB3MS"]
        cons = {
            "GOLD": gold,
            "TBILL": (1 + tb.shift(1) / 1200.0).cumprod() * 100.0,
            "UST10": (1 + bond_total_return(fred["GS10"], 10.0)).cumprod() * 100.0,
            "UST5": (1 + bond_total_return(fred["GS5"], 5.0)).cumprod() * 100.0,
            "UST1": (1 + bond_total_return(fred["GS1"], 1.0)).cumprod() * 100.0,
            "FF_MKT": ff3["Mkt-RF"] + ff3["RF"],
        }
        major, broad = _daily_to_me(usd["DTWEXM"]), _daily_to_me(usd["DTWEXBGS"])
        link = major.index.intersection(broad.index).min()
        scale = major.loc[link] / broad.loc[link]
        cons["USD_IDX"] = pd.concat([major.loc[:link], (broad * scale).loc[link + pd.Timedelta(days=1):]])
        return pd.DataFrame(cons).sort_index()
