"""The prefix caches (ADR 028) answer bit-identically to the reference path, and are faster."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from rotationlab.data.view import StoreViewFactory

ASSETS = ["US_EQ", "GOLD", "SILVER", "TBILL", "UST10", "WB_ENERGY", "WB_OIL", "FF_MKT", "FF_HITEC", "CASH"]
SERIES = [
    "static:usmkt:TR",
    "static:lbma:GOLD",
    "static:fredmd:CPIAUCSL",
    "static:fredmd:GS10",
    "static:shiller:Earnings",
    "static:cboe:VIX",
    "static:fredmd_rt:INDPRO",
    "static:french:ff3:RF",
]


@pytest.fixture(scope="module")
def pair(static_store, catalog, bundle, cal):
    fast = StoreViewFactory.from_store(
        static_store, catalog, bundle.universe, cal, chains=bundle.series.chains
    )
    slow = StoreViewFactory.from_store(
        static_store, catalog, bundle.universe, cal, chains=bundle.series.chains
    )
    slow.fast = False
    return fast, slow


def dates() -> list[pd.Timestamp]:
    rng = np.random.default_rng(8)
    month_ends = list(pd.date_range("1960-01-31", "2026-10-31", freq="ME"))
    mid = list(
        pd.to_datetime(
            rng.integers(pd.Timestamp("1950-01-01").value, pd.Timestamp("2026-10-24").value, 40)
        ).normalize()
    )
    return (
        [month_ends[i] for i in rng.choice(len(month_ends), 40, replace=False)]
        + mid
        + [pd.Timestamp("1871-01-31")]
    )


@pytest.mark.parametrize("freq", [None, "ME", "QE"])
def test_fast_equals_reference(pair, freq) -> None:
    fast, slow = pair
    for d in dates():
        vf, vs = fast.at(d.date()), slow.at(d.date())
        for sid in SERIES:
            pd.testing.assert_series_equal(
                vf.series(sid, freq), vs.series(sid, freq), check_exact=True, obj=f"{sid} {d.date()} {freq}"
            )
        pd.testing.assert_frame_equal(
            vf.total_return(ASSETS, freq),
            vs.total_return(ASSETS, freq),
            check_exact=True,
            obj=f"TR {d.date()} {freq}",
        )


def test_fast_results_cannot_corrupt_the_cache(pair) -> None:
    fast, _ = pair
    a = fast.at(pd.Timestamp("2000-06-30").date()).series("static:usmkt:TR")
    a.iloc[:] = -1.0
    assert (fast.at(pd.Timestamp("2000-06-30").date()).series("static:usmkt:TR") > 0).all()


def test_fast_path_is_faster(pair) -> None:
    fast, slow = pair
    ds = list(pd.date_range("1990-01-31", "2025-12-31", freq="ME"))
    t = {}
    for name, f in (("fast", fast), ("slow", slow)):
        t0 = time.perf_counter()
        for d in ds:
            f.at(d.date()).total_return(["US_EQ", "GOLD", "SILVER", "UST10", "WB_ENERGY", "TBILL"], "ME")
        t[name] = time.perf_counter() - t0
    assert t["fast"] < t["slow"] / 2, t
