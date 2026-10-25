"""Property tests (Hypothesis): the invariants the data layer promises, on generated histories.

* the interval index answers exactly like the reference as-of query;
* ingesting the same answer twice changes nothing;
* once a series has history, the past older than the late-arrival tolerance never changes, whatever
  later runs bring (Hypothesis found the one exception by itself: the first load of a series, which is
  history by design);
* compaction changes no as-of answer;
* monthly labels never point beyond the view date and keep the last value of each month;
* vectorised lags equal scalar lags; chains never alter the primary series.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.lags import Lag
from rotationlab.data.pit import PitIndex
from rotationlab.data.store import PointInTimeStore
from rotationlab.data.view import StoreViewFactory, as_of_pandas, resample_last

BASE = date(2020, 1, 1)
SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
PX = SeriesSpec(
    SeriesId("yahoo:P:close"), "yahoo", "P:close", SeriesKind.PRICE, Frequency.DAILY, revision_tolerance=1e-9
)

values = st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
revision_rows = st.lists(
    st.tuples(st.integers(0, 200), st.integers(0, 90), values), min_size=1, max_size=60
)  # (obs offset, vintage lag in days, value)


def to_frame(rows: list[tuple[int, int, float]], sid: str = "s:x") -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "series_id": sid,
            "obs_date": [pd.Timestamp(BASE) + pd.Timedelta(days=o) for o, _, _ in rows],
            "vintage_date": [pd.Timestamp(BASE) + pd.Timedelta(days=o + lag) for o, lag, _ in rows],
            "value": [v for _, _, v in rows],
        }
    )
    return df.drop_duplicates(["series_id", "obs_date", "vintage_date"], keep="last").reset_index(drop=True)


@SETTINGS
@given(revision_rows, st.lists(st.integers(-10, 320), min_size=1, max_size=12))
def test_interval_index_equals_reference_query(rows, probes) -> None:
    df = to_frame(rows)
    idx = PitIndex(df)
    for p in probes:
        d = BASE + timedelta(days=p)
        ref = as_of_pandas(df, d)
        expected = pd.Series(
            ref["value"].to_numpy(), index=pd.DatetimeIndex(ref["obs_date"].to_numpy()), name="s:x"
        )
        pd.testing.assert_series_equal(
            idx.as_of("s:x", pd.Timestamp(d)), expected, check_freq=False, check_index_type=False
        )


@SETTINGS
@given(st.lists(st.tuples(st.integers(0, 120), values), min_size=1, max_size=40, unique_by=lambda t: t[0]))
def test_ingesting_the_same_answer_twice_changes_nothing(points) -> None:
    store = PointInTimeStore(None)
    f = pd.DataFrame(
        {
            "obs_date": [pd.Timestamp(BASE) + pd.Timedelta(days=o) for o, _ in points],
            "vintage_date": [pd.Timestamp(BASE) + pd.Timedelta(days=o) for o, _ in points],
            "value": [v for _, v in points],
        }
    )
    today = BASE + timedelta(days=200)
    store.commit(store.diff(PX, f, today).rows, "2020-07-20T06:30:00Z")
    again = store.diff(PX, f, today + timedelta(days=1))
    assert again.rows.empty and again.unchanged == len(points)


@SETTINGS
@given(
    st.lists(
        st.tuples(
            st.lists(st.tuples(st.integers(0, 60), values), min_size=0, max_size=12),  # what a run receives
            st.integers(1, 6),  # days until the next run
        ),
        min_size=2,
        max_size=8,
    )
)
def test_the_past_beyond_the_tolerance_never_changes(runs) -> None:
    store = PointInTimeStore(None)
    run_day = BASE + timedelta(days=10)
    snapshots: list[tuple[date, PitIndex]] = []
    for k, (points, gap) in enumerate(runs):
        # a provider answers with sessions up to the day before the run (late values included)
        pts = {BASE + timedelta(days=o): v for o, v in points if BASE + timedelta(days=o) < run_day}
        f = pd.DataFrame(
            {
                "obs_date": pd.to_datetime(list(pts)),
                "vintage_date": pd.to_datetime(list(pts)),
                "value": list(pts.values()),
            }
        )
        store.commit(store.diff(PX, f, run_day, late_tolerance_days=5).rows, f"2020-01-{k + 1:02d}T06:30:00Z")
        if len(store.series_rows(PX.series_id)):  # the first load of a series is history by design (ADR 026)
            snapshots.append((run_day, PitIndex(store.observations())))
        run_day += timedelta(days=gap)
    final = PitIndex(store.observations())
    for day, idx in snapshots:
        cutoff = pd.Timestamp(day - timedelta(days=6))  # older than the tolerance window at that run
        for probe in pd.date_range(pd.Timestamp(BASE), cutoff, freq="3D"):
            pd.testing.assert_series_equal(final.as_of(PX.series_id, probe), idx.as_of(PX.series_id, probe))


@SETTINGS
@given(st.lists(revision_rows, min_size=1, max_size=4))
def test_compaction_changes_no_answer(batches) -> None:
    store = PointInTimeStore(None)
    for k, rows in enumerate(batches):
        df = to_frame(rows).assign(ingested_at="")
        store.commit(df, f"2021-01-0{k + 1}T00:00:00Z")
    before = PitIndex(store.observations())
    store.compact("2021-02-01T00:00:00Z")
    after = PitIndex(store.observations())
    for p in range(-5, 330, 7):
        d = pd.Timestamp(BASE) + pd.Timedelta(days=p)
        pd.testing.assert_series_equal(after.as_of("s:x", d), before.as_of("s:x", d))


@SETTINGS
@given(
    st.lists(st.integers(0, 800), min_size=1, max_size=80, unique=True),
    st.integers(0, 900),
    st.sampled_from(["ME", "QE"]),
)
def test_period_labels_and_values(offsets, view_offset, freq) -> None:
    idx = pd.DatetimeIndex(sorted(pd.Timestamp(BASE) + pd.Timedelta(days=o) for o in offsets))
    s = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    d = pd.Timestamp(BASE) + pd.Timedelta(days=view_offset)
    s = s[s.index <= d]
    out = resample_last(s, freq, d)
    if s.empty:
        assert out.empty
        return
    assert out.index.max() <= d and out.index.is_monotonic_increasing
    per = s.index.to_period("M" if freq == "ME" else "Q")
    assert out.tolist() == s.groupby(per).last().tolist()


@SETTINGS
@given(
    st.lists(st.integers(0, 20000), min_size=1, max_size=50), st.integers(0, 40), st.sampled_from(["D", "M"])
)
def test_vectorised_lag_equals_scalar(offsets, n, unit) -> None:
    lag = Lag(n if unit == "D" else n % 13, unit)
    obs = pd.DatetimeIndex([pd.Timestamp("1950-01-01") + pd.Timedelta(days=o) for o in offsets])
    assert [x.date() for x in lag.apply_index(obs)] == [lag.apply(o.date()) for o in obs]
    assert all(lag.apply(o.date()) >= o.date() for o in obs)


@SETTINGS
@given(st.integers(5, 40), st.integers(0, 30), st.integers(1, 30), values)
def test_chains_never_alter_the_primary(n_primary, start, extra, level) -> None:
    days = pd.bdate_range("2024-01-01", periods=start + n_primary + extra)
    prim_days = days[start : start + n_primary]
    rng = np.random.default_rng(n_primary + start)
    fb = level * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
    prim = fb[start : start + n_primary] * 1.37
    obs = pd.concat(
        [
            pd.DataFrame(
                {
                    "series_id": "yahoo:X:close",
                    "obs_date": prim_days,
                    "vintage_date": prim_days,
                    "value": prim,
                }
            ),
            pd.DataFrame({"series_id": "stooq:X:close", "obs_date": days, "vintage_date": days, "value": fb}),
        ]
    )
    specs = {
        s: SeriesSpec(SeriesId(s), s.split(":")[0], s.split(":", 1)[1], SeriesKind.PRICE, Frequency.DAILY)
        for s in ("yahoo:X:close", "stooq:X:close")
    }
    f = StoreViewFactory(obs, specs, {"X": {"close": ["yahoo:X:close", "stooq:X:close"]}}, WeekdayCalendar())
    s = f.at(days[-1].date()).asset_series("X", "close")
    assert np.allclose(s.loc[prim_days].to_numpy(), prim)
    assert len(s) == len(days)
    assert np.allclose(
        s.pct_change().dropna().to_numpy(), pd.Series(fb, index=days).pct_change().dropna().to_numpy()
    )
