"""Round 4 constructions (ADR 057 a) against hand calculations: quote conventions, the EUR/DEM splice, rate
splices, the publication lag of the deposit rate, the FX deposit index and the daily par bond."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rotationlab.data.providers.constructs_r4 import (
    DEM_PER_EUR,
    euro_spliced,
    fx_deposit_index,
    index_from_returns,
    par_bond_index_daily,
    published_rate,
    splice_at,
    spliced_rate,
    usd_per_unit,
)


def test_quote_conventions_and_the_euro_splice() -> None:
    q = pd.Series([100.0, 125.0], index=pd.to_datetime(["2000-01-03", "2000-01-04"]))
    assert usd_per_unit("DEXJPUS", q).tolist() == [0.01, 0.008]
    assert usd_per_unit("DEXUSUK", q).tolist() == [100.0, 125.0]
    with pytest.raises(ValueError):
        usd_per_unit("DEXXXUS", q)
    dem = pd.Series([1.8, 1.9, 1.95], index=pd.to_datetime(["1998-12-30", "1998-12-31", "1999-01-04"]))
    eur = pd.Series([1.17, 1.18], index=pd.to_datetime(["1999-01-04", "1999-01-05"]))
    e = euro_spliced(dem, eur)
    assert (
        e.index.tolist() == pd.to_datetime(["1998-12-30", "1998-12-31", "1999-01-04", "1999-01-05"]).tolist()
    )
    assert (
        e.iloc[0] == pytest.approx(DEM_PER_EUR / 1.8) and e.iloc[2] == 1.17
    )  # the euro wins from its first quote
    # ADR 059: without a DEM series (FRED no longer serves DEXGEUS) the euro starts at its first quote
    assert euro_spliced(None, eur).tolist() == [1.17, 1.18]
    assert euro_spliced(pd.Series(dtype=float), eur).index.tolist() == eur.index.tolist()


def test_rate_splices_and_publication_lag() -> None:
    m = lambda *d: pd.to_datetime(list(d))  # noqa: E731
    call = pd.Series([8.0, 8.5, 9.0], index=m("1980-01-31", "1980-02-29", "1980-03-31"))
    three = pd.Series([9.5, 9.7], index=m("1980-02-29", "1980-03-31"))
    s = spliced_rate(three, call)
    assert s.tolist() == [8.0, 9.5, 9.7]
    assert spliced_rate(None, call).tolist() == call.tolist() and spliced_rate(three, None).tolist() == [
        9.5,
        9.7,
    ]
    de = pd.Series([3.0, 3.1], index=m("1998-11-30", "1998-12-31"))
    ez = pd.Series([3.2, 3.3], index=m("1998-12-31", "1999-01-31"))
    assert splice_at(de, ez, pd.Timestamp("1999-01-01")).tolist() == [3.0, 3.1, 3.3]
    days = m("1980-02-28", "1980-02-29", "1980-03-30", "1980-03-31")
    p = published_rate(call, days, lag_months=1)  # January's value is public at the end of February
    assert np.isnan(p.iloc[0]) and p.iloc[1] == 8.0 and p.iloc[2] == 8.0 and p.iloc[3] == 8.5


def test_fx_deposit_index_accrues_the_rate_known_the_day_before() -> None:
    days = pd.date_range("1980-03-01", periods=11, freq="D")
    spot = pd.Series(2.0, index=days)
    rate = pd.Series([3.65], index=pd.to_datetime(["1980-01-31"]))  # public from 1980-02-29
    tr = fx_deposit_index(spot, rate)
    assert tr.iloc[0] == 100.0 and tr.iloc[-1] == pytest.approx(100.0 * (1 + 0.0365 / 365) ** 10)
    spot2 = spot.copy()
    spot2.iloc[5:] = 3.0  # the currency rises 50 % on day 5
    tr2 = fx_deposit_index(spot2, rate)
    assert tr2.iloc[-1] / tr.iloc[-1] == pytest.approx(1.5)
    # a rate published later in the window is used only from the next quote on (no same-day accrual)
    late = pd.Series([3.65, 36.5], index=pd.to_datetime(["1980-01-31", "1980-02-29"]))  # Feb public 03-31
    days3 = pd.date_range("1980-03-29", periods=5, freq="D")
    tr3 = fx_deposit_index(pd.Series(1.0, index=days3), late)
    steps = (tr3 / tr3.shift(1) - 1).iloc[1:]
    # published on 03-31: the deposit placed on 03-31 earns it until 04-01 – never before its publication day
    assert steps.tolist() == pytest.approx([0.0001, 0.0001, 0.001, 0.001])
    assert fx_deposit_index(spot, pd.Series(dtype=float)).empty  # no rate, no index


def test_daily_par_bond_index() -> None:
    days = pd.bdate_range("2000-01-03", periods=6)
    flat = par_bond_index_daily(pd.Series(5.0, index=days), 10.0)
    dt = np.diff(days.values).astype("timedelta64[D]").astype(float) / 365.0
    # a par bond stays at par and earns its yield compounded semi-annually: exactly (1 + y/2)^(2t) – not the
    # daily-compounded simple coupon, which would overstate by about y²/4 a year (ADR 058)
    assert flat.iloc[-1] == pytest.approx(100.0 * 1.025 ** (2 * dt.sum()), rel=1e-12)
    year = par_bond_index_daily(
        pd.Series(10.0, index=pd.date_range("2001-01-01", "2002-01-01", freq="D")), 10.0
    )
    assert year.iloc[-1] / 100.0 - 1 == pytest.approx(0.1025, abs=1e-12)  # (1 + 0.05)² − 1, not e^0.1 − 1
    jump = par_bond_index_daily(pd.Series([5.0, 6.0], index=days[:2]), 10.0)
    r = jump.iloc[1] / 100.0 - 1
    assert -0.080 < r < -0.070  # ≈ −modified duration × 1 pp for a 10-year bond (≈ 7.5)
    short = par_bond_index_daily(pd.Series([5.0, 6.0], index=days[:2]), 2.0)
    assert -0.020 < short.iloc[1] / 100.0 - 1 < -0.017  # 2-year: ≈ −1.85
    assert index_from_returns(pd.Series([0.1, -0.5])).tolist() == pytest.approx([110.0, 55.0])


def test_a_stale_rate_ends_the_deposit_index() -> None:
    """ADR 057 (a): a monthly value is usable for at most three months after its reference month."""
    m = lambda *d: pd.to_datetime(list(d))  # noqa: E731
    rate = pd.Series([3.65, 3.65], index=m("1980-01-31", "1980-02-29"))  # last value: February (public 03-31)
    days = m("1980-03-31", "1980-04-30", "1980-05-30", "1980-05-31", "1980-06-02")
    p = published_rate(rate, days, lag_months=1, max_age_months=3)
    assert p.iloc[:4].notna().all() and np.isnan(p.iloc[4])  # June is 4 months after February
    spot = pd.Series(1.0, index=pd.date_range("1980-03-01", "1980-06-30", freq="D"))
    tr = fx_deposit_index(spot, rate, 1, 3)
    assert tr.index[0] == pd.Timestamp("1980-03-01") and tr.index[-1] == pd.Timestamp("1980-05-31")
    # a gap in the middle ends the index for good: no second stretch after a stale period
    rate2 = pd.concat([rate, pd.Series([3.65], index=m("1980-09-30"))])
    tr2 = fx_deposit_index(
        pd.Series(1.0, index=pd.date_range("1980-03-01", "1980-12-31", freq="D")), rate2, 1, 3
    )
    assert tr2.index[-1] == pd.Timestamp("1980-05-31")
    assert published_rate(rate, days).notna().all()  # without the guard (default) the value runs on


def test_index_from_returns_ends_at_a_gap_and_can_carry_a_base() -> None:
    r = pd.Series(
        [np.nan, 0.1, -0.5, np.nan, 0.2],
        index=pd.to_datetime(["1975-01-31", "1975-02-28", "1975-03-31", "1975-04-30", "1975-05-31"]),
    )
    out = index_from_returns(r)
    assert out.index.tolist() == pd.to_datetime(["1975-02-28", "1975-03-31"]).tolist()
    assert out.tolist() == pytest.approx([110.0, 55.0])
    based = index_from_returns(r, base=pd.Timestamp("1975-01-31"))
    assert based.tolist() == pytest.approx([100.0, 110.0, 55.0])
    assert index_from_returns(pd.Series([np.nan, np.nan])).empty


def test_assembly_of_the_round4_series() -> None:
    from rotationlab.data.providers.constructs_r4 import (
        build_countries,
        build_daily,
        build_rates,
        country_slug,
        currency_rate,
    )

    days = pd.bdate_range("1998-11-02", "1999-03-31")
    me = pd.date_range("1998-01-31", "1999-03-31", freq="ME")
    fred = pd.DataFrame(index=days)
    for code in ("DEXJPUS", "DEXSZUS", "DEXCAUS", "DEXSDUS", "DEXNOUS"):
        fred[code] = 2.0  # foreign units per dollar: 0.5 USD per unit
    for code in ("DEXUSUK", "DEXUSAL", "DEXUSNZ"):
        fred[code] = 1.5
    fred["DEXGEUS"] = np.where(days < pd.Timestamp("1999-01-04"), 1.95583 / 1.2, np.nan)
    fred["DEXUSEU"] = np.where(days >= pd.Timestamp("1999-01-04"), 1.2, np.nan)
    for code in ("DGS2", "DGS5", "DGS10"):
        fred[code] = 5.0
    rates = pd.DataFrame(index=me)
    for a in ("JP", "GB", "CH", "CA", "AU", "NZ", "SE", "NO"):
        rates[f"IR3TIB01{a}M156N"] = 3.65
    rates["IR3TIB01DEM156N"] = 3.65
    rates["IR3TIB01EZM156N"] = 7.30  # euro area from 1999-01 only (the German rate before)
    ind = pd.DataFrame({"NoDur": 0.01, "Hlth": -0.01}, index=days)
    out = build_daily(fred, rates, ind)
    assert {f"FX_{c}" for c in ("JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "EUR")} <= set(
        out.columns
    )
    assert {"UST2_D", "UST5_D", "UST10_D", "IND_NODUR", "IND_HLTH"} <= set(out.columns)
    # constant spot and rate: the deposit only accrues; the euro rate switches to the euro area in 1999
    eur = currency_rate(rates, "EUR")
    assert eur[pd.Timestamp("1998-12-31")] == 3.65 and eur[pd.Timestamp("1999-01-31")] == 7.30
    fx = out["FX_JPY"].dropna()
    assert (fx.diff().dropna() >= 0).all()
    # currencies count as investable only from FX_FROM (ADR 058 f): nothing before, whatever the data
    early = build_daily(
        fred.set_axis(fred.index - pd.DateOffset(years=10)),
        rates.set_axis(rates.index - pd.DateOffset(years=10)),
        ind,
    )
    assert early[[c for c in early.columns if c.startswith("FX_")]].dropna(how="all").empty
    assert build_rates(rates).columns.tolist() == [
        f"RATE_{c}" for c in ("JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "EUR")
    ]
    c = build_countries(pd.DataFrame({"New Zealand": [np.nan, 0.1, 0.2]}, index=me[:3]))
    assert c.columns.tolist() == ["CTRY_NEWZEALAND"] and country_slug("Hong Kong") == "HONGKONG"
    assert c["CTRY_NEWZEALAND"].dropna().index[0] == me[0]  # base 100 one month before the first return
