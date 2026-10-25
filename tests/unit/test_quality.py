"""Every quality check with a passing and a failing case."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.config.models import QualityConfig
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data import quality as q
from rotationlab.data.calendar import NYSECalendar

CFG = QualityConfig()
CAL = NYSECalendar()


def spec(
    kind=SeriesKind.PRICE, freq=Frequency.DAILY, provider="yahoo", required=True, lag="0D"
) -> SeriesSpec:
    return SeriesSpec(
        SeriesId(f"{provider}:X:close"), provider, "X:close", kind, freq, required=required, lag=lag
    )


def frame(obs, values, vint=None) -> pd.DataFrame:
    o = pd.to_datetime(obs)
    return pd.DataFrame(
        {"obs_date": o, "vintage_date": o if vint is None else pd.to_datetime(vint), "value": values}
    )


def daily(n=400, seed=0, start="2025-01-02") -> pd.Series:
    days = pd.DatetimeIndex(CAL.trading_days(pd.Timestamp(start).date(), date(2027, 1, 1))[:n])
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=days)


# ---------------------------------------------------------------------------- schema
def test_schema_accepts_clean_rows() -> None:
    acc, rej, res = q.schema(spec(), frame(["2026-10-20", "2026-10-21"], [1.0, 2.0]), date(2026, 10, 22))
    assert len(acc) == 2 and rej.empty and q.worst(res) == q.Status.OK


@pytest.mark.parametrize(
    "kind,value,reason",
    [
        (SeriesKind.PRICE, -1.0, "non-positive"),
        (SeriesKind.PRICE, 0.0, "non-positive"),
        (SeriesKind.DIVIDEND, -0.1, "negative dividend"),
        (SeriesKind.RETURN, -1.2, "-100"),
        (SeriesKind.RETURN, 7.0, "unit error"),
        (SeriesKind.YIELD, 450.0, "unit error"),
        (SeriesKind.PRICE, float("inf"), "non-finite"),
    ],
)
def test_schema_rejects_impossible_values(kind, value, reason) -> None:
    acc, rej, res = q.schema(
        spec(kind=kind), frame(["2026-10-20", "2026-10-21"], [1.0, value]), date(2026, 10, 22)
    )
    assert len(acc) == 1 and len(rej) == 1 and reason in rej["reason"].iloc[0]
    assert q.worst(res) == q.Status.BLOCKING


def test_schema_rejects_future_and_inverted_vintage() -> None:
    f = frame(
        ["2026-10-20", "2026-10-25", "2026-10-21"],
        [1.0, 2.0, 3.0],
        vint=["2026-10-20", "2026-10-25", "2026-10-19"],
    )
    acc, rej, _ = q.schema(spec(), f, date(2026, 10, 22))
    assert len(acc) == 1 and set(rej["reason"]) == {"obs_date in the future", "vintage_date before obs_date"}


def test_schema_drops_the_unfinished_session_silently() -> None:
    acc, rej, res = q.schema(spec(), frame(["2026-10-21", "2026-10-22"], [1.0, 2.0]), date(2026, 10, 22))
    assert len(acc) == 1 and rej.empty and q.worst(res) == q.Status.OK


# ---------------------------------------------------------------------------- staleness
def test_staleness_daily_counts_sessions_not_days() -> None:
    # Tuesday 2026-01-20 run after the MLK Monday: Friday's close is the latest possible
    assert q.staleness(spec(), date(2026, 1, 16), date(2026, 1, 20), CAL, CFG).status == q.Status.OK
    # three sessions behind → blocking for a required series, warning otherwise
    r = q.staleness(spec(), date(2026, 1, 14), date(2026, 1, 21), CAL, CFG)
    assert r.status == q.Status.BLOCKING and "sessions behind" in r.detail
    assert (
        q.staleness(spec(required=False), date(2026, 1, 14), date(2026, 1, 21), CAL, CFG).status
        == q.Status.WARN
    )
    assert q.staleness(spec(), None, date(2026, 1, 21), CAL, CFG).status == q.Status.BLOCKING


def test_staleness_monthly_respects_publication_lag() -> None:
    m = spec(kind=SeriesKind.MACRO, freq=Frequency.MONTHLY, provider="fred", required=False, lag="1M")
    assert q.staleness(m, date(2026, 8, 31), date(2026, 10, 24), CAL, CFG).status == q.Status.OK
    assert q.staleness(m, date(2026, 3, 31), date(2026, 10, 24), CAL, CFG).status == q.Status.WARN


def test_staleness_ignores_static_history() -> None:
    assert q.staleness(spec(provider="static"), date(1990, 1, 1), date(2026, 10, 24), CAL, CFG) is None


# ---------------------------------------------------------------------------- gaps
def test_gaps_ok_and_warn() -> None:
    s = daily(300)
    assert q.gaps(spec(), s, CAL, CFG).status == q.Status.OK
    holes = s.drop(s.index[[50, 51, 52, 53, 120]])
    r = q.gaps(spec(), holes, CAL, CFG)
    assert r.status == q.Status.WARN and "5 missing" in r.detail
    extra = pd.concat([s, pd.Series([1.0], index=[pd.Timestamp("2025-07-04")])]).sort_index()
    assert "non-sessions" in q.gaps(spec(), extra, CAL, CFG).detail


# ---------------------------------------------------------------------------- outliers
def test_outliers_ok_and_warn() -> None:
    s = daily(400)
    since = s.index[-20].date()
    assert q.outliers(spec(), s, since, CFG).status == q.Status.OK
    jump = s.copy()
    jump.iloc[-5:] *= 1.5  # +50 % overnight on a 1 % vol series
    r = q.outliers(spec(), jump, since, CFG)
    assert r.status == q.Status.WARN and "sigma" in r.detail
    assert (
        q.outliers(spec(), jump, jump.index[-2].date(), CFG).status == q.Status.OK
    )  # outside the checked window


# ---------------------------------------------------------------------------- revisions
def test_revision_split_is_recognised() -> None:
    obs = pd.bdate_range("2026-01-01", periods=40)
    old = np.linspace(200, 240, 40)
    rev = pd.DataFrame({"obs_date": obs, "old": old, "new": old / 4.0})
    rev["rel_change"] = rev["new"] / rev["old"] - 1
    r = q.revisions(spec(), rev, CFG)
    assert r.status == q.Status.OK and "uniformly by 0.25" in r.detail


def test_revision_silent_change_warns_and_small_ones_pass() -> None:
    big = pd.DataFrame({"obs_date": pd.to_datetime(["2026-01-05"]), "old": [100.0], "new": [101.0]})
    big["rel_change"] = 0.01
    assert q.revisions(spec(), big, CFG).status == q.Status.WARN
    small = big.assign(new=100.1, rel_change=0.001)
    assert q.revisions(spec(), small, CFG).status == q.Status.OK
    macro = q.revisions(spec(kind=SeriesKind.MACRO, freq=Frequency.MONTHLY), big, CFG)
    assert macro.status == q.Status.OK  # statistics are revised by design


# ---------------------------------------------------------------------------- cross-source, TR
def test_cross_source() -> None:
    a = daily(60)
    assert q.cross_source("a", a, a * 1.37, CFG).status == q.Status.OK  # level basis may differ
    b = a.copy()
    b.iloc[-3] *= 1.05
    assert q.cross_source("a", a, b.rename("b"), CFG).status == q.Status.WARN


def test_total_return_vs_price() -> None:
    px = daily(100)
    tr = px * np.cumprod(np.r_[1.0, np.full(99, 1.0001)])
    since = px.index[-10].date()
    assert q.total_return_vs_price("tr", tr, px, since).status == q.Status.OK
    old_bad = tr.copy()
    old_bad.iloc[20:] *= 0.999
    assert q.total_return_vs_price("tr", old_bad, px, since).status == q.Status.WARN
    new_bad = tr.copy()
    new_bad.iloc[-3:] *= 0.99
    assert q.total_return_vs_price("tr", new_bad, px, since).status == q.Status.BLOCKING


def test_quality_frame_has_log_columns() -> None:
    f = q.to_frame([q.QualityResult("gaps", "x", q.Status.WARN, "d")], "2026-10-24T06:30:00Z")
    assert list(f.columns) == ["ingested_at", "series_id", "check", "status", "detail"]
