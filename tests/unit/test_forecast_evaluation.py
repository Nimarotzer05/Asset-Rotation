"""P4 (ADR 044): evaluation functions on inputs with known answers, and the holdout guard."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.forecast.evaluation import (
    assert_outside_holdout,
    block_rows,
    brier,
    by_class,
    by_decade,
    climatology,
    derived_portfolio,
    mean_ci,
    paired_diff,
    paired_sharpe_diff,
    perf,
    permutation_pvalue,
    previous_month_scores,
    reliability,
    sharpe_of,
    spearman_rows,
    top_bottom,
    trend_label,
    trend_table,
    window,
)
from rotationlab.forecast.model import (
    BlockBootstrap,
    fit_logistic,
    hit_matrix,
    logistic_class_probabilities,
    rank_class_probabilities,
    rank_hit_probabilities,
    ranks_of,
)

IDX = pd.date_range("2000-01-31", periods=6, freq="ME")
COLS = ["A", "B", "C", "D"]


def _frame(rows):
    return pd.DataFrame(rows, index=IDX[: len(rows)], columns=COLS)


def test_spearman_rows_perfect_reverse_and_missing() -> None:
    s = _frame([[4, 3, 2, 1], [4, 3, 2, 1], [1, 2, 3, 4], [1, 1, 1, 1]])
    y = _frame(
        [[0.04, 0.03, 0.02, 0.01], [0.01, 0.02, 0.03, 0.04], [0.1, np.nan, 0.3, 0.2], [0.1, 0.2, 0.3, 0.4]]
    )
    ic = spearman_rows(s, y)
    assert ic.iloc[0] == pytest.approx(1.0) and ic.iloc[1] == pytest.approx(-1.0)
    assert ic.iloc[2] == pytest.approx(0.5)  # three classes known: ranks (1,3,2) vs (1,2,3)? A<C<D → 0.5
    assert np.isnan(ic.iloc[3])  # constant scores: no ordering


def test_top_bottom_and_hit() -> None:
    s = _frame([[4, 3, 2, 1], [1, 2, 3, 4]])
    y = _frame([[0.04, 0.0, 0.0, -0.04], [0.02, 0.0, 0.0, 0.01]])
    tb = top_bottom(ranks_of(s), y)
    assert tb["top"].tolist() == [0.04, 0.01] and tb["bottom"].tolist() == [-0.04, 0.02]
    assert tb["hit"].tolist() == [1.0, 0.0]


def test_permutation_pvalue_detects_skill_and_not_noise() -> None:
    rng = np.random.default_rng(0)
    idx = pd.date_range("1990-01-31", periods=240, freq="ME")
    y = pd.DataFrame(rng.normal(size=(240, 4)), index=idx, columns=COLS)
    skilled = y + rng.normal(scale=2.0, size=y.shape)  # noisy but informative
    p_skill, q95, obs = permutation_pvalue(skilled, y, 500, 1)
    p_noise, _, obs_noise = permutation_pvalue(
        pd.DataFrame(rng.normal(size=y.shape), index=idx, columns=COLS), y, 500, 1
    )
    assert p_skill < 0.01 and obs > q95 > 0
    assert p_noise > 0.05 and abs(obs_noise) < 0.1


def test_brier_climatology_reliability() -> None:
    prob = _frame([[1.0, 0.0, 0.5, 0.5], [0.8, 0.2, 0.6, 0.4]])
    hit = _frame([[1.0, 0.0, 1.0, 0.0], [1.0, 1.0, 0.0, 0.0]])
    b = brier(prob, hit)
    assert b.iloc[0] == pytest.approx((0 + 0 + 0.25 + 0.25) / 4)
    assert b.iloc[1] == pytest.approx((0.04 + 0.64 + 0.36 + 0.16) / 4)
    clim = climatology(hit, 1)
    assert clim.iloc[0].isna().all() and clim.iloc[1].tolist() == [1.0, 0.0, 1.0, 0.0]
    r = reliability(prob, hit, step=0.5)
    assert r["n"].sum() == 8 and set(r["bin"]) == {"0.00–0.50", "0.50–1.00"}


def test_mean_ci_and_paired_diff_are_deterministic() -> None:
    x = pd.Series(
        np.random.default_rng(2).normal(0.05, 0.3, 300),
        index=pd.date_range("1990-01-31", periods=300, freq="ME"),
    )
    boot = BlockBootstrap(500, 12, 3)
    a = mean_ci(x, boot, 0.9)
    assert a.low < a.mean < a.high and a.n == 300 and a == mean_ci(x, BlockBootstrap(500, 12, 3), 0.9)
    assert mean_ci(x.iloc[:1], boot, 0.9).n == 1
    d = paired_diff(x, x - 0.01, boot, 0.9)
    assert d.mean == pytest.approx(0.12) and d.excludes_zero


def test_by_decade_and_by_class() -> None:
    idx = pd.date_range("1978-01-31", periods=48, freq="ME")
    ic = pd.Series(np.where(idx.year < 1980, 0.5, -0.5), index=idx)
    d = by_decade(ic)
    assert d.loc["1973–1979", "mean"] == pytest.approx(0.5) and d.loc["1980s", "share_positive"] == 0.0
    s = _frame([[4, 3, 2, 1], [4, 3, 2, 1], [1, 2, 3, 4]])
    y = _frame([[0.1, 0.0, 0.0, -0.1], [-0.1, 0.0, 0.0, 0.1], [0.2, 0.0, 0.0, -0.2]])
    bc = by_class(ranks_of(s), y).set_index(["class", "rank"])
    assert bc.loc[("A", 1), "months"] == 2 and bc.loc[("A", 1), "hit_rate"] == 0.5
    assert bc.loc[("A", 4), "mean_rel"] == pytest.approx(0.2)


def test_previous_month_scores_and_derived_portfolio() -> None:
    lv = _frame([[100, 100, 100, 100], [110, 100, 90, 100], [121, 100, 81, 100], [121, 110, 81, 90]]).astype(
        float
    )
    prev = previous_month_scores(lv)
    assert prev.iloc[1].tolist() == pytest.approx([0.1, 0.0, -0.1, 0.0])
    ranks = ranks_of(_frame([[4, 3, 1, 2]] * 4))  # scores: A and B are the top two
    trend = _frame([[1, 1, -1, 1]] * 4)
    ret = lv / lv.shift(1) - 1
    cash = pd.Series(0.0, index=IDX[:4])
    der = derived_portfolio(ranks, trend, ret, cash, top=2)
    assert np.isnan(der.iloc[0]) and der.iloc[1] == pytest.approx(0.5 * 0.1 + 0.5 * 0.0)
    trend2 = trend.copy()
    trend2.loc[IDX[1], "A"] = -1  # A below its average at the second decision → that half in cash
    der2 = derived_portfolio(ranks, trend2, ret, cash, top=2)
    assert der2.iloc[2] == pytest.approx(0.0 + 0.5 * 0.0)
    p = perf(der.dropna(), cash)
    assert p["months"] == 3 and p["max_drawdown"] <= 0


def test_holdout_guard(bundle) -> None:
    fc = bundle.forecast
    _first, last = window(fc, 1)
    assert (
        last == date(2018, 11, 30)
        and window(fc, 3)[1] == date(2018, 9, 30)
        and window(fc, 6)[1] == date(2018, 6, 30)
    )
    assert_outside_holdout([last], fc, 1)
    with pytest.raises(ValueError, match="holdout touched"):
        assert_outside_holdout([date(2018, 12, 31)], fc, 1)
    with pytest.raises(ValueError, match="holdout touched"):
        assert_outside_holdout([date(2018, 10, 31)], fc, 3)


def test_rank_probabilities_shrink_and_logistic_fits() -> None:
    idx = pd.date_range("2000-01-31", periods=100, freq="ME")
    ranks = pd.DataFrame([[1, 2]] * 100, index=idx, columns=["A", "B"], dtype=float)
    rel = pd.DataFrame({"A": [0.01] * 100, "B": [-0.01] * 100}, index=idx)
    hits = hit_matrix(rel, "beats_mean")
    assert hits.iloc[0].tolist() == [1.0, 0.0] and hit_matrix(rel, "top_half").iloc[0].tolist() == [1.0, 0.0]
    p, n = rank_hit_probabilities(ranks, hits, prior_months=60)
    assert n == {1: 100, 2: 100}
    assert p[1] == pytest.approx((100 + 30) / (100 + 60)) and p[2] == pytest.approx(30 / 160)
    x = np.linspace(-3, 3, 400)
    y = (1 / (1 + np.exp(-(0.2 + 1.5 * x))) > np.random.default_rng(5).random(400)).astype(float)
    a, b = fit_logistic(x, y)
    assert abs(a - 0.2) < 0.4 and abs(b - 1.5) < 0.5


def test_trend_label_and_table() -> None:
    idx = pd.date_range("2000-01-31", periods=24, freq="ME")
    up = pd.Series(np.linspace(100, 150, 24), index=idx)
    lab = trend_label(up, 10)
    assert lab.iloc[:9].isna().all() and lab.iloc[9:].eq(1.0).all()
    down = pd.Series(np.linspace(150, 100, 24), index=idx)
    assert trend_label(down, 10).iloc[9:].eq(0.0).all()
    label = pd.Series([1, 1, 0, 0, 1, 0, np.nan, 1], index=idx[:8], dtype=float)
    fwd = pd.Series([0.02, 0.01, -0.01, -0.02, 0.03, 0.0, 0.05, np.nan], index=idx[:8])
    t = trend_table(label, fwd, "x", BlockBootstrap(200, 1, 1), 0.9)
    assert t["months"] == 6 and t["share_up"] == pytest.approx(0.5)
    assert t["hit_up"] == 1.0 and t["hit_down"] == 0.0
    assert t["mean_fwd_up_pa"] == pytest.approx(0.02 * 12) and t["mean_fwd_down_pa"] == pytest.approx(
        -0.01 * 12
    )
    assert t["diff_pa"] == pytest.approx(0.36) and t["diff_low"] <= t["diff_pa"] <= t["diff_high"]


def test_top_half_target_and_class_models() -> None:
    idx = pd.date_range("2000-01-31", periods=200, freq="ME")
    rng = np.random.default_rng(9)
    scores = pd.DataFrame(rng.normal(size=(200, 4)), index=idx, columns=COLS)
    rel = scores * 0.5 + rng.normal(size=(200, 4))  # informative scores
    hits = hit_matrix(rel, "top_half")
    assert hits.sum(axis=1).eq(2.0).all()  # exactly two of four in the upper half
    fit = logistic_class_probabilities(scores, hits, scores.iloc[-1], 60)
    assert fit is not None
    probs, n = fit
    assert n == 200 and set(probs) == set(COLS) and all(0 < v < 1 for v in probs.values())
    top = scores.iloc[-1].idxmax()
    assert probs[top] == max(probs.values())  # a higher score → higher probability (positive slope)
    assert logistic_class_probabilities(scores.iloc[:30], hits.iloc[:30], scores.iloc[-1], 60) is None
    ranks = ranks_of(scores)
    rc = rank_class_probabilities(ranks, hits, ranks.iloc[-1], 60)
    assert set(rc) == set(COLS) and all(0 < v < 1 for v in rc.values())
    # with no data the Beta prior gives 0.5
    assert rank_class_probabilities(ranks.iloc[:0], hits.iloc[:0], ranks.iloc[-1], 60) == dict.fromkeys(
        COLS, 0.5
    )


# ---------------------------------------------------------------------------- P8: paired Sharpe bootstrap
def test_block_rows_reproduce_the_block_bootstrap_interval() -> None:
    """The row draws are the moving blocks of `BlockBootstrap.interval` (same uniform table): the mean over
    the drawn rows gives exactly the same interval, for full blocks and with a partial block."""
    boot = BlockBootstrap(500, 12, 7)
    rng = np.random.default_rng(1)
    for n in (24, 100, 547):
        x = rng.normal(0.01, 0.04, n)
        rows = block_rows(boot, n)
        assert rows.shape == (500, n) and rows.min() >= 0 and rows.max() < n
        lo, hi = boot.interval(x, 0.9)
        means = x[rows].mean(axis=1)
        assert np.quantile(means, 0.05) == pytest.approx(lo) and np.quantile(means, 0.95) == pytest.approx(hi)


def test_paired_sharpe_diff_is_zero_for_identical_series_and_signed_for_a_shift() -> None:
    boot = BlockBootstrap(400, 12, 11)
    idx = pd.date_range("1990-01-31", periods=240, freq="ME")
    rng = np.random.default_rng(3)
    a = pd.Series(rng.normal(0.008, 0.04, 240), idx)
    cash = pd.Series(0.003, idx)
    same = paired_sharpe_diff(a, a.copy(), cash, boot, 0.9)
    assert same.value == 0.0 and same.low == 0.0 and same.high == 0.0 and same.n == 240
    assert not same.excludes_zero
    better = paired_sharpe_diff(a + 0.01, a, cash, boot, 0.9)
    assert better.value > 0 and better.low > 0 and better.excludes_zero
    worse = paired_sharpe_diff(a - 0.01, a, cash, boot, 0.9)
    assert worse.value < 0 and worse.high < 0
    # the point estimate is the Sharpe difference of the excess returns, annualised like metrics.sharpe
    ex_a, ex_b = (a + 0.01 - cash).to_numpy(), (a - cash).to_numpy()
    expected = ex_a.mean() / ex_a.std(ddof=1) * np.sqrt(12) - ex_b.mean() / ex_b.std(ddof=1) * np.sqrt(12)
    assert better.value == pytest.approx(expected)
    assert (
        sharpe_of(np.zeros((2, 5))).tolist() == [np.nan, np.nan]
        or np.isnan(sharpe_of(np.zeros((2, 5)))).all()
    )


def test_deflated_sharpe_follows_bailey_lopez_de_prado() -> None:
    """One trial: SR0 = 0 and the PSR is the plain probabilistic Sharpe; more trials raise the hurdle and
    lower the probability; a zero-variance family of trials never raises it; skew/kurtosis enter the variance."""
    from rotationlab.forecast.evaluation import _norm_ppf, deflated_sharpe

    assert _norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-5) and _norm_ppf(0.5) == pytest.approx(
        0.0, abs=1e-6
    )
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(0.004, 0.02, 480))  # monthly SR ≈ 0.2 (≈ 0.7 annualised)
    sr, sr0, psr1 = deflated_sharpe(x, 1, 0.01)
    assert sr == pytest.approx(x.mean() / x.std(ddof=1)) and sr0 == 0.0
    _, sr0_30, psr30 = deflated_sharpe(x, 30, 0.01)
    assert sr0_30 > 0 and psr30 < psr1
    _, sr0_flat, psr_flat = deflated_sharpe(x, 30, 0.0)
    assert sr0_flat == 0.0 and psr_flat == pytest.approx(psr1)
    # SR0 for N trials with variance V: sqrt(V)·[(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))]
    g = 0.5772156649015329
    expect = 0.1 * ((1 - g) * _norm_ppf(1 - 1 / 30) + g * _norm_ppf(1 - 1 / (30 * np.e)))
    assert sr0_30 == pytest.approx(expect, rel=1e-6)
    with pytest.raises(ValueError):
        deflated_sharpe(x.iloc[:2], 1, 0.0)


def test_appraisal_residual_removes_leverage_but_keeps_alpha() -> None:
    """A strategy that is the baseline levered 1.5× plus a constant alpha: the residual is exactly the alpha
    (leverage is not skill); with zero alpha the residual is zero."""
    from rotationlab.forecast.evaluation import appraisal_residual

    rng = np.random.default_rng(4)
    cash = pd.Series(0.003, index=range(240))
    b = cash + pd.Series(rng.normal(0.004, 0.03, 240))
    lev = cash + 1.5 * (b - cash)
    assert appraisal_residual(lev, b, cash).abs().max() == pytest.approx(0.0, abs=1e-12)
    alpha = lev + 0.001
    assert appraisal_residual(alpha, b, cash).to_numpy() == pytest.approx(np.full(240, 0.001))


def test_newey_west_holm_sharpe_ci_and_rank_portfolio() -> None:
    from rotationlab.forecast.evaluation import (
        holm,
        long_short_rank_returns,
        newey_west_t,
        one_sided_p,
        sharpe_ci,
    )

    rng = np.random.default_rng(9)
    x = pd.Series(rng.normal(0.002, 0.01, 600))
    m, t0 = newey_west_t(x, lags=0)
    assert m == pytest.approx(x.mean()) and t0 == pytest.approx(x.mean() / (x.std(ddof=0) / np.sqrt(600)))
    ar = pd.Series(np.convolve(rng.normal(0.001, 0.01, 620), np.ones(12) / 12, mode="valid")[:600])
    _, t_nw = newey_west_t(ar, lags=12)
    _, t_iid = newey_west_t(ar, lags=0)
    assert abs(t_nw) < abs(t_iid)  # overlapping averages: the HAC error is larger
    assert one_sided_p(1.6448536) == pytest.approx(0.05, abs=1e-6) and one_sided_p(0.0) == pytest.approx(0.5)
    h = holm({"a": 0.01, "b": 0.04, "c": 0.30}, alpha=0.10)
    assert h["a"] == (pytest.approx(0.03), True) and h["b"] == (pytest.approx(0.08), True)
    assert h["c"] == (pytest.approx(0.30), False)
    h2 = holm({"a": 0.05, "b": 0.04}, alpha=0.05)  # step-down stops at the first non-rejection
    assert h2["b"][1] is False and h2["a"][1] is False
    with pytest.raises(
        ValueError, match="non-finite"
    ):  # an untested hypothesis must leave the family (ADR 058)
        holm({"a": float("nan"), "b": 0.02, "c": 0.04}, alpha=0.10)
    cash = pd.Series(0.0, index=x.index)
    ci = sharpe_ci(x, cash, BlockBootstrap(500, 12, 1), 0.90)
    assert ci.value == pytest.approx(x.mean() / x.std(ddof=1) * np.sqrt(12)) and ci.low < ci.value < ci.high
    sc = pd.DataFrame({"A": [3.0, 1.0], "B": [2.0, 2.0], "C": [1.0, np.nan]}, index=[0, 1])
    nr = pd.DataFrame({"A": [0.05, 0.01], "B": [0.0, 0.03], "C": [-0.05, 0.9]}, index=[0, 1])
    ls = long_short_rank_returns(sc, nr)
    assert ls[0] == pytest.approx(0.5 * 0.05 - 0.5 * (-0.05))  # ranks 3/2/1 → +1, 0, −1 → ±0.5
    assert ls[1] == pytest.approx(-0.5 * 0.01 + 0.5 * 0.03)  # C has no score: two names left
    # a scored name without a next-month return stays in the weights and earns 0 (no look at the next month)
    gone = long_short_rank_returns(sc.iloc[[0]], nr.iloc[[0]].assign(C=np.nan))
    assert gone[0] == pytest.approx(0.5 * 0.05)
    tie = long_short_rank_returns(
        pd.DataFrame({"X": [1.0], "Y": [1.0]}), pd.DataFrame({"X": [0.02], "Y": [0.0]})
    )
    assert tie[0] == pytest.approx(0.5 * 0.02)  # the earlier column wins the tie, as in the allocator
