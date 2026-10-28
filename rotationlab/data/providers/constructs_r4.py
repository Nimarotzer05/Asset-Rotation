"""Total-return constructions of research round 4 (ADR 057 a), pure functions on frozen source series.

* `usd_per_unit`       – FRED H.10 quotes either way round (DEXJPUS = JPY per USD, DEXUSUK = USD per GBP); the
                         index needs the dollar value of one unit of the foreign currency.
* `euro_spliced`       – USD per EUR from 1999 (DEXUSEU); before the first EUR quote the Deutsche Mark at the
                         irrevocable conversion rate 1.95583 DEM per EUR (USD per EUR = 1.95583 / DEXGEUS).
* `spliced_rate`       – the 3-month interbank rate where it exists, before its first value the call money rate;
                         a second splice point (e.g. DE → euro area in 1999) is given explicitly.
* `fx_deposit_index`   – a dollar investor's foreign deposit: TR_t = TR_{t−1}·(S_t/S_{t−1})·(1 + i·Δdays/365/100),
                         where i is the latest monthly rate *published* before the day (value of month M usable
                         from the month-end `lag_months` later – the house lag model, ADR 057 a) and at most
                         `max_age_months` old (ADR 058 b). The index covers the first unbroken stretch of days
                         with a usable rate; no rate, no index.
* `par_bond_index_daily` – a constant-maturity par bond bought at yesterday's yield and priced at today's: coupon
                         c = y_{t−1}, remaining maturity T − Δt (fractional semi-annual periods), interest earned
                         (1 + c/2)^(2Δt) − 1 (Δt = calendar days / 365) – compounding semi-annually like the bond,
                         so a flat yield y earns exactly (1 + y/2)² − 1 a year (ADR 058; a simple c·Δt compounded
                         daily would overstate by about y²/4 a year).
* `index_from_returns` – a total-return index from simple returns over its first unbroken stretch (ADR 058 c).

Assembly (`build_daily`, `build_rates`, `build_countries`) turns the frozen files of
scripts/freeze_research_data.py into the series of the static catalog. Currencies trade from FX_FROM only: until
the end of the 1980s capital controls made domestic deposit rates unavailable to a dollar investor in several of
the nine areas (Sweden dismantled its exchange controls 1986–1990, Norway by the end of the 1980s); the uniform,
conservative start avoids a judgement per currency (ADR 058 f).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEM_PER_EUR = 1.95583
QUOTED_PER_USD = {
    "DEXJPUS",
    "DEXSZUS",
    "DEXCAUS",
    "DEXSDUS",
    "DEXNOUS",
    "DEXGEUS",
}  # foreign units per dollar
QUOTED_USD_PER = {"DEXUSUK", "DEXUSAL", "DEXUSNZ", "DEXUSEU"}  # dollars per foreign unit


def usd_per_unit(code: str, quote: pd.Series) -> pd.Series:
    if code in QUOTED_PER_USD:
        return (1.0 / quote).rename(code)
    if code in QUOTED_USD_PER:
        return quote.rename(code)
    raise ValueError(f"unknown H.10 quote convention for {code}")


def euro_spliced(dexgeus: pd.Series, dexuseu: pd.Series) -> pd.Series:
    """USD per EUR: DEXUSEU from its first quote, before that 1.95583 / DEXGEUS."""
    eur = dexuseu.dropna()
    first = eur.index.min() if len(eur) else pd.Timestamp.max
    dem = DEM_PER_EUR / dexgeus.dropna()
    dem = dem[dem.index < first]
    out: pd.Series = pd.concat([dem, eur]).sort_index().rename("EUR")
    return out


def spliced_rate(primary: pd.Series | None, fallback: pd.Series | None) -> pd.Series:
    """Primary from its first value on, the fallback before; either may be missing."""
    p = primary.dropna() if primary is not None else pd.Series(dtype=float)
    f = fallback.dropna() if fallback is not None else pd.Series(dtype=float)
    if p.empty:
        return f.copy()
    if f.empty:
        return p.copy()
    out: pd.Series = pd.concat([f[f.index < p.index.min()], p]).sort_index()
    return out


def splice_at(before: pd.Series, after: pd.Series, at: pd.Timestamp) -> pd.Series:
    """`before` strictly before `at`, `after` from `at` on (e.g. German rate before 1999, euro area after)."""
    b, a = before.dropna(), after.dropna()
    out: pd.Series = pd.concat([b[b.index < at], a[a.index >= at]]).sort_index()
    return out


def published_rate(
    rate_monthly: pd.Series, days: pd.DatetimeIndex, lag_months: int = 1, max_age_months: int | None = None
) -> pd.Series:
    """For every day, the latest monthly value whose publication date (month-end of its month + `lag_months`
    month-ends) lies on or before the day; NaN before the first publication and – with `max_age_months` – once
    that value refers to a month more than `max_age_months` calendar months before the day's month (a source
    that stops updating ends the series instead of accruing a stale rate for ever)."""
    r = rate_monthly.dropna()
    if r.empty:
        return pd.Series(np.nan, index=days)
    ref = pd.DatetimeIndex(r.index) + pd.offsets.MonthEnd(0)
    published = ref + pd.offsets.MonthEnd(lag_months)
    s = pd.DataFrame({"v": r.to_numpy(dtype=float), "ref": ref}, index=published).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    on = s.reindex(s.index.union(days)).ffill().reindex(days)
    out: pd.Series = on["v"]
    if max_age_months is not None:
        day_m = pd.DatetimeIndex(days).year * 12 + pd.DatetimeIndex(days).month
        ref_m = pd.DatetimeIndex(on["ref"]).year * 12 + pd.DatetimeIndex(on["ref"]).month
        out = out.where(pd.Series(day_m - ref_m, index=days) <= max_age_months)
    return out


def fx_deposit_index(
    spot_usd: pd.Series, rate_monthly: pd.Series, lag_months: int = 1, max_age_months: int | None = None
) -> pd.Series:
    """Daily total-return index of a foreign deposit held by a dollar investor (start 100 at the first day with
    a published rate); the rate accrues from one quote to the next with the value known on the earlier day. The
    index covers the first unbroken stretch of days with a usable rate: it ends where the rate goes stale."""
    s = spot_usd.dropna().sort_index()
    rate = published_rate(rate_monthly, pd.DatetimeIndex(s.index), lag_months, max_age_months)
    usable = rate.notna().to_numpy()
    keep = np.zeros(len(usable), dtype=bool)
    if usable.any():  # the first unbroken stretch of days with a usable rate
        first = int(np.argmax(usable))
        gap = ~usable[first:]
        keep[first : first + (int(np.argmax(gap)) if gap.any() else len(gap))] = True
    s, rate = s[keep], rate[keep]
    if len(s) < 2:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    dt = pd.Series(s.index, index=s.index).diff().dt.days.to_numpy(dtype=float)
    growth = (s / s.shift(1)).to_numpy() * (1.0 + rate.shift(1).to_numpy() / 100.0 * dt / 365.0)
    growth[0] = 1.0
    return pd.Series(100.0 * np.cumprod(growth), index=s.index)


def _par_price(c: np.ndarray, y: np.ndarray, years: np.ndarray) -> np.ndarray:
    """Price per 1 of a semi-annual bond with coupon rate c, yield y and `years` to maturity (fractional periods)."""
    n = 2.0 * years
    per = y / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        disc = (1.0 + per) ** (-n)
        annuity = np.where(np.abs(per) > 1e-12, (1.0 - disc) / per, n)
    return (c / 2.0) * annuity + disc


def par_bond_index_daily(yields_pct: pd.Series, maturity_years: float) -> pd.Series:
    """Daily total-return index (start 100) of a constant-maturity par bond on daily yields (percent)."""
    y = yields_pct.dropna().sort_index().astype(float) / 100.0
    if len(y) < 2:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    dt = pd.Series(y.index, index=y.index).diff().dt.days.to_numpy(dtype=float) / 365.0
    c = y.shift(1).to_numpy()
    price = _par_price(c, y.to_numpy(), maturity_years - dt)
    r = price - 1.0 + ((1.0 + c / 2.0) ** (2.0 * dt) - 1.0)
    r[0] = 0.0
    return pd.Series(100.0 * np.cumprod(1.0 + r), index=y.index)


def index_from_returns(r: pd.Series, base: pd.Timestamp | None = None) -> pd.Series:
    """Total-return index from simple returns over the first unbroken stretch of values: leading NaN are skipped,
    the first NaN after a value ends the index (an instrument that leaves the data does not come back). With
    `base`, the level 100 is placed on that date, before the first return (no return is lost)."""
    x = r.sort_index()
    valid = x.notna().to_numpy()
    if not valid.any():
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    first = int(np.argmax(valid))
    rest = ~valid[first:]
    stop = first + (int(np.argmax(rest)) if rest.any() else len(rest))
    x = x.iloc[first:stop].astype(float)
    out: pd.Series = 100.0 * (1.0 + x).cumprod()
    if base is not None:
        out = pd.concat([pd.Series([100.0], index=pd.DatetimeIndex([base])), out])
    return out


# ---------------------------------------------------------------------------------------------------------------
# Assembly (ADR 057 a): the frozen files of scripts/freeze_research_data.py → the series of the static catalog
# ---------------------------------------------------------------------------------------------------------------
FX_SPOT: dict[str, str] = {  # currency → FRED H.10 series (EUR: DEM before the first euro quote)
    "JPY": "DEXJPUS",
    "GBP": "DEXUSUK",
    "CHF": "DEXSZUS",
    "CAD": "DEXCAUS",
    "AUD": "DEXUSAL",
    "NZD": "DEXUSNZ",
    "SEK": "DEXSDUS",
    "NOK": "DEXNOUS",
    "EUR": "DEXUSEU",
}
RATE_AREA = {"JPY": "JP", "GBP": "GB", "CHF": "CH", "CAD": "CA", "AUD": "AU", "NZD": "NZ", "SEK": "SE", "NOK": "NO"}
EURO_START = pd.Timestamp("1999-01-01")  # EUR rate: Germany before, euro area from (ADR 057 a)
FX_FROM = pd.Timestamp("1991-01-01")  # first day a currency deposit counts as investable (ADR 058 f)
TREASURIES = {"UST2_D": ("DGS2", 2.0), "UST5_D": ("DGS5", 5.0), "UST10_D": ("DGS10", 10.0)}
RATE_LAG_MONTHS = 1  # a monthly OECD value is public at the month-end after its month (house lag model)
RATE_MAX_AGE_MONTHS = 3  # usable for at most three months after its reference month (normal age 1–2)


def area_rate(rates: pd.DataFrame, area: str) -> pd.Series:
    """3-month interbank rate of an area, the call money rate before its first value (percent, monthly)."""
    return spliced_rate(rates.get(f"IR3TIB01{area}M156N"), rates.get(f"IRSTCI01{area}M156N"))


def currency_rate(rates: pd.DataFrame, ccy: str) -> pd.Series:
    if ccy == "EUR":
        return splice_at(area_rate(rates, "DE"), area_rate(rates, "EZ"), EURO_START)
    return area_rate(rates, RATE_AREA[ccy])


def spot_usd(fred: pd.DataFrame, ccy: str) -> pd.Series:
    if ccy == "EUR":
        return euro_spliced(fred["DEXGEUS"], fred["DEXUSEU"])
    code = FX_SPOT[ccy]
    return usd_per_unit(code, fred[code].dropna())


def build_daily(fred: pd.DataFrame, rates: pd.DataFrame, industries: pd.DataFrame) -> pd.DataFrame:
    """Daily total-return indices: FX_<ccy> (deposit), UST{2,5,10}_D (par bond), IND_<industry> (French)."""
    out: dict[str, pd.Series] = {}
    for ccy in FX_SPOT:
        spot = spot_usd(fred, ccy)
        out[f"FX_{ccy}"] = fx_deposit_index(
            spot[spot.index >= FX_FROM], currency_rate(rates, ccy), RATE_LAG_MONTHS, RATE_MAX_AGE_MONTHS
        )
    for name, (code, maturity) in TREASURIES.items():
        out[name] = par_bond_index_daily(fred[code], maturity)
    for col in industries.columns:
        out[f"IND_{str(col).upper()}"] = index_from_returns(industries[col])
    return pd.DataFrame(out).sort_index()


def build_rates(rates: pd.DataFrame) -> pd.DataFrame:
    """RATE_<ccy>: the spliced short rate of every currency (percent, month-end of the reference month)."""
    return pd.DataFrame({f"RATE_{ccy}": currency_rate(rates, ccy) for ccy in FX_SPOT}).sort_index()


def country_slug(name: str) -> str:
    return "".join(ch for ch in str(name).upper() if ch.isalnum())


def build_countries(countries: pd.DataFrame) -> pd.DataFrame:
    """CTRY_<country>: monthly total-return index per country (level 100 at the month-end before the first
    return), from the market returns with dividends in USD of the frozen French file."""
    out: dict[str, pd.Series] = {}
    for col in countries.columns:
        r = countries[col]
        fv = r.first_valid_index()
        if fv is None:
            continue
        first = pd.Timestamp(str(fv))
        out[f"CTRY_{country_slug(str(col))}"] = index_from_returns(r, base=first - pd.offsets.MonthEnd(1))
    return pd.DataFrame(out).sort_index()
