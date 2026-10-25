"""Feature and strategy registries.

Registration attaches metadata (name, kind, inputs, lookback, version) and makes the object
discoverable for tests (look-ahead harness), reports (signal health) and configuration
(strategies referenced by id). Registration is explicit: nothing is picked up by import
side effects alone except through these decorators.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from rotationlab.core.errors import RegistryError
from rotationlab.core.types import Months

FeatureKind = Literal["cross_section", "state"]
NO_LAG = Months(0)


@dataclass(frozen=True)
class FeatureMeta:
    name: str
    kind: FeatureKind
    inputs: tuple[str, ...]  # which MarketView methods are read: close, total_return, series:<id>, ...
    lookback: Months
    macro_lag: Months
    version: int
    fn: Callable[..., Any]
    panel_fn: Callable[..., Any] | None = None  # optional vectorised variant; equivalence-tested
    params: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))  # declared, with defaults
    panel_input: Callable[..., Any] | None = (
        None  # (view, assets | None, **params) -> as-of panel for panel_fn
    )

    def call(self, view: Any, assets: Sequence[str] | None = None, **params: Any) -> Any:
        """Evaluate with declared parameters only (undeclared parameters are an error, ADR 005)."""
        unknown = set(params) - set(self.params)
        if unknown:
            raise RegistryError(f"feature '{self.name}': undeclared parameter(s) {sorted(unknown)}")
        kw = {**self.params, **params}
        if self.kind == "cross_section" and assets is None:
            raise RegistryError(f"feature '{self.name}' is cross-sectional: pass assets")
        memo = getattr(view, "memo", None)  # per-view cache: several modules / candidates read one feature
        key = (
            self.name,
            None if assets is None else tuple(str(a) for a in assets),
            tuple(sorted(kw.items())),
        )
        if memo is not None and key in memo:
            hit = memo[key]
            return hit.copy() if hasattr(hit, "copy") else hit
        out = self.fn(view, list(assets), **kw) if self.kind == "cross_section" else self.fn(view, **kw)  # type: ignore[arg-type]
        if memo is not None:
            memo[key] = out.copy() if hasattr(out, "copy") else out
        return out

    def call_panel(self, panel: Any, **params: Any) -> Any:
        if self.panel_fn is None:
            raise RegistryError(f"feature '{self.name}' has no panel variant")
        unknown = set(params) - set(self.params)
        if unknown:
            raise RegistryError(f"feature '{self.name}': undeclared parameter(s) {sorted(unknown)}")
        return self.panel_fn(panel, **{**self.params, **params})


_FEATURES: dict[str, FeatureMeta] = {}
_STRATEGIES: dict[str, type] = {}


def feature(
    *,
    name: str,
    kind: FeatureKind,
    inputs: Sequence[str],
    lookback: Months,
    macro_lag: Months = NO_LAG,
    version: int = 1,
    params: Mapping[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _FEATURES:
            raise RegistryError(f"feature '{name}' registered twice")
        meta = FeatureMeta(
            name,
            kind,
            tuple(inputs),
            lookback,
            macro_lag,
            version,
            fn,
            params=MappingProxyType(dict(params or {})),
        )
        _FEATURES[name] = meta
        fn.name = name  # type: ignore[attr-defined]
        fn.lookback = lookback  # type: ignore[attr-defined]
        fn.meta = meta  # type: ignore[attr-defined]
        return fn

    return deco


def panel_variant(
    name: str, panel_input: Callable[..., Any] | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach a vectorised implementation (and the as-of panel it reads) to a registered feature."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        meta = _FEATURES.get(name)
        if meta is None:
            raise RegistryError(f"panel_variant: feature '{name}' not registered")
        _FEATURES[name] = FeatureMeta(**{**meta.__dict__, "panel_fn": fn, "panel_input": panel_input})
        return fn

    return deco


def strategy(cls: type) -> type:
    sid = getattr(cls, "strategy_id", None) or cls.__name__
    if sid in _STRATEGIES:
        raise RegistryError(f"strategy '{sid}' registered twice")
    _STRATEGIES[sid] = cls
    return cls


def features() -> dict[str, FeatureMeta]:
    return dict(_FEATURES)


def strategies() -> dict[str, type]:
    return dict(_STRATEGIES)


def get_feature(name: str) -> FeatureMeta:
    try:
        return _FEATURES[name]
    except KeyError as e:
        raise RegistryError(f"unknown feature '{name}'") from e


def get_strategy(strategy_id: str) -> type:
    try:
        return _STRATEGIES[strategy_id]
    except KeyError as e:
        raise RegistryError(f"unknown strategy '{strategy_id}'") from e


def _reset_for_tests() -> None:
    _FEATURES.clear()
    _STRATEGIES.clear()
