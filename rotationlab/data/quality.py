"""Data quality checks (docs/ARCHITECTURE.md §3.3).

Two stages:

* ``schema`` runs on every provider frame *before* it reaches the store. Rows that violate the
  schema (future dates, negative prices, impossible returns, yields in the wrong unit) are rejected
  into quarantine and reported as ``blocking`` – bad rows never enter the append-only log.
  A row for the current, unfinished session is dropped silently (``ok``).
* the store checks run *after* the commit on what is now known: staleness of required series
  (``blocking``: no live decision on old prices), gaps against the NYSE calendar, outliers in the
  newly ingested days, silent revisions of stored prices (uniform rescaling such as a split is
  recognised and reported as ``ok``), Yahoo vs Stooq daily returns, total return vs price.

Every result is a row in ``quality_log.csv``. The ingest exits with code 3 if any result is blocking.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

import numpy as np
import pandas as pd

from rotationlab.config.models import QualityConfig
from rotationlab.core.protocols import TradingCalendar
from rotationlab.core.types import Frequency, SeriesKind, SeriesSpec
from rotationlab.data.calendar import CALENDAR_VALID_FROM
from rotationlab.data.lags import Lag

POSITIVE_KINDS = (SeriesKind.PRICE, SeriesKind.TOTAL_RETURN, SeriesKind.INDEX)
LIVE_PROVIDERS = ("yahoo", "stooq", "fred", "cftc", "french")


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class QualityResult:
    check: str
    series_id: str | None
    status: Status
    detail: str = ""

    def row(self, ingested_at: str) -> dict[str, str]:
        return {"ingested_at": ingested_at, "series_id": self.series_id or "", "check": self.check,
                "status": str(self.status), "detail": self.detail}


def to_frame(results: Iterable[QualityResult], ingested_at: str) -> pd.DataFrame:
    return pd.DataFrame([r.row(ingested_at) for r in results],
                        columns=["ingested_at", "series_id", "check", "status", "detail"])


def worst(results: Iterable[QualityResult]) -> Status:
    order = {Status.OK: 0, Status.WARN: 1, Status.BLOCKING: 2}
    return max((r.status for r in results), key=order.__getitem__, default=Status.OK)


# ---------------------------------------------------------------------------
# Stage 1: schema (before the store)
# ---------------------------------------------------------------------------
def schema(spec: SeriesSpec, frame: pd.DataFrame, ingest_date: date) -> tuple[pd.DataFrame, pd.DataFrame, list[QualityResult]]:
    """Split a provider frame into (accepted, rejected-with-reason, results)."""
    if frame.empty:
        return frame, frame.assign(reason=pd.Series(dtype=str)), []
    f = frame.reset_index(drop=True)
    reason = pd.Series("", index=f.index, dtype=object)
    values = f["value"].to_numpy(dtype=float)
    obs = pd.to_datetime(f["obs_date"])
    vint = pd.to_datetime(f["vintage_date"])
    today = pd.Timestamp(ingest_date)

    def mark(mask: np.ndarray | pd.Series, why: str) -> None:
        m = np.asarray(mask) & (reason.to_numpy() == "")
        reason[m] = why

    mark(~np.isfinite(values), "non-finite value")
    mark(obs > today, "obs_date in the future")
    mark(vint < obs, "vintage_date before obs_date")
    if spec.kind in POSITIVE_KINDS:
        mark(values <= 0, f"non-positive {spec.kind}")
    if spec.kind == SeriesKind.DIVIDEND:
        mark(values < 0, "negative dividend")
    if spec.kind == SeriesKind.SPLIT:
        mark(values <= 0, "non-positive split factor")
    if spec.kind == SeriesKind.RETURN:
        mark(values <= -1.0, "return at or below -100 %")
        mark(values > 5.0, "return above +500 % (unit error?)")
    if spec.kind == SeriesKind.YIELD:
        mark((values < -10) | (values > 100), "yield outside [-10, 100] percent (unit error?)")

    # an unfinished session: daily market data stamped with the ingest date itself
    partial = (spec.frequency == Frequency.DAILY) & (obs == today) & (reason.to_numpy() == "")
    results: list[QualityResult] = []
    if partial.any():
        results.append(QualityResult("schema", spec.series_id, Status.OK, f"dropped {int(partial.sum())} row(s) of the unfinished session {ingest_date}"))
    bad = reason.to_numpy() != ""
    rejected = f[bad].assign(reason=reason[bad].to_numpy(), series_id=spec.series_id)
    accepted = f[~bad & ~np.asarray(partial)].reset_index(drop=True)
    if bad.any():
        kinds = rejected["reason"].value_counts().to_dict()
        results.append(QualityResult("schema", spec.series_id, Status.BLOCKING,
                                     f"rejected {int(bad.sum())} row(s) into quarantine: {kinds}"))
    return accepted, rejected, results


# ---------------------------------------------------------------------------
# Stage 2: on the store
# ---------------------------------------------------------------------------
def staleness(spec: SeriesSpec, last_obs: date | None, run_date: date, cal: TradingCalendar,
              cfg: QualityConfig) -> QualityResult | None:
    """Is the newest observation older than the provider's rhythm allows?"""
    if spec.provider not in LIVE_PROVIDERS:
        return None
    status_bad = Status.BLOCKING if spec.required else Status.WARN
    if last_obs is None:
        return QualityResult("staleness", spec.series_id, status_bad, "no observations at all")
    if spec.frequency == Frequency.DAILY:
        expected = cal.previous_trading_day(run_date)  # last completed session
        behind = len(cal.trading_days(last_obs + timedelta(days=1), expected)) if last_obs < expected else 0
        if behind > cfg.stale_trading_days:
            return QualityResult("staleness", spec.series_id, status_bad,
                                 f"last obs {last_obs}, {behind} sessions behind {expected}")
        return QualityResult("staleness", spec.series_id, Status.OK, f"last obs {last_obs}")
    period_days = {Frequency.WEEKLY: 7, Frequency.MONTHLY: 31, Frequency.QUARTERLY: 92}[Frequency(spec.frequency)]
    allowed = Lag.parse(spec.lag).max_days() + cfg.stale_periods * period_days
    age = (run_date - last_obs).days
    if age > allowed:
        return QualityResult("staleness", spec.series_id, status_bad, f"last obs {last_obs} is {age} days old (allowed {allowed})")
    return QualityResult("staleness", spec.series_id, Status.OK, f"last obs {last_obs}")


