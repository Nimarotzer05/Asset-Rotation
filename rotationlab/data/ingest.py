"""Ingest: providers → schema check → diff against the store → one delta file → quality checks.

One run writes at most one observation file, so a run is atomic from the store's point of view:
either its delta is listed in the manifest or it does not exist. Provider failures never abort the
run; they are logged, and the staleness check afterwards decides whether the missing data blocks
live decisions (exit code 3 via `IngestReport.blocking`).

Incremental windows (``since``): market data refetches ``refetch_buffer_days`` before the last
stored observation (so late corrections are seen); ALFRED series refetch real-time periods that
started since the last fetch minus 7 days; providers with ``refetch_buffer_days <= 0`` deliver whole
files (French) or are gated by a fingerprint of their inputs (static).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from rotationlab.config.models import Bundle, ProviderConfig
from rotationlab.core.protocols import TradingCalendar
from rotationlab.core.types import Frequency, SeriesSpec
from rotationlab.data import quality as q
from rotationlab.data.providers.base import BaseProvider
from rotationlab.data.store import PointInTimeStore, empty_observations, utc_stamp
from rotationlab.data.view import asset_roles

log = logging.getLogger("rotationlab.ingest")

ALFRED_REFETCH_DAYS = 7
OUTLIER_LOOKBACK_DAYS = 30
GAP_STATIC = ("static:usmkt:TR", "static:usmkt:CLOSE", "static:cboe:VIX")
TR_PRICE_PAIRS = (("static:usmkt:TR", "static:usmkt:CLOSE"),)


@dataclass
class IngestReport:
    ingested_at: str
    run_date: date
    file: str | None = None
    series: list[dict[str, object]] = field(default_factory=list)
    quality: list[q.QualityResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[q.QualityResult]:
        return [r for r in self.quality if r.status == q.Status.BLOCKING]

    @property
    def warnings(self) -> list[q.QualityResult]:
        return [r for r in self.quality if r.status == q.Status.WARN]

    def totals(self) -> dict[str, int]:
        df = pd.DataFrame(self.series)
        if df.empty:
            return {"series": 0, "fetched": 0, "new": 0, "revised": 0, "rejected": 0, "errors": 0}
        return {"series": len(df), "fetched": int(df["fetched"].sum()), "new": int(df["new"].sum()),
                "revised": int(df["revised"].sum()), "rejected": int(df["rejected"].sum()),
                "errors": int((df["error"] != "").sum())}

    def summary(self) -> str:
        t = self.totals()
        return (f"ingest {self.ingested_at}: {t['series']} series, {t['fetched']} rows fetched, {t['new']} new, "
                f"{t['revised']} revised, {t['rejected']} rejected, {t['errors']} fetch errors; "
                f"quality: {len(self.blocking)} blocking, {len(self.warnings)} warnings"
                + (f"; skipped: {', '.join(self.skipped)}" if self.skipped else ""))


def _since(spec: SeriesSpec, store: PointInTimeStore, pc: ProviderConfig, full: bool) -> date | None:
    if full or pc.refetch_buffer_days <= 0:
        return None
    if spec.vintages == "alfred":
        last_fetch = store.series_state(spec.series_id).get("last_fetch")
        if not last_fetch or store.last_obs(spec.series_id) is None:
            return None
        return date.fromisoformat(str(last_fetch)) - timedelta(days=ALFRED_REFETCH_DAYS)
    last = store.last_obs(spec.series_id)
    return None if last is None else last - timedelta(days=pc.refetch_buffer_days)


def _symbol(spec: SeriesSpec) -> str:
    return spec.series_id.rsplit(":", 1)[0] if spec.series_id.count(":") >= 2 else spec.series_id


def _series_order(spec: SeriesSpec) -> tuple[str, int, str]:
    """Prices first within a symbol, so a detected re-basing widens the refetch of its dividends too."""
    return (_symbol(spec), 0 if spec.kind.is_level else 1, spec.series_id)


def _is_rebase(d: object) -> bool:
    rev = getattr(d, "revisions", None)
    if rev is None or len(rev) < 3 or getattr(d, "unchanged", 0) > 0:
        return False
    ratio = (rev["new"] / rev["old"]).to_numpy(dtype=float)
    return bool(abs(ratio.mean() - 1.0) > 1e-3 and ratio.std() / abs(ratio.mean()) < 1e-4)


def run_ingest(store: PointInTimeStore, bundle: Bundle, catalog: Mapping[str, SeriesSpec],
               providers: Mapping[str, BaseProvider], calendar: TradingCalendar, run_date: date,
               full: bool = False, only_providers: Sequence[str] | None = None,
               only_series: Sequence[str] | None = None, clock: Callable[[], float] = time.monotonic) -> IngestReport:
    stamp = utc_stamp()
    rep = IngestReport(ingested_at=stamp, run_date=run_date)
    qcfg = bundle.system.quality
    commit_rows: list[pd.DataFrame] = []
    state: dict[str, dict[str, str]] = {}
    sources: dict[str, str] = {}
    revisions: dict[str, pd.DataFrame] = {}
    touched: list[SeriesSpec] = []
    noted_providers: set[str] = set()

    for pname, prov in providers.items():
        if only_providers and pname not in only_providers:
            continue
        specs = [s for s in catalog.values() if s.provider == pname and (not only_series or s.series_id in only_series)]
        if not specs:
            continue
        if pname == "static":
            fp = prov.fingerprint()  # type: ignore[attr-defined]
            if not full and store.source_fingerprint("static") == fp:
                rep.skipped.append("static (raw files unchanged)")
                continue
            sources["static"] = fp
        pc = bundle.system.providers.get(pname, ProviderConfig())
        rebased: set[str] = set()          # symbols whose history was re-based in this run → full refetch
        for spec in sorted(specs, key=_series_order):
            t0 = clock()
            since = None if _symbol(spec) in rebased else _since(spec, store, pc, full)
            stat: dict[str, object] = {"ingested_at": stamp, "run_date": run_date.isoformat(), "series_id": spec.series_id,
                                       "provider": pname, "since": "" if since is None else since.isoformat(),
                                       "fetched": 0, "new": 0, "revised": 0, "unchanged": 0, "rejected": 0, "late": 0, "rebased": False, "error": "",
                                       "seconds": 0.0}
            try:
                frame = prov.fetch_frame(spec, since)
            except Exception as e:  # provider failure: log, continue; staleness decides later
                stat["error"] = f"{type(e).__name__}: {e}"[:300]
                stat["seconds"] = round(clock() - t0, 3)
                rep.series.append(stat)
                rep.quality.append(q.QualityResult("fetch", spec.series_id, q.Status.WARN, str(stat["error"])))
                log.warning("fetch failed %s: %s", spec.series_id, stat["error"])
                continue
            note = frame.attrs.get("note")
            if note and pname not in noted_providers:
                rep.quality.append(q.QualityResult("provider", None, q.Status.WARN, f"{pname}: {note}"))
                noted_providers.add(pname)
            for k in ("backfilled", "clamped"):
                if frame.attrs.get(k):
                    rep.quality.append(q.QualityResult(f"alfred_{k}", spec.series_id, q.Status.OK,
                                                       f"{frame.attrs[k]} observation(s) {k} (see providers/fred.py)"))
            accepted, rejected, res = q.schema(spec, frame, run_date)
            real = bool(frame.attrs.get("real_vintages", False))
            symbol_rebased = _symbol(spec) in rebased
            d = store.diff(spec, accepted, run_date, real_vintages=real, late_tolerance_days=pc.late_tolerance_days,
                           new_from_today=symbol_rebased)
            if not symbol_rebased and spec.kind.is_level and _is_rebase(d):
                # the provider re-based the history (split, new adjustment basis): a window refetch would
                # leave a fake jump at its start, so take the full history of this symbol; and every row of
                # the symbol learned in this run is dated today, so no view mixes the two bases
                rebased.add(_symbol(spec))
                if since is not None:
                    frame = prov.fetch_frame(spec, None)
                    accepted, rejected, res = q.schema(spec, frame, run_date)
                d = store.diff(spec, accepted, run_date, real_vintages=real, late_tolerance_days=pc.late_tolerance_days,
                               new_from_today=True)
                rep.quality.append(q.QualityResult("rebase", spec.series_id, q.Status.OK,
                                                   "uniform rescaling of the stored history: full history refetched, "
                                                   "new rows of the symbol dated today"))
            rep.quality.extend(res)
            if len(rejected):
                store.quarantine(rejected.assign(ingested_at=stamp), stamp)
            commit_rows.append(d.rows)
            if not d.revisions.empty:
                revisions[spec.series_id] = d.revisions
            stat.update(fetched=d.fetched, new=d.new, revised=d.revised, unchanged=d.unchanged, rejected=len(rejected),
                        late=d.late, rebased=q.uniform_ratio(d.revisions) is not None, seconds=round(clock() - t0, 3))
            if d.late:
                rep.quality.append(q.QualityResult("late_arrival", spec.series_id, q.Status.WARN,
                                                   f"{d.late} observation(s) arrived after lag + {pc.late_tolerance_days} days: "
                                                   f"dated {run_date} (when the pipeline learned them)"))
            rep.series.append(stat)
            state[spec.series_id] = {"last_fetch": run_date.isoformat(), "last_ingest": stamp}
            touched.append(spec)

    rows = pd.concat(commit_rows, ignore_index=True) if commit_rows else empty_observations()
    rep.file = store.commit(rows, stamp, series_state=state, sources=sources,
                            kind="base" if full and not len(store.manifest()["files"]) else "delta")

    # ---- checks on what is now known --------------------------------------------------
    for spec in touched:
        rq = q.revisions(spec, revisions.get(spec.series_id), qcfg)
        if rq:
            rep.quality.append(rq)
    in_scope = [s for s in catalog.values()
                if (not only_providers or s.provider in only_providers) and s.provider in providers
                and (not only_series or s.series_id in only_series)]
    for spec in in_scope:
        r = q.staleness(spec, store.last_obs(spec.series_id), run_date, calendar, qcfg)
        if r and r.status != q.Status.OK:
            rep.quality.append(r)
    since_out = run_date - timedelta(days=OUTLIER_LOOKBACK_DAYS)
    for spec in touched:
        if spec.frequency != Frequency.DAILY:
            continue
        s = store.latest_values(spec.series_id)
        r = q.outliers(spec, s, since_out, qcfg)
        if r and r.status != q.Status.OK:
            rep.quality.append(r)
        gap_live = spec.provider in ("yahoo", "stooq") and spec.asset_id is not None
        if gap_live or spec.series_id in GAP_STATIC:
            r = q.gaps(spec, s, calendar, qcfg, window_days=730 if gap_live else None)
            if r:
                rep.quality.append(r)
    touched_ids = {s.series_id for s in touched}
    for a, b in q.chains(asset_roles(bundle.universe)):
        if a in touched_ids or b in touched_ids:
            s1, s2 = store.latest_values(a), store.latest_values(b).rename(b)
            if len(s1) and len(s2):
                r = q.cross_source(a, s1, s2, qcfg)
                if r:
                    rep.quality.append(r)
    for tr_id, px_id in TR_PRICE_PAIRS:
        if tr_id in touched_ids:
            r = q.total_return_vs_price(tr_id, store.latest_values(tr_id), store.latest_values(px_id), since_out)
            if r:
                rep.quality.append(r)

    history = pd.concat([store.read_log("ingest_log"), pd.DataFrame(rep.series)], ignore_index=True)
    for spec in touched:
        r = q.revision_cluster(spec, history, run_date, qcfg)
        if r:
            rep.quality.append(r)
    store.append_log("quality_log", q.to_frame(rep.quality, stamp))
    store.append_log("ingest_log", pd.DataFrame(rep.series))
    store.write_series_table(catalog.values())
    log.info(rep.summary())
    return rep
