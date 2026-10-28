"""The store reproduces the research inputs, so Phase 2 goldens can run on it.

* assets_monthly.csv (cross-asset studies): every column, as returns and levels;
* macro_monthly.csv raw columns: same values, visible exactly when the research lag convention says;
* Kenneth French data of the equity study; and, end to end, the golden figures of the US equity
  exposure module (Sharpe 0.573, return 9.9 % p.a., max DD −41.1 %) computed from store data only.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rotationlab.data.view import resample_last

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.golden

ASSET_SOURCES = {  # assets_monthly column -> (how to read it from the view)
    "US_EQ": ("asset", "US_EQ"),
    "GOLD": ("asset", "GOLD"),
    "SILVER": ("asset", "SILVER"),
    "TBILL": ("asset", "TBILL"),
    "UST10": ("asset", "UST10"),
    "UST5": ("series", "static:UST5"),
    "UST1": ("series", "static:UST1"),
    "SHILLER_SP500_AVG": ("series", "static:shiller:SP500"),
    **{
        c: ("series", f"static:{c}")
        for c in (
            "WB_ENERGY",
            "WB_BASEMETALS",
            "WB_METALS",
            "WB_AGRI",
            "WB_NONENERGY",
            "WB_TOTAL",
            "WB_PRECIOUS",
            "WB_OIL",
            "WB_WTI",
            "WB_COPPER",
            "WB_ALUMINUM",
            "WB_NICKEL",
            "WB_NATGAS",
            "WB_PLATINUM",
            "WB_GOLD_AVG",
            "WB_SILVER_AVG",
        )
    },
}
MACRO_RAW = {  # macro_monthly column -> (store series, research lag in months)
    "INDPRO": ("static:fredmd:INDPRO", 1),
    "CAPUTIL": ("static:fredmd:CUMFNS", 1),
    "PAYEMS": ("static:fredmd:PAYEMS", 1),
    "UNRATE": ("static:fredmd:UNRATE", 1),
    "CLAIMS": ("static:fredmd:CLAIMSx", 1),
    "HOUST": ("static:fredmd:HOUST", 1),
    "CPI": ("static:fredmd:CPIAUCSL", 1),
    "CPI_CORE": ("static:fredmd:CPIULFSL", 1),
    "PCE": ("static:fredmd:PCEPI", 2),
    "M2": ("static:fredmd:M2SL", 1),
    "UMCSENT": ("static:fredmd:UMCSENTx", 1),
    "REAL_INCOME": ("static:fredmd:RPI", 2),
    "FEDFUNDS": ("static:fredmd:FEDFUNDS", 0),
    "TB3M": ("static:fredmd:TB3MS", 0),
    "GS1": ("static:fredmd:GS1", 0),
    "GS5": ("static:fredmd:GS5", 0),
    "GS10": ("static:fredmd:GS10", 0),
    "AAA": ("static:fredmd:AAA", 0),
    "BAA": ("static:fredmd:BAA", 0),
    "USDCHF": ("static:fredmd:EXSZUSx", 0),
    "SP_PE": ("static:fredmd:SP_PE", 6),
    "VIX_AVG": ("static:fredmd:VIXCLSx", 0),
    "VIX": ("static:cboe:VIX", 0),
    "USD_IDX": ("static:USD_IDX", 0),
    "SHILLER_EPS": ("static:shiller:Earnings", 6),
    "SHILLER_CAPE": ("static:shiller:PE10", 6),
}


@pytest.fixture(scope="module")
def latest(static_factory):
    return static_factory.at(date(2026, 10, 24))


def read(view, how: tuple[str, str]) -> pd.Series:
    kind, name = how
    if kind == "asset":
        roles = view.roles(name)
        role = next(r for r in ("total_return", "close") if r in roles)
        return resample_last(view.asset_series(name, role), "ME", pd.Timestamp(view.date))
    return view.series(name, "ME")


def test_assets_monthly_levels_and_returns(latest) -> None:
    a = pd.read_csv(ROOT / "data/assets_monthly.csv", index_col=0, parse_dates=True)
    assert set(ASSET_SOURCES) == set(a.columns)
    for col, how in ASSET_SOURCES.items():
        x = a[col].dropna()
        y = read(latest, how).reindex(x.index)
        assert y.notna().all(), col
        assert np.allclose(y, x, rtol=1e-8, atol=5e-7), col  # file is rounded to 6 decimals
        assert np.allclose(y.pct_change().dropna(), x.pct_change().dropna(), atol=1e-6), col


def test_macro_raw_values_identical(latest) -> None:
    m = pd.read_csv(ROOT / "data/macro_monthly.csv", index_col=0, parse_dates=True)
    for col, (sid, _) in MACRO_RAW.items():
        x = m[col].dropna()
        y = latest.series(sid, "ME").reindex(x.index)
        # the research panel stops at 2026-09, the 1M/2M/6M lags hide the last months at the view date
        both = y.notna()
        assert both.sum() >= len(x) - 7, col
        assert np.allclose(y[both], x[both], rtol=1e-8, atol=5e-7), col


def test_macro_visibility_follows_the_research_lags(static_factory) -> None:
    m = pd.read_csv(ROOT / "data/macro_monthly.csv", index_col=0, parse_dates=True)
    rng = np.random.default_rng(3)
    dates = sorted(pd.Timestamp(d) for d in rng.choice(m.index[200:-8], 40, replace=False))
    for D in dates:
        v = static_factory.at(D.date())
        for col, (sid, lag) in MACRO_RAW.items():
            s = v.series(sid, "ME")
            expected_last = D - pd.offsets.MonthEnd(lag) if lag else D
            x = m[col].shift(lag).get(D)
            if pd.isna(x):
                continue
            assert s.index[-1] == expected_last, (col, D)
            assert s.iloc[-1] == pytest.approx(x, rel=1e-8, abs=5e-7), (col, D)


def test_month_end_treasury_series_are_visible_at_the_month_end(static_factory, latest) -> None:
    """ADR 047: the month-end yield and the par-bond index on it are market prices (0D): the view at a
    month-end D holds the value of D (the P8 build found them invisible with a 1D lag). The index equals
    the research formula on the month-end yields, and the extract's running month is not in the store."""
    from rotationlab.data.providers.static import StaticProvider, bond_total_return

    for D in (date(1980, 1, 31), date(2008, 10, 31), date(2018, 12, 31)):
        v = static_factory.at(D)
        y = v.series("static:fred:DGS10_ME", "ME")
        lv = v.total_return(["UST10_ME"], "ME")["UST10_ME"]
        assert y.index[-1] == pd.Timestamp(D) and lv.index[-1] == pd.Timestamp(D), D
        assert not np.isnan(lv.iloc[-1])
        # a trend at D can be computed: the registered feature sees the month-end level
        from rotationlab.features import feature

        assert not np.isnan(float(feature("trend_10m").call(v, ["UST10_ME"])["UST10_ME"]))
    y_all = latest.series("static:fred:DGS10_ME", "ME")
    idx = (1 + bond_total_return(y_all, 10.0)).cumprod() * 100.0
    lv_all = latest.total_return(["UST10_ME"], "ME")["UST10_ME"]
    both = idx.dropna().index.intersection(lv_all.dropna().index)
    assert len(both) > 700
    assert np.allclose(idx.loc[both].to_numpy(), lv_all.loc[both].to_numpy(), rtol=1e-9, atol=1e-6)
    assert (
        y_all.index.max() <= StaticProvider.LIVE_ME_EXTRACTED
    )  # the running month of the extract is dropped


