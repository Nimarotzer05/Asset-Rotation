"""NYSE trading calendar (XNYS), rule-based, no third-party dependency (ADR 023).

Valid from 1971 (Uniform Monday Holiday Act) onwards; before 1971 the calendar falls back to
weekdays minus the rule-based holidays, which is good enough for monthly research history.
Validated against 35 years of S&P 500 daily closes (tests/unit/test_calendar.py): the set of days
with a close equals the set of trading days produced here.

Rules (NYSE Rule 7.2 and historical practice):
  New Year's Day      Jan 1; Sunday → Monday; Saturday → not observed (Dec 31 stays open)
  Martin Luther King  3rd Monday in January, since 1998
  Washington/Presidents 3rd Monday in February
  Good Friday         Easter Sunday − 2 days
  Memorial Day        last Monday in May
  Juneteenth          June 19, since 2022; Saturday → Friday, Sunday → Monday
  Independence Day    July 4; Saturday → Friday, Sunday → Monday
  Labor Day           1st Monday in September
  Thanksgiving        4th Thursday in November
  Christmas           Dec 25; Saturday → Friday, Sunday → Monday
  Election Day        1st Tuesday after the 1st Monday in November, presidential years up to 1980
  Special closings    funerals, weather, 9/11 (list below)
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from functools import lru_cache

CALENDAR_VALID_FROM = date(1971, 1, 1)

SPECIAL_CLOSINGS: frozenset[date] = frozenset({
    date(1972, 12, 28),  # President Truman funeral
    date(1973, 1, 25),   # President Johnson funeral
    date(1977, 7, 14),   # New York City blackout
    date(1985, 9, 27),   # Hurricane Gloria
    date(1994, 4, 27),   # President Nixon funeral
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),  # 9/11
    date(2004, 6, 11),   # President Reagan funeral
    date(2007, 1, 2),    # President Ford national day of mourning
    date(2012, 10, 29), date(2012, 10, 30),  # Hurricane Sandy
    date(2018, 12, 5),   # President G.H.W. Bush funeral
    date(2025, 1, 9),    # President Carter national day of mourning
})


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=512)
def nyse_holidays(year: int) -> frozenset[date]:
    h: set[date | None] = set()
    h.add(_observed(date(year, 1, 1), saturday_to_friday=False))
    if year >= 1998:
        h.add(_nth_weekday(year, 1, 0, 3))
    h.add(_nth_weekday(year, 2, 0, 3) if year >= 1971 else _observed(date(year, 2, 22)))
    h.add(easter(year) - timedelta(days=2))
    h.add(_last_weekday(year, 5, 0) if year >= 1971 else _observed(date(year, 5, 30)))
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))
    h.add(_observed(date(year, 7, 4)))
    h.add(_nth_weekday(year, 9, 0, 1))
    h.add(_nth_weekday(year, 11, 3, 4))
    h.add(_observed(date(year, 12, 25)))
    if year <= 1980 and year % 4 == 0:
        h.add(_nth_weekday(year, 11, 0, 1) + timedelta(days=1))
    h.update(d for d in SPECIAL_CLOSINGS if d.year == year)
    return frozenset(d for d in h if d is not None)


class NYSECalendar:
    """TradingCalendar for XNYS."""

    name = "XNYS"

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in nyse_holidays(d.year)

    def trading_days(self, start: date, end: date) -> Sequence[date]:
        out: list[date] = []
        d = start
        while d <= end:
            if self.is_trading_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def month_ends(self, start: date, end: date) -> Sequence[date]:
        """Calendar month-ends in [start, end] – the decision dates (ADR 021)."""
        out: list[date] = []
        y, m = start.year, start.month
        while True:
            me = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            if me > end:
                break
            if me >= start:
                out.append(me)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out

    def trading_month_ends(self, start: date, end: date) -> Sequence[date]:
        """Last trading session of each complete month in [start, end]."""
        return [self.previous_trading_day(me + timedelta(days=1)) for me in self.month_ends(start, end)]

    def next_trading_day(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def previous_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def sessions_between(self, a: date, b: date) -> int:
        """Number of trading sessions in (a, b]."""
        if b <= a:
            return 0
        return len(self.trading_days(a + timedelta(days=1), b))

    def last_completed_session(self, now_date: date) -> date:
        """The most recent session strictly before `now_date` (runs happen the next morning)."""
        return self.previous_trading_day(now_date)
