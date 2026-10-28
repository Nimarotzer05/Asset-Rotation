"""Engine truncation sweep (audit 2026-10-25, finding E): the store cut at many dates across fifty years.

One cut proves only that the decision *at* the cut ignores the future (both stores agree before it). This
sweep cuts the research store every three years from 1976 to 2024 and lets the cut month walk through the
calendar (Jan, May, Sep, …), so a leak tied to a season, a holiday, a splice point or a data gap has many
chances to surface. Each module runs under its honest production timing (`next_tradable`). 85 cuts in
all, ~10 min: weekly in the network workflow (`pytest -m sweep`), not on every push.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from rotationlab.config.models import CostSpec
from rotationlab.engine.modes import backtest, research_factory
from tests.lookahead.test_audit_phase2 import _same_prefix, reduced, truncate  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.sweep,
    pytest.mark.filterwarnings("ignore:overflow encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning"),
    pytest.mark.filterwarnings("ignore:divide by zero encountered:RuntimeWarning"),
]

CUTS = [
    (pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)).date()
    for y, m in zip(range(1976, 2025, 3), [1, 5, 9] * 6, strict=False)
]


@pytest.mark.parametrize(
    "sid",
    [
        "us_equity_exposure",
        "us_sector_rotation",
        "multi_asset_rotation",
        "commodity_trend",
        "precious_metals",
        "forecast_portfolio",
    ],
)
def test_engine_is_invariant_to_cutting_the_store_every_three_years(reduced, bundle, cal, sid) -> None:  # noqa: F811
    assert len(CUTS) == 17 and {c.month for c in CUTS} == {1, 5, 9}
    gr = bundle.strategies[sid].golden_run
    # the forecast portfolio never runs into the pseudo-holdout (2019–2025) before the final evaluation
    start, end = date(1973, 1, 31), (date(2018, 12, 31) if sid == "forecast_portfolio" else date(2025, 6, 30))
    costs = CostSpec(default_bps=10)
    full = backtest(
        bundle,
        research_factory(bundle, reduced, cal, gr.data_from),
        sid,
        "long_history",
        start,
        end,
        "next_tradable",
        costs,
    )
    for cut_at in [c for c in CUTS if c <= end]:
        cut_f = research_factory(bundle, truncate(reduced, cut_at), cal, gr.data_from)
        cut = backtest(bundle, cut_f, sid, "long_history", start, cut_at, "next_tradable", costs)
        _same_prefix(full, cut, cut_at)