def test_french_inputs_of_the_equity_study(latest) -> None:
    lines = (ROOT / "data/raw/ff_3_factors_monthly.csv").read_text(encoding="latin-1").splitlines()
    rows = [ln.split(",") for ln in lines if ln[:6].strip().isdigit() and len(ln.split(",")[0].strip()) == 6]
    ff3 = (
        pd.DataFrame(
            {"mkt_rf": [float(r[1]) for r in rows], "rf": [float(r[4]) for r in rows]},
            index=pd.to_datetime([r[0].strip() for r in rows], format="%Y%m") + pd.offsets.MonthEnd(0),
        )
        / 100
    )
    mkt = latest.series("static:FF_MKT")
    rf = latest.series("static:french:ff3:RF")
    assert np.allclose(mkt.reindex(ff3.index), ff3["mkt_rf"] + ff3["rf"], atol=1e-12)
    assert np.allclose(rf.reindex(ff3.index), ff3["rf"], atol=1e-12)
    ind = latest.returns(["FF_NODUR", "FF_ENRGY", "FF_HITEC", "FF_OTHER"], "ME")
    assert ind.index[1] == pd.Timestamp("1926-07-31") and ind.notna().sum().min() > 1190  # first return kept


def test_golden_us_equity_exposure_from_the_store(latest) -> None:
    """Trend/momentum mean (0, ½, 1) on the French market, 5 bp per side.

    configs/strategies/us_equity_exposure.yaml: sharpe_ex_cash 0.573, ann_return 0.099, max_drawdown −0.411
    (output/equity/REPORT.md, table A2: vol 12.1 %)."""
    mkt = latest.series("static:FF_MKT")
    rf = latest.series("static:french:ff3:RF").reindex(mkt.index)
    tr = (1 + mkt).cumprod()
    trend = tr / tr.rolling(10).mean() - 1
    mom = (1 + (mkt - rf)).rolling(12).apply(np.prod, raw=True) - 1
    above = (trend > 0).astype(float).where(trend.notna())
    mom_on = (mom > 0).astype(float).where(mom.notna())
    w = (above + mom_on) / 2
    held = w.shift(1)
    cost = w.diff().abs().shift(1).fillna(0) * 5 / 1e4
    r = (held * mkt + (1 - held) * rf - cost).dropna().loc["1927-01-31":"2026-07-31"]
    ex = r - rf.reindex(r.index)
    sharpe = ex.mean() / ex.std() * np.sqrt(12)
    vol = r.std() * np.sqrt(12)
    ann = (1 + r).prod() ** (12 / len(r)) - 1
    eq = (1 + r).cumprod()
    mdd = (eq / eq.cummax() - 1).min()
    assert sharpe == pytest.approx(0.573, abs=0.0015)
    assert ann == pytest.approx(0.099, abs=0.0015)
    assert vol == pytest.approx(0.121, abs=0.0015)
    assert mdd == pytest.approx(-0.411, abs=0.0015)
