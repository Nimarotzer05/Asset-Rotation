"""Data layer: point-in-time store, providers, ingest, quality checks, calendar and MarketView.

Entry points for the layers above (docs/ARCHITECTURE.md §3):

    store   = open_store(bundle)                     # append-only observation log
    factory = view_factory(bundle, store)            # ViewFactory; factory.at(d) -> MarketView
    golden  = view_factory(bundle, store, providers=["static"])   # frozen research panel only
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rotationlab.config.models import Bundle
from rotationlab.core.clock import WeekdayCalendar
from rotationlab.core.protocols import TradingCalendar
from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.catalog import build_catalog
from rotationlab.data.store import PointInTimeStore
from rotationlab.data.view import StoreViewFactory


def make_calendar(bundle: Bundle) -> TradingCalendar:
    return NYSECalendar() if bundle.system.calendar == "XNYS" else WeekdayCalendar()


def open_store(bundle: Bundle, root: str | Path = ".") -> PointInTimeStore:
    return PointInTimeStore(Path(root) / bundle.system.store_path)


def view_factory(bundle: Bundle, store: PointInTimeStore, providers: Sequence[str] | None = None) -> StoreViewFactory:
    return StoreViewFactory.from_store(store, build_catalog(bundle), bundle.universe, make_calendar(bundle), providers,
                                       chains=bundle.series.chains)
