"""README figures (docs/figures/*.png) from the stored results – rerun after any result changes.

tests.png         every pre-registered comparison: paired Sharpe difference with its 90 % block-bootstrap interval
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

# label, Δ Sharpe, low, high – the paired comparisons as stored in output/*/…paired.csv and WALKFORWARD.md
TESTS = [
    ("Round 1  rule vs equal weight (1974–2018)", 0.181, -0.011, 0.395),
    ("Round 2  rule vs equal weight (1981–2018)", 0.274, -0.084, 0.556),
    ("Round 3  allocator vs risk parity (1979–2026)", -0.002, -0.188, 0.164),
    ("Round 4  allocator vs risk parity (1977–2025)", 0.285, 0.140, 0.430),
    ("  … of which cross-sectional signals", -0.001, -0.069, 0.060),
    ("  … since 2008 only", 0.080, -0.175, 0.277),
    ("ETF check  trend filter vs risk parity (2008–2026)", 0.064, -0.215, 0.199),
]
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
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    y = np.arange(len(TESTS))[::-1]
    for yi, (_, v, lo, hi) in zip(y, TESTS, strict=True):
        sig = lo > 0
        colour = BLUE if sig else MUTED
        ax.plot([lo, hi], [yi, yi], color=colour, lw=2, solid_capstyle="round")
        ax.plot(v, yi, "o", ms=8, color=BLUE if sig else SURF, mec=colour, mew=2, zorder=3)
        value = f"{v:+.3f}" if abs(v) < 0.01 else f"{v:+.2f}"
        ax.text(hi + 0.02, yi, f"{value}  [{lo:+.2f}, {hi:+.2f}]", va="center", fontsize=8.5, color=INK2)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(y, [t[0] for t in TESTS], fontsize=9, color=INK)
    ax.set_xlim(-0.35, 0.95)
    ax.set_xlabel("Paired Sharpe difference (90 % block-bootstrap interval)")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.suptitle(
        "Every pre-registered test: only round 4's main comparison excludes zero",
        x=0.01,
        ha="left",
        fontsize=11,
        color=INK,
    )
    fig.text(
        0.01,
        0.01,
        "Filled dot = interval excludes zero. Sources: output/forecast, forecast_v2, allocator, allocator_v2, etf_check.",
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
