"""Download of the FRED-MD vintage archive into ``data/raw/fredmd_vintages`` (+ ``vintages.yaml``).

The St. Louis Fed publishes every monthly FRED-MD vintage since 1999-08: older ones in a historical
zip archive, recent ones as monthly CSV files. URLs have moved over the years, so several patterns are
tried in order and the first that answers wins; the source of every file is recorded in the manifest.
Vintage dates are conservative: the vintage ``YYYY-MM`` counts as known 7 days after the end of that
month (files appear during the month or in the first days of the next one).

Run where the site is reachable: ``rotationlab fredmd-archive`` (or the ``network`` workflow).
"""
from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from rotationlab.core.errors import DataError
from rotationlab.data.providers.http import HttpClient

MONTHLY_PATTERNS: tuple[str, ...] = (
    "https://www.stlouisfed.org/-/media/project/frbstl/stlouisfed/research/fred-md/monthly/{label}-md.csv",
    "https://files.stlouisfed.org/files/htdocs/fred-databases/monthly/{label}.csv",
)
HISTORICAL_ZIPS: tuple[str, ...] = (
    "https://www.stlouisfed.org/-/media/project/frbstl/stlouisfed/research/fred-md/historical_fred-md.zip",
    "https://files.stlouisfed.org/files/htdocs/fred-databases/Historical_FRED-MD.zip",
)
_LABEL_RE = re.compile(r"(\d{4})-(\d{2})(?:-md)?\.csv$", re.IGNORECASE)
KNOWN_AFTER_DAYS = 7


@dataclass
class ArchiveReport:
    added: list[str]
    skipped: list[str]
    missing: list[str]


def vintage_date(label: str) -> date:
    y, m = int(label[:4]), int(label[5:7])
    month_end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return month_end + timedelta(days=KNOWN_AFTER_DAYS)


def is_fredmd_csv(raw: bytes) -> bool:
    head = raw[:200].decode("latin-1", errors="replace").lower()
    return head.startswith("sasdate") or head.startswith("﻿sasdate")


def labels_between(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def _read_manifest(path: Path) -> dict[str, list[dict[str, object]]]:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {"vintages": []}
    return {"vintages": []}


def _write_manifest(path: Path, manifest: dict[str, list[dict[str, object]]], header: str) -> None:
    manifest["vintages"] = sorted(manifest["vintages"], key=lambda e: str(e["vintage_date"]))
    path.write_text(header + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))


def zip_members(raw: bytes) -> dict[str, bytes]:
    """label -> CSV bytes for every FRED-MD vintage inside a (possibly nested-folder) zip."""
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            m = _LABEL_RE.search(name)
            if m:
                out[f"{m.group(1)}-{m.group(2)}"] = z.read(name)
    return out


def fetch_archive(http: HttpClient, raw_path: str | Path, start: str = "1999-08", end: str | None = None,
                  log: Callable[[str], None] = print) -> ArchiveReport:
    """Fetch missing vintages; existing files are never overwritten (the archive is append-only)."""
    vdir = Path(raw_path) / "fredmd_vintages"
    vdir.mkdir(parents=True, exist_ok=True)
    mpath = vdir / "vintages.yaml"
    header = mpath.read_text().split("vintages:")[0] if mpath.exists() else "# FRED-MD vintages (see providers/fredmd_archive.py)\n"
    manifest = _read_manifest(mpath)
    have = {str(e["label"]) for e in manifest["vintages"]}
    end = end or (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    wanted = [lb for lb in labels_between(start, end) if lb not in have]
    rep = ArchiveReport(added=[], skipped=sorted(have), missing=[])

    def add(label: str, raw: bytes, source: str) -> None:
        (vdir / f"{label}.csv").write_bytes(raw)
        manifest["vintages"].append({"file": f"{label}.csv", "label": label, "vintage_date": vintage_date(label),
                                     "source": source})
        rep.added.append(label)

    historical: dict[str, tuple[bytes, str]] = {}
    if any(lb < "2015-01" for lb in wanted):
        for url in HISTORICAL_ZIPS:
            try:
                members = zip_members(http.get(url))
            except (DataError, zipfile.BadZipFile) as e:
                log(f"historical archive not at {url}: {e}")
                continue
            historical = {lb: (raw, url) for lb, raw in members.items()}
            break
    for label in wanted:
        if label in historical and is_fredmd_csv(historical[label][0]):
            add(label, historical[label][0], historical[label][1])
            continue
        for pattern in MONTHLY_PATTERNS:
            url = pattern.format(label=label)
            try:
                raw = http.get(url)
            except DataError:
                continue
            if is_fredmd_csv(raw):
                add(label, raw, url)
                break
        else:
            rep.missing.append(label)
    _write_manifest(mpath, manifest, header)
    log(f"FRED-MD archive: {len(rep.added)} added, {len(rep.skipped)} already present, {len(rep.missing)} not found")
    return rep


def describe(entries: Iterable[dict[str, object]]) -> str:
    e = list(entries)
    return f"{len(e)} vintages" + (f" ({e[0]['label']} … {e[-1]['label']})" if e else "")
