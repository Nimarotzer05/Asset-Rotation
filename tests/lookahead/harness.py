"""Generic look-ahead harness.

Contract: a feature or strategy evaluated at date D must return bit-identical results whether or
not the store contains data after D (by obs_date) or revisions published after D (by vintage_date).

Usage (Phase 1+):
    harness = LookaheadHarness(observations_df, view_factory_builder, dates)
    harness.check_feature(meta)          # for every registered FeatureMeta
    harness.check_strategy(strategy)     # for every registered Strategy

`view_factory_builder(observations_df) -> ViewFactory` builds a factory over an in-memory store,
so the harness can hand it a mutated copy of the data.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date

import numpy as np
import pandas as pd

from rotationlab.core.errors import LookaheadError
from rotationlab.core.protocols import Strategy, ViewFactory
from rotationlab.core.registry import FeatureMeta


def mutate_future(observations: pd.DataFrame, d: date, seed: int = 0) -> pd.DataFrame:
    """Replace every value not knowable at D (obs_date > D or vintage_date > D) with noise."""
    rng = np.random.default_rng(seed)
    out = observations.copy()
    future = (pd.to_datetime(out["obs_date"]) > pd.Timestamp(d)) | (
        pd.to_datetime(out["vintage_date"]) > pd.Timestamp(d)
    )
    out.loc[future, "value"] = rng.normal(0, 1, future.sum()) * 1e6
    return out


def _same_scalar(a: object, b: object) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    fa = float("nan") if a is None else float(a)  # type: ignore[arg-type]
    fb = float("nan") if b is None else float(b)  # type: ignore[arg-type]
    return (np.isnan(fa) and np.isnan(fb)) or fa == fb


def _identical(a: object, b: object) -> bool:
    if isinstance(a, pd.Series | pd.DataFrame) and isinstance(b, pd.Series | pd.DataFrame):
        try:
            pd.testing.assert_frame_equal(pd.DataFrame(a), pd.DataFrame(b), check_exact=True)
            return True
        except AssertionError:
            return False
    if isinstance(a, float | int | str) and isinstance(b, float | int | str):
        return _same_scalar(a, b)
    return bool(a == b)


def _dump(x: object) -> str:
    """NaN-aware identity of a proposal or state (NaN signals compare equal to themselves)."""
    return json.dumps(asdict(x), sort_keys=True, default=str)  # type: ignore[call-overload]


class LookaheadHarness:
    def __init__(
        self,
        observations: pd.DataFrame,
        build_factory: Callable[[pd.DataFrame], ViewFactory],
        dates: Sequence[date],
        assets: Sequence[str] = (),
    ) -> None:
        self.obs = observations
        self.build = build_factory
        self.dates = list(dates)
        self.assets = list(assets)

    def _eval(self, meta: FeatureMeta, view: object, params: dict[str, object]) -> object:
        return meta.call(view, self.assets if meta.kind == "cross_section" else None, **params)

    def check_feature(self, meta: FeatureMeta, params: dict[str, object] | None = None) -> None:
        """Declared parameters only (defaults unless given); each date on a fresh mutated store."""
        clean = self.build(self.obs)
        for i, d in enumerate(self.dates):
            dirty = self.build(mutate_future(self.obs, d, seed=i))
            r1 = self._eval(meta, clean.at(d), params or {})
            r2 = self._eval(meta, dirty.at(d), params or {})
            if not _identical(r1, r2):
                raise LookaheadError(f"feature '{meta.name}' differs at {d} when future data is mutated")

    def check_features(
        self, metas: Sequence[FeatureMeta], params: dict[str, dict[str, object]] | None = None
    ) -> list[str]:
        """All features at once: one mutated store per date (much faster than feature by feature).
        Returns the names that leak (empty list = all clean)."""
        params = params or {}
        clean = self.build(self.obs)
        leaks: set[str] = set()
        for i, d in enumerate(self.dates):
            dirty = self.build(mutate_future(self.obs, d, seed=i))
            v1, v2 = clean.at(d), dirty.at(d)
            for m in metas:
                if not _identical(
                    self._eval(m, v1, params.get(m.name, {})), self._eval(m, v2, params.get(m.name, {}))
                ):
                    leaks.add(m.name)
        return sorted(leaks)

    def check_strategies(self, strategies: Sequence[Strategy]) -> list[str]:
        """All strategies at once, each carrying its own state across the dates. Returns leaking ids."""
        clean = self.build(self.obs)
        states = [s.initial_state() for s in strategies]
        leaks: set[str] = set()
        for i, d in enumerate(self.dates):
            dirty = self.build(mutate_future(self.obs, d, seed=i))
            v1, v2 = clean.at(d), dirty.at(d)
            for k, s in enumerate(strategies):
                p1, s1 = s.propose(v1, states[k])
                p2, s2 = s.propose(v2, states[k])
                if _dump(p1) != _dump(p2) or _dump(s1) != _dump(s2):
                    leaks.add(str(s.spec.strategy_id))
                states[k] = s1
        return sorted(leaks)

    def check_panel_equivalence(self, meta: FeatureMeta, params: dict[str, object] | None = None) -> None:
        """The panel variant on the as-of panel at D equals the pointwise value at D (bit for bit)."""
        if meta.panel_fn is None or meta.panel_input is None:
            return
        clean = self.build(self.obs)
        kw = {**meta.params, **(params or {})}
        for d in self.dates:
            view = clean.at(d)
            pointwise = self._eval(meta, view, params or {})
            panel = meta.call_panel(meta.panel_input(view, self.assets or None, **kw), **(params or {}))
            if isinstance(panel, pd.DataFrame):
                row = panel.reindex(columns=self.assets).iloc[-1] if len(panel) else pd.Series(dtype=float)
                same = _identical(
                    pd.Series(pointwise, dtype=float), pd.Series(row, dtype=float).rename(meta.name)
                )
            else:
                last = panel.iloc[-1] if len(panel) else float("nan")
                same = _same_scalar(pointwise, last)
            if not same:
                raise LookaheadError(f"feature '{meta.name}': panel variant differs from pointwise at {d}")

    def check_strategy(self, strategy: Strategy) -> None:
        clean = self.build(self.obs)
        state = strategy.initial_state()
        for i, d in enumerate(self.dates):
            dirty = self.build(mutate_future(self.obs, d, seed=i))
            p1, s1 = strategy.propose(clean.at(d), state)
            p2, s2 = strategy.propose(dirty.at(d), state)
            if _dump(p1) != _dump(p2) or _dump(s1) != _dump(s2):
                raise LookaheadError(
                    f"strategy '{strategy.spec.strategy_id}' differs at {d} when future data is mutated"
                )
            state = s1
