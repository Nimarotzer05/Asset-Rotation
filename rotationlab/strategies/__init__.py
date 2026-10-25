"""Strategy modules (docs/ARCHITECTURE.md §5) and how they are built from configuration.

    build_strategy(bundle, "multi_asset_rotation")                       # live universe (ETFs)
    build_strategy(bundle, "multi_asset_rotation", "long_history")       # research universe (goldens)
    build_walkforward(bundle, "multi_asset_rotation", "long_history", turnover_cost)

The universe of a strategy is its risky assets plus exactly one cash asset (asset_class "cash"); the cash
asset is passed to the module as `params["cash"]` (excess-return features) and is never weighted: the
remainder of a proposal is cash.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from rotationlab.config.models import Bundle
from rotationlab.core import registry
from rotationlab.core.errors import ConfigError
from rotationlab.core.types import AssetId, Cadence, Months, Role, StrategyId, StrategySpec
from rotationlab.strategies import (
    commodity_trend,
    multi_asset_rotation,
    precious_metals,
    us_equity_exposure,
    us_sector_rotation,
)
from rotationlab.strategies.base import BaseStrategy, deep_merge
from rotationlab.strategies.walkforward import TurnoverCost, WalkForward, grid_points, label

Universe = Literal["live", "long_history"]

__all__ = [
    "BaseStrategy",
    "WalkForward",
    "build_strategy",
    "build_walkforward",
    "commodity_trend",
    "multi_asset_rotation",
    "precious_metals",
    "strategy_spec",
    "us_equity_exposure",
    "us_sector_rotation",
]


def strategy_spec(
    bundle: Bundle, sid: str, universe: Universe = "live", overrides: Mapping[str, Any] | None = None
) -> StrategySpec:
    cfg = bundle.strategies.get(sid)
    if cfg is None:
        raise ConfigError(f"unknown strategy {sid}")
    assets = list(cfg.universe if universe == "live" else cfg.long_history_universe)
    if not assets:
        raise ConfigError(f"strategy {sid} has no {universe} universe")
    cash = [a for a in assets if bundle.universe.assets[a].asset_class == "cash"]
    if len(cash) != 1:
        raise ConfigError(
            f"strategy {sid}: the {universe} universe needs exactly one cash asset, found {cash}"
        )
    params = dict(cfg.params)
    if universe == "long_history":
        params = deep_merge(params, cfg.long_history_params)
    params = deep_merge(params, overrides or {})
    params["cash"] = cash[0]
    risky = [a for a in assets if a != cash[0]]
    return StrategySpec(
        strategy_id=StrategyId(sid),
        version=cfg.version,
        role=Role(cfg.role),
        cadence=Cadence(cfg.cadence),
        universe=tuple(AssetId(a) for a in [*risky, cash[0]]),
        warmup=Months(cfg.warmup_months),
        params=params,
    )


def build_strategy(
    bundle: Bundle, sid: str, universe: Universe = "live", overrides: Mapping[str, Any] | None = None
) -> BaseStrategy:
    cfg = bundle.strategies[sid] if sid in bundle.strategies else None
    if cfg is None:
        raise ConfigError(f"unknown strategy {sid}")
    cls = registry.get_strategy(sid)
    spec = strategy_spec(bundle, sid, universe, overrides)
    strat: BaseStrategy = cls(spec, cfg.confidence.model_dump(), cfg.stops)
    return strat


def build_walkforward(
    bundle: Bundle,
    sid: str,
    universe: Universe,
    turnover_cost: TurnoverCost,
    overrides: Mapping[str, Any] | None = None,
) -> WalkForward:
    cfg = bundle.strategies[sid]
    if cfg.walkforward is None:
        raise ConfigError(f"strategy {sid} has no walkforward section")
    wf = cfg.walkforward
    cands = {
        label(p): build_strategy(bundle, sid, universe, deep_merge(overrides or {}, p))
        for p in grid_points(wf.grid)
    }
    base = strategy_spec(bundle, sid, universe, overrides)
    return WalkForward(
        base, cands, wf.refit_every_months, wf.min_train_months, turnover_cost, str(base.params["cash"])
    )
