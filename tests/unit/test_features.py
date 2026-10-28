"""Feature layer: formulas on hand-made panels, the registry contract, and values against the research."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core import registry
from rotationlab.core.errors import RegistryError
from rotationlab.features import feature
from rotationlab.features._panel import expanding_pct, last_value, month_grid, rolling_z
from tests.fixtures.toy import Toy, geometric


# ---------------------------------------------------------------------------- panel helpers
def test_month_grid_labels_and_cap() -> None:
    g = month_grid(pd.Timestamp("2025-11-15"), date(2026, 2, 10))
    assert [x.date() for x in g] == [
        date(2025, 11, 30),
        date(2025, 12, 31),
        date(2026, 1, 31),
        date(2026, 2, 10),
    ]
    assert list(month_grid(pd.Timestamp("2026-01-31"), date(2026, 1, 31))) == [pd.Timestamp("2026-01-31")]
    assert month_grid(pd.Timestamp("2026-03-31"), date(2026, 1, 31)).empty


def test_expanding_percentile_counts_ties_half_and_waits_for_history() -> None:
    s = pd.Series([1.0, np.nan, 3.0, 2.0, 3.0])
    out = expanding_pct(s, min_periods=2)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(0.75)  # {1, 3}: below 1/2, equal 1/2 → 0.5 + 0.25
    assert out.iloc[3] == pytest.approx(0.5)  # {1, 3, 2}: 1/3 below + 1/6 equal
    assert out.iloc[4] == pytest.approx(0.75)  # {1, 3, 2, 3}: 2/4 below + 0.5·2/4 equal


def test_last_value_keeps_labels_and_nan() -> None:
    assert last_value(pd.Series(["a", "low_high"])) == "low_high"
    assert np.isnan(last_value(pd.Series([1.0, None], dtype=object)))
    assert np.isnan(last_value(pd.Series(dtype=float)))
    z = rolling_z(pd.Series(np.arange(10.0)), 5, 3)
    assert np.isnan(z.iloc[1]) and z.iloc[4] == pytest.approx((4 - 2) / np.std([0, 1, 2, 3, 4], ddof=1))


# ---------------------------------------------------------------------------- price features
@pytest.fixture
def market():
    up = geometric(100, 0.01, 30)
    down = geometric(100, -0.01, 30)
    w = Toy().monthly("UP", up).monthly("DOWN", down).cash("C", 0.002, n=30)
    w.monthly("LATE", geometric(50, 0.02, 10), start="2002-01-31")
    w.monthly("FLAT", [100.0] * 30)
    return w.factory()


def test_momentum_trend_and_volatility_formulas(market) -> None:
    v = market.at(date(2002, 6, 30))  # 30th month of UP/DOWN
    m = feature("mom_12_1").call(v, ["UP", "DOWN"])
    assert m["UP"] == pytest.approx(1.01**12 - 1) and m["DOWN"] == pytest.approx(0.99**12 - 1)
    assert feature("mom_3_1").call(v, ["UP"])["UP"] == pytest.approx(1.01**3 - 1)
    assert feature("mom_12").call(v, ["UP"])["UP"] == pytest.approx(1.01**12 - 1)
    t = feature("trend_10m").call(v, ["UP"])["UP"]
    assert t == pytest.approx(1 / np.mean(1.01 ** -np.arange(10)) - 1)
    vol = feature("vol_12m").call(v, ["UP"])["UP"]
    assert vol == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(feature("inv_vol_12m").call(v, ["FLAT"])["FLAT"])  # zero volatility → NaN, never inf
    assert feature("inv_vol_12m").call(v, ["UP"])["UP"] > 1e6
    assert feature("drawdown").call(v, ["DOWN"])["DOWN"] == pytest.approx(0.99**29 - 1)
    ex = feature("excess_mom_12m").call(v, ["UP"], cash="C")["UP"]
    assert ex == pytest.approx((1 + (0.01 - 0.002)) ** 12 - 1)


def test_short_history_and_missing_current_month_give_nan(market) -> None:
    v = market.at(date(2002, 6, 30))
    late = feature("mom_12_1").call(v, ["LATE", "UP"])
    assert np.isnan(late["LATE"]) and not np.isnan(late["UP"])  # 6 months of history only
    after = market.at(date(2002, 10, 31))  # UP/DOWN end 2002-06
    assert feature("trend_10m").call(after, ["UP", "LATE"]).isna().tolist() == [True, False]


# ---------------------------------------------------------------------------- registry contract
def test_registry_checks_parameters_and_kinds(market) -> None:
    v = market.at(date(2002, 6, 30))
    with pytest.raises(RegistryError, match="undeclared"):
        feature("mom_12_1").call(v, ["UP"], window=7)
    with pytest.raises(RegistryError, match="pass assets"):
        feature("trend_10m").call(v)
    with pytest.raises(RegistryError, match="undeclared"):
        feature("excess_mom_12m").call_panel(pd.DataFrame(), window=3)
    m = registry.get_feature("growth_dir")
    with pytest.raises(RegistryError, match="no panel variant"):
        registry.FeatureMeta(m.name, m.kind, m.inputs, m.lookback, m.macro_lag, 1, m.fn).call_panel(
            pd.DataFrame()
        )


def test_memo_hands_out_copies(market) -> None:
    v = market.at(date(2002, 6, 30))
    a = feature("mom_12_1").call(v, ["UP", "DOWN"])
    a.loc["UP"] = 99.0
    b = feature("mom_12_1").call(v, ["UP", "DOWN"])
    assert b["UP"] == pytest.approx(1.01**12 - 1)
    assert any(k[0] == "mom_12_1" for k in v.memo)


def test_every_feature_is_documented_and_has_a_panel_variant() -> None:
    feats = registry.features()
    assert len(feats) >= 30
    for name, m in feats.items():
        assert m.fn.__doc__, name
        assert m.panel_fn is not None and m.panel_input is not None, name


# ---------------------------------------------------------------------------- against the research
def test_valuation_and_regime_match_the_research(static_factory) -> None:
    """Values printed by scripts/run_equity.py::signals_a and src/features.py::macro_regime."""
    v = static_factory.at(date(2008, 9, 30))
    assert feature("cape").call(v) == pytest.approx(20.335793199415967, rel=1e-12)
    assert feature("excess_cape_yield").call(v) == pytest.approx(0.04203682644124952, rel=1e-12)
    assert feature("quadrant").call(v) == "low_high"
    old = static_factory.at(date(1950, 6, 30))
    assert feature("cape").call(old) == pytest.approx(11.829127641820097, rel=1e-12)
    assert feature("excess_cape_yield").call(old) == pytest.approx(0.11438907401540002, rel=1e-12)
    assert feature("quadrant").call(static_factory.at(date(1975, 6, 30))) == "low_low"
    assert feature("commodity_state").call(v) in {
        f"USD{a} IP{b} CPI{c}" for a in "↑↓" for b in "↑↓" for c in "↑↓"
    }


def test_gold_silver_ratio_and_risk_appetite_match_the_research(static_factory) -> None:
    """output/gold_silver/DERISK.md 'Stand': ratio z60 −2.8, risk appetite +0.54 (75th percentile), 2026-02."""
    v = static_factory.at(date(2026, 2, 28))
    assert feature("gs_ratio_z60").call(v) == pytest.approx(-2.8, abs=0.05)
    ra = feature("risk_appetite").call(v)
    assert ra == pytest.approx(0.54, abs=0.01)
    assert feature("risk_appetite_pct").call(v, min_history=1) == pytest.approx(0.75, abs=0.01)


# ---------------------------------------------------------------------------- round-2 families (ADR 052)
def test_value_reversal_and_carry_yield_formulas() -> None:
    from rotationlab.core.types import SeriesKind

    n = 70  # value needs 60 months of history, carry 12
    w = Toy().monthly("UP", geometric(100, 0.01, n)).monthly("DOWN", geometric(100, -0.01, n))
    w.monthly("EQ", geometric(100, 0.01, n))  # total return +1 % per month
    w.series("t:EQ:px", pd.Series(geometric(100, 0.005, n), index=w.frames[-1]["obs_date"]), SeriesKind.PRICE)
    w.series("t:Y:ten", pd.Series(5.0, index=w.frames[-1]["obs_date"]), SeriesKind.YIELD)
    w.monthly("ETF", [100.0] * n)
    w.series("t:ETF:close", pd.Series(100.0, index=w.frames[-1]["obs_date"]), SeriesKind.PRICE)
    divs = pd.Series(0.0, index=w.frames[-1]["obs_date"])
    divs.iloc[3::3] = 1.0  # a quarterly dividend of 1.00 → 4.00 per trailing year on a close of 100
    w.series("t:ETF:div", divs, SeriesKind.DIVIDEND)
    w.monthly("ZERO", [100.0] * n)
    v = w.factory().at(date(2005, 10, 31))  # 70th month

    val = feature("value_rev_60m").call(v, ["UP", "DOWN"])
    assert val["UP"] == pytest.approx(-(1.01**60 - 1)) and val["DOWN"] == pytest.approx(-(0.99**60 - 1))
    assert np.isnan(feature("value_rev_60m").call(w.factory().at(date(2004, 10, 31)), ["UP"])["UP"])

    spec = {
        "EQ": {"kind": "equity_dy", "tr": "t:EQ:tr", "px": "t:EQ:px"},
        "Y": {"kind": "yield", "series": "t:Y:ten"},
        "ETF": {"kind": "dividend_dy", "close": "t:ETF:close", "dividend": "t:ETF:div"},
        "ZERO": {"kind": "zero"},
    }
    c = feature("carry_yield").call(v, ["EQ", "Y", "ETF", "ZERO", "UNSPEC"], spec=spec)
    assert c["EQ"] == pytest.approx(1.01**12 / 1.005**12 - 1)
    assert c["Y"] == pytest.approx(0.05)
    assert c["ETF"] == pytest.approx(0.04)
    assert c["ZERO"] == 0.0
    assert "UNSPEC" not in c.index or np.isnan(c["UNSPEC"])  # a class without a spec carries no signal
    # the panel variant agrees with the point-wise feature
    panel = feature("carry_yield").call_panel(
        feature("carry_yield").panel_input(v, ["EQ", "Y", "ETF", "ZERO"], spec=spec), spec=spec
    )
    assert panel.iloc[-1]["EQ"] == pytest.approx(c["EQ"]) and panel.iloc[-1]["ETF"] == pytest.approx(0.04)