def gaps(spec: SeriesSpec, s: pd.Series, cal: TradingCalendar, cfg: QualityConfig,
         window_days: int | None = 730) -> QualityResult | None:
    """Daily series against the NYSE calendar: missing sessions and values on non-sessions."""
    if spec.frequency != Frequency.DAILY or s.empty or spec.kind in (SeriesKind.DIVIDEND, SeriesKind.SPLIT):
        return None
    end = s.index.max().date()
    start = s.index.min().date() if window_days is None else max(s.index.min().date(), end - timedelta(days=window_days))
    start = max(start, CALENDAR_VALID_FROM)  # the NYSE rules are exact from 1971 on
    if start > end:
        return None
    have = {d.date() for d in s.index if d.date() >= start}
    sessions = set(cal.trading_days(start, end))
    missing = sorted(sessions - have)
    extra = sorted(have - sessions)
    detail = f"{len(missing)} missing session(s) since {start}" + (f" (e.g. {', '.join(map(str, missing[:5]))})" if missing else "")
    if extra:
        detail += f"; {len(extra)} value(s) on non-sessions (e.g. {', '.join(map(str, extra[:3]))})"
    status = Status.WARN if len(missing) > cfg.gap_warn_days else Status.OK
    return QualityResult("gaps", spec.series_id, status, detail)


