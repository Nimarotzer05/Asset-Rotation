"""Phase 2 acceptance: every registered feature and every strategy module passes the look-ahead harness on
the real research store, and every panel variant equals its pointwise feature (docs/ARCHITECTURE.md §4).

The store is cut to the series the features and the long-history universes read (≈ 120 000 rows); at each
date every value not knowable then (obs_date > D or vintage_date > D) is replaced by noise. Deliberately
leaky versions prove that the checks bite.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core import registry
from rotationlab.core.errors import LookaheadError
from rotationlab.core.types import Proposal, StrategyId, StrategyState
from rotationlab.data.view import StoreViewFactory, asset_roles
from rotationlab.portfolio.costs import CostModel
from rotationlab.strategies import build_strategy, build_walkforward
from rotationlab.strategies.base import BaseStrategy
from tests.lookahead.harness import LookaheadHarness

pytestmark = [
    pytest.mark.lookahead,
    pytest.mark.filterwarnings("ignore:overflow encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:divide by zero encountered:RuntimeWarning"),
]

ASSETS = ["US_EQ", "GOLD", "SILVER", "UST10", "FF_MKT", "TBILL"]
# the carry family needs an income spec per class (ADR 052); the harness exercises every kind
CARRY_SPEC = {
    "US_EQ": {"kind": "equity_dy", "tr": "static:usmkt:TR", "px": "static:usmkt:CLOSE"},
    "UST10": {"kind": "yield", "series": "static:fredmd:GS10"},
    "TBILL": {"kind": "yield", "series": "static:fredmd:TB3MS"},
    "GOLD": {"kind": "zero"},
    "SILVER": {"kind": "zero"},
}
FEATURE_PARAMS = {
    "excess_mom_12m": {"cash": "TBILL"},
    "ecy_percentile": {"pct_start": "1926-07-31"},
    "sleeve_vol_12m": {"weights": {"US_EQ": 0.5, "GOLD": 0.5}},
    "basket_vol_ewma": {"weights": {"US_EQ": 0.5, "GOLD": 0.5}},
    "basket_vol_ewma_d": {"weights": {"US_EQ": 0.5, "SILVER": 0.5}},
    "book_vol_hybrid": {
        "baskets": {"EQ": {"US_EQ": 1.0}, "FI": {"UST10": 1.0}, "PM": {"GOLD": 0.6, "SILVER": 0.4}},
        "sizes": {"EQ": 0.3, "FI": 1.0, "PM": 0.3},
        "vols": {"EQ": 0.15, "FI": 0.07, "PM": 0.18},
    },
    "carry_yield": {"spec": CARRY_SPEC},
}
FEATURE_SERIES = [
    *(
        f"static:fredmd:{c}"
        for c in ("INDPRO", "CPIAUCSL", "GS10", "BAA", "AAA", "TB3MS", "FEDFUNDS", "UNRATE")
    ),
    "static:USD_IDX",
    "static:usmkt:CLOSE",
    "static:cboe:VIX",
    "static:shiller:SP500",
    "static:shiller:Earnings",
    "static:shiller:Consumer_Price_Index",
    "static:shiller:Long_Interest_Rate",
]
STRESS = [
    date(1974, 9, 30),
    date(1987, 10, 31),
    date(2000, 3, 31),
    date(2008, 9, 30),
    date(2008, 10, 31),
    date(2020, 3, 31),
    date(2022, 6, 30),
]


@pytest.fixture(scope="module")
def reduced(static_store, bundle):
    roles = asset_roles(bundle.universe)
    assets = set(ASSETS) | {"XAU", "XAG", "CASH", "FF_RF"}
    for cfg in bundle.strategies.values():
        assets |= set(cfg.long_history_universe)
    ids = set(FEATURE_SERIES)
    for a in assets:
        for chain in roles[a].values():
            ids |= set(chain)
    obs = static_store.observations()
    return obs[obs["series_id"].isin(ids)].reset_index(drop=True)


@pytest.fixture(scope="module")
def harness(reduced, catalog, bundle, cal):
    rng = np.random.default_rng(11)
    month_ends = pd.date_range("1975-01-31", "2025-11-30", freq="ME")
    dates = sorted({*STRESS, *(pd.Timestamp(d).date() for d in rng.choice(month_ends, 6, replace=False))})

    def build(obs: pd.DataFrame) -> StoreViewFactory:
        return StoreViewFactory(obs, catalog, asset_roles(bundle.universe), cal, chains=bundle.series.chains)

    return LookaheadHarness(reduced, build, dates, ASSETS)


def test_every_registered_feature_passes_the_harness(harness) -> None:
    metas = list(registry.features().values())
    assert len(metas) >= 30
    assert harness.check_features(metas, FEATURE_PARAMS) == []


def test_every_panel_variant_equals_its_pointwise_feature(harness) -> None:
    for meta in registry.features().values():
        assert meta.panel_fn is not None and meta.panel_input is not None, meta.name
        harness.check_panel_equivalence(meta, FEATURE_PARAMS.get(meta.name))


def test_every_module_and_the_walk_forward_pass_the_harness(harness, bundle) -> None:
    modules = [build_strategy(bundle, sid, "long_history") for sid in bundle.strategies]
    modules.append(build_strategy(bundle, "precious_metals", "long_history", {"hedge": {"enabled": True}}))
    wf = build_walkforward(
        bundle, "multi_asset_rotation", "long_history", CostModel(default_bps=7.5).turnover_cost
    )
    assert harness.check_strategies([*modules, wf]) == []


def test_a_leaky_feature_and_a_leaky_module_are_caught(harness, bundle) -> None:
    def peek(view, assets):
        tr = view.total_return(assets, "ME")
        return tr.iloc[-1] * 0 + float(view.date.month)  # harmless: no future data

    def leaky(view, assets):
        # reads the store-level history beyond the view date through the factory (forbidden)
        f = view._f
        return pd.Series(
            float(f.raw_as_of("static:FF_MKT", pd.Timestamp("2026-07-31")).iloc[-1]), index=assets
        )

    clean_meta = registry.FeatureMeta(
        "peek", "cross_section", ("total_return",), registry.NO_LAG, registry.NO_LAG, 1, peek
    )
    leaky_meta = registry.FeatureMeta(
        "leak", "cross_section", ("total_return",), registry.NO_LAG, registry.NO_LAG, 1, leaky
    )
    assert harness.check_features([clean_meta, leaky_meta]) == ["leak"]

    class Leaky(BaseStrategy):
        strategy_id = "leaky"

        def propose(self, view, state: StrategyState) -> tuple[Proposal, StrategyState]:
            future = view._f.raw_as_of("static:FF_MKT", pd.Timestamp("2026-07-31")).iloc[-1]
            return self.proposal(
                view, {"FF_MKT": 0.5 if future > 0 else 1.0}, 1.0, {"x": float(future)}
            ), state

    honest = build_strategy(bundle, "us_equity_exposure", "long_history")
    leak = Leaky(honest.spec.__class__(**{**honest.spec.__dict__, "strategy_id": StrategyId("leaky")}))
    assert harness.check_strategies([honest, leak]) == ["leaky"]
    with pytest.raises(LookaheadError):
        harness.check_strategy(leak)
