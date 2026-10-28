"""Phase 2 acceptance: the five modules, run through the engine on the store, reproduce the research.

Two levels:
* figures – Sharpe, return, drawdown of each golden run (strategy YAML `golden`, `golden_run`) within the
  configured tolerance, and within 0.003 Sharpe of the exact research value;
* weights – the target weights at every decision date equal those of the research code (src/signals.py,
  src/commodity_model.py, the formulas of scripts/run_equity.py and scripts/run_gold_silver.py) applied to
  the same store panel. This checks the logic itself, independent of costs and timing.

Also: the walk-forward golden (0.772, top 4 with trend filter in all 44 years), the crash-hedge record
(gold beat silver in 8 of 8 equity drawdowns > 15 %), the optional valuation scaling (0.587, 1931–2023),
and what production timing (execution at the next close, ADR 011) changes where daily closes exist.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

import config as research_config
from rotationlab.engine.modes import golden, research_factory, walkforward_golden
from rotationlab.features.ratio import monthly_last
from rotationlab.stats import change_over, drawdown_episodes
from src import commodity_model, signals
from src import features as research_features

pytestmark = [pytest.mark.golden, pytest.mark.slow]

# exact research values (output/*/…csv) – the YAML goldens are these, rounded
RESEARCH_SHARPE = {
    "us_equity_exposure": 0.5732112733862765,  # output/equity/A2_strategies_1927_2026.csv
    "us_sector_rotation": 0.5913014439634415,  # output/equity/B3_strategies.csv
    "multi_asset_rotation": 0.5703318188040025,  # output/long/07_backtest_summary.csv
    "commodity_trend": 0.7406860175584565,  # output/commodities/04_backtest.csv (C)
    "precious_metals": 0.2201169366771409,  # output/gold_silver/05_slow_strategies.csv
}
SIDS = list(RESEARCH_SHARPE)


@pytest.fixture(scope="module")
def obs(static_store):
    return static_store.observations()


@pytest.fixture(scope="module")
def reports(bundle, obs, cal):
    return {sid: golden(bundle, obs, sid, cal) for sid in SIDS}


@pytest.mark.parametrize("sid", SIDS)
def test_golden_figures(reports, sid) -> None:
    rep = reports[sid]
    assert rep.execution == "same_close"
    assert rep.failures() == []
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(RESEARCH_SHARPE[sid], abs=0.003)


def _panel(bundle, obs, cal, sid):
    gr = bundle.strategies[sid].golden_run
    f = research_factory(bundle, obs, cal, gr.data_from)
    return f.at(gr.end)


def _engine_weights(rep, columns) -> pd.DataFrame:
    w = rep.result.weights.reindex(columns=columns).fillna(0.0)
    return w


def test_multi_asset_weights_equal_the_research_code(bundle, obs, cal, reports) -> None:
    uni = list(research_config.LONG_UNIVERSE)
    lv = _panel(bundle, obs, cal, "multi_asset_rotation").total_return(uni, "ME").loc["1972-12-31":]
    score = signals.composite_score(research_features.asset_features(lv), research_config.FEATURE_WEIGHTS)
    ref = signals.build_weights(score, lv, top_n=3, trend_filter=True)
    eng = _engine_weights(reports["multi_asset_rotation"], ref.columns).reindex(ref.index)
    assert np.abs(eng.to_numpy() - ref.to_numpy()).max() < 1e-9


def test_commodity_weights_equal_the_research_code(bundle, obs, cal, reports) -> None:
    uni = list(commodity_model.COMMODITIES)
    lv = _panel(bundle, obs, cal, "commodity_trend").total_return(uni, "ME").loc["1972-12-31":]
    ref = commodity_model.tilted_weights(pd.DataFrame(0.0, index=lv.index, columns=lv.columns), lv, lam=0.0)
    eng = _engine_weights(reports["commodity_trend"], ref.columns).reindex(ref.index)
    assert np.abs(eng.to_numpy() - ref.to_numpy()).max() < 1e-9


def test_sector_weights_equal_the_research_code(bundle, obs, cal, reports) -> None:
    """scripts/run_equity.py part B3: rank composite, top 3 equal weight, market trend gate."""
    inds = [a for a in bundle.strategies["us_sector_rotation"].long_history_universe if a != "FF_RF"]
    view = _panel(bundle, obs, cal, "us_sector_rotation")
    lv = view.total_return(inds, "ME")  # the index starts at 100 one month before the first return
    sig12, sig6 = lv.shift(1) / lv.shift(13) - 1, lv.shift(1) / lv.shift(7) - 1
    trend = lv / lv.rolling(10).mean() - 1
    combo = sig12.rank(axis=1) * 0.5 + sig6.rank(axis=1) * 0.3 + trend.rank(axis=1) * 0.2
    mkt = view.total_return(["FF_MKT"], "ME")["FF_MKT"]
    mt = mkt / mkt.rolling(10).mean() - 1
    above = (mt > 0).astype(float).where(mt.notna())
    ref = pd.DataFrame(0.0, index=combo.index, columns=[*inds, "CASH"])
    for t in combo.index:
        s = combo.loc[t].dropna()
        if len(s) < 8:
            ref.loc[t, "CASH"] = 1.0
            continue
        picks = s.sort_values(ascending=False).index[:3]
        g = 1.0 if pd.isna(above.get(t)) else float(above.get(t))
        ref.loc[t, picks] = g / 3
        ref.loc[t, "CASH"] = 1 - g
    eng = _engine_weights(reports["us_sector_rotation"], ref.columns)
    ref = ref.loc[eng.index]  # decisions start 1926-07 (the index base is 1926-06)
    assert len(ref) == 1201 and np.abs(eng.to_numpy() - ref.to_numpy()).max() < 1e-9


def test_equity_exposure_equals_the_research_votes(bundle, obs, cal, reports) -> None:
    view = _panel(bundle, obs, cal, "us_equity_exposure")
    tr = view.total_return(["FF_MKT", "FF_RF"], "ME")
    mkt, rf = tr["FF_MKT"].pct_change(), tr["FF_RF"].pct_change()
    lvl = tr["FF_MKT"]
    trend = lvl / lvl.rolling(10).mean() - 1
    mom = (1 + (mkt - rf)).rolling(12).apply(np.prod, raw=True) - 1
    w = ((trend > 0).astype(float).where(trend.notna()) + (mom > 0).astype(float).where(mom.notna())) / 2
    eng = reports["us_equity_exposure"].result.weights["FF_MKT"]
    both = pd.DataFrame({"eng": eng, "ref": w}).dropna()
    assert len(both) > 1180 and (both["eng"] - both["ref"]).abs().max() < 1e-12


def test_gold_silver_position_equals_the_research_tranches(bundle, obs, cal, reports) -> None:
    view = _panel(bundle, obs, cal, "precious_metals")
    g = monthly_last(view.asset_series("XAU", "close"), view.date)
    s = monthly_last(view.asset_series("XAG", "close"), view.date)
    lr = np.log(pd.DataFrame({"G": g, "S": s}).dropna().eval("G / S")).loc["1970-12-31":]
    z60 = (lr - lr.rolling(60, min_periods=30).mean()) / lr.rolling(60, min_periods=30).std()
    pos = (-z60 / 2).clip(-1, 1).fillna(0).rolling(6, min_periods=1).mean()
    w = reports["precious_metals"].result.weights.reindex(columns=["XAU", "XAG"]).fillna(0.0)
    both = pd.DataFrame({"gold": w["XAU"], "silver": w["XAG"], "ref": pos}).dropna()
    assert len(both) > 600
    assert (both["gold"] - both["ref"]).abs().max() < 1e-12 and (
        both["silver"] + both["ref"]
    ).abs().max() < 1e-12


@pytest.mark.parametrize("sid", ["multi_asset_rotation", "precious_metals"])
def test_execution_at_the_next_close_stays_within_tolerance(bundle, obs, cal, sid) -> None:
    """ADR 011: production trades at the next session's close. Only daily series move (US equities and
    silver in multi-asset, both metals in the satellite); monthly series price at their month-end."""
    rep = golden(bundle, obs, sid, cal, "next_close")
    assert rep.failures() == []


# ADR 042, output/execution/TIMING.md: Sharpe ex cash with honest timing for monthly averages. Pinned so a
# change to the engine or the data that moves them is a visible decision, not a silent drift.
HONEST = {"commodity_trend": 0.4225, "multi_asset_rotation": 0.5574}


@pytest.mark.parametrize("sid", sorted(HONEST))
def test_honest_timing_for_monthly_averages(bundle, obs, cal, sid) -> None:
    """`next_tradable`: World Bank monthly averages trade at the next decision date, closing prices at the
    next session. The study figure (same_close) re-uses the average that made the signal as the price."""
    rep = golden(bundle, obs, sid, cal, "next_tradable")
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(HONEST[sid], abs=5e-4)
    research = golden(bundle, obs, sid, cal, "same_close").measured["sharpe_ex_cash"]
    assert rep.measured["sharpe_ex_cash"] < research


def test_honest_timing_leaves_modules_without_averages_unchanged(bundle, obs, cal) -> None:
    a = golden(bundle, obs, "us_equity_exposure", cal, "next_tradable").result.decisions
    b = golden(bundle, obs, "us_equity_exposure", cal, "next_close").result.decisions
    pd.testing.assert_frame_equal(a, b)


def test_forecast_portfolio_golden(bundle, obs, cal) -> None:
    """P8 (ADR 048): the pre-registered paper rule reproduces its first run (regression pin, not a verdict):
    Sharpe 0.487, 9.2 % p.a., drawdown −15.9 % over 1974-01 … 2018-12, tradable timing, 15 bp costs."""
    rep = golden(bundle, obs, "forecast_portfolio", cal)
    assert rep.execution == "next_tradable"
    assert rep.failures() == []
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(0.48677, abs=5e-4)
    assert rep.measured["months"] == 540
    assert rep.result.decisions.index.max() <= pd.Timestamp("2018-12-31")  # never into the pseudo-holdout


def test_forecast_portfolio_v2_golden(bundle, obs, cal) -> None:
    """Round 2 (ADR 052/053): the same rule on five classes reproduces its first run (regression pin; the
    criterion of ADR 048 e was not met): Sharpe 0.605, 7.6 % p.a., drawdown −9.1 % over 1981-08 … 2018-12."""
    rep = golden(bundle, obs, "forecast_portfolio_v2", cal)
    assert rep.execution == "next_tradable"
    assert rep.failures() == []
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(0.6047, abs=5e-4)
    assert rep.measured["months"] == 449
    assert rep.result.decisions.index.max() <= pd.Timestamp("2018-12-31")


def test_sleeve_allocator_golden(bundle, obs, cal) -> None:
    """Round 3 (ADR 054/056): the sleeve allocator reproduces its corrected walk-forward run (regression pin; the
    criterion of ADR 054 e was not met): Sharpe 0.683, 10.7 % p.a., drawdown −14.7 % over 1979-01 … 2026-01,
    gross exposure never above 1.5, every sleeve within its budget share. Ties in the two-instrument sleeves go
    to configuration order (ADR 054 b), not to float residues (the first run's 0.705, ADR 056)."""
    rep = golden(bundle, obs, "sleeve_allocator", cal)
    assert rep.execution == "next_tradable"
    assert rep.failures() == []
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(0.6830, abs=5e-4)
    assert rep.measured["months"] == 565
    gross = [sum(p.weights.values()) for p in rep.result.proposals if not p.warmup]
    assert max(gross) <= 1.5 + 1e-9 and min(gross) >= 0.0
    sleeves = [k for k in rep.result.proposals[-1].signals if k.startswith("sleeve_weight:")]
    assert all(rep.result.proposals[-1].signals[k] <= 1.0 + 1e-9 for k in sleeves)


def test_sleeve_allocator_v2_golden(bundle, obs, cal) -> None:
    """Round 4 (ADR 057/058/059): the allocator v2 reproduces its pre-registered walk-forward run of 2026-10-28
    (regression pin; the primary criterion of ADR 057 f WAS met: Δ Sharpe to B1 +0.285 [+0.140, +0.430]):
    Sharpe 0.791, 10.8 % p.a., drawdown −13.1 % over 1977-01 … 2025-11 (587 months, window by rule), the long
    book never above 1.5 gross, the currency overlay never above 0.5 gross (ADR 057 c)."""
    rep = golden(bundle, obs, "sleeve_allocator_v2", cal)
    assert rep.execution == "next_tradable"
    assert rep.failures() == []
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(0.7911, abs=5e-4)
    assert rep.measured["months"] == 587
    props = [p for p in rep.result.proposals if not p.warmup]
    long_gross = [sum(w for a, w in p.weights.items() if not a.startswith("FX_")) for p in props]
    fx_gross = [sum(abs(w) for a, w in p.weights.items() if a.startswith("FX_")) for p in props]
    assert max(long_gross) <= 1.5 + 1e-9 and min(long_gross) >= 0.0
    assert max(fx_gross) <= 0.5 + 1e-9


def test_walk_forward_golden(bundle, obs, cal) -> None:
    rep = walkforward_golden(bundle, obs, "multi_asset_rotation", cal)
    assert rep.failures() == []
    chosen = {c["chosen"] for c in rep.extra["choices"]}
    assert len(rep.extra["choices"]) == 44 and chosen == {"top_n=4,trend_filter=True"}
    assert rep.extra["choices"][0]["date"] == "1982-11-30"


def test_gold_beat_silver_in_every_large_equity_drawdown(bundle, obs, cal) -> None:
    """DERISK.md §1: equity drawdowns > 15 % since 1971 (recovery within 2 %), 8 of 8 with a rising ratio."""
    view = research_factory(bundle, obs, cal, date(1970, 12, 31)).at(date(2026, 2, 28))
    g = monthly_last(view.asset_series("XAU", "close"), view.date)
    s = monthly_last(view.asset_series("XAG", "close"), view.date)
    gs = pd.DataFrame({"G": g, "S": s}).dropna()
    eq = view.total_return(["US_EQ"], "ME")["US_EQ"].reindex(gs.index)
    eps = drawdown_episodes(eq)
    spread = change_over(gs["G"] / gs["S"], eps, log=True)
    expected = bundle.strategies["precious_metals"].golden
    assert len(eps) == expected["crash_episodes_total"] == 8
    assert int((spread > 0).sum()) == expected["crash_episodes_positive"]
    research = [0.11, 0.43, 0.12, 0.03, 0.24, 0.27, 0.32, 0.12]  # DERISK.md, "Spread (log)"
    assert spread.round(2).tolist() == research
    assert [f"{e.peak:%Y-%m}" for e in eps] == [
        "1972-12",
        "1980-11",
        "1987-08",
        "1998-06",
        "2000-08",
        "2007-10",
        "2019-12",
        "2021-12",
    ]


def test_valuation_scaling_reproduces_the_research(bundle, obs, cal) -> None:
    """output/equity/A2_strategies_1931_2023.csv: trend/momentum mean × (0.75 + 0.25 · ECY percentile)."""
    base = bundle.strategies["us_equity_exposure"].golden_run
    run = base.model_copy(
        update={
            "sample": (date(1931, 1, 31), date(2023, 6, 30)),
            "params": {"valuation_scaling": {"enabled": True, "pct_start": "1926-07-31"}},
        }
    )
    rep = golden(bundle, obs, "us_equity_exposure", cal, run=run)
    assert rep.measured["sharpe_ex_cash"] == pytest.approx(0.5872990524535742, abs=0.002)
    assert rep.measured["ann_return"] == pytest.approx(0.08981813022530427, abs=0.001)
    assert rep.measured["max_drawdown"] == pytest.approx(-0.3547053426182649, abs=0.002)
