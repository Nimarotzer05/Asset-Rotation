"""The live run (ADR 043, step P6): forecast at each month-end, settle what has matured, write the report.

    run(bundle, factory, journal, run_date, universe)
        D = the last calendar month-end before run_date
        if the store holds every class's prices through the last session ≤ D (else: wait, no forecast)
            append the forecasts at D (every horizon) to the journal – a no-op if they are already there
        settle every journal forecast whose outcome window has closed and whose data is complete
        render reports/forecast/<YYYY-MM>.md and latest.md

The forecast is computed from the view at D (nothing after D is visible); outcomes from the view at the
run date. Both go through the same `ForecastModel`, so the live forecast is the backtested one with the
clock set to today (principle 1). Every step is idempotent: the daily workflow calls `run` every day.

Late data (second review 2026-10-26): a price that reached the store more than a few days after its
session is dated by its arrival (`store.diff`), so the view at D never contains it and the month's forecast
would never be written. Then – and only then – the forecast is made from the view with observations
through D and vintages through the run date (`factory.at(D, knowledge=run_date)`); the forecast carries a
note naming the late classes, and its `created_at` shows the delay. Revisions of past prices between D and
the run date are the only way such a forecast can differ from an on-time one (price history is re-based
only by adjustments, which leave returns before D unchanged).

Settlement waits for the data of every class in the forecast: ranked classes through the end of the
horizon, trend-only classes valued at monthly averages one month longer (decision 5). Nothing is settled
with a missing level, and the outcome carries the forecast's own probability target.

Paper weights (ADR 048): the 1-month forecast carries the target weights of the pre-registered rule
(`forecast_portfolio`: top two of the forecast's ranking, trend filter, 10 % vol target, no leverage) on
the forecast's own universe – a derived output, never an input. The outcome records the month-end to
month-end return of those weights (remainder in cash), of equal weight and of cash, before costs; the
historical verdict with honest timing and costs is `output/forecast/PORTFOLIO.md`.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.config.models import Bundle
from rotationlab.core.protocols import MarketView, TradingCalendar
from rotationlab.core.types import AssetId, Cadence, Frequency, Months, Role, StrategyId, StrategySpec
from rotationlab.data.view import StoreViewFactory
from rotationlab.engine.modes import averaged_assets
from rotationlab.forecast.evaluation import spearman_rows
from rotationlab.forecast.journal import ForecastJournal, Outcome, forecast_key
from rotationlab.forecast.model import BlockBootstrap, ForecastModel, complete_months, hit_matrix, relative
from rotationlab.forecast.report import render_latest, render_month
from rotationlab.forecast.types import Forecast
from rotationlab.strategies.forecast_portfolio import ForecastPortfolio

log = logging.getLogger(__name__)


def decision_date_for(run_date: date) -> date:
    """The last calendar month-end strictly before the run date (that month's closes are complete)."""
    return (pd.Timestamp(run_date) - pd.offsets.MonthEnd(1)).date()


def month_end_after(d: date, months: int) -> date:
    return (pd.Timestamp(d) + pd.offsets.MonthEnd(months)).date()


def price_series(view: MarketView, asset: str) -> list[str]:
    """The series whose presence says the asset is priced: its total-return / return / close / yield chain."""
    roles = view.roles(asset)  # type: ignore[attr-defined]
    for role in ("total_return", "return", "close", "yield"):
        chain = roles.get(role)
        if chain:
            return list(chain)
    return []


def data_complete(view: MarketView, assets: Sequence[str], cal: TradingCalendar, through: date) -> list[str]:
    """Assets whose price history (as of the view) does not reach the last session on or before `through`;
    empty = complete. Monthly series count as complete when their last month is the month of `through`."""
    missing = []
    need = through if cal.is_trading_day(through) else cal.previous_trading_day(through)
    for a in assets:
        chain = price_series(view, a)
        last: date | None = None
        for sid in chain:
            lo = view.last_obs(sid)
            if lo is not None and (last is None or lo > last):
                last = lo
        if last is None:
            missing.append(a)
            continue
        monthly = all(view.spec(sid).frequency == Frequency.MONTHLY for sid in chain)  # type: ignore[attr-defined]
        ok = (
            (pd.Timestamp(last).to_period("M") >= pd.Timestamp(through).to_period("M"))
            if monthly
            else last >= need
        )
        if not ok:
            missing.append(a)
    return missing


@dataclass(frozen=True)
class RunReport:
    run_date: date
    decision_date: date
    forecasts_written: int
    outcomes_written: int
    skipped: str | None  # why no forecast was written (data not complete), else None
    report_path: Path | None
    late: str | None = None  # the forecast was made from late data (see module docstring), else None


def class_windows(f: Forecast) -> dict[str, tuple[date, date]]:
    """The return window of every class of the forecast: ranked classes from D to the end of the horizon;
    trend-only classes valued at monthly averages (the forecast's `params.averaged`) one month later each,
    the first average that lies wholly after the decision (decision 5)."""
    end = month_end_after(f.decision_date, f.horizon_months)
    averaged = set(f.params.get("averaged", ()))
    out = {}
    for c in f.classes:
        if not c.ranked and c.asset in averaged:
            out[c.asset] = (month_end_after(f.decision_date, 1), month_end_after(end, 1))
        else:
            out[c.asset] = (f.decision_date, end)
    return out


def paper_rule(bundle: Bundle, model: ForecastModel) -> ForecastPortfolio | None:
    """The pre-registered rule (`paper_rule` strategy of the forecast config) on the forecast's universe – its
    ranked classes and cash – and on the forecast's *own* score (feature weights, params and clip of the model,
    also for a variant), so the weights follow exactly the ranking the forecast publishes (second review of P8)."""
    sid = model.cfg.paper_rule
    cfg = bundle.strategies.get(sid) if sid else None
    if cfg is None or sid is None:
        return None
    spec = StrategySpec(
        strategy_id=StrategyId(sid),
        version=cfg.version,
        role=Role.PAPER,
        cadence=Cadence.MONTHLY,
        universe=tuple(AssetId(a) for a in [*model.ranked, model.cash]),
        warmup=Months(cfg.warmup_months),
        params={
            **cfg.params,
            "feature_weights": dict(model.weights),
            "zscore_clip": model.clip,
            "feature_params": model.feature_params,
            "cash": model.cash,
        },
    )
    return ForecastPortfolio(spec, cfg.confidence.model_dump(), cfg.stops)


def paper_weights(
    rule: ForecastPortfolio | None, view: MarketView, forecast: Forecast | None = None
) -> dict[str, float] | None:
    """Target weights of the rule at the view date; None while the rule is in warm-up. With `forecast`, the
    weights are checked against its ranking: a sleeve outside the published top `top_n` is a contradiction
    and raises rather than being journaled."""
    if rule is None:
        return None
    p, _ = rule.propose(view, rule.initial_state())
    if p.warmup:
        return None
    w = {str(a): float(x) for a, x in p.weights.items()}
    if forecast is not None:
        top = set(forecast.ranking()[: rule.n])
        if not set(w) <= top:
            raise RuntimeError(
                f"paper rule at {view.date}: weights on {sorted(w)} but the forecast ranks {sorted(top)} first"
            )
    return w


def paper_returns(
    f: Forecast, ret: pd.Series, ranked: Sequence[str], cash_ret: float | None
) -> tuple[float | None, float | None]:
    """(return of the forecast's weights with the remainder in cash, equal-weight return) over the window;
    the equal-weight return needs no cash, the portfolio return does."""
    if ret[list(ranked)].isna().any():
        return None, None
    ew = float(sum(float(ret[a]) for a in ranked) / len(ranked))
    if f.weights is None or cash_ret is None:
        return None, ew
    invested = sum(float(w) for w in f.weights.values())
    port = sum(float(w) * float(ret[a]) for a, w in f.weights.items() if a in ret.index)
    return float(port + (1.0 - invested) * cash_ret), ew


def _level_return(
    view: MarketView, asset: str, cal: TradingCalendar, start: date, through: date
) -> float | None:
    """Total return of `asset` from `start` to `through` on month-end levels, None while a level is missing."""
    if view.date <= through or data_complete(view, [asset], cal, through):
        return None
    lv = complete_months(view, view.total_return([asset], "ME"))
    d0, d1 = pd.Timestamp(start), pd.Timestamp(through)
    if asset not in lv.columns or d0 not in lv.index or d1 not in lv.index:
        return None
    l0, l1 = float(lv.at[d0, asset]), float(lv.at[d1, asset])  # type: ignore[arg-type]
    if math.isnan(l0) or math.isnan(l1):
        return None
    return l1 / l0 - 1.0


def settle(f: Forecast, view: MarketView, cal: TradingCalendar) -> Outcome | None:
    """The outcome of `f` from the view at the run date, or None while any class's window has not closed or
    its data through the window's end is not in the store yet."""
    end = month_end_after(f.decision_date, f.horizon_months)
    if view.date <= end:
        return None
    ranked = [c.asset for c in f.classes if c.ranked]
    trend_only = [c.asset for c in f.classes if not c.ranked]
    windows = class_windows(f)
    for a, (_, through) in windows.items():
        if view.date <= through or data_complete(view, [a], cal, through):
            return None
    levels = complete_months(view, view.total_return([*ranked, *trend_only], "ME"))
    ret = pd.Series(np.nan, index=[*ranked, *trend_only], dtype=float)
    for a, (start, through) in windows.items():
        d0, d1 = pd.Timestamp(start), pd.Timestamp(through)
        if a not in levels.columns or d0 not in levels.index or d1 not in levels.index:
            return None
        lv0, lv1 = float(levels.at[d0, a]), float(levels.at[d1, a])  # type: ignore[arg-type]
        if math.isnan(lv0) or math.isnan(lv1):
            return None  # the level at the window's edge is not in the store yet (second review, finding 2)
        ret[a] = lv1 / lv0 - 1.0
    rel_row = relative(ret[ranked].to_frame().T)
    rel = rel_row.iloc[0]
    realised_rank = rel.rank(ascending=False, method="first").astype(int)
    target = str(dict(f.params.get("probability", {})).get("target", "top_half"))
    hits = hit_matrix(rel_row, target).iloc[0]
    by = f.by_asset()
    scores = pd.Series({a: by[a].score for a in ranked}, dtype=float)
    probs = pd.Series({a: by[a].probability for a in ranked}, dtype=float)
    ic = spearman_rows(scores.to_frame().T, rel_row).iloc[0] if scores.notna().all() else math.nan
    ranks = pd.Series({a: by[a].rank for a in ranked}, dtype=float)
    tbb: float | None = None
    if ranks.notna().all():
        top, bottom = str(ranks.idxmin()), str(ranks.idxmax())
        tbb = float(rel[top] > rel[bottom])
    brier = float(((probs - hits) ** 2).mean()) if probs.notna().all() else None
    brier_const = float(((0.5 - hits) ** 2).mean())
    # previous-month-rank baseline: the realised return of the month that ended at D, as a score
    prev_ic: float | None = None
    d0 = pd.Timestamp(f.decision_date)
    before = levels.index[levels.index < d0]
    if len(before):
        prev_ret = levels.loc[d0, ranked] / levels.loc[before[-1], ranked] - 1
        if prev_ret.notna().all():
            prev_ic = float(spearman_rows(prev_ret.to_frame().T, rel_row).iloc[0])
    trend_hit = {
        a: float((ret[a] > 0) == (by[a].trend == "up")) for a in trend_only if by[a].trend is not None
    }
    # paper track (ADR 048): the cash asset's level over the ranked window. A forecast that carries weights
    # waits for it like for any class (an outcome is written once; a missing cash level would lose the
    # paper return for good – second review of P8); without weights the cash level is optional
    cash_asset = str(f.params.get("cash", "")) or None
    cash_ret: float | None = None
    if cash_asset is not None:
        cash_ret = _level_return(view, cash_asset, cal, f.decision_date, end)
        if cash_ret is None and f.weights is not None:
            return None
    port_ret, ew_ret = paper_returns(f, ret, ranked, cash_ret)
    return Outcome(
        decision_date=f.decision_date,
        horizon_months=f.horizon_months,
        model_id=f.model_id,
        model_version=f.model_version,
        settled_through=end,
        relative={a: float(rel[a]) for a in ranked},
        realised_rank={a: int(realised_rank[a]) for a in ranked},
        hit={a: float(hits[a]) for a in ranked},
        ic=None if ic is None or (isinstance(ic, float) and math.isnan(ic)) else float(ic),
        top_beats_bottom=tbb,
        brier=brier,
        brier_const=brier_const,
        ic_prev_month=None if prev_ic is None or math.isnan(prev_ic) else prev_ic,
        trend_hit=trend_hit,
        target=target,
        portfolio_return=port_ret,
        ew_return=ew_ret,
        cash_return=cash_ret,
    )


BACKFILL_NOTE = "backfilled"


def is_backfill(f: Forecast) -> bool:
    """Written long after its decision date (ADR 050): correct, but not an out-of-sample point."""
    return any(n.startswith(BACKFILL_NOTE) for n in f.notes)


def backfill_note(d: date, run_date: date, limit: int) -> str | None:
    """The note for a forecast at D written on `run_date`, or None when it is written in time."""
    delay = (run_date - d).days
    if delay <= limit:
        return None
    return (
        f"{BACKFILL_NOTE}: written {run_date}, {delay} days after the decision date (limit {limit}); computed from "
        f"the view at {d} like any forecast, but not counted in the live track record"
    )


def track_record(
    outcomes: Sequence[Outcome], horizon: int, boot: BlockBootstrap | None = None
) -> dict[str, Any]:
    """Summary of the settled forecasts of one horizon."""
    rows = [o for o in outcomes if o.horizon_months == horizon]
    out: dict[str, Any] = {"horizon": horizon, "n": len(rows)}
    if not rows:
        return out
    ic = pd.Series([o.ic for o in rows if o.ic is not None], dtype=float)
    tb = pd.Series([o.top_beats_bottom for o in rows if o.top_beats_bottom is not None], dtype=float)
    br = pd.Series([o.brier for o in rows if o.brier is not None], dtype=float)
    bc = pd.Series([o.brier_const for o in rows if o.brier is not None], dtype=float)
    pm = pd.Series([o.ic_prev_month for o in rows if o.ic_prev_month is not None], dtype=float)
    out.update(
        {
            "ic_mean": float(ic.mean()) if len(ic) else math.nan,
            "ic_share_positive": float((ic > 0).mean()) if len(ic) else math.nan,
            "hit_rate": float(tb.mean()) if len(tb) else math.nan,
            "brier": float(br.mean()) if len(br) else math.nan,
            "brier_const": float(bc.mean()) if len(bc) else math.nan,
            "ic_prev_month": float(pm.mean()) if len(pm) else math.nan,
        }
    )
    if boot is not None and len(ic) >= 24:
        lo, hi = boot.interval(ic.to_numpy(), 0.9)
        out["ic_low"], out["ic_high"] = lo, hi
    th: dict[str, list[float]] = {}
    for o in rows:
        for a, v in o.trend_hit.items():
            th.setdefault(a, []).append(v)
    out["trend_hit"] = {a: float(np.mean(v)) for a, v in th.items()}
    out["trend_n"] = {a: len(v) for a, v in th.items()}
    paper = [o for o in rows if o.portfolio_return is not None and o.ew_return is not None]
    if paper:
        pr = np.array([o.portfolio_return for o in paper], dtype=float)
        er = np.array([o.ew_return for o in paper], dtype=float)
        out["paper_n"] = len(paper)
        out["paper_cum"] = float(np.prod(1 + pr) - 1)
        out["ew_cum"] = float(np.prod(1 + er) - 1)
        out["paper_excess_mean"] = float((pr - er).mean())
    return out


def run(
    bundle: Bundle,
    factory: StoreViewFactory,
    journal: ForecastJournal,
    run_date: date,
    universe: str = "live",
    reports_dir: str | Path | None = None,
    variant: str | None = None,
    config: str = "forecast",
) -> RunReport:
    fc = bundle.forecasts.get(config)
    if fc is None:
        raise ValueError(f"configs/{config}.yaml is missing")
    cal = factory.cal
    model = ForecastModel(fc, universe=universe, variant=variant, averaged=averaged_assets(bundle))
    d = decision_date_for(run_date)
    assets = [*model.ranked, *model.trend_only]  # cash is reported, not read: it must not block the forecast
    written = 0
    skipped: str | None = None
    late: str | None = None
    view = factory.at(d)
    missing = data_complete(view, assets, cal, d)
    if missing:
        known = factory.at(d, knowledge=run_date)  # observations through D as known on the run date
        if data_complete(known, assets, cal, d):
            skipped = f"no forecast at {d}: prices not complete through the last session for {missing}"
            log.warning(skipped)
        else:
            view = known
            late = (
                f"late data: prices of {missing} through {d} were not in the store's view at {d} (arrived late, "
                f"or published after {d} by their lag); forecast made on {run_date} from observations through {d} "
                f"with vintages through {run_date}"
            )
            log.warning(late)
    if skipped is None:
        rule = paper_rule(bundle, model)
        backfill = backfill_note(d, run_date, fc.backfill_after_days)
        for made in model.forecast(view, factory.data_snapshot()):
            f = made if late is None else made.with_notes(late)
            if backfill is not None:
                f = f.with_notes(backfill)
            if f.horizon_months == 1 and f.status != "warmup":
                f = f.with_weights(paper_weights(rule, view, f))
            if journal.append_forecast(f):
                written += 1
    # settlement from the view at the run date
    now = factory.at(run_date)
    settled = 0
    for f in journal.unsettled():
        o = settle(f, now, cal)
        if o is not None and journal.append_outcome(o):
            settled += 1
    report_path = None
    if reports_dir is not None:
        report_path = _write_report(
            Path(reports_dir), journal, model, d, run_date, skipped, factory.data_snapshot()
        )
    return RunReport(run_date, d, written, settled, skipped, report_path, late)


def _write_report(
    out: Path,
    journal: ForecastJournal,
    model: ForecastModel,
    d: date,
    run_date: date,
    skipped: str | None,
    snapshot: str,
) -> Path:
    """The month's report and latest.md; backfilled forecasts (ADR 050) are shown but not counted."""
    fc = model.cfg
    all_forecasts = journal.forecasts()
    outcomes = journal.outcomes()
    boot = BlockBootstrap(fc.calibration.draws, fc.calibration.block_months, fc.calibration.seed)
    backfilled = {forecast_key(f) for f in all_forecasts if is_backfill(f)}
    counted = [o for o in outcomes if o.key() not in backfilled]
    tracks = {h: track_record(counted, h, boot) for h in fc.horizons}
    for h in fc.horizons:
        tracks[h]["backfilled"] = sum(1 for o in outcomes if o.horizon_months == h and o.key() in backfilled)
    last = _last_settled(outcomes, all_forecasts, 1)
    forecasts = [f for f in all_forecasts if f.decision_date == d]
    text = render_month(d, forecasts, tracks, last, skipped, model, snapshot, run_date)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{d:%Y-%m}.md"
    path.write_text(text, encoding="utf-8")
    (out / "latest.md").write_text(render_latest(path.name, text), encoding="utf-8")
    return path


def _last_settled(
    outcomes: Sequence[Outcome], forecasts: Sequence[Forecast], horizon: int
) -> tuple[Forecast, Outcome] | None:
    rows = [o for o in outcomes if o.horizon_months == horizon]
    if not rows:
        return None
    o = max(rows, key=lambda x: x.decision_date)
    by_key: Mapping[tuple[str, int, str, int], Forecast] = {forecast_key(f): f for f in forecasts}
    f = by_key.get(o.key())
    return (f, o) if f is not None else None


__all__ = [
    "BACKFILL_NOTE",
    "RunReport",
    "backfill_note",
    "class_windows",
    "data_complete",
    "decision_date_for",
    "is_backfill",
    "month_end_after",
    "paper_returns",
    "paper_rule",
    "paper_weights",
    "run",
    "settle",
    "track_record",
]
