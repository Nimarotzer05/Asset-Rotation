"""The look-ahead harness against the real store and the ALFRED fixture (Phase 1 acceptance).

Each feature is evaluated at stress dates and random dates twice: on the clean store and on a copy
in which every value that was not knowable at that date (obs_date > D or vintage_date > D) is
replaced by noise. Identical results ⇒ the view leaks nothing. A deliberately leaky feature proves
that the harness bites.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.errors import LookaheadError
from rotationlab.core.registry import FeatureMeta
from rotationlab.core.types import Months
from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.providers.fred import alfred_frame, parse_observations
from rotationlab.data.view import StoreViewFactory, asset_roles
from tests.fixtures import fakes
from tests.fixtures.build_fixtures import alfred_rows, cpi_vintages
from tests.lookahead.harness import LookaheadHarness

# the harness writes 1e6-scale noise into the unknowable future; compounding it overflows harmlessly
pytestmark = pytest.mark.filterwarnings("ignore:overflow encountered:RuntimeWarning")

CAL = NYSECalendar()
ASSETS = ["US_EQ", "GOLD", "SILVER", "UST10", "WB_ENERGY", "FF_MKT", "TBILL"]
SERIES = [
    "static:usmkt:TR",
    "static:GOLD",
    "static:lbma:SILVER",
    "static:UST10",
    "static:WB_ENERGY",
    "static:FF_MKT",
    "static:TBILL",
    "static:fredmd:CPIAUCSL",
    "static:fredmd:UNRATE",
    "static:fredmd:GS10",
    "static:shiller:Earnings",
    "static:shiller:SP500",
    "static:shiller:Consumer_Price_Index",
]
STRESS = [
    date(1974, 9, 30),
    date(1987, 10, 31),
    date(2000, 3, 31),
    date(2008, 9, 30),
    date(2008, 10, 31),
    date(2020, 3, 31),
    date(2022, 6, 30),
    date(2025, 4, 30),
]


def momentum(view, assets) -> pd.Series:
    tr = view.total_return(assets, "ME")
    return (tr.shift(1).iloc[-1] / tr.shift(12).iloc[-1] - 1).rename("mom_12_1")


def macro_state(view) -> pd.Series:
    cpi = view.series("static:fredmd:CPIAUCSL", "ME")
    un = view.series("static:fredmd:UNRATE", "ME")
    gs = view.series("static:fredmd:GS10", "ME")
    return pd.Series(
        {
            "cpi_yoy": cpi.iloc[-1] / cpi.iloc[-13] - 1,
            "sahm": un.rolling(3).mean().iloc[-1] - un.rolling(3).mean().iloc[-13:].min(),
            "real_10y": gs.iloc[-1] - 100 * (cpi.iloc[-1] / cpi.iloc[-13] - 1),
        }
    )


def cape_like(view) -> pd.Series:
    px = view.series("static:shiller:SP500", "ME")
    cpi = view.series("static:shiller:Consumer_Price_Index", "ME")
    e = view.series("static:shiller:Earnings", "ME")
    real_e = (e / cpi.reindex(e.index)).rolling(120).mean()
    return pd.Series(
        {"cape": px.iloc[-1] / cpi.iloc[-1] / real_e.iloc[-1], "last_e": e.index[-1].toordinal()}
    )


def leaky(view) -> pd.Series:
    # reads the factory behind the view's back: everything ever stored
    s = view._f.raw_as_of("static:usmkt:TR", pd.Timestamp("2100-01-01"))
    return pd.Series({"x": float(s.iloc[-1])})


def meta(name, kind, fn) -> FeatureMeta:
    return FeatureMeta(name, kind, (), Months(12), Months(0), 1, fn)


@pytest.fixture(scope="module")
def harness(static_store, catalog, bundle):
    obs = static_store.observations()
    obs = obs[obs["series_id"].isin(SERIES)].reset_index(drop=True)
    roles = asset_roles(bundle.universe)
    rng = np.random.default_rng(42)
    month_ends = pd.date_range("1980-01-31", "2025-12-31", freq="ME")
    dates = (
        STRESS
        + sorted(pd.Timestamp(d).date() for d in rng.choice(month_ends, 12, replace=False))
        + [date(2025, 7, 15)]
    )

    def build(df: pd.DataFrame) -> StoreViewFactory:
        return StoreViewFactory(df, catalog, roles, CAL)

    return LookaheadHarness(obs, build, dates, assets=ASSETS)


@pytest.mark.parametrize(
    "name,kind,fn",
    [
        ("mom_12_1", "cross_section", momentum),
        ("macro_state", "state", macro_state),
        ("cape_like", "state", cape_like),
    ],
)
def test_features_on_the_static_store_do_not_look_ahead(harness, name, kind, fn) -> None:
    harness.check_feature(meta(name, kind, fn))


def test_harness_catches_a_leaky_feature(harness) -> None:
    with pytest.raises(LookaheadError):
        harness.check_feature(meta("leaky", "state", leaky))


def test_vintages_are_respected_under_mutation(catalog, bundle) -> None:
    """Revisions published after D are noise to a view at D: features on ALFRED data stay identical."""
    rows, _ = parse_observations(fakes.fred_observations(alfred_rows(cpi_vintages())))
    f = alfred_frame(rows, catalog["fred:CPIAUCSL"], clip=None)
    obs = f.assign(series_id="fred:CPIAUCSL")
    roles = asset_roles(bundle.universe)

    def cpi_yoy(view) -> pd.Series:
        s = view.series("fred:CPIAUCSL", "ME")
        return pd.Series({"yoy": s.iloc[-1] / s.iloc[-13] - 1, "n": len(s)})

    dates = [
        date(2006, 6, 30),
        date(2007, 2, 19),
        date(2007, 2, 20),
        date(2008, 6, 30),
        date(2008, 12, 31),
        date(2009, 3, 31),
    ]
    h = LookaheadHarness(obs, lambda df: StoreViewFactory(df, catalog, roles, CAL), dates)
    h.check_feature(meta("cpi_yoy", "state", cpi_yoy))
    # and the mutation really touches revisions: at 2007-02-19 rows with later vintages exist for old months
    later = obs[
        (obs["obs_date"] <= pd.Timestamp("2007-01-31")) & (obs["vintage_date"] > pd.Timestamp("2007-02-19"))
    ]
    assert len(later) > 10
