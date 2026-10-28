"""Historical evaluation of the forecast (ADR 044, step P4): does the ranking beat simple baselines?

Everything here is a pure function of a score history, a realised-return history and the configuration.
The pre-registered criteria live in ADR 044 (f); this module only measures.

    rank IC         Spearman correlation per month between the scores and the realised relative returns
                    of the ranked classes; mean with a moving-block-bootstrap interval and a permutation
                    p-value (random rankings)
    hit rate        P(the class ranked first beats the class ranked last)
    spread          relative return of rank 1 minus rank n (equal notional, one month)
    Brier           mean squared error of the probabilities against the hit indicator; skill against the
                    constant 0.5 and against the climatology (expanding hit frequency per class)
    reliability     observed hit frequency per probability bin

Holdout (decision 6): `window` returns the decision dates whose outcome windows end before the holdout
starts; `assert_outside_holdout` is the guard every evaluation run passes through.
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
from rotationlab.forecast.model import BlockBootstrap, ranks_of

DECADES = [
    ("1973–1979", 1973, 1979),
    ("1980s", 1980, 1989),
    ("1990s", 1990, 1999),
    ("2000s", 2000, 2009),
    ("2010–2018", 2010, 2018),
]
COMPLETE_DECADES = ["1980s", "1990s", "2000s", "2010–2018"]


# ---------------------------------------------------------------------------
# holdout
# ---------------------------------------------------------------------------
def window(cfg: ForecastConfig, h: int, first: date = date(1973, 1, 31)) -> tuple[date, date]:
    """Decision dates whose h-month outcome window ends before the holdout starts."""
    last = (pd.Timestamp(cfg.holdout.start) - pd.offsets.MonthEnd(h + 1)).date()
    return first, last


def assert_outside_holdout(dates: Sequence[date | pd.Timestamp], cfg: ForecastConfig, h: int) -> None:
    """Raise if any decision date, or the end of its outcome window, lies inside the holdout."""
    start = pd.Timestamp(cfg.holdout.start)
    for d in dates:
        end = pd.Timestamp(d) + pd.offsets.MonthEnd(h)
        if end >= start:
            raise ValueError(
                f"holdout touched: decision {pd.Timestamp(d).date()} + {h} M ends {end.date()} ≥ {start.date()}"
            )


# ---------------------------------------------------------------------------
# per-month statistics
# ---------------------------------------------------------------------------
def spearman_rows(x: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
    """Spearman correlation per row over the columns where both are known (NaN below 3 columns)."""
    y = y.reindex(index=x.index, columns=x.columns)
    out = pd.Series(np.nan, index=x.index, dtype=float)
    for t in x.index:
        a, b = x.loc[t], y.loc[t]
        m = a.notna() & b.notna()
        if m.sum() < 3:
            continue
        ra, rb = a[m].rank(), b[m].rank()
        if ra.std() == 0 or rb.std() == 0:
            continue
        out[t] = float(np.corrcoef(ra.to_numpy(), rb.to_numpy())[0, 1])
    return out.rename("ic")


def top_bottom(ranks: pd.DataFrame, rel: pd.DataFrame) -> pd.DataFrame:
    """Per month: relative return of the class ranked 1 and of the class ranked last, hit (1 > last)."""
    rel = rel.reindex(index=ranks.index, columns=ranks.columns)
    n = ranks.shape[1]
    rows = []
    for t in ranks.index:
        r = ranks.loc[t]
        if r.isna().any() or rel.loc[t].isna().any():
            rows.append((np.nan, np.nan))
            continue
        top, bot = r.idxmin(), r.idxmax()
        assert r[top] == 1 and r[bot] == n
        rows.append((float(rel.loc[t, top]), float(rel.loc[t, bot])))
    df = pd.DataFrame(rows, index=ranks.index, columns=["top", "bottom"])
    df["spread"] = df["top"] - df["bottom"]
    df["hit"] = (df["spread"] > 0).astype(float).where(df["spread"].notna())
    return df


def permutation_pvalue(
    scores: pd.DataFrame, rel: pd.DataFrame, draws: int, seed: int
) -> tuple[float, float, float]:
    """Random-ranking baseline: the mean IC under independent random orderings of the classes each month.
    Returns (p-value = share of draws with a mean IC ≥ the observed one, 95th percentile, observed)."""
    rel = rel.reindex(index=scores.index, columns=scores.columns)
    both = scores.notna().all(axis=1) & rel.notna().all(axis=1)
    s, r = scores[both].to_numpy(), rel[both].to_numpy()
    n_months, n = s.shape
    rs = pd.DataFrame(s).rank(axis=1).to_numpy()
    rr = pd.DataFrame(r).rank(axis=1).to_numpy()
    mu = (n + 1) / 2.0
    var = ((np.arange(1, n + 1) - mu) ** 2).sum()
    observed = float((((rs - mu) * (rr - mu)).sum(axis=1) / var).mean())
    rng = np.random.default_rng(seed)
    null = np.empty(draws)
    for i in range(draws):
        perm = np.argsort(rng.random((n_months, n)), axis=1) + 1  # a random permutation per month
        null[i] = (((perm - mu) * (rr - mu)).sum(axis=1) / var).mean()
    p = float((null >= observed).mean())
    return p, float(np.quantile(null, 0.95)), observed


# ---------------------------------------------------------------------------
# probabilities
# ---------------------------------------------------------------------------
def brier(prob: pd.DataFrame, hit: pd.DataFrame) -> pd.Series:
    """Mean squared error per month over the classes (both known)."""
    hit = hit.reindex(index=prob.index, columns=prob.columns)
    sq = (prob - hit) ** 2
    return sq.mean(axis=1).where(prob.notna().all(axis=1) & hit.notna().all(axis=1)).rename("brier")


def climatology(hit: pd.DataFrame, min_months: int) -> pd.DataFrame:
    """Expanding hit frequency per class, shifted by one month (known at the decision date)."""
    return hit.expanding(min_months).mean().shift(1)


def reliability(prob: pd.DataFrame, hit: pd.DataFrame, step: float = 0.05) -> pd.DataFrame:
    hit = hit.reindex(index=prob.index, columns=prob.columns)
    p = prob.to_numpy().ravel()
    y = hit.to_numpy().ravel()
    m = ~np.isnan(p) & ~np.isnan(y)
    p, y = p[m], y[m]
    edges = np.arange(0.0, 1.0 + step / 2, step)
    idx = np.clip(np.digitize(p, edges) - 1, 0, len(edges) - 2)
    rows = []
    for i in range(len(edges) - 1):
        sel = idx == i
        if sel.any():
            rows.append(
                {
                    "bin": f"{edges[i]:.2f}–{edges[i + 1]:.2f}",
                    "n": int(sel.sum()),
                    "mean_prob": float(p[sel].mean()),
                    "hit_freq": float(y[sel].mean()),
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MeanCI:
    mean: float
    low: float
    high: float
    n: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0


def mean_ci(x: pd.Series, boot: BlockBootstrap, confidence: float) -> MeanCI:
    v = x.dropna().to_numpy(dtype=float)
    if len(v) < 2:
        return MeanCI(math.nan, math.nan, math.nan, len(v))
    lo, hi = boot.interval(v, confidence)
    return MeanCI(float(v.mean()), lo, hi, len(v))


def by_decade(x: pd.Series, decades: Sequence[tuple[str, int, int]] = DECADES) -> pd.DataFrame:
    rows = []
    years = pd.DatetimeIndex(x.index).year
    for name, a, b in decades:
        s = x[(years >= a) & (years <= b)].dropna()
        if len(s):
            rows.append(
                {
                    "decade": name,
                    "months": len(s),
                    "mean": float(s.mean()),
                    "share_positive": float((s > 0).mean()),
                }
            )
    return pd.DataFrame(rows).set_index("decade")


def by_class(ranks: pd.DataFrame, rel: pd.DataFrame) -> pd.DataFrame:
    """Per class and rank: months, hit rate (relative return > 0), mean relative return."""
    rel = rel.reindex(index=ranks.index, columns=ranks.columns)
    rows = []
    for a in ranks.columns:
        for k in range(1, ranks.shape[1] + 1):
            m = (ranks[a] == k) & rel[a].notna()
            if m.sum():
                x = rel.loc[m, a]
                rows.append(
                    {
                        "class": a,
                        "rank": k,
                        "months": int(m.sum()),
                        "hit_rate": float((x > 0).mean()),
                        "mean_rel": float(x.mean()),
                    }
                )
    return pd.DataFrame(rows)


def previous_month_scores(levels: pd.DataFrame) -> pd.DataFrame:
    """Baseline scores: the realised return of the month that just ended (rank persistence)."""
    return levels / levels.shift(1) - 1


# ---------------------------------------------------------------------------
# absolute trend (trend-only classes, P5)
# ---------------------------------------------------------------------------
def trend_label(level: pd.Series, window_m: int = 10) -> pd.Series:
    """1 where the level is above its `window_m`-month mean, 0 below, NaN without enough history."""
    m = level.rolling(window_m).mean()
    return (level / m - 1 > 0).astype(float).where(m.notna())


def trend_table(
    label: pd.Series, fwd: pd.Series, name: str, boot: BlockBootstrap | None = None, confidence: float = 0.9
) -> dict[str, Any]:
    """Forward return after an up- and after a down-label: share of up months, hit rates, annualised means,
    and the up-minus-down difference with a moving-block-bootstrap interval of the OLS slope (fwd on label)."""
    both = label.notna() & fwd.notna()
    lab, f = label[both], fwd[both]
    up, down = lab == 1, lab == 0
    out: dict[str, Any] = {
        "basis": name,
        "months": int(both.sum()),
        "share_up": float(lab.mean()) if len(lab) else math.nan,
        "hit_up": float((f[up] > 0).mean()) if up.any() else math.nan,
        "hit_down": float((f[down] > 0).mean()) if down.any() else math.nan,
        "mean_fwd_up_pa": float(f[up].mean() * 12) if up.any() else math.nan,
        "mean_fwd_down_pa": float(f[down].mean() * 12) if down.any() else math.nan,
    }
    if boot is not None and up.any() and down.any():
        var = float(lab.var(ddof=0))
        contrib = (f - f.mean()) * (lab - lab.mean()) / var * 12  # per-month contribution to the OLS slope
        ci = mean_ci(contrib, boot, confidence)
        out.update({"diff_pa": ci.mean, "diff_low": ci.low, "diff_high": ci.high})
    return out


# ---------------------------------------------------------------------------
# derived-weight comparison (not the portfolio layer: before costs, research timing)
# ---------------------------------------------------------------------------
def derived_portfolio(
    ranks: pd.DataFrame, trend: pd.DataFrame, returns: pd.DataFrame, cash: pd.Series, top: int = 2
) -> pd.Series:
    """Top-`top` equal weight among the ranked classes, a pick below its 10-month average goes to cash;
    the weights decided at t earn the return of t+1."""
    returns = returns.reindex(columns=ranks.columns)
    out = pd.Series(np.nan, index=ranks.index)
    for i, t in enumerate(ranks.index[:-1]):
        r = ranks.loc[t]
        if r.isna().any():
            continue
        nxt = ranks.index[i + 1]
        picks = [a for a in r.index if r[a] <= top]
        w = {a: (1.0 / top if trend.loc[t, a] > 0 else 0.0) for a in picks}
        invested = sum(w.values())
        ret = sum(w[a] * returns.loc[nxt, a] for a in picks) + (1 - invested) * cash.get(nxt, 0.0)
        out[nxt] = ret
    return out.rename("derived")


def perf(r: pd.Series, cash: pd.Series) -> dict[str, float]:
    r = r.dropna()
    ex = r - cash.reindex(r.index).fillna(0.0)
    lvl = (1 + r).cumprod()
    return {
        "months": float(len(r)),
        "ann_return": float(lvl.iloc[-1] ** (12 / len(r)) - 1) if len(r) else math.nan,
        "ann_vol": float(r.std(ddof=1) * math.sqrt(12)),
        "sharpe_ex_cash": float(ex.mean() / ex.std(ddof=1) * math.sqrt(12))
        if ex.std(ddof=1) > 0
        else math.nan,
        "max_drawdown": float((lvl / lvl.cummax() - 1).min()),
    }


def paired_diff(a: pd.Series, b: pd.Series, boot: BlockBootstrap, confidence: float) -> MeanCI:
    d = (a - b).dropna() * 12
    return mean_ci(d, boot, confidence)


def block_rows(boot: BlockBootstrap, n: int) -> np.ndarray:
    """Row indices of every bootstrap draw (draws × n): the moving blocks of `boot` on n rows – the same
    uniform table as `BlockBootstrap.interval`, so a statistic of paired series is resampled in step."""
    b = min(boot.block, n)
    k, r = divmod(n, b)
    n_starts = n - b + 1
    starts = np.minimum((boot.u[:, : k + 1] * n_starts).astype(np.int64), n_starts - 1)
    full = (starts[:, :k, None] + np.arange(b)[None, None, :]).reshape(boot.draws, k * b)
    if r:
        part = starts[:, k, None] + np.arange(r)[None, :]
        full = np.concatenate([full, part], axis=1)
    return full


def sharpe_of(x: np.ndarray) -> np.ndarray:
    """Annualised Sharpe of excess returns along axis 1 (sample SD)."""
    sd = x.std(axis=1, ddof=1)
    return np.where(sd > 0, x.mean(axis=1) / np.where(sd > 0, sd, 1.0) * math.sqrt(12), np.nan)


@dataclass(frozen=True)
class StatCI:
    value: float
    low: float
    high: float
    n: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0


_EULER = 0.5772156649015329


def _norm_ppf(p: float) -> float:
    """Inverse standard normal via the bisection of math.erf (no scipy dependency; |error| < 1e-9)."""
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def deflated_sharpe(excess: pd.Series, n_trials: int, trials_var: float) -> tuple[float, float, float]:
    """Bailey/López de Prado (2014): the probability that the observed Sharpe (monthly, not annualised) exceeds
    the Sharpe one expects from the best of `n_trials` unskilled trials whose Sharpe estimates have variance
    `trials_var` (monthly units). Returns (observed monthly Sharpe, expected maximum SR0, PSR = probability that
    the true Sharpe exceeds SR0), skew and kurtosis of the series taken into account. A PSR below 0.95 means the
    track record does not survive the number of things tried."""
    x = excess.dropna().to_numpy(float)
    t = len(x)
    if t < 3 or n_trials < 1 or trials_var < 0:
        raise ValueError("deflated_sharpe: need ≥ 3 months, n_trials ≥ 1, trials_var ≥ 0")
    sd = x.std(ddof=1)
    if sd == 0:
        return 0.0, 0.0, float("nan")
    sr = float(x.mean() / sd)
    z = (x - x.mean()) / sd
    skew, kurt = float((z**3).mean()), float((z**4).mean())
    if n_trials == 1:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(trials_var) * (
            (1 - _EULER) * _norm_ppf(1 - 1 / n_trials) + _EULER * _norm_ppf(1 - 1 / (n_trials * math.e))
        )
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    stat = (sr - sr0) * math.sqrt(t - 1) / denom
    psr = 0.5 * (1 + math.erf(stat / math.sqrt(2)))
    return sr, sr0, float(psr)


def appraisal_residual(a: pd.Series, b: pd.Series, cash: pd.Series) -> pd.Series:
    """Excess return of `a` net of its full-sample beta to the excess return of the baseline `b` (Treynor/Black):
    ε = (a − c) − β·(b − c), β = cov/var. Its Sharpe (the appraisal ratio) measures what `a` adds beyond `b`
    without rewarding a different level of risk; β is an ex-post statistic, never a trading input (ADR 056)."""
    df = pd.DataFrame({"a": a, "b": b, "c": cash}).dropna()
    ea, eb = df["a"] - df["c"], df["b"] - df["c"]
    var = float(eb.var(ddof=1))
    beta = float(np.cov(ea, eb, ddof=1)[0, 1] / var) if var > 0 else 0.0
    return (ea - beta * eb).rename("residual")


def sharpe_ci(r: pd.Series, cash: pd.Series, boot: BlockBootstrap, confidence: float) -> StatCI:
    """Annualised Sharpe of r − cash with a moving-block bootstrap interval."""
    df = pd.DataFrame({"r": r, "c": cash}).dropna()
    e = (df["r"] - df["c"]).to_numpy()
    rows = block_rows(boot, len(e))
    draws = sharpe_of(e[rows])
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.nanquantile(draws, [alpha, 1.0 - alpha])
    value = float(sharpe_of(e[None, :])[0])
    return StatCI(value, float(min(lo, value)), float(max(hi, value)), len(e))


def newey_west_t(x: pd.Series, lags: int = 12) -> tuple[float, float]:
    """Mean of x and its t-statistic with Newey-West (Bartlett) standard errors: the right test for a mean of
    monthly returns with overlapping or autocorrelated information."""
    v = x.dropna().to_numpy(dtype=float)
    n = len(v)
    if n < 3:
        return float("nan"), float("nan")
    u = v - v.mean()
    s = float(u @ u) / n
    for k in range(1, min(lags, n - 1) + 1):
        s += 2.0 * (1.0 - k / (lags + 1.0)) * float(u[k:] @ u[:-k]) / n
    se = math.sqrt(max(s, 0.0) / n)
    return float(v.mean()), float(v.mean() / se) if se > 0 else float("nan")


def one_sided_p(t: float) -> float:
    """P(Z ≥ t) under the standard normal."""
    return float(0.5 * math.erfc(t / math.sqrt(2.0))) if math.isfinite(t) else float("nan")


def holm(pvalues: Mapping[str, float], alpha: float) -> dict[str, tuple[float, bool]]:
    """Holm's step-down adjustment: adjusted p-value and rejection at family-wise level `alpha` per hypothesis. Every
    p-value must be finite: a hypothesis that could not be tested does not belong to the family (ADR 058)."""
    bad = sorted(k for k, v in pvalues.items() if not math.isfinite(float(v)))
    if bad:
        raise ValueError(f"holm: non-finite p-values for {bad} – leave untested hypotheses out of the family")
    order = sorted(pvalues, key=lambda k: pvalues[k])
    m = len(order)
    out: dict[str, tuple[float, bool]] = {}
    running = 0.0
    still = True
    for i, k in enumerate(order):
        adj = min(1.0, (m - i) * pvalues[k])
        running = max(running, adj)
        still = still and pvalues[k] <= alpha / (m - i)
        out[k] = (running, still)
    return out


def long_short_rank_returns(scores: pd.DataFrame, next_returns: pd.DataFrame) -> pd.Series:
    """Monthly return of the dollar-neutral rank portfolio (Asness/Moskowitz/Pedersen 2013): at each date the
    instruments with a score get w ∝ (N+1)/2 − rank (rank 1 = highest; ties on 1e-12 go to the earlier column, as
    in the allocator), Σ|w| = 1, earning the next month's return. The weights use only what is known at the date:
    an instrument without a next-month return (it left the data) is held at weight but earns 0 – never dropped
    and re-ranked on information from the following month (ADR 058). Dates with fewer than two scores are skipped."""
    out: dict[Any, float] = {}
    aligned = next_returns.reindex(index=scores.index, columns=scores.columns)
    for i, t in enumerate(scores.index):
        s = scores.iloc[i].dropna()
        if len(s) < 2:
            continue
        r = aligned.iloc[i].reindex(s.index).fillna(0.0)
        off = (len(s) + 1) / 2.0 - s.round(12).rank(ascending=False, method="first")
        w = off / off.abs().sum()
        out[t] = float((w * r).sum())
    return pd.Series(out, dtype=float).rename("long_short")


def paired_sharpe_diff(
    a: pd.Series, b: pd.Series, cash: pd.Series, boot: BlockBootstrap, confidence: float
) -> StatCI:
    """Sharpe(a − cash) − Sharpe(b − cash) with a moving-block bootstrap interval over paired months (the
    two series are resampled on the same block draws)."""
    df = pd.DataFrame({"a": a, "b": b, "c": cash}).dropna()
    ea, eb = (df["a"] - df["c"]).to_numpy(), (df["b"] - df["c"]).to_numpy()
    n = len(df)
    rows = block_rows(boot, n)
    diffs = sharpe_of(ea[rows]) - sharpe_of(eb[rows])
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.nanquantile(diffs, [alpha, 1.0 - alpha])
    value = float(sharpe_of(ea[None, :])[0] - sharpe_of(eb[None, :])[0])
    return StatCI(value, float(min(lo, value)), float(max(hi, value)), n)


def last_full_month(level: pd.Series, calendar: Any) -> pd.Timestamp | None:
    """The last calendar month a level series covers completely (ADR 058 e): a monthly series its last month; a
    daily series the month of its last value if that value is on or after the month's last session of
    `calendar`, else the month before – a series that stops mid-month gives that month no complete return."""
    s = level.dropna()
    if s.empty:
        return None
    last = pd.Timestamp(s.index.max())
    me = last + pd.offsets.MonthEnd(0)
    if len(s) > 1 and float(pd.Series(s.index).diff().dt.days.median()) > 20:
        return me
    sessions = calendar.trading_days(me.replace(day=1).date(), me.date())
    if sessions and last.date() >= sessions[-1]:
        return me
    return me - pd.offsets.MonthEnd(1)


def common_data_end(
    groups: Mapping[str, pd.DataFrame], calendar: Any
) -> tuple[pd.Timestamp, dict[str, pd.Timestamp]]:
    """End of an evaluation window (ADR 058 e): per data group (levels of its members, native frequency) the
    last complete month of its longest-running member – a member that stops earlier has left the data and is
    handled by availability – and over the groups the earliest of these months."""
    per: dict[str, pd.Timestamp] = {}
    for g, frame in groups.items():
        ends = [e for e in (last_full_month(frame[c], calendar) for c in frame.columns) if e is not None]
        if not ends:
            raise ValueError(f"data group {g} has no data")
        per[g] = max(ends)
    return min(per.values()), per


__all__ = [
    "COMPLETE_DECADES",
    "DECADES",
    "MeanCI",
    "StatCI",
    "appraisal_residual",
    "assert_outside_holdout",
    "block_rows",
    "brier",
    "by_class",
    "by_decade",
    "climatology",
    "common_data_end",
    "deflated_sharpe",
    "derived_portfolio",
    "holm",
    "last_full_month",
    "long_short_rank_returns",
    "mean_ci",
    "newey_west_t",
    "one_sided_p",
    "paired_diff",
    "paired_sharpe_diff",
    "perf",
    "permutation_pvalue",
    "previous_month_scores",
    "ranks_of",
    "reliability",
    "sharpe_ci",
    "sharpe_of",
    "spearman_rows",
    "top_bottom",
    "trend_label",
    "trend_table",
    "window",
]
