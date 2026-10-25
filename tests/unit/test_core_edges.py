"""Contracts of the core layer that the main tests do not reach: clocks, registry, value types."""

from __future__ import annotations

from datetime import date

import pytest

from rotationlab.core import registry
from rotationlab.core.clock import MonthEndClock, SingleDateClock, WeekdayCalendar, calendar_month_ends
from rotationlab.core.errors import RegistryError
from rotationlab.core.types import (
    AssetId,
    Cadence,
    Months,
    Proposal,
    Role,
    StrategyId,
    StrategySpec,
    StrategyState,
    weights_from,
)


@pytest.fixture
def clean_registry():
    saved = (dict(registry._FEATURES), dict(registry._STRATEGIES))
    registry._reset_for_tests()
    yield registry
    registry._reset_for_tests()
    registry._FEATURES.update(saved[0])
    registry._STRATEGIES.update(saved[1])


# ---------------------------------------------------------------------------- clocks
def test_weekday_calendar_navigation() -> None:
    cal = WeekdayCalendar(holidays=[date(2026, 1, 1)])
    assert cal.previous_trading_day(date(2026, 1, 5)) == date(2026, 1, 2)
    assert cal.previous_trading_day(date(2026, 1, 2)) == date(2025, 12, 31)
    assert calendar_month_ends(date(2025, 12, 31), date(2026, 2, 27)) == [
        date(2025, 12, 31),
        date(2026, 1, 31),
    ]


def test_month_end_clock_full_surface() -> None:
    cal = WeekdayCalendar()
    clock = MonthEndClock(cal, date(2026, 1, 1), date(2026, 3, 31))
    assert clock.next_decision(date(2026, 3, 31)) is None
    assert clock.trading_days(date(2026, 1, 1), date(2026, 1, 4)) == [date(2026, 1, 1), date(2026, 1, 2)]
    assert clock.next_trading_day(date(2026, 1, 2)) == date(2026, 1, 5)


def test_single_date_clock_live_mode() -> None:
    cal = WeekdayCalendar()
    clock = SingleDateClock(cal, decision=date(2026, 9, 30), today=date(2026, 10, 2))
    assert clock.decision_dates() == [date(2026, 9, 30)]
    assert clock.next_decision(date(2026, 9, 30)) is None
    assert clock.execution_day(date(2026, 9, 30)) == date(2026, 10, 1)
    assert clock.trading_days(date(2026, 9, 30), date(2026, 12, 31)) == [
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
    ]
    assert clock.next_trading_day(date(2026, 10, 2)) == date(2026, 10, 5)


# ---------------------------------------------------------------------------- registry
def test_feature_registry_and_panel_variant(clean_registry) -> None:
    @registry.feature(name="mom", kind="cross_section", inputs=["total_return"], lookback=Months(12))
    def mom(view, assets):
        return None

    @registry.panel_variant("mom")
    def mom_panel(panel):
        return panel

    meta = registry.get_feature("mom")
    assert meta.panel_fn is mom_panel and meta.macro_lag == Months(0) and "mom" in registry.features()
    with pytest.raises(RegistryError):
        registry.panel_variant("nope")(mom_panel)
    with pytest.raises(RegistryError):
        registry.get_feature("nope")


def test_strategy_registry(clean_registry) -> None:
    @registry.strategy
    class Alpha:
        strategy_id = "alpha"

    assert registry.get_strategy("alpha") is Alpha and "alpha" in registry.strategies()
    with pytest.raises(RegistryError):
        registry.strategy(Alpha)
    with pytest.raises(RegistryError):
        registry.get_strategy("beta")


# ---------------------------------------------------------------------------- value types
def test_months_and_proposal_validation() -> None:
    with pytest.raises(ValueError):
        Months(-1)
    ok = Proposal(StrategyId("s"), date(2026, 9, 30), {AssetId("A"): 0.6, AssetId("B"): -0.4}, 0.8, 1)
    assert ok.net == pytest.approx(0.2) and ok.gross == pytest.approx(1.0)
    with pytest.raises(ValueError, match="confidence"):
        Proposal(StrategyId("s"), date(2026, 9, 30), {}, 1.2, 1)
    with pytest.raises(ValueError, match="gross"):
        Proposal(StrategyId("s"), date(2026, 9, 30), {AssetId("A"): 1.5, AssetId("B"): -0.6}, 0.5, 1)
    with pytest.raises(ValueError, match="NaN"):
        Proposal(StrategyId("s"), date(2026, 9, 30), {AssetId("A"): float("nan")}, 0.5, 1)


def test_state_and_spec_serialise_deterministically() -> None:
    st = StrategyState(StrategyId("pm"), positions={AssetId("GLD"): 0.1}, entries={"ratio_entry": 49.6})
    assert (
        st.to_json()
        == StrategyState(
            StrategyId("pm"), positions={AssetId("GLD"): 0.1}, entries={"ratio_entry": 49.6}
        ).to_json()
    )
    spec = StrategySpec(
        StrategyId("x"), 1, Role.CORE, Cadence.MONTHLY, (AssetId("SPY"),), Months(12), {"k": 1}
    )
    assert len(spec.config_hash()) == 12
    assert (
        spec.config_hash()
        != StrategySpec(
            StrategyId("x"), 2, Role.CORE, Cadence.MONTHLY, (AssetId("SPY"),), Months(12), {"k": 1}
        ).config_hash()
    )
    assert weights_from([(AssetId("A"), 0.5), (AssetId("B"), 0.0)]) == {"A": 0.5}
