"""MarketView guarantees, frequencies, chains and total-return construction."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.errors import DataError, LookaheadError
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.view import StoreViewFactory, assert_no_lookahead, resample_last


def spec(sid: str, kind: SeriesKind, freq: Frequency = Frequency.DAILY) -> SeriesSpec:
    return SeriesSpec(SeriesId(sid), sid.split(":", maxsplit=1)[0], sid.split(":", 1)[1], kind, freq)


def rows(sid: str, dates, values, vintages=None) -> pd.DataFrame:
    d = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    v = d if vintages is None else pd.DatetimeIndex(pd.to_datetime(list(vintages)))
    return pd.DataFrame({"series_id": sid, "obs_date": d, "vintage_date": v, "value": list(values)})


def make(obs: pd.DataFrame, specs: list[SeriesSpec], assets: dict, cal=None) -> StoreViewFactory:
    return StoreViewFactory(obs, {s.series_id: s for s in specs}, assets, cal or NYSECalendar())


# ---------------------------------------------------------------------------- guarantees
def test_no_index_after_view_date_and_vintage_respected() -> None:
    obs = pd.concat(
        [
            rows("a:px", ["2026-01-05", "2026-01-06", "2026-01-07"], [1, 2, 3]),
            rows("a:px", ["2026-01-06"], [2.5], vintages=["2026-01-09"]),
        ]
    )
    f = make(obs, [spec("a:px", SeriesKind.PRICE)], {})
    s6 = f.at(date(2026, 1, 6)).series("a:px")
    assert s6.index.max() == pd.Timestamp("2026-01-06") and s6.iloc[-1] == 2
    assert f.at(date(2026, 1, 8)).series("a:px").loc["2026-01-06"] == 2  # revision not yet public
    assert f.at(date(2026, 1, 9)).series("a:px").loc["2026-01-06"] == 2.5


def test_views_are_deterministic_and_isolated() -> None:
    obs = rows("a:px", pd.bdate_range("2025-01-01", periods=300), np.linspace(1, 2, 300))
    f = make(obs, [spec("a:px", SeriesKind.PRICE)], {})
    a = f.at(date(2025, 6, 30)).series("a:px", "ME")
    a.iloc[0] = -999.0  # callers cannot corrupt the cache
    b = f.at(date(2025, 6, 30)).series("a:px", "ME")
    c = (
        make(obs.sample(frac=1, random_state=1), [spec("a:px", SeriesKind.PRICE)], {})
        .at(date(2025, 6, 30))
        .series("a:px", "ME")
    )
    assert b.iloc[0] != -999.0
    pd.testing.assert_series_equal(b, c)


def test_guard_raises() -> None:
    with pytest.raises(LookaheadError):
        assert_no_lookahead(pd.Series([1.0], index=[pd.Timestamp("2026-01-02")]), date(2026, 1, 1))


def test_monthly_labels_never_point_into_the_future() -> None:
    s = pd.Series(
        range(5),
        index=pd.to_datetime(["2026-01-30", "2026-02-27", "2026-03-02", "2026-03-10", "2026-03-11"]),
        dtype=float,
    )
    m = resample_last(s, "ME", pd.Timestamp("2026-03-11"))
    assert list(m.index) == [
        pd.Timestamp("2026-01-31"),
        pd.Timestamp("2026-02-28"),
        pd.Timestamp("2026-03-11"),
    ]
    assert list(m) == [0.0, 1.0, 4.0]
    m2 = resample_last(s, "ME", pd.Timestamp("2026-03-31"))
    assert m2.index[-1] == pd.Timestamp("2026-03-31")
    q = resample_last(s, "QE", pd.Timestamp("2026-03-31"))
    assert list(q.index) == [pd.Timestamp("2026-03-31")] and q.iloc[0] == 4.0
    with pytest.raises(ValueError):
        resample_last(s, "W", pd.Timestamp("2026-03-31"))


# ---------------------------------------------------------------------------- chains
def test_chain_splices_history_backwards_and_staleness_forwards_by_ratio() -> None:
    days = pd.bdate_range("2026-01-05", periods=10)
    primary = rows("yahoo:X:close", days[3:7], [10, 11, 12, 13])
    fallback = rows("stooq:X:close", days, [5.0, 5.0, 5.0, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0])
    specs = [spec("yahoo:X:close", SeriesKind.PRICE), spec("stooq:X:close", SeriesKind.PRICE)]
    f = make(pd.concat([primary, fallback]), specs, {"X": {"close": ["yahoo:X:close", "stooq:X:close"]}})
    v = f.at(days[-1].date())
    s = v.asset_series("X", "close")
    assert len(s) == 10
    assert s.loc[days[3] : days[6]].tolist() == [10, 11, 12, 13]  # primary untouched
    assert s.loc[days[0]] == pytest.approx(5.0 * 10 / 5.0)  # scaled at the first primary date
    r_fb = fallback.set_index("obs_date")["value"].pct_change()
    assert s.pct_change().loc[days[7] :].tolist() == pytest.approx(
        r_fb.loc[days[7] :].tolist()
    )  # fallback returns forward
    prov = v.provenance("X", "close")
    assert [p.series_id for p in prov] == ["stooq:X:close", "yahoo:X:close", "stooq:X:close"]


def test_chain_of_yields_splices_by_value() -> None:
    a = rows("fred:Y", ["2026-03-31", "2026-04-30"], [4.0, 4.1])
    b = rows("static:Y", ["2026-01-31", "2026-02-28", "2026-03-31"], [3.8, 3.9, 9.9])
    specs = [
        spec("fred:Y", SeriesKind.YIELD, Frequency.MONTHLY),
        spec("static:Y", SeriesKind.YIELD, Frequency.MONTHLY),
    ]
    f = make(pd.concat([a, b]), specs, {"C": {"yield": ["fred:Y", "static:Y"]}})
    assert f.at(date(2026, 4, 30)).asset_series("C", "yield").tolist() == [3.8, 3.9, 4.0, 4.1]


def test_unknown_asset_and_role() -> None:
    f = make(
        rows("a:px", ["2026-01-05"], [1.0]), [spec("a:px", SeriesKind.PRICE)], {"A": {"close": ["a:px"]}}
    )
    with pytest.raises(DataError):
        f.at(date(2026, 1, 5)).asset_series("B", "close")
    with pytest.raises(DataError):
        f.at(date(2026, 1, 5)).asset_series("A", "dividend")


# ---------------------------------------------------------------------------- total return
def test_total_return_from_close_and_dividends() -> None:
    days = pd.bdate_range("2026-03-02", periods=4)
    px = rows("y:A:close", days, [100.0, 98.0, 99.0, 101.0])
    div = rows("y:A:dividend", [days[1]], [1.0])
    specs = [spec("y:A:close", SeriesKind.PRICE), spec("y:A:dividend", SeriesKind.DIVIDEND)]
    f = make(pd.concat([px, div]), specs, {"A": {"close": ["y:A:close"], "dividend": ["y:A:dividend"]}})
    tr = f.at(days[-1].date()).total_return(["A"], freq=None)["A"]
    expected = 100 * np.cumprod([1.0, (98 + 1) / 100, 99 / 98, 101 / 99])
    assert tr.tolist() == pytest.approx(expected.tolist())


def test_dividend_on_a_non_session_is_paid_with_the_next_close() -> None:
    days = pd.to_datetime(["2026-03-06", "2026-03-09"])  # Friday, Monday
    px = rows("y:A:close", days, [100.0, 100.0])
    div = rows("y:A:dividend", ["2026-03-07"], [2.0])  # stamped on a Saturday
    specs = [spec("y:A:close", SeriesKind.PRICE), spec("y:A:dividend", SeriesKind.DIVIDEND)]
    f = make(pd.concat([px, div]), specs, {"A": {"close": ["y:A:close"], "dividend": ["y:A:dividend"]}})
    tr = f.at(date(2026, 3, 9)).total_return(["A"], freq=None)["A"]
    assert tr.iloc[-1] == pytest.approx(102.0)


def test_total_return_from_monthly_returns() -> None:
    r = rows("s:R", ["2026-01-31", "2026-02-28", "2026-03-31"], [0.01, -0.02, 0.03])
    f = make(r, [spec("s:R", SeriesKind.RETURN, Frequency.MONTHLY)], {"R": {"return": ["s:R"]}})
    tr = f.at(date(2026, 3, 31)).total_return(["R"])["R"]
    # base 100 at the end of the month before the first return, so the January return is not lost
    assert tr.index[0] == pd.Timestamp("2025-12-31")
    assert tr.tolist() == pytest.approx([100.0, 101.0, 101.0 * 0.98, 101.0 * 0.98 * 1.03])
    assert f.at(date(2026, 3, 31)).returns(["R"])["R"].iloc[1:].tolist() == pytest.approx([0.01, -0.02, 0.03])
    assert (
        f.at(date(2025, 12, 31)).total_return(["R"])["R"].empty
    )  # the base exists only once a return is known


def test_cash_index_from_monthly_yield_daily_and_monthly_agree() -> None:
    y = rows("fred:TB", ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"], [4.8, 4.5, 4.2, 4.0])
    cal = WeekdayCalendar()
    f = make(y, [spec("fred:TB", SeriesKind.YIELD, Frequency.MONTHLY)], {"CASH": {"yield": ["fred:TB"]}}, cal)
    v = f.at(date(2026, 4, 30))
    monthly = v.total_return(["CASH"], "ME")["CASH"]
    assert monthly.tolist() == pytest.approx([100.0, 100.4, 100.4 * 1.00375, 100.4 * 1.00375 * 1.0035])
    daily = v.total_return(["CASH"], None)["CASH"]
    for me in monthly.index[1:]:
        last_session = daily[daily.index <= me].iloc[-1]
        assert last_session == pytest.approx(monthly.loc[me], rel=1e-12)


def test_static_view_reproduces_research_cash_and_equity(static_factory) -> None:
    v = static_factory.at(date(2025, 12, 31))
    a = pd.read_csv("data/assets_monthly.csv", index_col=0, parse_dates=True)
    got = v.total_return(["US_EQ", "TBILL"], "ME")
    for col in ("US_EQ", "TBILL"):
        x = a[col].dropna()
        assert np.allclose(got[col].reindex(x.index), x, rtol=1e-8)


def test_last_obs_and_calendar(static_factory) -> None:
    v = static_factory.at(date(2008, 6, 30))
    assert v.last_obs("static:fredmd:CPIAUCSL") == date(2008, 5, 31)  # lag 1M: May known by end of June
    assert v.last_obs("static:usmkt:TR") == date(2008, 6, 30)
    assert v.calendar().is_trading_day(date(2008, 6, 30))


def test_session_cache_grows_and_equals_the_calendar() -> None:
    from rotationlab.core.clock import WeekdayCalendar
    from rotationlab.data.view import _sessions

    cal = WeekdayCalendar(holidays=[date(2020, 1, 1)])
    a = _sessions(cal, date(2020, 1, 1), date(2020, 1, 31))
    assert [np.datetime64(d, "D") for d in cal.trading_days(date(2020, 1, 1), date(2020, 1, 31))] == list(a)
    b = _sessions(cal, date(1999, 12, 1), date(2021, 2, 1))  # outside the cached years: rebuilt wider
    assert b[0] == np.datetime64("1999-12-01") and b[-1] == np.datetime64("2021-02-01")
    assert list(_sessions(cal, date(2020, 1, 1), date(2020, 1, 31))) == list(a)
    assert _sessions(WeekdayCalendar(), date(2020, 1, 4), date(2020, 1, 5)).size == 0  # a weekend