def outliers(spec: SeriesSpec, s: pd.Series, since: date, cfg: QualityConfig) -> QualityResult | None:
    """Daily log returns of observations dated on/after `since` beyond k sigma of the trailing window."""
    if spec.frequency != Frequency.DAILY or spec.kind not in POSITIVE_KINDS or len(s) < cfg.outlier_window // 2:
        return None
    lr = np.log(s).diff()
    sigma = lr.rolling(cfg.outlier_window, min_periods=cfg.outlier_window // 2).std().shift(1)
    z = (lr / sigma).abs()
    recent = z[z.index >= pd.Timestamp(since)]
    hits = recent[recent > cfg.outlier_sigma]
    if hits.empty:
        return QualityResult("outliers", spec.series_id, Status.OK, f"none beyond {cfg.outlier_sigma} sigma since {since}")
    lst = ", ".join(f"{d.date()} ({lr.loc[d]:+.1%}, {z.loc[d]:.0f} sigma)" for d in hits.index[:5])
    return QualityResult("outliers", spec.series_id, Status.WARN, f"{len(hits)} return(s) beyond {cfg.outlier_sigma} sigma: {lst} – check, both kept")


def uniform_ratio(rev: pd.DataFrame | None) -> float | None:
    """The common factor if every revised value changed by the same ratio (split, new adjustment basis)."""
    if rev is None or len(rev) < 5:
        return None
    ratio = rev["new"].to_numpy(dtype=float) / rev["old"].to_numpy(dtype=float)
    mean = float(np.nanmean(ratio))
    if abs(mean - 1.0) > 1e-3 and np.nanstd(ratio) / abs(mean) < 1e-4:
        return mean
    return None


def revision_cluster(spec: SeriesSpec, ingest_log: pd.DataFrame, run_date: date, cfg: QualityConfig) -> QualityResult | None:
    """Many small revisions of stored prices within a few days: each is below the warning threshold, together
    they say the provider is unstable (re-adjusting closes, flapping between sources)."""
    if spec.kind not in POSITIVE_KINDS or ingest_log.empty or "revised" not in ingest_log.columns:
        return None
    log = ingest_log[ingest_log["series_id"] == spec.series_id]
    if log.empty:
        return None
    since = pd.Timestamp(run_date - timedelta(days=cfg.revision_cluster_days))
    recent = log[pd.to_datetime(log["run_date"]) > since]
    if "rebased" in recent.columns:
        recent = recent[~recent["rebased"].astype(str).str.lower().isin(["true", "1"])]
    n = int(pd.to_numeric(recent["revised"], errors="coerce").fillna(0).sum())
    if n >= cfg.revision_cluster_min:
        return QualityResult("revision_cluster", spec.series_id, Status.WARN,
                             f"{n} revisions of stored values in the last {cfg.revision_cluster_days} days "
                             f"({len(recent)} runs, splits excluded): provider unstable?")
    return None


def revisions(spec: SeriesSpec, rev: pd.DataFrame | None, cfg: QualityConfig) -> QualityResult | None:
    """Changes to already stored values. A uniform rescaling of the history is a split/adjustment."""
    if rev is None or rev.empty:
        return None
    rel = rev["rel_change"].to_numpy(dtype=float)
    if spec.kind not in POSITIVE_KINDS:
        big = np.abs(rel) > cfg.revision_warn
        status = Status.OK  # statistics are revised by design; ALFRED keeps both
        return QualityResult("revision", spec.series_id, status,
                             f"{len(rev)} revised value(s), {int(big.sum())} by more than {cfg.revision_warn:.1%}")
    factor = uniform_ratio(rev)
    if factor is not None:
        return QualityResult("revision", spec.series_id, Status.OK,
                             f"history rescaled uniformly by {factor:.6g} over {len(rev)} obs "
                             f"({rev['obs_date'].min():%Y-%m-%d} – {rev['obs_date'].max():%Y-%m-%d}): split or adjustment, both vintages kept")
    big = np.abs(rel) > cfg.revision_warn
    if not big.any():
        return QualityResult("revision", spec.series_id, Status.OK, f"{len(rev)} small revision(s) below {cfg.revision_warn:.1%}")
    rows = rev[big].head(5)
    lst = ", ".join(f"{r.obs_date:%Y-%m-%d} {r.old:.6g}→{r.new:.6g}" for r in rows.itertuples())
    return QualityResult("revision", spec.series_id, Status.WARN,
                         f"{int(big.sum())} silent revision(s) above {cfg.revision_warn:.1%}: {lst}; both vintages kept")


def cross_source(primary_id: str, s1: pd.Series, s2: pd.Series, cfg: QualityConfig, last_n: int = 20) -> QualityResult | None:
    """Daily returns of two sources for the same instrument should agree."""
    common = s1.index.intersection(s2.index)
    if len(common) < 3:
        return None
    common = common[-(last_n + 1):]
    r1 = s1.reindex(common).pct_change().dropna()
    r2 = s2.reindex(common).pct_change().dropna()
    diff = (r1 - r2).abs()
    worst_day = pd.Timestamp(diff.index[int(np.argmax(diff.to_numpy()))])
    if diff.max() > cfg.cross_source_warn:
        return QualityResult("cross_source", primary_id, Status.WARN,
                             f"returns differ by {diff.max():.2%} on {worst_day.date()} vs {s2.name} (last {len(diff)} common days)")
    return QualityResult("cross_source", primary_id, Status.OK, f"max return difference {diff.max():.3%} vs {s2.name}")


def total_return_vs_price(tr_id: str, tr: pd.Series, px: pd.Series, recent_since: date,
                          tol: float = 1e-4) -> QualityResult | None:
    """A total-return index can never return less than its price index on the same day.

    Violations among recently ingested days block (a broken feed); violations in old history are a
    property of the frozen source (the S&P reconstruction before 1990 has 110 such days, all below
    0.3 %) and are reported as a warning.
    """
    common = tr.index.intersection(px.index)
    if len(common) < 3:
        return None
    rt = tr.reindex(common).pct_change().dropna()
    rp = px.reindex(common).pct_change().dropna()
    bad = rt < rp - tol
    recent = bad & (rt.index >= pd.Timestamp(recent_since))
    if recent.any():
        days = ", ".join(str(d.date()) for d in rt.index[recent][:5])
        return QualityResult("tr_vs_price", tr_id, Status.BLOCKING,
                             f"{int(recent.sum())} recent day(s) with TR return below price return: {days}")
    if bad.any():
        worst_gap = float((rt - rp)[bad].min())
        return QualityResult("tr_vs_price", tr_id, Status.WARN,
                             f"{int(bad.sum())} historical day(s) with TR return below price return "
                             f"(largest {worst_gap:.2%}, last {rt.index[bad][-1].date()}); none recent")
    return QualityResult("tr_vs_price", tr_id, Status.OK, f"TR ≥ price return on {len(rt)} days")


def chains(universe_roles: dict[str, dict[str, list[str]]]) -> Sequence[tuple[str, str]]:
    """(primary, fallback) pairs of daily price chains, for the cross-source check."""
    pairs: list[tuple[str, str]] = []
    for roles in universe_roles.values():
        c = roles.get("close", [])
        if len(c) >= 2:
            pairs.append((c[0], c[1]))
    return pairs
