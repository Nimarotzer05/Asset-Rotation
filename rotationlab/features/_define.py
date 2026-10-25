"""`define`: register a feature from its panel formula.

    define(name, kind, inputs, lookback, panel_input, compute, params)

registers the pointwise feature (the D-row of `compute(panel_input(view, …))`) and the panel variant
(`compute` itself) together, so the two cannot drift apart. `compute(panel, **params)` returns a frame
(cross-sectional: one column per asset) or a series (state); the pointwise value is its last row.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd

from rotationlab.core import registry
from rotationlab.core.registry import FeatureKind
from rotationlab.core.types import Months
from rotationlab.features._panel import last_row, last_value

PanelInput = Callable[..., pd.DataFrame]
Compute = Callable[..., Any]


def define(
    name: str,
    kind: FeatureKind,
    inputs: Sequence[str],
    lookback: Months,
    panel_input: PanelInput,
    compute: Compute,
    params: Mapping[str, Any] | None = None,
    version: int = 1,
    macro_lag: Months = registry.NO_LAG,
) -> Callable[..., Any]:
    if kind == "cross_section":

        def pointwise(view: Any, assets: Sequence[str], **kw: Any) -> pd.Series:
            out = compute(panel_input(view, assets, **kw), **kw)
            return last_row(out.reindex(columns=list(assets)), name)

    else:

        def pointwise(view: Any, **kw: Any) -> Any:  # type: ignore[misc]
            out = compute(panel_input(view, None, **kw), **kw)
            return last_value(out) if isinstance(out, pd.Series) else out

    pointwise.__name__ = name
    pointwise.__doc__ = compute.__doc__
    registry.feature(
        name=name,
        kind=kind,
        inputs=inputs,
        lookback=lookback,
        macro_lag=macro_lag,
        version=version,
        params=params,
    )(pointwise)
    registry.panel_variant(name, panel_input)(compute)
    return pointwise


def feature(name: str) -> registry.FeatureMeta:
    """The registered feature (strategies read features only through the registry, so every one they use
    has passed the look-ahead harness)."""
    return registry.get_feature(name)
