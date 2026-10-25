"""Live checks against the real services (``pytest -m network``; CI weekly, not on every push).

They verify that the wire formats still match the parsers and that the ALFRED vintage logic agrees
with FRED's own real-time answer: the store's view of CPI on 2008-06-30 must equal what the API
returns for ``realtime_start = realtime_end = 2008-06-30`` – an independent oracle.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import pytest

from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.providers.fred import API_URL, FredProvider, parse_observations
from rotationlab.data.providers.french import FrenchProvider
from rotationlab.data.providers.http import UrllibClient
from rotationlab.data.providers.stooq import StooqProvider
from rotationlab.data.providers.yahoo import YahooProvider
from rotationlab.data.store import PointInTimeStore
from rotationlab.data.view import StoreViewFactory

pytestmark = pytest.mark.network
HTTP = UrllibClient(timeout_s=30, retries=2)


def spec(sid, kind, freq, lag="0D", vintages="none", params=()):
    p, code = sid.split(":", 1)
    return SeriesSpec(SeriesId(sid), p, code, kind, freq, lag=lag, vintages=vintages, params=tuple(params))


def test_yahoo_live() -> None:
    since = date.today() - timedelta(days=30)
    f = YahooProvider(HTTP).fetch_frame(spec("yahoo:SPY:close", SeriesKind.PRICE, Frequency.DAILY), since)
    assert len(f) >= 15 and (f["value"] > 0).all()
    sessions = set(NYSECalendar().trading_days(since, date.today() - timedelta(days=1)))
    assert {d.date() for d in f["obs_date"]} <= sessions | {date.today()}


@pytest.mark.skipif(not os.environ.get("STOOQ_API_KEY"), reason="needs STOOQ_API_KEY (Stooq CSV since 2026-03)")
def test_stooq_live() -> None:
    f = StooqProvider(HTTP, os.environ["STOOQ_API_KEY"]).fetch_frame(
        spec("stooq:SPY:close", SeriesKind.PRICE, Frequency.DAILY), date.today() - timedelta(days=30)
    )
    assert len(f) >= 15


def test_french_live() -> None:
    f = FrenchProvider(HTTP).fetch_frame(
        spec(
            "french:ff3:RF",
            SeriesKind.RETURN,
            Frequency.MONTHLY,
            params=[("file", "F-F_Research_Data_Factors_CSV.zip"), ("column", "RF")],
        ),
        None,
    )
    assert f["obs_date"].iloc[0] == pd.Timestamp("1926-07-31") and len(f) > 1190


@pytest.mark.skipif(not os.environ.get("FRED_API_KEY"), reason="needs FRED_API_KEY")
def test_alfred_cpi_2008_matches_fred_realtime_oracle(catalog, bundle) -> None:
    key = os.environ["FRED_API_KEY"]
    cpi = catalog["fred:CPIAUCSL"]
    store = PointInTimeStore(None)
    f = FredProvider(HTTP, key).fetch_frame(cpi, None)
    d = store.diff(cpi, f, date.today(), real_vintages=True)
    store.commit(d.rows, "2026-01-01T00:00:00Z")
    view = StoreViewFactory.from_store(store, catalog, bundle.universe, NYSECalendar()).at(date(2008, 6, 30))
    ours = view.series("fred:CPIAUCSL").loc["2007-01-31":]
    raw = HTTP.get(
        API_URL,
        {
            "series_id": "CPIAUCSL",
            "api_key": key,
            "file_type": "json",
            "realtime_start": "2008-06-30",
            "realtime_end": "2008-06-30",
            "observation_start": "2007-01-01",
        },
    )
    oracle, _ = parse_observations(raw)
    oracle = pd.Series(
        oracle["value"].to_numpy(), index=pd.DatetimeIndex(oracle["date"]) + pd.offsets.MonthEnd(0)
    ).dropna()
    pd.testing.assert_series_equal(ours, oracle.reindex(ours.index), check_names=False, check_freq=False)
