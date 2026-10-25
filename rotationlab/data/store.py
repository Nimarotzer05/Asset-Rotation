"""Point-in-time store: an append-only log of what was learned when.

Layout under ``store_path`` (Branch ``data``)::

    manifest.json                 files with row counts and SHA-256, per-series ingest state, sources
    observations/base-*.csv.gz    compacted history (optional)
    observations/delta-*.csv.gz   one file per ingest run: only new observations and revisions
    series.csv                    catalog snapshot (for humans and DuckDB)
    quality_log.csv               every quality check result
    ingest_log.csv                per run and series: fetched / new / revised / unchanged / rejected
    quarantine/*.csv              rows rejected by blocking schema checks, never in observations

Why a log of gzip CSV files and not Parquet + DuckDB (ADR 020): the store holds ~1-2 million rows;
a daily run adds a few hundred. Deltas keep Git growth at kilobytes per day, every file is
readable without a binary dependency, checksums make tampering or partial writes visible, and
DuckDB can still query it directly: ``SELECT * FROM read_csv('data/store/observations/*.csv.gz')``.

Row semantics: primary key ``(series_id, obs_date, vintage_date)``. If the same key appears in two
files, the row with the later ``ingested_at`` wins (a correction before anyone could see it).
Nothing is ever deleted except by ``compact()``, which only drops such superseded duplicates.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.lags import Lag

COLUMNS = ["series_id", "obs_date", "vintage_date", "value", "ingested_at"]
PK = ["series_id", "obs_date", "vintage_date"]
FORMAT_VERSION = 1


def utc_stamp(ts: datetime | None = None) -> str:
    ts = ts or datetime.now(UTC)
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_observations() -> pd.DataFrame:
    return pd.DataFrame({
        "series_id": pd.Series(dtype="object"),
        "obs_date": pd.Series(dtype="datetime64[ns]"),
        "vintage_date": pd.Series(dtype="datetime64[ns]"),
        "value": pd.Series(dtype="float64"),
        "ingested_at": pd.Series(dtype="object"),
    })


def _encode(frame: pd.DataFrame) -> bytes:
    """Deterministic bytes: fixed column order, ISO dates, round-trip floats, gzip without timestamp."""
    f = frame.loc[:, COLUMNS].copy()
    f["obs_date"] = pd.DatetimeIndex(f["obs_date"]).strftime("%Y-%m-%d")
    f["vintage_date"] = pd.DatetimeIndex(f["vintage_date"]).strftime("%Y-%m-%d")
    f = f.sort_values(PK, kind="mergesort")
    text = f.to_csv(index=False, float_format="%.17g", lineterminator="\n")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6) as gz:
        gz.write(text.encode())
    return buf.getvalue()


def _decode(raw: bytes) -> pd.DataFrame:
    text = gzip.decompress(raw).decode()
    if not text.strip():
        return empty_observations()
    # values are read as text and parsed by Python's float(): exact round trip of the "%.17g" encoding on
    # every pandas version (pandas' own `float_precision="round_trip"` is deprecated in newer releases)
    f = pd.read_csv(io.StringIO(text), dtype={"series_id": str, "ingested_at": str, "value": str},
                    keep_default_na=False, na_values=[])
    f["value"] = np.fromiter((float(v) if v else np.nan for v in f["value"]), dtype=float, count=len(f))
    f["obs_date"] = pd.to_datetime(f["obs_date"], format="%Y-%m-%d")
    f["vintage_date"] = pd.to_datetime(f["vintage_date"], format="%Y-%m-%d")
    return f.loc[:, COLUMNS]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@dataclass
class SeriesDiff:
    """What an ingest of one series changes."""

    series_id: str
    fetched: int = 0
    new: int = 0
    revised: int = 0
    unchanged: int = 0
    late: int = 0                                      # new observations dated at their arrival (see diff)
    rows: pd.DataFrame = field(default_factory=empty_observations)
    revisions: pd.DataFrame = field(default_factory=pd.DataFrame)  # obs_date, old, new, rel_change


class PointInTimeStore:
    """Append-only observation log. ``path=None`` keeps everything in memory (tests, harness)."""

    def __init__(self, path: str | os.PathLike[str] | None) -> None:
        self.path = Path(path) if path is not None else None
        self._mem_files: list[tuple[str, bytes]] = []
        self._mem_manifest: dict[str, Any] = {"format": FORMAT_VERSION, "files": [], "series": {}, "sources": {}}
        self._obs: pd.DataFrame | None = None
        self._by_series: dict[str, pd.DataFrame] | None = None
        self._logs: dict[str, list[pd.DataFrame]] = {}

    # ------------------------------------------------------------------ manifest
    @property
    def obs_dir(self) -> Path:
        assert self.path is not None
        return self.path / "observations"

    def manifest(self) -> dict[str, Any]:
        if self.path is None:
            return self._mem_manifest
        p = self.path / "manifest.json"
        if not p.exists():
            return {"format": FORMAT_VERSION, "files": [], "series": {}, "sources": {}}
        m: dict[str, Any] = json.loads(p.read_text())
        if m.get("format") != FORMAT_VERSION:
            raise DataError(f"store format {m.get('format')} not supported (expected {FORMAT_VERSION})")
        return m

    def _write_manifest(self, m: dict[str, Any]) -> None:
        if self.path is None:
            self._mem_manifest = m
            return
        _atomic_write(self.path / "manifest.json", json.dumps(m, indent=1, sort_keys=True).encode())

    def snapshot_id(self) -> str:
        """Identifies the exact data state (run records, reproducibility): latest ingest + manifest hash."""
        m = self.manifest()
        files = m["files"]
        last = max((f["ingested_at"] for f in files), default="empty")
        digest = hashlib.sha256(json.dumps([(f["name"], f["sha256"]) for f in files]).encode()).hexdigest()[:10]
        return f"{last}/{digest}"

    # ------------------------------------------------------------------ reading
    def _read_file(self, name: str) -> bytes:
        if self.path is None:
            return dict(self._mem_files)[name]
        return (self.obs_dir / name).read_bytes()

    def observations(self) -> pd.DataFrame:
        """All rows, superseded duplicates removed, sorted by series, obs_date, vintage_date."""
        if self._obs is None:
            frames = [_decode(self._read_file(f["name"])) for f in self.manifest()["files"]]
            frames = [f for f in frames if len(f)]
            if not frames:
                self._obs = empty_observations()
            else:
                obs = pd.concat(frames, ignore_index=True)
                obs = obs.sort_values([*PK, "ingested_at"], kind="mergesort")
                obs = obs.drop_duplicates(PK, keep="last").reset_index(drop=True)
                self._obs = obs
        return self._obs

    def series_rows(self, series_id: str) -> pd.DataFrame:
        if self._by_series is None:
            obs = self.observations()
            self._by_series = {str(k): g.reset_index(drop=True) for k, g in obs.groupby("series_id", sort=False)}
        return self._by_series.get(series_id, empty_observations())

    def series_ids(self) -> list[str]:
        return sorted(self.observations()["series_id"].unique().tolist())

    def latest_values(self, series_id: str) -> pd.Series:
        """Latest known value per obs_date (any vintage, i.e. as of 'now')."""
        rows = self.series_rows(series_id)
        if rows.empty:
            return pd.Series(dtype=float)
        last = rows.drop_duplicates("obs_date", keep="last")  # rows are sorted by vintage within obs_date
        return pd.Series(last["value"].to_numpy(), index=pd.DatetimeIndex(last["obs_date"]), name=series_id)

    def last_obs(self, series_id: str) -> date | None:
        rows = self.series_rows(series_id)
        return None if rows.empty else pd.Timestamp(rows["obs_date"].max()).date()

    def series_state(self, series_id: str) -> Mapping[str, Any]:
        state: Mapping[str, Any] = self.manifest()["series"].get(series_id, {})
        return state

    def source_fingerprint(self, provider: str) -> str | None:
        fp: str | None = self.manifest()["sources"].get(provider)
        return fp

    # ------------------------------------------------------------------ diffing
    def diff(self, spec: SeriesSpec, frame: pd.DataFrame, today: date, real_vintages: bool = False,
             late_tolerance_days: int = 5, new_from_today: bool = False) -> SeriesDiff:
        """Compare a provider frame with the store. Pure: nothing is written.

        * real vintages (ALFRED): a row is new if its key is unknown or its value changed (archive fix);
        * lag-model vintages: unknown obs_date → new row at the lag vintage; a changed value for a known
          obs_date → revision row at ``max(today, lag vintage)``; same value → unchanged.
        * late arrivals: once a series has history in the store, a new observation that arrives more than
          ``late_tolerance_days`` after its lag vintage (a gap filled later, a delayed release, our own
          outage) is dated ``today`` – the store must not claim the pipeline knew it earlier. The initial
          load of a series keeps lag vintages: that is the history a backtest needs.
        * ``new_from_today``: the run re-bases this symbol's history (split, new adjustment basis; the
          ingest detects it). New rows are then dated no earlier than ``today`` like the revisions, so no
          view date mixes the old basis of the history with the new basis of the latest sessions (Fable
          review 2026-10-24: otherwise the view at the split date shows a fake −50 % return).
        """
        d = SeriesDiff(series_id=spec.series_id, fetched=len(frame))
        if frame.empty:
            return d
        f = frame.copy()
        f["obs_date"] = pd.to_datetime(f["obs_date"]).dt.normalize()
        f["vintage_date"] = pd.to_datetime(f["vintage_date"]).dt.normalize()
        if (f["vintage_date"] < f["obs_date"]).any():
            raise DataError(f"{spec.series_id}: provider returned vintage_date < obs_date")
        tol = spec.revision_tolerance
        rows = self.series_rows(spec.series_id)

        def changed(old: np.ndarray, new: np.ndarray) -> np.ndarray:
            scale = np.maximum(np.maximum(np.abs(old), np.abs(new)), 1e-12)
            return np.asarray(np.abs(new - old) > tol * scale, dtype=bool)

        if real_vintages:
            f = f.drop_duplicates(["obs_date", "vintage_date"], keep="last")
            m = f.merge(rows[["obs_date", "vintage_date", "value"]], on=["obs_date", "vintage_date"], how="left",
                        suffixes=("", "_old"))
            is_new = m["value_old"].isna().to_numpy()
            fix = ~is_new & changed(m["value_old"].to_numpy(dtype=float), m["value"].to_numpy(dtype=float))
            take = m[is_new | fix]
            d.new, d.revised, d.unchanged = int(is_new.sum()), int(fix.sum()), int(len(m) - is_new.sum() - fix.sum())
            out = take[["obs_date", "vintage_date", "value"]]
            if fix.any():
                r = m[fix]
                d.revisions = pd.DataFrame({"obs_date": r["obs_date"], "old": r["value_old"], "new": r["value"]})
        else:
            f = f.drop_duplicates("obs_date", keep="last")
            latest = self.latest_values(spec.series_id)
            old = latest.reindex(pd.DatetimeIndex(f["obs_date"])).to_numpy(dtype=float)
            new_vals = f["value"].to_numpy(dtype=float)
            is_new = np.isnan(old)
            rev = ~is_new & changed(np.nan_to_num(old), new_vals)
            today_ts = pd.Timestamp(today)
            today64 = np.datetime64(today_ts, "ns")
            vint = f["vintage_date"].to_numpy(dtype="datetime64[ns]").copy()
            vint[rev] = np.maximum(vint[rev], today64)
            if new_from_today:
                vint[is_new] = np.maximum(vint[is_new], today64)
            if not rows.empty:
                late = is_new & (today64 > vint + np.timedelta64(late_tolerance_days, "D"))
                vint[late] = today64
                d.late = int(late.sum())
            out = pd.DataFrame({"obs_date": f["obs_date"].to_numpy(), "vintage_date": vint, "value": new_vals})[is_new | rev]
            d.new, d.revised, d.unchanged = int(is_new.sum()), int(rev.sum()), int(len(f) - is_new.sum() - rev.sum())
            if rev.any():
                d.revisions = pd.DataFrame({"obs_date": f["obs_date"].to_numpy()[rev], "old": old[rev], "new": new_vals[rev]})
        if not d.revisions.empty:
            o = d.revisions["old"].to_numpy(dtype=float)
            n = d.revisions["new"].to_numpy(dtype=float)
            d.revisions["rel_change"] = (n - o) / np.where(o == 0, np.nan, np.abs(o))
        out = out.copy()
        out.insert(0, "series_id", spec.series_id)
        out["ingested_at"] = ""
        d.rows = out.loc[:, COLUMNS].reset_index(drop=True)
        return d

    # ------------------------------------------------------------------ writing
    def commit(self, rows: pd.DataFrame, ingested_at: str, series_state: Mapping[str, Mapping[str, Any]] | None = None,
               sources: Mapping[str, str] | None = None, kind: str = "delta") -> str | None:
        """Append one file with `rows` (may be empty: then only the manifest state is updated)."""
        m = self.manifest()
        name = None
        if len(rows):
            r = rows.copy()
            r["ingested_at"] = ingested_at
            bad = (pd.to_datetime(r["vintage_date"]) < pd.to_datetime(r["obs_date"])) | ~np.isfinite(r["value"].to_numpy(dtype=float))
            if bad.any():
                raise DataError(f"commit refused: {int(bad.sum())} rows with vintage < obs_date or non-finite value")
            raw = _encode(r)
            stamp = ingested_at.replace("-", "").replace(":", "")
            name = f"{kind}-{stamp}-{_sha(raw)[:8]}.csv.gz"
            if self.path is None:
                self._mem_files.append((name, raw))
            else:
                _atomic_write(self.obs_dir / name, raw)
            m["files"].append({"name": name, "rows": len(r), "sha256": _sha(raw), "ingested_at": ingested_at, "kind": kind})
        for sid, st in (series_state or {}).items():
            m["series"].setdefault(sid, {}).update(st)
        for prov, fp in (sources or {}).items():
            m["sources"][prov] = fp
        self._write_manifest(m)
        self._obs = None
        self._by_series = None
        return name

    def append_log(self, name: str, frame: pd.DataFrame) -> None:
        """quality_log / ingest_log: plain CSV, append-only."""
        if frame.empty:
            return
        if self.path is None:
            self._logs.setdefault(name, []).append(frame.copy())
            return
        p = self.path / f"{name}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            with open(p, encoding="utf-8") as fh:
                header = fh.readline().strip().split(",")
            if header != [str(c) for c in frame.columns]:  # a log gained columns: rewrite with the union
                merged = pd.concat([pd.read_csv(p), frame], ignore_index=True)
                merged.to_csv(p, index=False, lineterminator="\n")
                return
        frame.to_csv(p, mode="a", header=not p.exists(), index=False, lineterminator="\n")

    def read_log(self, name: str) -> pd.DataFrame:
        if self.path is None:
            parts = self._logs.get(name, [])
            return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        p = self.path / f"{name}.csv"
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    def quarantine(self, frame: pd.DataFrame, ingested_at: str) -> None:
        if frame.empty:
            return
        if self.path is None:
            self._logs.setdefault("quarantine", []).append(frame.copy())
            return
        p = self.path / "quarantine" / f"{ingested_at.replace(':', '')}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(p, mode="a", header=not p.exists(), index=False, lineterminator="\n")

    def write_series_table(self, specs: Iterable[SeriesSpec]) -> None:
        """Human/DuckDB-readable catalog snapshot with coverage."""
        if self.path is None:
            return
        obs = self.observations()
        cov: dict[str, dict[str, Any]] = {}
        if len(obs):
            agg = obs.groupby("series_id").agg(first_obs=("obs_date", "min"), last_obs=("obs_date", "max"),
                                               rows=("value", "size"), vintages=("vintage_date", "nunique"))
            cov = {str(k): {str(c): x for c, x in v.items()} for k, v in agg.to_dict("index").items()}
        recs = []
        for s in sorted(specs, key=lambda s: s.series_id):
            c = cov.get(s.series_id)
            recs.append({"series_id": s.series_id, "provider": s.provider, "provider_code": s.provider_code,
                         "kind": str(s.kind), "frequency": str(s.frequency), "lag": s.lag, "vintages": s.vintages,
                         "required": s.required, "unit": s.unit, "name": s.name,
                         "first_obs": None if c is None else pd.Timestamp(c["first_obs"]).date(),
                         "last_obs": None if c is None else pd.Timestamp(c["last_obs"]).date(),
                         "rows": 0 if c is None else int(c["rows"]), "vintage_dates": 0 if c is None else int(c["vintages"])})
        pd.DataFrame(recs).to_csv(self.path / "series.csv", index=False, lineterminator="\n")

    # ------------------------------------------------------------------ maintenance
    def verify(self) -> list[str]:
        """Integrity: every listed file exists with the recorded hash and row count, no unlisted files,
        no row with vintage < obs or non-finite value."""
        problems: list[str] = []
        m = self.manifest()
        listed = {f["name"] for f in m["files"]}
        for f in m["files"]:
            try:
                raw = self._read_file(f["name"])
            except (FileNotFoundError, KeyError):
                problems.append(f"missing file {f['name']}")
                continue
            if _sha(raw) != f["sha256"]:
                problems.append(f"checksum mismatch {f['name']}")
                continue
            df = _decode(raw)
            if len(df) != f["rows"]:
                problems.append(f"row count {len(df)} != {f['rows']} in {f['name']}")
            if (df["vintage_date"] < df["obs_date"]).any():
                problems.append(f"vintage before obs in {f['name']}")
            if not np.isfinite(df["value"].to_numpy(dtype=float)).all():
                problems.append(f"non-finite values in {f['name']}")
        if self.path is not None and self.obs_dir.exists():
            for p in self.obs_dir.glob("*.csv.gz"):
                if p.name not in listed:
                    problems.append(f"unlisted file {p.name} (interrupted write? remove or re-ingest)")
        return problems

    def compact(self, ingested_at: str | None = None) -> str | None:
        """Merge all files into one base file. Only superseded duplicate keys disappear."""
        obs = self.observations().copy()
        old = self.manifest()
        stamp = ingested_at or utc_stamp()
        new_manifest = {**old, "files": []}
        if obs.empty:
            self._write_manifest(new_manifest)
            return None
        raw = _encode(obs)
        name = f"base-{stamp.replace('-', '').replace(':', '')}-{_sha(raw)[:8]}.csv.gz"
        if self.path is None:
            self._mem_files = [(name, raw)]
        else:
            _atomic_write(self.obs_dir / name, raw)
        new_manifest["files"] = [{"name": name, "rows": len(obs), "sha256": _sha(raw),
                                  "ingested_at": str(obs["ingested_at"].max()), "kind": "base"}]
        new_manifest["compacted_at"] = stamp
        self._write_manifest(new_manifest)
        if self.path is not None:
            for f in old["files"]:
                if f["name"] != name:
                    (self.obs_dir / f["name"]).unlink(missing_ok=True)
        self._obs = None
        self._by_series = None
        return name
