"""Research data for round 4 (ADR 057): download the raw source files once, unchanged, with a manifest.

The research workspace cannot reach FRED or the Kenneth French Data Library, so this script runs in GitHub
Actions (workflow `research-data`, started by hand). It writes every answer byte for byte (gzip-compressed)
under ``--out`` plus ``MANIFEST.json`` with, per file: source URL (API key redacted), SHA-256 and size of the
*uncompressed* bytes, fetch time (UTC), format and status. The workflow commits the folder to the orphan
branch ``research-data``; ``scripts/freeze_research_data.py`` turns a pinned commit of that branch into
data/raw files. Nothing here touches the store, the live configuration or the daily run.

Sources (fixed in ADR 057 before any of them was downloaded):

* FRED H.10 spot rates, daily: the nine G10 currencies against the dollar (EUR before 1999 via DEM).
* FRED constant-maturity Treasury yields, daily: 2, 5 and 10 years.
* FRED / OECD short rates, monthly: 3-month interbank rate per currency area and, as the pre-registered
  fallback, the call money rate (optional: a missing series is recorded, not fatal).
* Kenneth French: 10 industry portfolios (daily) and the international country portfolios (monthly).

Exit code 1 if a required source failed (the files that did arrive are still written), else 0.

Aufruf: python scripts/fetch_research_data.py --out research_data
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.core.errors import DataError  # noqa: E402
from rotationlab.data.providers.fred import API_URL, GRAPH_URL  # noqa: E402
from rotationlab.data.providers.french import BASE_URL  # noqa: E402
from rotationlab.data.providers.http import HttpClient, UrllibClient, _redact, build_url  # noqa: E402

FX_SPOT = [
    "DEXJPUS",
    "DEXUSUK",
    "DEXSZUS",
    "DEXCAUS",
    "DEXUSAL",
    "DEXUSNZ",
    "DEXSDUS",
    "DEXNOUS",
    "DEXUSEU",
]
DEM_SPOT = [
    "DEXGEUS"
]  # optional since ADR 059: FRED answered HTTP 400 on 2026-10-28 (series no longer served)
TREASURY = ["DGS2", "DGS5", "DGS10"]
AREAS = ["JP", "GB", "CH", "CA", "AU", "NZ", "SE", "NO", "DE", "EZ"]  # currency areas of the nine currencies
RATES_3M = [f"IR3TIB01{a}M156N" for a in AREAS]
RATES_CALL = [f"IRSTCI01{a}M156N" for a in AREAS]
FRENCH = ["10_Industry_Portfolios_daily_CSV.zip", "F-F_International_Countries.zip"]


@dataclass(frozen=True)
class Source:
    key: str  # path under the output folder, without the .gz suffix
    kind: str  # "fred" | "french"
    code: str  # FRED series id or French zip name
    required: bool


def sources() -> list[Source]:
    out = [Source(f"fred/{c}", "fred", c, True) for c in [*FX_SPOT, *TREASURY]]
    out += [Source(f"fred/{c}", "fred", c, False) for c in [*DEM_SPOT, *RATES_3M, *RATES_CALL]]
    out += [Source(f"french/{z}", "french", z, True) for z in FRENCH]
    return out


def _download(http: HttpClient, src: Source, api_key: str | None) -> tuple[bytes, str, str]:
    """Raw bytes, the redacted URL and the format of one source."""
    if src.kind == "french":
        url = BASE_URL + src.code
        return http.get(url), url, "french_zip"
    if api_key:
        params = {"series_id": src.code, "api_key": api_key, "file_type": "json", "limit": "100000"}
        raw = http.get(API_URL, params)
        doc = json.loads(raw)
        if "error_message" in doc:
            raise DataError(f"FRED: {doc['error_message']}")
        if int(doc.get("count", 0)) > len(doc.get("observations", [])):
            raise DataError(f"FRED: {src.code} has more than one page ({doc.get('count')} observations)")
        return raw, _redact(build_url(API_URL, params)), "fred_api_json"
    params = {"id": src.code}
    return http.get(GRAPH_URL, params), build_url(GRAPH_URL, params), "fredgraph_csv"


def fetch_all(
    http: HttpClient, out: Path, api_key: str | None, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> dict[str, object]:
    """Download every source into `out` (gzip of the raw bytes) and write MANIFEST.json; returns the manifest."""
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}
    for src in sources():
        entry: dict[str, object] = {"kind": src.kind, "code": src.code, "required": src.required}
        try:
            raw, url, fmt = _download(http, src, api_key)
            path = out / f"{src.key}.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(raw, mtime=0))  # mtime 0: identical bytes give an identical file
            entry.update(
                status="ok",
                url=url,
                format=fmt,
                file=f"{src.key}.gz",
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
                fetched_at=now().replace(microsecond=0).isoformat(),
            )
        except (DataError, ValueError, OSError) as e:  # recorded, never silent
            entry.update(status=f"error: {e}", fetched_at=now().replace(microsecond=0).isoformat())
        files[src.key] = entry
    manifest = {
        "adr": "057",
        "created_at": now().replace(microsecond=0).isoformat(),
        "fred_mode": "api" if api_key else "fredgraph",
        "files": files,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def missing_required(manifest: dict[str, object]) -> list[str]:
    files = manifest["files"]
    assert isinstance(files, dict)
    return sorted(k for k, v in files.items() if v["required"] and v["status"] != "ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    http = UrllibClient(timeout_s=60.0, retries=4, backoff_s=2.0, min_interval_s=0.5)
    manifest = fetch_all(http, Path(args.out), os.environ.get("FRED_API_KEY") or None)
    files = manifest["files"]
    assert isinstance(files, dict)
    ok = sum(1 for v in files.values() if v["status"] == "ok")
    print(f"research data: {ok} of {len(files)} files fetched")
    for k, v in sorted(files.items()):
        if v["status"] != "ok":
            print(f"  {'REQUIRED ' if v['required'] else 'optional '}{k}: {v['status']}")
    bad = missing_required(manifest)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
