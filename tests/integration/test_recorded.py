"""Replays real provider answers recorded by ``rotationlab record-fixtures`` (weekly network job).

Skipped until a recording exists in tests/fixtures/recorded (the build environment could not reach the
providers). Each recorded series must parse to the same number of rows and pass the schema check.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from rotationlab.config.models import Bundle
from rotationlab.data import quality as q
from rotationlab.data.catalog import build_catalog
from rotationlab.data.providers import make_providers
from rotationlab.data.providers.http import ReplayClient

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"


def replay_all(directory: Path, bundle: Bundle) -> int:
    meta = json.loads((directory / "meta.json").read_text())
    today = date.fromisoformat(meta["recorded_on"])
    catalog = build_catalog(bundle)
    client = ReplayClient(directory)
    providers = make_providers(
        bundle, today, env={"FRED_API_KEY": "replay"}, http_factory=lambda name, pc: client
    )
    checked = 0
    for entry in meta["series"]:
        if entry["error"]:
            continue
        since = None if entry["since"] is None else date.fromisoformat(entry["since"])
        spec = catalog[entry["series_id"]]
        f = providers[entry["provider"]].fetch_frame(spec, since)
        assert len(f) == entry["rows"], entry
        _, rejected, _ = q.schema(spec, f, today)
        assert rejected.empty, (entry["series_id"], rejected.head())
        checked += 1
    return checked


@pytest.mark.skipif(
    not (RECORDED / "meta.json").exists(), reason="no recording yet: run `rotationlab record-fixtures`"
)
def test_recorded_answers_still_parse(bundle) -> None:
    assert replay_all(RECORDED, bundle) > 0
