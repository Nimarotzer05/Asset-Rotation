"""Edge cases of the data layer: view internals, lags, index, provider base, catalog checks."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.config.models import Bundle, UniverseConfig
from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.errors import DataError
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.catalog import build_catalog, check_catalog
from rotationlab.data.lags import Lag, validate_vintages
from rotationlab.data.pit import PitIndex
from rotationlab.data.providers.base import (
    BaseProvider,
    frame_from_series,
    lagged_vintage,
    make_observation,
    period_end,
)
from rotationlab.data.store import PointInTimeStore, utc_stamp
from rotationlab.data.view import StoreViewFactory, _anchor_scale, _frame_digest


def spec(sid: str, kind=SeriesKind.PRICE, freq=Frequency.DAILY, lag="0D") -> SeriesSpec:
    return SeriesSpec(SeriesId(sid), sid.split(":", maxsplit=1)[0], sid.split(":", 1)[1], kind, freq, lag=lag)


def rows(sid, dates, values) -> pd.DataFrame:
    d = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    return pd.DataFrame({"series_id": sid, "obs_date": d, "vintage_date": d, "value": list(values)})


# ---------------------------------------------------------------------------- view internals
def test_factory_from_store_filters_providers_and_reports_snapshot() -> None:
    store = PointInTimeStore(None)
    obs = pd.concat([rows("static:A", ["2026-01-05"], [1.0]), rows("yahoo:B:close", ["2026-01-05"], [2.0])])
    store.commit(obs.assign(ingested_at=""), utc_stamp())
    cat = {s: spec(s) for s in ("static:A", "yahoo:B:close")}
    f = StoreViewFactory.from_store(store, cat, {}, WeekdayCalendar(), providers=["static"])
    v = f.at(date(2026, 1, 5))
    assert v.series("yahoo:B:close").empty and len(v.series("static:A")) == 1
    assert f.data_snapshot() == store.snapshot_id()
    f.precompute([date(2026, 1, 5)])
    assert f.vintages_as_of("static:A", date(2026, 1, 5)).iloc[0] == pd.Timestamp("2026-01-05")
    with pytest.raises(DataError):
        f.spec("nope:x")


def test_cache_is_bounded() -> None:
    f = StoreViewFactory(rows("s:A", ["2026-01-05"], [1.0]), {"s:A": spec("s:A")}, {}, WeekdayCalendar())
    f._cache.update({(str(i), pd.Timestamp("2026-01-01")): pd.Series(dtype=float) for i in range(20001)})
    f.raw_as_of("s:A", pd.Timestamp("2026-01-05"))
    assert len(f._cache) == 1


def test_panel_close_lookback_and_digest() -> None:
    days = pd.bdate_range("2026-01-01", periods=30)
    obs = pd.concat([rows("s:A", days, np.arange(30.0) + 1), rows("s:B", days, np.arange(30.0) + 2)])
    cat = {"s:A": spec("s:A"), "s:B": spec("s:B")}
    f = StoreViewFactory(obs, cat, {"A": {"close": ["s:A"]}}, WeekdayCalendar())
    v = f.at(days[-1].date())
    p = v.panel(["s:A", "s:B"], "ME")
    assert list(p.columns) == ["s:A", "s:B"] and len(p) == 2
    assert v.panel([]).empty
    assert len(v.close(["A"], lookback_days=7)) <= 6
    assert _frame_digest(obs).startswith("frame/") and _frame_digest(obs.iloc[:0]) == "empty"
    assert _frame_digest(obs) == _frame_digest(obs.copy())  # same data, same snapshot id


def test_chain_with_empty_primary_uses_fallback_only() -> None:
    obs = rows("stooq:X:close", ["2026-01-05", "2026-01-06"], [10.0, 11.0])
    cat = {
        "yahoo:X:close": spec("yahoo:X:close"),
        "stooq:X:close": spec("stooq:X:close"),
        "stooq:Y:close": spec("stooq:Y:close"),
    }
    f = StoreViewFactory(
        obs, cat, {"X": {"close": ["yahoo:X:close", "stooq:Y:close", "stooq:X:close"]}}, WeekdayCalendar()
    )
    v = f.at(date(2026, 1, 6))
    assert v.asset_series("X", "close").tolist() == [10.0, 11.0]
    assert [p.series_id for p in v.provenance("X", "close")] == ["stooq:X:close"]


def test_asset_without_total_return_role() -> None:
    f = StoreViewFactory(
        rows("s:D", ["2026-01-05"], [1.0]),
        {"s:D": spec("s:D", SeriesKind.DIVIDEND)},
        {"Z": {"dividend": ["s:D"]}},
        WeekdayCalendar(),
    )
    with pytest.raises(DataError, match="total-return role"):
        f.at(date(2026, 1, 5)).total_return(["Z"])


def test_anchor_scale_variants() -> None:
    out = pd.Series([10.0], index=[pd.Timestamp("2026-01-07")])
    other = pd.Series([5.0, 4.0], index=pd.to_datetime(["2026-01-05", "2026-01-09"]))
    assert _anchor_scale(out, other, pd.Timestamp("2026-01-07")) == 2.0  # last value before
    later_only = pd.Series([4.0], index=[pd.Timestamp("2026-01-09")])
    assert _anchor_scale(out, later_only, pd.Timestamp("2026-01-07")) == 2.5  # first value after
    assert np.isnan(
        _anchor_scale(out, pd.Series(dtype=float, index=pd.DatetimeIndex([])), pd.Timestamp("2026-01-07"))
    )
    zero = pd.Series([0.0], index=[pd.Timestamp("2026-01-07")])
    assert np.isnan(_anchor_scale(out, zero, pd.Timestamp("2026-01-07")))
    # the fallback lacks the anchor date but overlaps elsewhere: the nearest common session gives the ratio
    out2 = pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-01-07", "2026-01-08"]))
    gap = pd.Series([50.0, 51.0, 52.0], index=pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-08"]))
    assert _anchor_scale(out2, gap, pd.Timestamp("2026-01-07")) == pytest.approx(101.0 / 52.0)


def test_yield_index_edge_cases() -> None:
    cal = WeekdayCalendar()
    daily = rows("fred:DGS3MO", ["2026-01-05", "2026-01-06", "2026-01-08"], [4.0, 4.0, 4.0])
    f = StoreViewFactory(
        daily, {"fred:DGS3MO": spec("fred:DGS3MO", SeriesKind.YIELD)}, {"C": {"yield": ["fred:DGS3MO"]}}, cal
    )
    tr = f.at(date(2026, 1, 8)).total_return(["C"], None)["C"]
    assert tr.iloc[-1] == pytest.approx(100 * 1.04 ** (3 / 365))  # act/365 accrual
    assert f.at(date(2026, 1, 2)).total_return(["C"], None)["C"].empty  # nothing known yet
    monthly = rows("fred:TB", ["2026-01-31"], [4.0])  # Saturday month-end
    g = StoreViewFactory(
        monthly,
        {"fred:TB": spec("fred:TB", SeriesKind.YIELD, Frequency.MONTHLY)},
        {"C": {"yield": ["fred:TB"]}},
        cal,
    )
    assert g.at(date(2026, 1, 31)).total_return(["C"], None)["C"].tolist() == [
        100.0
    ]  # no session after the obs


# ---------------------------------------------------------------------------- lags, index, provider base
def test_lag_helpers() -> None:
    assert (
        str(Lag.parse("6m")) == "6M"
        and Lag.parse("6M").max_days() == 217
        and Lag.parse("14D").max_days() == 14
    )
    assert list(Lag.parse("0M").apply_index(pd.to_datetime(["2026-02-03"]))) == [pd.Timestamp("2026-02-28")]
    validate_vintages(np.array([1, 2]), np.array([1, 3]))
    with pytest.raises(ValueError, match="precedes"):
        validate_vintages(np.array([1, 2]), np.array([1, 1]))


def test_pit_index_empty_and_unknown() -> None:
    idx = PitIndex(pd.DataFrame(columns=["series_id", "obs_date", "vintage_date", "value"]))
    assert idx.series_ids() == [] and "x" not in idx and idx.n_rows("x") == 0
    assert idx.as_of("x", pd.Timestamp("2026-01-01")).empty
    assert idx.vintage_as_of("x", pd.Timestamp("2026-01-01")).empty
    full = PitIndex(rows("s:A", ["2026-01-05"], [1.0]))
    assert "s:A" in full and full.n_rows("s:A") == 1


def test_provider_base_helpers() -> None:
    q = period_end(pd.DatetimeIndex(pd.to_datetime(["2026-04-01", "2026-05-15"])), Frequency.QUARTERLY)
    assert list(q) == [pd.Timestamp("2026-06-30")] * 2
    s = spec("fred:X", SeriesKind.MACRO, Frequency.MONTHLY, "1M")
    assert frame_from_series(
        pd.Series([np.nan, np.inf], index=pd.to_datetime(["2026-01-01", "2026-02-01"])), s
    ).empty
    assert lagged_vintage(date(2026, 1, 31), s) == date(2026, 2, 28)
    assert make_observation(s, date(2026, 1, 31), 1.5).vintage_date == date(2026, 2, 28)

    class P(BaseProvider):
        def fetch_frame(self, spec, since):
            return frame_from_series(
                pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-01-01", "2026-02-01"])), spec
            )

    obs = list(P().fetch(s, None))
    assert [(o.obs_date, o.vintage_date, o.value) for o in obs] == [
        (date(2026, 1, 31), date(2026, 2, 28), 1.0),
        (date(2026, 2, 28), date(2026, 3, 31), 2.0),
    ]


# ---------------------------------------------------------------------------- catalog checks
def test_catalog_check_reports_every_problem(bundle: Bundle) -> None:
    assets = {
        "OK": {
            "name": "ok",
            "asset_class": "equity",
            "instrument": "etf",
            "series": {"close": "yahoo:OK:close"},
        },
        "MISS": {
            "name": "m",
            "asset_class": "equity",
            "instrument": "etf",
            "series": {"close": "nowhere:M:close"},
        },
        "MIXF": {
            "name": "f",
            "asset_class": "cash",
            "instrument": "index",
            "series": {"yield": ["fred:TB3MS", "fred:DGS10"]},
        },
        "MIXL": {
            "name": "l",
            "asset_class": "equity",
            "instrument": "etf",
            "series": {"close": ["yahoo:OK:close", "static:fredmd:GS10"]},
        },
        "KIND": {
            "name": "k",
            "asset_class": "equity",
            "instrument": "etf",
            "series": {"close": "yahoo:K:close", "dividend": "static:fredmd:GS10"},
        },
        "NOTR": {
            "name": "n",
            "asset_class": "equity",
            "instrument": "etf",
            "series": {"split": "yahoo:N:split"},
        },
        "ODD": {
            "name": "o",
            "asset_class": "equity",
            "instrument": "etf",
            "series": {"close": "yahoo:O:close", "weird": "yahoo:O:weird"},
        },
    }
    b = bundle.model_copy(update={"universe": UniverseConfig(assets=assets)})
    cat = build_catalog(b)
    assert "yahoo:O:weird" not in cat  # a role without a kind is not derived
    problems = " | ".join(check_catalog(b, cat))
    for expected in (
        "MISS.close: series nowhere:M:close not in catalog",
        "MIXF.yield: chain mixes frequencies",
        "MIXL.close: chain mixes levels and values",
        "KIND.dividend",
        "NOTR: no role",
        "weird",
    ):
        assert expected in problems, expected
    cat["bogus:x"] = spec("bogus:x")
    assert "unknown provider 'bogus'" in " | ".join(check_catalog(b, cat))
