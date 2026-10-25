"""Shared fixtures. The static store is built once per session in memory (~7 s) from data/raw."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from rotationlab.config.models import Bundle, load_bundle
from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.catalog import build_catalog
from rotationlab.data.ingest import run_ingest
from rotationlab.data.providers.static import StaticProvider
from rotationlab.data.store import PointInTimeStore
from rotationlab.data.view import StoreViewFactory

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def bundle() -> Bundle:
    return load_bundle(ROOT / "configs")


@pytest.fixture(scope="session")
def catalog(bundle):
    return build_catalog(bundle)


@pytest.fixture(scope="session")
def cal() -> NYSECalendar:
    return NYSECalendar()


@pytest.fixture(scope="session")
def static_store(bundle, catalog, cal) -> PointInTimeStore:
    store = PointInTimeStore(None)
    rep = run_ingest(
        store,
        bundle,
        catalog,
        {"static": StaticProvider(ROOT / "data" / "raw")},
        cal,
        run_date=date(2026, 10, 24),
        full=True,
    )
    assert not rep.blocking, rep.blocking
    return store


@pytest.fixture(scope="session")
def static_factory(static_store, catalog, bundle, cal) -> StoreViewFactory:
    return StoreViewFactory.from_store(
        static_store, catalog, bundle.universe, cal, chains=bundle.series.chains
    )
