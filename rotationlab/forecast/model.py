"""The base forecast model (ADR 043, step P3): rank the asset classes for the next month.

    score   the multi_asset_rotation composite (z-scores of 3-1, 6-1, 12-1 momentum, distance to the
            10-month average and inverse volatility, weighted, clipped), over the *ranked* classes only
    rank    1 = highest score
    trend   above / below the 10-month average, for every class (the only output for trend-only classes)
    probability (main output, ADR 044/045) that a class ends in the upper half of the ranked classes over
            the horizon (`target`): a logistic curve on the score with a constant per class, fitted on all
            past months whose outcome was known at D (`logistic_tophalf`); variants per rank or per
            class × rank with a Beta prior, or one curve without class constants
    expected relative excess return of a rank and its band: the mean relative return that this rank earned
            in all past months whose outcome was known at D, with a moving-block-bootstrap interval
    status  `no_clear_signal` when no probability lies further than `no_signal_margin` from 0.5

Everything is a function of the view at D. The past scores behind the expectations come from the as-of
panel at D (the panel formula of every feature, ADR 036), the past outcomes from total-return levels known
at D. Nothing adapts: the model is fixed by `configs/forecast.yaml`; variants are separate model ids. Round 5
(`configs/forecast_fed.yaml`, ADR 063) adds an optional macro component whose per-class ridge is refitted on the
expanding past at every D by a fixed rule (rotationlab/forecast/macro.py).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.config.models import ForecastConfig
from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.features._panel import month_grid
from rotationlab.forecast.macro import ridge_path, state_panel
from rotationlab.forecast.types import ClassForecast, Forecast, Status, Trend, thaw

SUPPORTED = (
    "mom_3_1",
    "mom_6_1",
    "mom_12_1",
    "mom_12",
    "trend_10m",
    "inv_vol_12m",
    "value_rev_60m",  # ADR 052: long-term reversal
    "carry_yield",  # ADR 052: income yield per class (feature_params.carry_yield.spec)
)


# ---------------------------------------------------------------------------
# scores
# ---------------------------------------------------------------------------
def feature_panel(view: MarketView, name: str, assets: Sequence[str], **params: Any) -> pd.DataFrame:
    """A registered cross-sectional feature over the whole as-of panel at view.date (rows = month-ends,
    the running month labelled with the view date); `params` override the feature's defaults."""
    meta = registry.get_feature(name)
    assert meta.panel_input is not None and meta.panel_fn is not None
    kw = {**dict(meta.params), **params}
    panel = meta.panel_input(view, list(assets), **kw)
    out = meta.call_panel(panel, **params)
    return pd.DataFrame(out).reindex(columns=list(assets))


def zscore_rows(df: pd.DataFrame, clip: float) -> pd.DataFrame:
    """Cross-sectional z-score per row (sample SD over the classes with a value), clipped – the research
    formula of src/signals.py::zscore_cross_section."""
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0).clip(-clip, clip)


def composite(feats: Mapping[str, pd.DataFrame], weights: Mapping[str, float], clip: float) -> pd.DataFrame:
    """Σ w_k/Σw · z_k; a class missing in one feature keeps the sum of the others, missing in all is NaN."""
    total = sum(weights.values())
    out: pd.DataFrame | None = None
    for name, w in weights.items():
        z = zscore_rows(feats[name], clip) * (w / total)
        out = z if out is None else out.add(z, fill_value=0)
    assert out is not None
    return out


def ranks_of(scores: pd.DataFrame) -> pd.DataFrame:
    """Rank 1 = highest score, per row; rows where any ranked class lacks a score get no ranks."""
    complete = scores.notna().all(axis=1)
    r = scores.rank(axis=1, ascending=False, method="first")
    return r.where(complete)


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------
def complete_months(view: MarketView, levels: pd.DataFrame) -> pd.DataFrame:
    """Drop the running (partial) month: the last row when it is labelled with a view date that is not a
    calendar month-end. A last row labelled with an earlier month-end is a complete month and stays."""
    if not len(levels):
        return levels
    d = pd.Timestamp(view.date)
    last = pd.Timestamp(levels.index[-1])
    if last == d and d != d + pd.offsets.MonthEnd(0):
        return levels.iloc[:-1]
    return levels


