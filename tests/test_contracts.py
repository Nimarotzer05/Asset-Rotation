"""Phase-0 tests: the skeleton imports, configs validate, contracts hold on a dummy strategy,
the as-of rule behaves, the clock yields month-ends, and the look-ahead harness catches a leak."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from rotationlab.config.models import load_bundle
from rotationlab.core import registry
from rotationlab.core.clock import MonthEndClock, WeekdayCalendar
from rotationlab.core.errors import LookaheadError
from rotationlab.core.protocols import Strategy
from rotationlab.core.types import (
    AssetId,
    Cadence,
    Months,
    Observation,
    Proposal,
    Role,
    StrategyId,
    StrategySpec,
    StrategyState,
)
from rotationlab.data.view import as_of_pandas

ROOT = __file__.rsplit("/tests/", 1)[0]


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def test_configs_load_and_cross_check() -> None:
    b = load_bundle(f"{ROOT}/configs")
    expected = {
        "us_equity_exposure",
        "us_sector_rotation",
        "multi_asset_rotation",
        "commodity_trend",
        "precious_metals",
    }
    budgeted = {sid for sid, s in b.strategies.items() if s.role in ("core", "satellite")}
    assert budgeted == expected
    assert set(b.portfolio.risk_budgets) == expected
    # paper modules (ADR 048) sit outside the risk budgets: the forecast's rule and its baselines
    assert {sid for sid, s in b.strategies.items() if s.role == "paper"} == {
        "forecast_portfolio",
        "forecast_portfolio_v2",  # ADR 052
        "fixed_weights",
        "sleeve_allocator",  # ADR 054
        "sleeve_allocator_v2",  # ADR 057/058, registered 2026-10-28 with the window by rule
        "trend_rp_etf",  # ADR 061: implementability check of round 4 with ETFs
    }
    # every forecast config names a paper rule that exists and is registered (ADR 048/052)
    assert set(b.forecasts) == {"forecast", "forecast_v2"}
    for fc in b.forecasts.values():
        assert fc.paper_rule in b.strategies and fc.paper_rule in registry.strategies()
    assert (
        abs(
            b.portfolio.risk_budgets["us_equity_exposure"]
            + b.portfolio.risk_budgets["us_sector_rotation"]
            - 0.60
        )
        < 1e-9
    )
    assert len(b.hash()) == 12
    assert b.live is not None and b.live.strategy_versions["precious_metals"] == 1


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------
def test_observation_rejects_vintage_before_obs() -> None:
    with pytest.raises(ValueError):
        Observation("fred:CPIAUCSL", date(2024, 1, 31), date(2024, 1, 15), 300.0)  # type: ignore[arg-type]


def test_proposal_validation() -> None:
    a, b = AssetId("A"), AssetId("B")
    Proposal(StrategyId("x"), date(2024, 1, 31), {a: 0.6, b: 0.4}, 0.8, 6)
    with pytest.raises(ValueError):
        Proposal(StrategyId("x"), date(2024, 1, 31), {a: 1.5, b: -1.5}, 0.8, 6)  # gross 3
    with pytest.raises(ValueError):
        Proposal(StrategyId("x"), date(2024, 1, 31), {a: 1.0}, 1.2, 6)  # confidence


# ---------------------------------------------------------------------------
# as-of rule
# ---------------------------------------------------------------------------
def test_as_of_picks_latest_published_vintage() -> None:
    obs = pd.DataFrame(
        {
            "series_id": ["m"] * 3 + ["p"] * 2,
            "obs_date": ["2008-05-31", "2008-05-31", "2008-06-30", "2008-06-27", "2008-06-30"],
            "vintage_date": ["2008-06-17", "2008-07-16", "2008-07-16", "2008-06-27", "2008-06-30"],
            "value": [100.0, 100.5, 99.0, 1.0, 2.0],
        }
    )
    at = as_of_pandas(obs, date(2008, 6, 30))
    m = at[at.series_id == "m"]
    assert list(m.obs_date) == ["2008-05-31"] and list(m.value) == [
        100.0
    ]  # June value not yet published, May unrevised
    p = at[at.series_id == "p"]
    assert list(p.value) == [1.0, 2.0]
    later = as_of_pandas(obs, date(2008, 7, 31))
    assert list(later[later.series_id == "m"].value) == [100.5, 99.0]  # revision and June value now visible


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------
def test_month_end_clock() -> None:
    # ADR 021: decisions at calendar month-ends, execution at the next session's close
    cal = WeekdayCalendar(holidays=[date(2024, 1, 1), date(2024, 4, 1)])
    clock = MonthEndClock(cal, date(2024, 1, 1), date(2024, 3, 31))
    assert clock.decision_dates() == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)]
    assert clock.execution_day(date(2024, 2, 29)) == date(2024, 3, 1)
    assert clock.execution_day(date(2024, 3, 31)) == date(2024, 4, 2)  # Sunday month-end, Monday holiday
    assert clock.next_decision(date(2024, 1, 31)) == date(2024, 2, 29)
    assert MonthEndClock(cal, date(2024, 1, 1), date(2024, 3, 30)).decision_dates()[-1] == date(2024, 2, 29)


# ---------------------------------------------------------------------------
# strategy contract + look-ahead harness on an in-memory view
# ---------------------------------------------------------------------------
class _MemView:
    def __init__(self, df: pd.DataFrame, d: date) -> None:
        self.date = d
        self._df = df

    def close(self, assets, lookback_days=None):  # type: ignore[no-untyped-def]
        out = self._df.loc[: pd.Timestamp(self.date), list(assets)]
        return out if lookback_days is None else out.tail(lookback_days)

    def total_return(self, assets, freq="ME"):  # type: ignore[no-untyped-def]
        return self.close(assets).resample(freq).last()

    def series(self, series_id, freq=None):  # type: ignore[no-untyped-def]
        return self._df.loc[: pd.Timestamp(self.date), series_id]

    def panel(self, series_ids, freq="ME"):  # type: ignore[no-untyped-def]
        return self.close(series_ids).resample(freq).last()

    def calendar(self):  # type: ignore[no-untyped-def]
        return WeekdayCalendar()


class _MemFactory:
    def __init__(self, obs: pd.DataFrame) -> None:
        wide = obs.pivot_table(index="obs_date", columns="series_id", values="value", aggfunc="last")
        wide.index = pd.to_datetime(wide.index)
        self._wide = wide.sort_index()
        self._obs = obs

    def at(self, d: date) -> _MemView:
        at = as_of_pandas(self._obs, d).pivot_table(index="obs_date", columns="series_id", values="value")
        at.index = pd.to_datetime(at.index)
        return _MemView(at.sort_index(), d)

    def precompute(self, dates) -> None:  # type: ignore[no-untyped-def]
        return None

    def data_snapshot(self) -> str:
        return "mem"


class _MomStrategy:
    """Minimal long-only module: momentum on prices, tilted by a revised macro series M."""

    strategy_id = "dummy_mom"

    def __init__(self) -> None:
        self.spec = StrategySpec(
            StrategyId("dummy_mom"),
            1,
            Role.CORE,
            Cadence.MONTHLY,
            (AssetId("A"), AssetId("B")),
            Months(3),
            {},
        )

    def warmup(self) -> Months:
        return Months(3)

    def initial_state(self) -> StrategyState:
        return StrategyState(StrategyId("dummy_mom"))

    def propose(self, view, state):  # type: ignore[no-untyped-def]
        px = view.close(["A", "B"])
        mom = px.iloc[-1] / px.iloc[0] - 1
        m = view.series("M").dropna()
        tilt = 0.1 if len(m) and float(m.iloc[-1]) > float(m.mean()) else -0.1  # macro tilt towards A
        score = mom + pd.Series({"A": tilt, "B": -tilt})
        best = str(score.idxmax())
        p = Proposal(
            StrategyId("dummy_mom"),
            view.date,
            {AssetId(best): 1.0},
            0.7,
            1,
            {
                "mom_A": float(mom["A"]),
                "mom_B": float(mom["B"]),
                "macro_last": float(m.iloc[-1]) if len(m) else 0.0,
            },
        )
        return p, state


class _BadFactory(_MemFactory):
    """The classic bug: filters by obs_date only and takes the latest revision regardless of when it was published."""

    def at(self, d: date) -> _MemView:
        obs = self._obs[pd.to_datetime(self._obs["obs_date"]) <= pd.Timestamp(d)]
        latest = (
            obs.sort_values(["series_id", "obs_date", "vintage_date"])
            .groupby(["series_id", "obs_date"])
            .tail(1)
        )
        at = latest.pivot_table(index="obs_date", columns="series_id", values="value")
        at.index = pd.to_datetime(at.index)
        return _MemView(at.sort_index(), d)


def _toy_observations() -> pd.DataFrame:
    import numpy as np

    idx = pd.bdate_range("2020-01-01", "2020-06-30")
    rng = np.random.default_rng(1)
    a = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, len(idx))))
    b = 100 * np.exp(np.cumsum(rng.normal(0.0000, 0.01, len(idx))))
    rows = []
    for d, va, vb in zip(idx, a, b, strict=True):
        rows.append({"series_id": "A", "obs_date": d.date(), "vintage_date": d.date(), "value": va})
        rows.append({"series_id": "B", "obs_date": d.date(), "vintage_date": d.date(), "value": vb})
    # monthly macro series M: first print 15 days after month-end, revision (+ noise) 45 days after
    for k, me in enumerate(pd.date_range("2020-01-31", "2020-06-30", freq="ME")):
        v = 100 + k
        rows.append(
            {
                "series_id": "M",
                "obs_date": me.date(),
                "vintage_date": (me + pd.Timedelta(days=15)).date(),
                "value": v,
            }
        )
        rows.append(
            {
                "series_id": "M",
                "obs_date": me.date(),
                "vintage_date": (me + pd.Timedelta(days=45)).date(),
                "value": v + 3.0,
            }
        )
    return pd.DataFrame(rows)


def test_dummy_strategy_satisfies_protocol_and_passes_harness() -> None:
    from tests.lookahead.harness import LookaheadHarness

    obs = _toy_observations()
    strat = _MomStrategy()
    assert isinstance(strat, Strategy)
    dates = [date(2020, 3, 31), date(2020, 4, 30), date(2020, 5, 29)]
    LookaheadHarness(obs, _MemFactory, dates, assets=["A", "B"]).check_strategy(strat)


def test_harness_catches_a_view_that_ignores_vintages() -> None:
    from tests.lookahead.harness import LookaheadHarness

    obs = _toy_observations()
    dates = [date(2020, 3, 31), date(2020, 4, 30), date(2020, 5, 29)]
    with pytest.raises(LookaheadError):
        LookaheadHarness(obs, _BadFactory, dates, assets=["A", "B"]).check_strategy(_MomStrategy())


def test_registry_rejects_duplicates() -> None:
    saved = (dict(registry._FEATURES), dict(registry._STRATEGIES))  # the package registers on import
    registry._reset_for_tests()

    @registry.feature(name="f", kind="state", inputs=["series:x"], lookback=Months(1))
    def f(view):  # type: ignore[no-untyped-def]
        return 1.0

    with pytest.raises(Exception, match="registered twice"):

        @registry.feature(name="f", kind="state", inputs=["series:x"], lookback=Months(1))
        def g(view):  # type: ignore[no-untyped-def]
            return 2.0

    assert registry.get_feature("f").lookback == Months(1)
    registry._reset_for_tests()
    registry._FEATURES.update(saved[0])
    registry._STRATEGIES.update(saved[1])
