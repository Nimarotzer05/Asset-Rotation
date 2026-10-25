"""Edge cases of the phase-2 layers: empty inputs, guards, rarely taken branches."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.errors import ConfigError, DataError
from rotationlab.core.types import CASH, AssetId, Frequency, SeriesKind, StrategyState, Targets
from rotationlab.data.view import _return_index
from rotationlab.engine.modes import walkforward_golden
from rotationlab.features import feature
from rotationlab.features._panel import last_row
from rotationlab.features.ratio import monthly_last
from rotationlab.portfolio.book import Book
from rotationlab.portfolio.costs import CostModel
from rotationlab.strategies import strategy_spec
from rotationlab.strategies.multi_asset_rotation import MultiAssetRotation
from rotationlab.strategies.precious_metals import PreciousMetals
from rotationlab.strategies.us_sector_rotation import UsSectorRotation
from rotationlab.strategies.walkforward import WalkForward
from tests.fixtures.toy import Toy, spec


def test_return_index_base_for_every_frequency() -> None:
    r = pd.Series([0.1, 0.1], index=pd.to_datetime(["2026-03-31", "2026-06-30"]))
    assert _return_index(r, Frequency.QUARTERLY).index[0] == pd.Timestamp("2025-12-31")
    w = pd.Series([0.1], index=pd.to_datetime(["2026-03-06"]))
    assert _return_index(w, Frequency.WEEKLY).index[0] == pd.Timestamp("2026-02-27")
    assert _return_index(w, Frequency.DAILY).index[0] == pd.Timestamp("2026-03-05")
    assert _return_index(w.iloc[:0], Frequency.DAILY).empty


def test_chain_provenance_and_prefix_fallbacks(static_factory) -> None:
    v = static_factory.at(date(2008, 9, 30))
    segs = v.chain_provenance("macro:CPI")
    assert [s.series_id for s in segs] == ["static:fredmd:CPIAUCSL"]
    assert static_factory.tr_prefix("CASH") is None  # a chain: no single primary, reference path


def test_cot_positioning_on_weekly_reports() -> None:
    weeks = pd.date_range("2020-01-07", periods=120, freq="W-TUE")
    rng = np.random.default_rng(1)
    net = pd.Series(rng.normal(1000, 300, 120), index=weeks)
    oi = pd.Series(10000.0, index=weeks)
    w = Toy().monthly("A", [1.0] * 30)
    w.series("cftc:X:noncomm_net", net, SeriesKind.POSITIONING, Frequency.WEEKLY, lag_days=3)
    w.series("cftc:X:open_interest", oi, SeriesKind.POSITIONING, Frequency.WEEKLY, lag_days=3)
    f = w.factory()
    z = feature("cot_spec_net_z").call(
        f.at(date(2022, 4, 15)), net="cftc:X:noncomm_net", open_interest="cftc:X:open_interest"
    )
    known = net[net.index <= pd.Timestamp("2022-04-12")] / 10000
    assert z == pytest.approx((known.iloc[-1] - known.iloc[-120:].mean()) / known.iloc[-120:].std())
    early = feature("cot_spec_net_z").call(
        f.at(date(2020, 3, 31)), net="cftc:X:noncomm_net", open_interest="cftc:X:open_interest"
    )
    assert np.isnan(early)


def test_empty_inputs_give_nan_not_errors() -> None:
    f = Toy().daily("A", [100.0] * 5).factory()
    v = f.at(date(1999, 6, 30))  # before any data
    assert np.isnan(feature("gs_ratio_z60").call(v, gold="A", silver="A"))
    assert np.isnan(
        feature("risk_appetite").call(v, equity="A", baa="t:A:close", aaa="t:A:close", vix="t:A:close")
    )
    assert last_row(pd.DataFrame(columns=["A"]), "x").isna().all()
    assert monthly_last(
        pd.Series([0.0, -1.0], index=pd.to_datetime(["2026-01-02", "2026-01-05"])), date(2026, 1, 5)
    ).empty


def test_book_guards() -> None:
    b = Book("BIL", CostModel(default_bps=10.0, borrow_bps={"S": 100.0}), capital=100.0)
    b.rebalance(
        Targets(date(2026, 1, 2), {AssetId("S"): -0.5}, {}, 1.0), {"S": 10.0}, date(2026, 1, 2)
    )  # no cash price yet
    assert b.cash_units is None and b.weights()[CASH] == pytest.approx(1.5, rel=1e-3)
    b.mark({"S": 10.0}, date(2026, 2, 2))  # carry paid out of the cash value
    assert b.equity() < 100.0 - 0.5 * 10 / 1e4 * 100
    b.units["GHOST"] = 1.0
    with pytest.raises(DataError, match="no price for held"):
        b.mark({}, date(2026, 2, 3))


def test_strategy_guards(bundle) -> None:
    with pytest.raises(ValueError, match="inverse_vol"):
        MultiAssetRotation(
            spec("m", ["A", "RF"], {"cash": "RF", "feature_weights": {"mom_12_1": 1.0}, "weighting": "equal"})
        )
    with pytest.raises(ValueError, match="unsupported"):
        UsSectorRotation(spec("s", ["A", "RF"], {"cash": "RF", "feature_weights": {"inv_vol_12m": 1.0}}))
    with pytest.raises(ValueError, match="60-month"):
        PreciousMetals(
            spec("p", ["G", "S", "RF"], {"cash": "RF", "mean_reversion": {"z_window_months": 120}})
        )
    with pytest.raises(ConfigError, match="unknown strategy"):
        strategy_spec(bundle, "nope")
    s = MultiAssetRotation(
        spec("m", ["A", "RF"], {"cash": "RF", "feature_weights": {"mom_12_1": 1.0}}, warmup=14)
    )
    assert s.warmup().n == 14


def test_walk_forward_survives_a_period_without_prices() -> None:
    from tests.unit.test_strategies import Fixed

    cand = Fixed(spec("fixed", ["A", "RF"], {"cash": "RF", "hold": "A"}))
    f = (
        Toy()
        .monthly("A", [100.0, 101.0], start="2000-03-31")
        .cash("RF", 0.001, n=2, start="2000-03-31")
        .factory()
    )
    wf = WalkForward(
        spec("w", ["A", "RF"], {"cash": "RF"}),
        {"a": cand},
        refit_every=12,
        min_train=1,
        turnover_cost=lambda a, b: 0.0,
        cash="RF",
    )
    st = StrategyState(wf.spec.strategy_id, extra={**wf.initial_state().extra, "prev_date": "1999-12-31"})
    p, st2 = wf.propose(f.at(date(2000, 4, 30)), st)  # no level on or before the previous date
    assert st2.extra["excess"]["a"] == [] and p.weights == {"A": 1.0}


def test_walk_forward_golden_needs_its_sections(bundle, static_store, cal) -> None:
    with pytest.raises(ValueError, match="needs golden_run and walkforward"):
        walkforward_golden(bundle, static_store.observations(), "commodity_trend", cal)