def forward_returns(levels: pd.DataFrame, h: int, lag: Mapping[str, int] | None = None) -> pd.DataFrame:
    """Return over the h months after each row's month-end; known only where the end row exists.

    `lag[a] = 1` for classes valued at monthly averages (decision 5): the return from the average of month
    t+1 to the average of month t+1+h, the first average that lies wholly after the decision."""
    out = {}
    for a in levels.columns:
        k = int((lag or {}).get(str(a), 0))
        s = levels[a]
        out[a] = s.shift(-(h + k)) / s.shift(-k) - 1
    return pd.DataFrame(out, index=levels.index)


def relative(returns: pd.DataFrame) -> pd.DataFrame:
    """Return minus the mean of the classes with a return in the same row (the cash rate cancels)."""
    return returns.sub(returns.mean(axis=1), axis=0)


# ---------------------------------------------------------------------------
# calibration: mean relative return per rank, moving-block bootstrap
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RankCalibration:
    rank: int
    months: int
    mean: float
    low: float
    high: float


class BlockBootstrap:
    """Moving-block bootstrap of a mean with a fixed table of uniforms (deterministic for a seed; the same
    resampling pattern is used for every rank, so ranks are compared on paired draws)."""

    def __init__(self, draws: int, block: int, seed: int, max_len: int = 2400) -> None:
        self.draws, self.block = int(draws), int(block)
        rng = np.random.default_rng(seed)
        self.u = rng.random((self.draws, max_len // self.block + 2))

    def interval(self, x: np.ndarray, confidence: float) -> tuple[float, float]:
        n, b = len(x), min(self.block, len(x))
        k, r = divmod(n, b)
        csum = np.r_[0.0, np.cumsum(x)]
        n_starts = n - b + 1
        starts = np.minimum((self.u[:, : k + 1] * n_starts).astype(np.int64), n_starts - 1)
        full = (csum[starts[:, :k] + b] - csum[starts[:, :k]]).sum(axis=1)
        part = csum[starts[:, k] + r] - csum[starts[:, k]] if r else 0.0
        means = (full + part) / n
        a = (1.0 - confidence) / 2.0
        lo, hi = np.quantile(means, [a, 1.0 - a])
        return float(lo), float(hi)


def calibrate(
    ranks: pd.DataFrame, rel: pd.DataFrame, boot: BlockBootstrap, confidence: float
) -> list[RankCalibration]:
    """For every rank k: the relative returns of the class holding rank k, in months with both a rank and a
    known outcome; their mean and its bootstrap interval."""
    rel = rel.reindex(index=ranks.index, columns=ranks.columns)
    both = ranks.notna().all(axis=1) & rel.notna().all(axis=1)
    rk, rv = ranks[both].to_numpy(), rel[both].to_numpy()
    out = []
    for k in range(1, ranks.shape[1] + 1):
        x = rv[rk == k]
        if len(x) == 0:
            out.append(RankCalibration(k, 0, math.nan, math.nan, math.nan))
            continue
        m = float(x.mean())
        lo, hi = boot.interval(x, confidence)
        out.append(RankCalibration(k, len(x), m, min(lo, m), max(hi, m)))
    return out


# ---------------------------------------------------------------------------
# probabilities (ADR 044 a, ADR 045 b)
# ---------------------------------------------------------------------------
def hit_matrix(rel: pd.DataFrame, target: str) -> pd.DataFrame:
    """The event a probability refers to, per month and class: `beats_mean` = relative return > 0;
    `top_half` = realised rank among the classes in the upper half (rank ≤ n/2). NaN where unknown."""
    known = rel.notna().all(axis=1)
    if target == "beats_mean":
        out = (rel > 0).astype(float)
    elif target == "top_half":
        n = rel.shape[1]
        out = (rel.rank(axis=1, ascending=False, method="first") <= n // 2).astype(float)
    else:
        raise ValueError(f"unknown probability target {target}")
    return out.where(known)


def fit_logistic_multi(
    design: np.ndarray, y: np.ndarray, iterations: int = 50, ridge: float = 1e-3
) -> np.ndarray:
    """Logistic regression y ~ sigmoid(design @ w) by Newton's method with a small ridge on every
    parameter (keeps the fit finite when the classes separate)."""
    w = np.zeros(design.shape[1])
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-(design @ w)))
        g = design.T @ (p - y) + ridge * w
        h = (design * (p * (1 - p))[:, None]).T @ design + ridge * np.eye(design.shape[1])
        step = np.linalg.solve(h, g)
        w = w - step
        if np.max(np.abs(step)) < 1e-10:
            break
    return w


def logistic_class_probabilities(
    scores: pd.DataFrame, hits: pd.DataFrame, now: pd.Series, min_months: int
) -> tuple[dict[str, float], int] | None:
    """Primary model (ADR 045): P(hit) = sigmoid(c_class + b·score) – one slope on the score, one constant
    per class (their different base rates), fitted on all past (month, class) pairs with a known outcome.
    None before `min_months` complete months."""
    hits = hits.reindex(index=scores.index, columns=scores.columns)
    both = scores.notna().all(axis=1) & hits.notna().all(axis=1)
    n_months = int(both.sum())
    if n_months < min_months:
        return None
    cols = list(scores.columns)
    k = len(cols)
    x = scores[both].to_numpy()
    y = hits[both].to_numpy()
    design = np.zeros((n_months * k, k + 1))
    for j in range(k):
        design[j::k, j] = 1.0  # class constant
    design[:, k] = x.ravel()
    w = fit_logistic_multi(design, y.ravel())
    out = {c: float(1.0 / (1.0 + math.exp(-(w[j] + w[k] * float(now[c]))))) for j, c in enumerate(cols)}
    return out, n_months


def rank_class_probabilities(
    ranks: pd.DataFrame, hits: pd.DataFrame, now_ranks: pd.Series, prior_months: int
) -> dict[str, float]:
    """Variant: hit frequency per (class, rank) cell with a Beta(a, a) prior centred on 0.5, a = prior_months / 2."""
    hits = hits.reindex(index=ranks.index, columns=ranks.columns)
    both = ranks.notna().all(axis=1) & hits.notna().all(axis=1)
    a = prior_months / 2.0
    out = {}
    for c in ranks.columns:
        sel = both & (ranks[c] == float(now_ranks[c]))
        n = int(sel.sum())
        h = float(hits.loc[sel, c].sum()) if n else 0.0
        out[str(c)] = float((h + a) / (n + 2 * a))
    return out


def rank_hit_probabilities(
    ranks: pd.DataFrame, hits: pd.DataFrame, prior_months: int
) -> tuple[dict[int, float], dict[int, int]]:
    """Per rank: (hits + a) / (n + 2a) with a = prior_months / 2 – the posterior mean of a Beta(a, a) prior
    centred on 0.5 after n outcomes (`hits` = the 0/1 event matrix of `hit_matrix`); also n per rank."""
    hits = hits.reindex(index=ranks.index, columns=ranks.columns)
    both = ranks.notna().all(axis=1) & hits.notna().all(axis=1)
    rk, hv = ranks[both].to_numpy(), hits[both].to_numpy()
    a = prior_months / 2.0
    probs, counts = {}, {}
    for k in range(1, ranks.shape[1] + 1):
        x = hv[rk == k]
        n = len(x)
        probs[k] = float((np.sum(x) + a) / (n + 2 * a)) if n else 0.5
        counts[k] = n
    return probs, counts


def fit_logistic(
    x: np.ndarray, y: np.ndarray, iterations: int = 25, ridge: float = 1e-3
) -> tuple[float, float]:
    """Logistic regression y ~ sigmoid(a + b x) by Newton's method with a small ridge on both parameters
    (keeps the fit finite when the classes separate)."""
    design = np.c_[np.ones(len(x)), x]
    w = np.zeros(2)
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-design @ w))
        g = design.T @ (p - y) + ridge * w
        h = (design * (p * (1 - p))[:, None]).T @ design + ridge * np.eye(2)
        step = np.linalg.solve(h, g)
        w = w - step
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(w[0]), float(w[1])


