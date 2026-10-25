"""Publication lags and the NYSE calendar."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from rotationlab.core.clock import MonthEndClock, last_month_end_before
from rotationlab.data.calendar import NYSECalendar, easter, nyse_holidays
from rotationlab.data.lags import Lag

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------- lags
@pytest.mark.parametrize(
    "text,obs,expected",
    [
        ("0D", date(2026, 9, 30), date(2026, 9, 30)),
        ("1D", date(2026, 9, 30), date(2026, 10, 1)),
        ("7d", date(2026, 2, 26), date(2026, 3, 5)),
        ("1M", date(2026, 9, 30), date(2026, 10, 31)),
        ("1M", date(2026, 1, 31), date(2026, 2, 28)),
        ("1M", date(2024, 1, 31), date(2024, 2, 29)),
        ("2M", date(2026, 12, 31), date(2027, 2, 28)),
        ("6M", date(2026, 3, 31), date(2026, 9, 30)),
        ("6M", date(2026, 8, 31), date(2027, 2, 28)),
        ("0M", date(2026, 9, 15), date(2026, 9, 30)),
    ],
)
def test_lag_apply(text: str, obs: date, expected: date) -> None:
    assert Lag.parse(text).apply(obs) == expected


@pytest.mark.parametrize("text", ["1", "M", "1W", "-1D", "1.5M", ""])
def test_lag_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        Lag.parse(text)


def test_lag_vectorised_equals_scalar() -> None:
    obs = pd.date_range("1990-01-31", "2026-12-31", freq="ME").append(
        pd.date_range("2020-01-01", periods=400, freq="D")
    )
    for text in ("0D", "1D", "35D", "1M", "2M", "6M"):
        lag = Lag.parse(text)
        vec = lag.apply_index(obs)
        assert [d.date() for d in vec] == [lag.apply(d.date()) for d in obs], text


def test_month_lag_reproduces_research_shift() -> None:
    """'nM' at calendar month-end decisions ≡ series.shift(n) on a month-end panel."""
    idx = pd.date_range("2000-01-31", "2005-12-31", freq="ME")
    s = pd.Series(range(len(idx)), index=idx, dtype=float)
    for n in (1, 2, 6):
        lag = Lag.parse(f"{n}M")
        for D in idx[n:]:
            visible = s[[lag.apply(o.date()) <= D.date() for o in s.index]]
            assert visible.iloc[-1] == s.shift(n).loc[D]


# ---------------------------------------------------------------------------- calendar
def test_easter_known_years() -> None:
    assert easter(2024) == date(2024, 3, 31)
    assert easter(2025) == date(2025, 4, 20)
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2000) == date(2000, 4, 23)


def test_holidays_2025_2026() -> None:
    assert sorted(nyse_holidays(2026)) == [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    ]
    assert sorted(nyse_holidays(2025)) == [
        date(2025, 1, 1),
        date(2025, 1, 9),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
    ]


def test_observance_rules() -> None:
    cal = NYSECalendar()
    assert cal.is_trading_day(date(2021, 12, 31))  # New Year 2022 on a Saturday is not observed
    assert not cal.is_trading_day(date(2026, 7, 3))  # July 4 on a Saturday → Friday
    assert not cal.is_trading_day(date(2022, 6, 20))  # Juneteenth on a Sunday → Monday
    assert cal.is_trading_day(date(2021, 6, 18))  # Juneteenth not a holiday before 2022
    assert not cal.is_trading_day(date(2012, 10, 29))  # Hurricane Sandy
    assert not cal.is_trading_day(date(1980, 11, 4))  # presidential election day until 1980
    assert cal.is_trading_day(date(1984, 11, 6))


def test_navigation() -> None:
    cal = NYSECalendar()
    assert cal.next_trading_day(date(2026, 7, 2)) == date(2026, 7, 6)
    assert cal.previous_trading_day(date(2026, 1, 20)) == date(2026, 1, 16)
    assert cal.month_ends(date(2026, 1, 15), date(2026, 4, 30)) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]
    assert cal.trading_month_ends(date(2026, 1, 1), date(2026, 3, 31)) == [
        date(2026, 1, 30),
        date(2026, 2, 27),
        date(2026, 3, 31),
    ]
    assert cal.sessions_between(date(2026, 7, 2), date(2026, 7, 7)) == 2


def test_decision_and_execution_dates() -> None:
    cal = NYSECalendar()
    clock = MonthEndClock(cal, date(2026, 1, 1), date(2026, 12, 31))
    assert len(clock.decision_dates()) == 12
    assert clock.execution_day(date(2026, 1, 31)) == date(2026, 2, 2)  # Saturday month-end
    assert clock.execution_day(date(2026, 3, 31)) == date(2026, 4, 1)  # Tuesday month-end
    assert last_month_end_before(date(2026, 11, 2)) == date(2026, 10, 31)
    assert last_month_end_before(date(2026, 11, 1)) == date(2026, 10, 31)


@pytest.mark.data
def test_calendar_matches_55_years_of_sp500_sessions() -> None:
    """Every day with an S&P 500 close 1971–2025 is a session and every session has a close."""
    d = pd.read_csv(ROOT / "data/raw/us_market_data_daily.csv", usecols=["Date"], parse_dates=["Date"])[
        "Date"
    ].dt.date
    have = {x for x in d if x >= date(1971, 1, 1)}
    sessions = set(NYSECalendar().trading_days(date(1971, 1, 1), max(have)))
    assert have - sessions == set()
    assert sessions - have == set()
