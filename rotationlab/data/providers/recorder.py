"""Record real provider answers as test fixtures (``rotationlab record-fixtures``, weekly network job).

The build environment of this repository could not reach the data providers, so the parsers were
first tested against responses rebuilt from the documented formats. This tool closes the gap: it
fetches a small sample per provider through a `RecordingClient`, stores the raw answers and a
``meta.json`` (what was asked, how many rows came back), and ``tests/integration/test_recorded.py``
replays them offline on every CI run. When a provider changes its format, the next recording fails
loudly instead of the daily ingest.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from pathlib import Path

from rotationlab.config.models import Bundle, ProviderConfig
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers import make_providers
from rotationlab.data.providers.http import HttpClient, RecordingClient, UrllibClient

SAMPLE: dict[str, list[tuple[str, int | None]]] = {  # provider -> [(series id, lookback days or None = full)]
    "yahoo": [("yahoo:SPY:close", 45), ("yahoo:SPY:dividend", 400), ("yahoo:XLK:split", None)],
    "stooq": [("stooq:SPY:close", 45)],
    "fred": [("fred:DGS10", 45), ("fred:TB3MS", 400), ("fred:CPIAUCSL", None)],
    "french": [("french:ff3:RF", None), ("french:ind10:HITEC", None)],
    "cftc": [("cftc:088691:noncomm_net", 120)],
    "bls": [("bls:CUSR0000SA0", None)],
    "shiller": [("shiller:E", None)],
}


def record(bundle: Bundle, catalog: Mapping[str, SeriesSpec], out_dir: str | Path, today: date,
           env: Mapping[str, str] | None = None,
           transport: Callable[[str, ProviderConfig], HttpClient] | None = None) -> list[dict[str, object]]:
    """`transport` builds the real client per provider (default: urllib); tests pass fixture clients."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def factory(name: str, pc: ProviderConfig) -> RecordingClient:
        inner = transport(name, pc) if transport else UrllibClient(timeout_s=pc.timeout_s, retries=pc.retries,
                                                                   min_interval_s=pc.min_interval_s)
        return RecordingClient(inner, out, label=name)

    providers = make_providers(bundle, today, env=env, http_factory=factory)
    rows: list[dict[str, object]] = []
    for pname, items in SAMPLE.items():
        prov = providers.get(pname)
        for sid, days in items:
            since = None if days is None else today - timedelta(days=days)
            entry: dict[str, object] = {"provider": pname, "series_id": sid,
                                        "since": None if since is None else since.isoformat()}
            try:
                if prov is None:
                    raise RuntimeError("provider disabled")
                f = prov.fetch_frame(catalog[sid], since)
                entry.update(rows=len(f), first=str(f["obs_date"].min().date()) if len(f) else None,
                             last=str(f["obs_date"].max().date()) if len(f) else None, error=None)
            except Exception as e:  # recorded, never fatal: the point is to see which provider broke
                entry.update(rows=None, error=f"{type(e).__name__}: {e}"[:300])
            rows.append(entry)
    (out / "meta.json").write_text(json.dumps({"recorded_on": today.isoformat(), "series": rows}, indent=1))
    return rows
