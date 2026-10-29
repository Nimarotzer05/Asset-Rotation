"""P3 (ADR 043): the base forecast model on the research store.

* scores = the multi_asset_rotation module's composite on the same cross-section, and = the research formula
* panel ≡ pointwise: the past scores behind the calibration equal the scores computed at those dates
* look-ahead: a forecast at D is identical whether the store holds the future (overwritten or removed) or not
* outcomes and calibration: definitions on small known inputs
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.types import AssetId, Cadence, Months, Role, StrategyId, StrategySpec
from rotationlab.engine.modes import averaged_assets, research_factory
from rotationlab.forecast.model import (
    BlockBootstrap,
    ForecastModel,
    calibrate,
    composite,
    feature_panel,
    forward_returns,
    ranks_of,
    relative,
)
from rotationlab.strategies.forecast_portfolio import ForecastPortfolio
from rotationlab.strategies.multi_asset_rotation import MultiAssetRotation
from tests.fixtures.toy import Toy
from tests.lookahead.harness import mutate_future
from tests.lookahead.test_audit_phase2 import truncate

pytestmark = [
    pytest.mark.lookahead,
    pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:divide by zero encountered:RuntimeWarning"),
]

DATES = [date(1979, 1, 31), date(1987, 10, 31), date(1999, 6, 30), date(2008, 10, 31), date(2018, 12, 31)]


@pytest.fixture(scope="module")
def obs(static_store, bundle):
    o = static_store.observations()
    u = bundle.forecast.universe["long_history"]
    ids = set()
    roles = {a: c for a, c in bundle.universe.assets.items()}
    for a in [*u.ranked, *u.trend_only, u.cash]:
        for v in roles[a].series.values():
            ids |= {v} if isinstance(v, str) else set(v)
    return o[o["series_id"].isin(ids)].reset_index(drop=True)


@pytest.fixture(scope="module")
def factory(bundle, obs, cal):
    return research_factory(bundle, obs, cal, date(1972, 12, 31))


@pytest.fixture(scope="module")
def model(bundle):
    return ForecastModel(bundle.forecast, averaged=averaged_assets(bundle))


def test_scores_equal_the_module_composite_on_the_same_cross_section(model, factory, bundle) -> None:
    mp = bundle.strategies["multi_asset_rotation"].params
    spec = StrategySpec(
        StrategyId("m"),
        1,
        Role.CORE,
        Cadence.MONTHLY,
        tuple(AssetId(a) for a in [*model.ranked, model.cash]),
        Months(14),
        {**mp, "cash": model.cash},
    )
    module = MultiAssetRotation(spec)
    for d in DATES:
        v = factory.at(d)
        ours = model.score_history(v).iloc[-1]
        theirs = module.composite(v).reindex(model.ranked)
        assert np.allclose(ours.to_numpy(float), theirs.to_numpy(float), rtol=0, atol=1e-12), d
        assert list(ours.sort_values(ascending=False).index) == list(
            theirs.sort_values(ascending=False).index
        )


def test_portfolio_rule_picks_the_forecasts_top_two(model, factory, bundle) -> None:
    """P8 (ADR 048 b): the paper rule on the forecast's own universe holds exactly the two classes the
    forecast ranks first and second (before trend filter and vol scaling, which only shrink them)."""
    pp = bundle.strategies["forecast_portfolio"].params
    spec = StrategySpec(
        StrategyId("p"),
        1,
        Role.PAPER,
        Cadence.MONTHLY,
        tuple(AssetId(a) for a in [*model.ranked, model.cash]),
        Months(13),
        {**pp, "cash": model.cash},
    )
    rule = ForecastPortfolio(spec)
    for d in DATES:
        v = factory.at(d)
        f = model.forecast(v, "test", [1])[0]
        p, _ = rule.propose(v, rule.initial_state())
        top2 = f.ranking()[:2]
        assert [a for a in top2 if p.signals[f"trend:{a}"] > 0] == [str(a) for a in p.weights], d
        assert all(abs(w - 0.5 * p.signals["scale"]) < 1e-12 for w in p.weights.values()) or not p.weights


def test_scores_equal_the_research_formula(model, factory) -> None:
    v = factory.at(date(2018, 12, 31))
    feats = {k: feature_panel(v, k, model.ranked) for k in model.weights}
    ours = composite(feats, model.weights, model.clip)
    # src/signals.py composite_score (clip ±3, weights normalised), frozen 2026-10-28 – legacy code archived
    research = pd.read_csv(
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "legacy_reference"
        / "forecast_composite_2018-12-31.csv.gz",
        index_col=0,
        parse_dates=True,
    ).reindex(index=ours.index, columns=ours.columns)
    assert (ours - research).abs().max().max() <= 1e-9
    assert ours.notna().sum().sum() > 4 * 500


def test_past_scores_equal_the_scores_computed_at_those_dates(model, factory) -> None:
    """Panel ≡ pointwise: the calibration ranks past months by scores from the as-of panel at D; they must be
    the scores the model gave at those dates (unrevised price data: prefix property, ADR 036)."""
    hist = model.score_history(factory.at(date(2018, 12, 31)))
    ranks = ranks_of(hist)
    for d in [date(1976, 6, 30), *DATES[:-1], date(2012, 3, 31)]:
        then = model.score_history(factory.at(d)).iloc[-1]
        row = hist.loc[pd.Timestamp(d)]
        assert np.allclose(row.to_numpy(float), then.to_numpy(float), rtol=0, atol=1e-12, equal_nan=True), d
        assert ranks.loc[pd.Timestamp(d)].equals(ranks_of(then.to_frame().T).iloc[0]), d


def test_forecast_is_invariant_to_the_future(model, bundle, obs, cal) -> None:
    clean = research_factory(bundle, obs, cal, date(1972, 12, 31))
    for i, d in enumerate(DATES):
        a = [f.to_json() for f in model.forecast(clean.at(d), "s")]
        noisy = research_factory(bundle, mutate_future(obs, d, seed=i), cal, date(1972, 12, 31))
        cut = research_factory(bundle, truncate(obs, d), cal, date(1972, 12, 31))
        assert a == [f.to_json() for f in model.forecast(noisy.at(d), "s")], d
        assert a == [f.to_json() for f in model.forecast(cut.at(d), "s")], d


def test_forecast_shape_at_a_month_end(model, factory) -> None:
    fcs = model.forecast(factory.at(date(2008, 10, 31)), factory.data_snapshot())
    assert [f.horizon_months for f in fcs] == [1, 3, 6]
    f = fcs[0]
    assert f.status in ("signal", "no_clear_signal") and f.calibration_months >= 60
    assert sorted(f.ranking()) == sorted(model.ranked)
    by = f.by_asset()
    assert all(
        by[a].rank is None and by[a].score is None and by[a].trend in ("up", "down") for a in model.trend_only
    )
    assert f.params["ranked"] == tuple(model.ranked) and f.data_snapshot == factory.data_snapshot()
    early = model.forecast(factory.at(date(1975, 12, 31)), "s")[0]
    assert early.status == "warmup" and early.ranking() == [] and "warmup" in early.notes[0]


# ---------------------------------------------------------------------------- definitions on known inputs
def test_forward_and_relative_returns() -> None:
    idx = pd.date_range("2000-01-31", periods=5, freq="ME")
    lv = pd.DataFrame({"A": [100, 110, 121, 133.1, 146.41], "B": [100, 100, 100, 100, 100.0]}, index=idx)
    f1 = forward_returns(lv, 1)
    assert f1["A"].iloc[0] == pytest.approx(0.10) and np.isnan(f1["A"].iloc[-1])
    f2 = forward_returns(lv, 2)
    assert f2["A"].iloc[0] == pytest.approx(0.21) and f2["A"].iloc[-2:].isna().all()
    lagged = forward_returns(lv, 1, {"A": 1})  # monthly average: from t+1 to t+2
    assert lagged["A"].iloc[0] == pytest.approx(121 / 110 - 1) and lagged["A"].iloc[-2:].isna().all()
    rel = relative(f1)
    assert rel.iloc[0].tolist() == pytest.approx([0.05, -0.05])


def test_ranks_and_calibration() -> None:
    idx = pd.date_range("2000-01-31", periods=4, freq="ME")
    scores = pd.DataFrame({"A": [2.0, 1.0, np.nan, 0.0], "B": [1.0, 2.0, 1.0, 1.0]}, index=idx)
    r = ranks_of(scores)
    assert r.iloc[0].tolist() == [1.0, 2.0] and r.iloc[2].isna().all()
    rel = pd.DataFrame({"A": [0.02, -0.01, 0.0, np.nan], "B": [-0.02, 0.01, 0.0, 0.0]}, index=idx)
    cal = calibrate(r, rel, BlockBootstrap(200, 1, 1), 0.9)
    assert [c.months for c in cal] == [2, 2]  # month 3 has no rank, month 4 no outcome for A
    assert cal[0].mean == pytest.approx(0.015) and cal[1].mean == pytest.approx(-0.015)


def test_block_bootstrap_interval_is_deterministic_and_sensible() -> None:
    x = np.random.default_rng(0).normal(0.01, 0.04, 480)
    b = BlockBootstrap(2000, 12, 7)
    lo, hi = b.interval(x, 0.90)
    assert (lo, hi) == BlockBootstrap(2000, 12, 7).interval(x, 0.90)
    se = x.std(ddof=1) / np.sqrt(len(x))
    assert lo < x.mean() < hi
    assert 0.6 * 1.645 * se < (hi - lo) / 2 < 1.5 * 1.645 * se  # iid data: close to the normal interval


def test_complete_months_drops_only_the_partial_running_month() -> None:
    from rotationlab.forecast.model import complete_months

    w = (
        Toy()
        .monthly("A", [100.0, 101.0, 102.0], start="2000-01-31")
        .daily("B", [1.0 + i / 100 for i in range(70)])
    )
    f = w.factory()
    mid = f.at(date(2000, 4, 5))  # no April data for A; B has daily closes into April
    a = complete_months(mid, mid.total_return(["A"], "ME"))
    assert a.index[-1] == pd.Timestamp("2000-03-31")  # a complete month stays
    b = complete_months(mid, mid.total_return(["B"], "ME"))
    assert b.index[-1] == pd.Timestamp("2000-03-31")  # the partial April row (labelled 04-05) is dropped
    end = f.at(date(2000, 3, 31))
    assert complete_months(end, end.total_return(["B"], "ME")).index[-1] == pd.Timestamp("2000-03-31")


# ---------------------------------------------------------------------------- round 5 (ADR 063): the Fed model
FED_DATES = [date(1985, 6, 30), date(2008, 10, 31), date(2021, 6, 30)]


@pytest.fixture(scope="module")
def fed_obs(static_store, bundle):
    o = static_store.observations()
    fc = bundle.forecasts["forecast_fed"]
    u = fc.universe["long_history"]
    ids: set[str] = set()
    for a in [*u.ranked, *u.trend_only, u.cash]:
        for v in bundle.universe.assets[a].series.values():
            ids |= {v} if isinstance(v, str) else set(v)
    keep = o["series_id"].isin(ids) | o["series_id"].str.startswith("static:fredmd")
    return o[keep].reset_index(drop=True)


def test_fed_forecast_is_invariant_to_the_future(bundle, fed_obs, cal) -> None:
    """The macro component reads revised macro vintages (fredmd_rt from 2019) and refits its ridge at every D:
    noise in, or removal of, everything after D must not change the forecast at D."""
    fc = bundle.forecasts["forecast_fed"]
    model = ForecastModel(fc, averaged=averaged_assets(bundle))
    start = fc.evaluation.data_from
    clean = research_factory(bundle, fed_obs, cal, start)
    for i, d in enumerate(FED_DATES):
        a = [f.to_json() for f in model.forecast(clean.at(d), "s", [1])]
        noisy = research_factory(bundle, mutate_future(fed_obs, d, seed=10 + i), cal, start)
        cut = research_factory(bundle, truncate(fed_obs, d), cal, start)
        assert a == [f.to_json() for f in model.forecast(noisy.at(d), "s", [1])], d
        assert a == [f.to_json() for f in model.forecast(cut.at(d), "s", [1])], d
        assert model.score_history(clean.at(d)).iloc[-1].notna().all(), d  # the Fed score exists at D


def test_fed_score_blends_the_round1_composite(bundle, fed_obs, cal) -> None:
    """Without its macro component the round-5 model is exactly the round-1 composite on its classes."""
    fc = bundle.forecasts["forecast_fed"]
    base = ForecastModel(fc.model_copy(update={"model": fc.model.model_copy(update={"macro": None})}))
    v = research_factory(bundle, fed_obs, cal, fc.evaluation.data_from).at(date(2008, 10, 31))
    feats = {k: feature_panel(v, k, base.ranked) for k in base.weights}
    ours = composite(feats, base.weights, base.clip).reindex(columns=base.ranked).iloc[-1]
    assert np.allclose(base.score_history(v).iloc[-1].to_numpy(float), ours.to_numpy(float), atol=1e-12)
