"""Round 5 (ADR 063): the Fed category as a component of the forecast score.

Macro state variables (rate decisions, inflation, unemployment, policy stance, curve) are the same number for
every asset class, so they cannot rank classes by themselves. They act through a mapping learnt per class:

    y[s, a]  relative return of class a over the month after s (return minus the mean of the ranked classes)
    x[s]     the standardised state variables at month-end s
    β_a(t)   ridge slopes of y[·, a] on x[·], fitted on every month s with s + 1 month ≤ t (outcome known at t)
    m[t, a]  = z(x[t]) · β_a(t)           – slopes only: the intercept (a class's average relative return) is
                                            not Fed information and is left out on purpose

Standardisation uses the training months only (mean, sample SD). The penalty is λ·n on the standardised slopes,
so with λ = 1 a single uncorrelated variable's slope is halved relative to OLS. No month enters its own fit and
no fit uses an outcome that was not known at t: the expanding window is the whole look-ahead guard, tested by
mutating the future (tests/unit/test_forecast_macro.py).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView


def state_panel(view: MarketView, names: Sequence[str], fill_gaps: int = 0) -> pd.DataFrame:
    """The registered state features over the as-of panel at view.date (rows = month-ends).

    `fill_gaps`: interior gaps of at most this many months in a raw input series (a release that never came, e.g.
    the October 2025 CPI and jobs reports lost to the US government shutdown) are interpolated linearly between the
    values on both sides. Both neighbours are in the as-of panel, so they were known at D – no look-ahead; a gap at
    the end (a release not out yet) is never filled here. Without it one missing unemployment month blanks the
    Sahm indicator for 14 months (3-month mean, then 12-month minimum)."""
    cols = {}
    for n in names:
        meta = registry.get_feature(n)
        if meta.kind == "cross_section" or meta.panel_input is None or meta.panel_fn is None:
            raise ValueError(f"macro component: '{n}' is not a state feature with a panel formula")
        panel = meta.panel_input(view, None, **dict(meta.params))
        if fill_gaps > 0:
            panel = _fill_inside(panel, fill_gaps)
        cols[n] = pd.Series(meta.call_panel(panel), index=panel.index, dtype=float)
    return pd.DataFrame(cols).reindex(columns=list(names))


def _fill_inside(panel: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Linear interpolation of interior runs of NaN no longer than `limit` rows; longer runs stay NaN."""
    out = panel.copy()
    for c in out.columns:
        s = out[c]
        if not pd.api.types.is_numeric_dtype(s) or not s.isna().any():
            continue
        na = s.isna()
        run_id = (~na).cumsum()
        run_len = na.groupby(run_id).transform("sum")
        filled = s.interpolate(method="linear", limit_area="inside")
        out[c] = s.where(~na | (run_len > limit), filled)
    return out


def ridge_path(
    x: pd.DataFrame,
    y: pd.DataFrame,
    lam: float,
    min_train: int,
    ffill: int = 0,
) -> pd.DataFrame:
    """m[t, a] for every row t of `x` (see the module docstring); NaN where fewer than `min_train` complete
    training months exist or a state variable is missing at t after carrying it forward `ffill` rows.

    `x` and `y` share one monthly index; y.loc[s] is the outcome of the month after s, so row s is a training
    month for every t > s (on that index). Training months need every variable and every class."""
    if not x.index.equals(y.index):
        raise ValueError("ridge_path: x and y need the same index")
    xs = x.to_numpy(dtype=float)
    ys = y.to_numpy(dtype=float)
    ok = ~np.isnan(xs).any(axis=1) & ~np.isnan(ys).any(axis=1)
    k, c = xs.shape[1], ys.shape[1]
    # running sums over the complete rows: Σ1, Σx, Σxxᵀ, Σy, Σxyᵀ – each t reads the sums of rows < t
    xo = np.where(ok[:, None], xs, 0.0)
    yo = np.where(ok[:, None], ys, 0.0)
    n_c = np.concatenate([[0], np.cumsum(ok)])
    sx = np.vstack([np.zeros(k), np.cumsum(xo, axis=0)])
    sxx = np.concatenate([np.zeros((1, k, k)), np.cumsum(xo[:, :, None] * xo[:, None, :], axis=0)])
    sy = np.vstack([np.zeros(c), np.cumsum(yo, axis=0)])
    sxy = np.concatenate([np.zeros((1, k, c)), np.cumsum(xo[:, :, None] * yo[:, None, :], axis=0)])
    x_now = x.ffill(limit=ffill).to_numpy(dtype=float) if ffill > 0 else xs
    out = np.full((len(x), c), np.nan)
    for t in range(len(x)):
        n = int(n_c[t])  # complete rows strictly before t
        if n < max(min_train, 2) or np.isnan(x_now[t]).any():
            continue
        mu, my = sx[t] / n, sy[t] / n
        cxx = sxx[t] - n * np.outer(mu, mu)
        cxy = sxy[t] - n * np.outer(mu, my)
        sd = np.sqrt(np.clip(np.diag(cxx), 0.0, None) / (n - 1))
        if (sd <= 0).any():
            continue
        zz = cxx / np.outer(sd, sd)
        zy = cxy / sd[:, None]
        beta = np.linalg.solve(zz + lam * n * np.eye(k), zy)
        out[t] = ((x_now[t] - mu) / sd) @ beta
    return pd.DataFrame(out, index=x.index, columns=y.columns)


def ridge_reference(x: np.ndarray, y: np.ndarray, x_now: np.ndarray, lam: float) -> np.ndarray:
    """The same fit written out directly on one training sample – the test oracle for `ridge_path`."""
    mu, sd = x.mean(axis=0), x.std(axis=0, ddof=1)
    z = (x - mu) / sd
    yc = y - y.mean(axis=0)
    n = len(x)
    beta = np.linalg.solve(z.T @ z + lam * n * np.eye(x.shape[1]), z.T @ yc)
    return np.asarray(((x_now - mu) / sd) @ beta)


def ridge_coefficients(x: pd.DataFrame, y: pd.DataFrame, lam: float) -> pd.DataFrame:
    """The standardised slopes (variables × classes) of the fit on every complete row of `x`/`y` – for reports:
    which way each Fed variable pushes each class in the last fit."""
    ok = x.notna().all(axis=1) & y.notna().all(axis=1)
    xs, ys = x[ok].to_numpy(dtype=float), y[ok].to_numpy(dtype=float)
    z = (xs - xs.mean(axis=0)) / xs.std(axis=0, ddof=1)
    n = len(xs)
    beta = np.linalg.solve(z.T @ z + lam * n * np.eye(z.shape[1]), z.T @ (ys - ys.mean(axis=0)))
    return pd.DataFrame(beta, index=x.columns, columns=y.columns)
