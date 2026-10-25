"""Vom Feature-Set zum Portfolio: Cross-Sectional z-Scores → Composite → Gewichte."""
from __future__ import annotations

import numpy as np
import pandas as pd


def zscore_cross_section(df: pd.DataFrame) -> pd.DataFrame:
    """z-Standardisierung über Assets pro Datum (Zeile)."""
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0).clip(-3, 3)


def composite_score(
    feats: dict[str, pd.DataFrame],
    weights: dict[str, float],
    regime: pd.DataFrame | None = None,
    regime_tilts: dict | None = None,
) -> pd.DataFrame:
    total = sum(weights.values())
    score = None
    for name, w in weights.items():
        z = zscore_cross_section(feats[name]) * (w / total)
        score = z if score is None else score.add(z, fill_value=0)

    if regime is not None and regime_tilts:
        tilt = pd.DataFrame(0.0, index=score.index, columns=score.columns)
        reg = regime.reindex(score.index)
        for (g, i), bonus in regime_tilts.items():
            mask = (reg["growth"] == g) & (reg["inflation"] == i)
            for asset, b in bonus.items():
                if asset in tilt.columns:
                    tilt.loc[mask, asset] += b
        score = score + tilt
    return score


def build_weights(
    score: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    top_n: int = 3,
    trend_filter: bool = True,
    vol_window: int = 12,
) -> pd.DataFrame:
    """Top-N nach Score, inverse-Vol-gewichtet. Rest (Trendfilter) → Cash-Spalte."""
    rets = monthly_prices.pct_change()
    vol = rets.rolling(vol_window).std()
    above_trend = monthly_prices > monthly_prices.rolling(10).mean()

    weights = pd.DataFrame(0.0, index=score.index, columns=list(score.columns) + ["CASH"])
    for t in score.index:
        s = score.loc[t].dropna()
        if len(s) < top_n:
            weights.loc[t, "CASH"] = 1.0
            continue
        picks = s.sort_values(ascending=False).index[:top_n]
        iv = 1 / vol.loc[t, picks]
        iv = iv.replace([np.inf, -np.inf], np.nan).dropna()
        if iv.empty:
            weights.loc[t, "CASH"] = 1.0
            continue
        w = iv / iv.sum()
        if trend_filter:
            keep = above_trend.loc[t, w.index]
            cash = w[~keep].sum()
            w = w[keep]
            weights.loc[t, "CASH"] = cash
        weights.loc[t, w.index] = w.values
    return weights
