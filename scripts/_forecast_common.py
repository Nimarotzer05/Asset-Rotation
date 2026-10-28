"""Shared pieces of the forecast research scripts (evaluation, paper rule, holdout).

Every script takes `--config <name>` (default `forecast`, the round-1 model): the forecast config of that
name in configs/forecast*.yaml is evaluated and the outputs go to output/<name>/. The round-1 run with the
default keeps producing the files it produced before round 2 existed.
"""

from __future__ import annotations

import argparse
import os
from datetime import date

import pandas as pd

from rotationlab.config.models import Bundle, ForecastConfig, load_bundle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = 0.90
REGISTER = os.path.join(ROOT, "docs", "TRIALS.yaml")  # Versuchsregister (ADR 056)


def md_table(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join([df.index.name or "", *map(str, cols)]) + " |", "|" + "---|" * (len(cols) + 1)]
    ints = {c for c in cols if pd.api.types.is_integer_dtype(df[c])}
    for i, row in df.iterrows():  # iterrows upcasts mixed rows to float: integer columns go by dtype
        cells = [
            str(int(row[c]))
            if c in ints
            else (floatfmt.format(row[c]) if isinstance(row[c], float) else str(row[c]))
            for c in cols
        ]
        lines.append("| " + " | ".join([str(i), *cells]) + " |")
    return "\n".join(lines)


def ci_text(c) -> str:  # type: ignore[no-untyped-def]
    return f"{c.mean:+.4f} [{c.low:+.4f}, {c.high:+.4f}] (n = {c.n})"


def p_text(p: float, draws: int) -> str:
    """A permutation p-value is a share of draws: zero means 'below the resolution', not zero."""
    return f"< {1 / draws:.4f} (0 von {draws} Ziehungen)" if p == 0 else f"{p:.4f}"


def parse_args(doc: str, *extra: tuple[str, dict[str, object]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=doc.splitlines()[0])
    ap.add_argument("--config", default="forecast", help="forecast config name (configs/<name>.yaml)")
    for flag, kw in extra:
        ap.add_argument(flag, **kw)  # type: ignore[arg-type]
    return ap.parse_args()


def load(config: str) -> tuple[Bundle, ForecastConfig, str]:
    """The bundle, the forecast config of that name and its output directory (created)."""
    b = load_bundle(os.path.join(ROOT, "configs"))
    if config not in b.forecasts:
        raise SystemExit(f"unknown forecast config '{config}'; known: {sorted(b.forecasts)}")
    out = os.path.join(ROOT, "output", config)
    os.makedirs(out, exist_ok=True)
    return b, b.forecasts[config], out


def display_decades(fc: ForecastConfig) -> list[tuple[str, int, int]]:
    """The complete decades of the criterion plus, in front, the partial one the window starts in."""
    dec = list(fc.evaluation.decades)
    y0, first = fc.evaluation.start.year, dec[0][1]
    if y0 < first:
        dec.insert(0, (f"{y0}–{first - 1}", y0, first - 1))
    return dec


def bond_class(b: Bundle, ranked: list[str]) -> str:
    """The Treasury leg of the 60/40 baseline: the first ranked bond class."""
    return next(a for a in ranked if b.universe.assets[a].asset_class == "bond")


def years(a: date | pd.Timestamp, z: date | pd.Timestamp) -> str:
    return f"{pd.Timestamp(a).year}–{pd.Timestamp(z).year}"


def register(include_planned: bool = False) -> tuple[int, pd.Series]:
    """The trial register (docs/TRIALS.yaml): N = every variant ever scored on the overlapping history, and the
    annualised appraisal ratio (Sharpe of the beta-adjusted residual against its baseline) of every trial with a
    stored series – the statistic the deflated Sharpe tests (ADR 056: the variance must be that of the tested
    statistic, and the statistic must not reward a different level of risk)."""
    import numpy as np
    import yaml

    from rotationlab.forecast.evaluation import appraisal_residual

    with open(REGISTER, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    n = sum(int(e["count"]) for e in doc.get("unstored", [])) + len(doc.get("stored", []))
    if include_planned:
        n += sum(int(e["count"]) for e in doc.get("planned", []))
    sharpes: dict[str, float] = {}
    for e in doc.get("stored", []):
        df = pd.read_csv(os.path.join(ROOT, e["file"]), index_col=0)
        a = appraisal_residual(df[e["column"]], df[e["baseline"]], df["cash"])
        sharpes[str(e["name"])] = float(a.mean() / a.std(ddof=1) * np.sqrt(12))
    return n, pd.Series(sharpes, dtype=float)


def trials_variance(extra: pd.Series | None = None) -> float:
    """Variance of the monthly (not annualised) appraisal ratios across the stored trials, together with `extra`
    – the annualised appraisal ratios of the runs of the round being scored, which are produced in the same run
    (ADR 058: the variance must include the round's own trials)."""
    import numpy as np

    _, sh = register()
    if extra is not None and len(extra):
        sh = pd.concat([sh, extra.astype(float)])
    return float((sh / np.sqrt(12)).var(ddof=1))