def score_hit_probabilities(
    scores: pd.DataFrame, hits: pd.DataFrame, now: pd.Series, min_months: int
) -> tuple[dict[str, float], int] | None:
    """Variant: one logistic curve P(hit) = sigmoid(a + b·score) over all past (month, class) pairs with a
    known outcome; applied to today's scores. None before `min_months` complete months."""
    hits = hits.reindex(index=scores.index, columns=scores.columns)
    both = scores.notna().all(axis=1) & hits.notna().all(axis=1)
    if int(both.sum()) < min_months:
        return None
    x = scores[both].to_numpy().ravel()
    y = hits[both].to_numpy().ravel()
    a, b = fit_logistic(x, y)
    out = {str(c): float(1.0 / (1.0 + math.exp(-(a + b * float(now[c]))))) for c in scores.columns}
    return out, int(both.sum())


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------
class ForecastModel:
    def __init__(
        self,
        cfg: ForecastConfig,
        universe: str = "long_history",
        variant: str | None = None,
        averaged: Sequence[str] = (),
    ) -> None:
        u = cfg.universe[universe]  # type: ignore[index]
        self.cfg = cfg
        self.ranked, self.trend_only, self.cash = list(u.ranked), list(u.trend_only), u.cash
        if variant is None:
            self.weights = dict(cfg.model.feature_weights)
            self.model_id = cfg.model.id
        else:
            self.weights = dict(cfg.variants[variant].feature_weights)
            self.model_id = f"{cfg.model.id}:{variant}"
        unknown = set(self.weights) - set(SUPPORTED)
        if unknown:
            raise ValueError(f"forecast model: unsupported features {sorted(unknown)}")
        if cfg.trend_window_months != 10:
            raise ValueError("forecast model: the trend is the registered 10-month feature (trend_10m)")
        self.clip = cfg.model.zscore_clip
        self.feature_params = {k: dict(v) for k, v in cfg.model.feature_params.items()}
        self.version = cfg.model.version
        self.cal = cfg.calibration
        self.prob = cfg.probability
        self.averaged = {a for a in averaged if a in set(self.ranked) | set(self.trend_only)}
        self.boot = BlockBootstrap(self.cal.draws, self.cal.block_months, self.cal.seed)
        self.macro = cfg.model.macro  # round 5 (ADR 063); None for every earlier model
        if self.macro is not None:
            bad = [n for n in self.macro.features if registry.get_feature(n).kind == "cross_section"]
            if bad:
                raise ValueError(f"forecast model: macro features must be state variables, not {bad}")
        self.params: dict[str, Any] = {
            "universe": universe,
            "variant": variant,
            "feature_weights": self.weights,
            "zscore_clip": self.clip,
            "feature_params": thaw(self.feature_params),
            "ranked": self.ranked,
            "trend_only": self.trend_only,
            "cash": self.cash,
            "trend_window_months": cfg.trend_window_months,
            "averaged": sorted(self.averaged),
            "probability": thaw(dict(self.prob.model_dump())),
            "calibration": thaw(dict(self.cal.model_dump())),
        }
        if (
            self.macro is not None
        ):  # the key exists only for round-5 models: earlier records stay as they were
            self.params["macro"] = thaw(dict(self.macro.model_dump()))

    # -- pieces ------------------------------------------------------------------
    def score_history(self, view: MarketView) -> pd.DataFrame:
        """Composite score of every month on the as-of panel at view.date (last row = the score at D)."""
        feats = {
            k: feature_panel(view, k, self.ranked, **self.feature_params.get(k, {})) for k in self.weights
        }
        s = composite(feats, self.weights, self.clip)
        if s.empty:
            return s
        s = s.reindex(month_grid(s.index[0], view.date)).reindex(columns=self.ranked)
        if self.macro is None:
            return s
        m = self.macro_predictions(view, s.index)
        w = self.macro.weight
        return (1.0 - w) * s + w * zscore_rows(m, self.clip)  # NaN until the macro fit has enough months

    def macro_predictions(self, view: MarketView, index: pd.Index) -> pd.DataFrame:
        """Round 5 (ADR 063): the per-class ridge prediction m[t, a] on the as-of panel at D, for every row of
        `index` – each row fitted only on months whose next-month outcome was known at that row."""
        assert self.macro is not None
        x = state_panel(view, self.macro.features, self.macro.fill_gaps_months).reindex(index)
        y = self.outcomes(view, 1).reindex(index=index, columns=self.ranked)
        return ridge_path(x, y, self.macro.ridge_lambda, self.macro.min_train_months, self.macro.ffill_months)

    def trends(self, view: MarketView) -> pd.Series:
        assets = self.ranked + self.trend_only
        out: pd.Series = registry.get_feature("trend_10m").call(view, assets)
        return out.reindex(assets)

    def outcomes(self, view: MarketView, h: int) -> pd.DataFrame:
        """Relative returns of the ranked classes over h months after each past month-end, known at D."""
        levels = complete_months(view, view.total_return(self.ranked, "ME").reindex(columns=self.ranked))
        lag = {a: 1 for a in self.averaged}
        return relative(forward_returns(levels, h, lag))

    # -- the forecast ------------------------------------------------------------
    def forecast(
        self, view: MarketView, data_snapshot: str, horizons: Sequence[int] | None = None
    ) -> list[Forecast]:
        hist = self.score_history(view)
        trend = self.trends(view)
        ranks_hist = ranks_of(hist) if len(hist) else hist
        now = hist.iloc[-1] if len(hist) else pd.Series(np.nan, index=self.ranked)
        ranks_now = ranks_hist.iloc[-1] if len(hist) else pd.Series(np.nan, index=self.ranked)
        out = []
        for h in horizons or self.cfg.horizons:
            out.append(self._one(view, data_snapshot, h, hist, ranks_hist, now, ranks_now, trend))
        return out

    def _one(
        self,
        view: MarketView,
        snapshot: str,
        h: int,
        hist: pd.DataFrame,
        ranks_hist: pd.DataFrame,
        now: pd.Series,
        ranks_now: pd.Series,
        trend: pd.Series,
    ) -> Forecast:
        notes: list[str] = []
        status: Status = "warmup"
        cal: list[RankCalibration] = []
        probs: dict[str, float] = {}
        if ranks_now.notna().all():
            past = ranks_hist.iloc[:-1] if len(ranks_hist) else ranks_hist
            rel = self.outcomes(view, h)
            cal = calibrate(past, rel, self.boot, self.cal.confidence)
            n = min(c.months for c in cal)
            if n >= self.cal.min_months:
                probs = self._probabilities(hist.iloc[:-1], past, rel, now, ranks_now)
                margin = self.prob.no_signal_margin
                clear = any(abs(p - 0.5) > margin for p in probs.values())
                status = "signal" if clear else "no_clear_signal"
            else:
                notes.append(f"warmup: {n} months of outcomes per rank, {self.cal.min_months} needed")
                cal = []
        else:
            notes.append("warmup: not every ranked class has a score")
        by_rank = {c.rank: c for c in cal}
        classes = []
        for a in self.ranked:
            tv = trend.get(a, math.nan)
            r = None if status == "warmup" or pd.isna(ranks_now.get(a)) else int(ranks_now[a])
            c = by_rank.get(r) if r is not None else None
            classes.append(
                ClassForecast(
                    asset=a,
                    ranked=True,
                    trend=_trend(tv),
                    trend_value=_num(tv),
                    score=_num(now.get(a, math.nan)),
                    rank=r,
                    expected=c.mean if c else None,
                    band=(c.low, c.high) if c else None,
                    probability=probs.get(a) if status != "warmup" else None,
                )
            )
        for a in self.trend_only:
            tv = trend.get(a, math.nan)
            classes.append(ClassForecast(asset=a, ranked=False, trend=_trend(tv), trend_value=_num(tv)))
        return Forecast(
            decision_date=view.date,
            horizon_months=h,
            status=status,
            model_id=self.model_id,
            model_version=self.version,
            params=self.params,
            data_snapshot=snapshot,
            classes=tuple(classes),
            calibration_months=min((c.months for c in cal), default=0),
            notes=tuple(notes),
        )

    def _probabilities(
        self,
        scores_past: pd.DataFrame,
        ranks_past: pd.DataFrame,
        rel: pd.DataFrame,
        now: pd.Series,
        ranks_now: pd.Series,
    ) -> dict[str, float]:
        hits = hit_matrix(rel.reindex(columns=self.ranked), self.prob.target)
        if self.prob.model == "logistic_tophalf":
            fit_c = logistic_class_probabilities(scores_past, hits, now, self.cal.min_months)
            if fit_c is not None:
                return fit_c[0]
        if self.prob.model == "rank_class":
            return rank_class_probabilities(ranks_past, hits, ranks_now, self.prob.prior_months)
        if self.prob.model == "logistic_score":
            fit = score_hit_probabilities(scores_past, hits, now, self.cal.min_months)
            if fit is not None:
                return fit[0]
        by_rank, _ = rank_hit_probabilities(ranks_past, hits, self.prob.prior_months)
        return {a: by_rank[int(ranks_now[a])] for a in self.ranked}


def _num(v: Any) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _trend(v: Any) -> Trend | None:
    if v is None or pd.isna(v):
        return None
    return "up" if float(v) > 0 else "down"


def forecast_at(
    model: ForecastModel, factory: Any, d: date, horizons: Sequence[int] | None = None
) -> list[Forecast]:
    """The forecasts at D from a view factory (records the factory's data snapshot)."""
    return model.forecast(factory.at(d), factory.data_snapshot(), horizons)
