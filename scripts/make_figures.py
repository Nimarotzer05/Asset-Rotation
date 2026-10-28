"""README figures (docs/figures/*.png) from the stored results – rerun after any result changes.

tests.png         the pre-registered primary tests and round 4's breakdowns: paired Sharpe difference, 90 % interval
round4_growth.png round 4: allocator, the same book without cross-sectional selection, passive risk parity

Colours: the validated categorical palette of the data-viz guidance (blue, orange, aqua; aqua is below 3:1 contrast,
so every line is labelled directly), recessive grid, one axis.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "figures")
SURF, INK, INK2, MUTED, GRID, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#f1f0ec"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"

# label, file, baseline row, Sharpe columns (Δ, low, high) – the paired comparisons as each study stored them
PAIRED = [
    ("Round 1  rule vs equal weight (1974–2018)", "forecast/portfolio_paired.csv", "Equal Weight (4 Klassen)", ("Δ Sharpe", "low ", "high ")),
    ("Round 2  rule vs equal weight (1981–2018)", "forecast_v2/portfolio_paired.csv", "Equal Weight (5 Klassen)", ("Δ Sharpe", "low ", "high ")),
    ("Round 3  allocator vs risk parity (1979–2026)", "allocator/walkforward_paired.csv", "B1 Risikoparität ohne Signale", ("Δ Sharpe", "low ", "high ")),
    ("Round 4  allocator vs risk parity (1977–2025)", "allocator_v2/walkforward_paired.csv", "B1 passive Risikoparität", ("Δ Sharpe", "low", "high")),
]
ETF = ("ETF check  trend filter vs risk parity (2008–2026)", "etf_check/paired.csv", "B1 Risikoparität ohne Filter (ETF)", ("Δ Sharpe", "low", "high"))
R4 = "allocator_v2/walkforward_monthly.csv"  # the two round-4 breakdowns are recomputed from its monthly series


def stored(file: str, baseline: str, cols: tuple[str, str, str]) -> tuple[float, float, float]:
    row = pd.read_csv(os.path.join(ROOT, "output", file), index_col=0).loc[baseline]
    return float(row[cols[0]]), float(row[cols[1]]), float(row[cols[2]])


def tests() -> list[tuple[str, float, float, float]]:
    """Every value from output/: the stored paired files, and for round 4's breakdowns the same paired block
    bootstrap the study used (2000 draws, block 12, seed 20261025, 90 %) on its stored monthly returns."""
    import sys

    sys.path.insert(0, ROOT)
    from rotationlab.forecast.evaluation import paired_sharpe_diff
    from rotationlab.forecast.model import BlockBootstrap

    boot = BlockBootstrap(2000, 12, 20261025)
    df = pd.read_csv(os.path.join(ROOT, "output", R4), index_col=0, parse_dates=True)
    main, ablation, b1, cash = (
        df["Allokator v2 (ADR 057/058)"],
        df["ohne Querschnitt"],
        df["B1 passive Risikoparität"],
        df["cash"],
    )
    since = df.index >= "2008-01-01"
    d_x = paired_sharpe_diff(main, ablation, cash, boot, 0.90)
    d_08 = paired_sharpe_diff(main[since], b1[since], cash[since], boot, 0.90)
    rows = [(label, *stored(f, b, c)) for label, f, b, c in PAIRED]
    rows += [
        ("  … of which cross-sectional signals", d_x.value, d_x.low, d_x.high),
        ("  … since 2008 only", d_08.value, d_08.low, d_08.high),
        (ETF[0], *stored(*ETF[1:])),
    ]
    return rows


GROWTH = [  # label, column of output/allocator_v2/walkforward_monthly.csv, colour, line style
    ("Allocator v2 (Sharpe 0.79)", "Allokator v2 (ADR 057/058)", BLUE, "-"),
    ("Risk parity + trend filter, no selection (0.79)", "ohne Querschnitt", ORANGE, "--"),
    ("Passive risk parity B1 (0.51)", "B1 passive Risikoparität", AQUA, "-"),
]


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK2,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "figure.facecolor": SURF,
            "axes.facecolor": SURF,
        }
    )


def tests_figure(path: str) -> None:
    rows = tests()
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    y = np.arange(len(rows))[::-1]
    for yi, (_, v, lo, hi) in zip(y, rows, strict=True):
        sig = lo > 0
        colour = BLUE if sig else MUTED
        ax.plot([lo, hi], [yi, yi], color=colour, lw=2, solid_capstyle="round")
        ax.plot(v, yi, "o", ms=8, color=BLUE if sig else SURF, mec=colour, mew=2, zorder=3)
        ax.text(hi + 0.02, yi, f"{v:+.3f}  [{lo:+.3f}, {hi:+.3f}]", va="center", fontsize=8.5, color=INK2)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(y, [t[0] for t in rows], fontsize=9, color=INK)
    ax.set_xlim(-0.35, 1.05)
    ax.set_xlabel("Paired Sharpe difference (90 % block-bootstrap interval)")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.suptitle(
        "Primary tests and round 4's breakdowns: only round 4's main comparison excludes zero",
        x=0.01,
        ha="left",
        fontsize=11,
        color=INK,
    )
    fig.text(
        0.01,
        0.01,
        "Filled dot = interval excludes zero. Rows 1–4 and 7 are the pre-registered primary tests; rows 5–6 are breakdowns of round 4. Source: output/.",
        fontsize=7.5,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def growth_figure(path: str) -> None:
    df = pd.read_csv(
        os.path.join(ROOT, "output", "allocator_v2", "walkforward_monthly.csv"), index_col=0, parse_dates=True
    )
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    for label, column, colour, line in GROWTH:
        g = (1 + df[column]).cumprod()
        ax.plot(g.index, g, color=colour, lw=2, ls=line)
        ax.text(g.index[-1] + pd.Timedelta(days=120), g.iloc[-1], label, color=INK2, fontsize=8.5, va="center")
    ax.set_yscale("log")
    ax.set_ylabel("Growth of 1 (log scale)")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.axvspan(pd.Timestamp("2008-01-01"), df.index[-1], color=BAND, zorder=0)
    ax.text(pd.Timestamp("2008-03-01"), ax.get_ylim()[0] * 1.15, "since 2008: no significant edge", fontsize=8, color=MUTED)
    ax.set_xlim(df.index[0], df.index[-1] + pd.Timedelta(days=4200))
    years = range(1980, 2030, 10)
    ax.set_xticks([pd.Timestamp(f"{yr}-01-01") for yr in years], [str(yr) for yr in years])
    ax.set_title("Round 4 (1977–2025): the edge over risk parity is the trend filter", loc="left", fontsize=11, color=INK)
    fig.text(
        0.01,
        0.01,
        "Monthly returns after costs. Same Sharpe: the allocator ends higher only because it runs at more volatility "
        "(8.0 % vs 6.8 %). Source: output/allocator_v2.",
        fontsize=7.5,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    style()
    tests_figure(os.path.join(OUT, "tests.png"))
    growth_figure(os.path.join(OUT, "round4_growth.png"))
    print(f"written: {OUT}/tests.png, {OUT}/round4_growth.png")


if __name__ == "__main__":
    main()
