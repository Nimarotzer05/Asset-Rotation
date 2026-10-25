"""Tiny synthetic markets for unit tests of features, strategies and the engine.

world = Toy()
world.monthly("A", levels)                # asset A with a monthly total-return series
world.daily("B", closes)                  # asset B with daily closes (role close)
world.cash("C", monthly_returns)          # cash asset (role return, asset_class cash)
f = world.factory()                       # StoreViewFactory over everything (WeekdayCalendar)
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.types import (
    AssetId,
    Cadence,
    Frequency,
    Months,
    Role,
    SeriesId,
    SeriesKind,
    SeriesSpec,
    StrategyId,
    StrategySpec,
)
from rotationlab.data.view import StoreViewFactory


class Toy:
    def __init__(self) -> None:
        self.frames: list[pd.DataFrame] = []
        self.specs: dict[str, SeriesSpec] = {}
        self.roles: dict[str, dict[str, list[str]]] = {}
        self.chains: dict[str, list[str]] = {}

    def _add(self, sid: str, kind: SeriesKind, freq: Frequency, s: pd.Series, lag_days: int = 0) -> None:
        idx = pd.DatetimeIndex(s.index)
        self.frames.append(
            pd.DataFrame(
                {
                    "series_id": sid,
                    "obs_date": idx,
                    "vintage_date": idx + pd.Timedelta(days=lag_days),
                    "value": s.to_numpy(float),
                }
            )
        )
        self.specs[sid] = SeriesSpec(
            SeriesId(sid), sid.split(":", maxsplit=1)[0], sid.split(":", 1)[1], kind, freq
        )

    def monthly(self, asset: str, levels: Sequence[float] | pd.Series, start: str = "2000-01-31") -> Toy:
        s = (
            levels
            if isinstance(levels, pd.Series)
            else pd.Series(levels, index=pd.date_range(start, periods=len(levels), freq="ME"))
        )
        sid = f"t:{asset}:tr"
        self._add(sid, SeriesKind.TOTAL_RETURN, Frequency.MONTHLY, s)
        self.roles[asset] = {"total_return": [sid]}
        return self

    def daily(self, asset: str, closes: Sequence[float] | pd.Series, start: str = "2000-01-03") -> Toy:
        s = (
            closes
            if isinstance(closes, pd.Series)
            else pd.Series(closes, index=pd.bdate_range(start, periods=len(closes)))
        )
        sid = f"t:{asset}:close"
        self._add(sid, SeriesKind.PRICE, Frequency.DAILY, s)
        self.roles[asset] = {"close": [sid]}
        return self

    def cash(
        self,
        asset: str,
        monthly_returns: Sequence[float] | float,
        n: int | None = None,
        start: str = "2000-01-31",
    ) -> Toy:
        r = [monthly_returns] * (n or 0) if isinstance(monthly_returns, float) else list(monthly_returns)
        s = pd.Series(r, index=pd.date_range(start, periods=len(r), freq="ME"))
        sid = f"t:{asset}:ret"
        self._add(sid, SeriesKind.RETURN, Frequency.MONTHLY, s)
        self.roles[asset] = {"return": [sid]}
        return self

    def series(
        self,
        sid: str,
        values: pd.Series,
        kind: SeriesKind = SeriesKind.MACRO,
        freq: Frequency = Frequency.MONTHLY,
        lag_days: int = 0,
    ) -> Toy:
        self._add(sid, kind, freq, values, lag_days)
        return self

    def factory(self) -> StoreViewFactory:
        obs = pd.concat(self.frames, ignore_index=True)
        return StoreViewFactory(obs, self.specs, self.roles, WeekdayCalendar(), chains=self.chains)


def geometric(start: float, growth: float, n: int) -> list[float]:
    return list(start * (1 + growth) ** np.arange(n))


def spec(sid: str, universe: Sequence[str], params: dict | None = None, warmup: int = 13) -> StrategySpec:
    return StrategySpec(
        StrategyId(sid),
        1,
        Role.CORE,
        Cadence.MONTHLY,
        tuple(AssetId(a) for a in universe),
        Months(warmup),
        dict(params or {}),
    )
