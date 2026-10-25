"""Decision calendar (ADR 021).

Decisions are taken as of calendar month-ends D: the view at D contains every close up to the last
session on or before D and every release published by D. Orders execute at the close of the next
trading session after D (``execution_day``). Live runs happen the morning after a session, so the
decision for D is computed on the first run after D and executed at that day's close.

Calendar month-ends (not last sessions) make monthly labels identical to the research panels and
make month-based publication lags (``"1M"``) exact; nothing that happens between the last session
and the calendar month-end is information a market participant could act on before the next session.

`WeekdayCalendar` is a dependency-free test double; production uses `rotationlab.data.calendar.NYSECalendar`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from rotationlab.core.protocols import TradingCalendar


def calendar_month_ends(start: date, end: date) -> list[date]:
    out: list[date] = []
    y, m = start.year, start.month
    while True:
        me = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        if me > end:
            return out
        if me >= start:
            out.append(me)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def last_month_end_before(today: date) -> date:
    """Latest calendar month-end strictly before `today` (the live decision date)."""
    return today.replace(day=1) - timedelta(days=1)


class WeekdayCalendar:
    """Mon–Fri minus an explicit holiday set. Sufficient for tests; production uses NYSECalendar."""

    name = "weekday"

    def __init__(self, holidays: Sequence[date] = ()) -> None:
        self._holidays = frozenset(holidays)

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holidays

    def trading_days(self, start: date, end: date) -> Sequence[date]:
        out: list[date] = []
        d = start
        while d <= end:
            if self.is_trading_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def month_ends(self, start: date, end: date) -> Sequence[date]:
        return calendar_month_ends(start, end)

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


class MonthEndClock:
    """Backtest/walk-forward: every calendar month-end in [start, end]."""

    def __init__(self, calendar: TradingCalendar, start: date, end: date) -> None:
        self._cal = calendar
        self._dates = list(calendar.month_ends(start, end))

    def decision_dates(self) -> Sequence[date]:
        return list(self._dates)

    def next_decision(self, d: date) -> date | None:
        for x in self._dates:
            if x > d:
                return x
        return None

    def execution_day(self, d: date) -> date:
        return self._cal.next_trading_day(d)

    def trading_days(self, start: date, end: date) -> Sequence[date]:
        return self._cal.trading_days(start, end)

    def next_trading_day(self, d: date) -> date:
        return self._cal.next_trading_day(d)


class SingleDateClock:
    """Live mode: exactly one decision date (the last calendar month-end), daily loop up to `today`."""

    def __init__(self, calendar: TradingCalendar, decision: date, today: date) -> None:
        self._cal = calendar
        self._decision = decision
        self._today = today

    def decision_dates(self) -> Sequence[date]:
        return [self._decision]

    def next_decision(self, d: date) -> date | None:
        return None

    def execution_day(self, d: date) -> date:
        return self._cal.next_trading_day(d)

    def trading_days(self, start: date, end: date) -> Sequence[date]:
        return self._cal.trading_days(start, min(end, self._today))

    def next_trading_day(self, d: date) -> date:
        return self._cal.next_trading_day(d)
