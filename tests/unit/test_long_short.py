"""ADR 063 (a): the leveraged long-short rule's accounting on hand-checked inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rotationlab.forecast.long_short import Frictions, picks, run_long_short

IDX = pd.date_range("2000-01-31", periods=5, freq="ME")
NONE = Frictions(cost_bps=0.0, financing_spread=0.0, borrow={})


def _returns(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=IDX[1 : len(rows) + 1], columns=["A", "B", "C"])


def _choice(pairs: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(pairs, index=IDX[: len(pairs)], columns=["long", "short"])


def test_picks_first_and_last_rank() -> None:
    ranks = pd.DataFrame({"A": [1.0, 3.0, np.nan], "B": [2.0, 1.0, 1.0], "C": [3.0, 2.0, 2.0]}, index=IDX[:3])
    p = picks(ranks)
    assert p.iloc[0].tolist() == ["A", "C"] and p.iloc[1].tolist() == ["B", "A"]
    assert p.iloc[2].isna().all()  # incomplete ranking: no new information
    empty = pd.DataFrame(
        {"A": [np.nan, 1.0], "B": [np.nan, 2.0]}, index=IDX[:2]
    )  # panel start: no value at all
    assert picks(empty).iloc[0].isna().all() and picks(empty).iloc[1].tolist() == ["A", "B"]


def test_one_month_closed_form_with_frictions() -> None:
    r = _returns([[0.04, -0.02, 0.01]])
    cash = pd.Series(0.003, index=IDX)
    fr = Frictions(cost_bps=10.0, financing_spread=0.012, borrow={"B": 0.024})
    out = run_long_short(_choice([("A", "B")]), r, cash, 1.5, "per_leg", fr).monthly
    expect = (
        0.003
        + 1.5 * (0.04 - 0.003)
        - 1.5 * (-0.02 - 0.003)
        - 0.5 * 0.012 / 12
        - 1.5 * 0.024 / 12
        - 3.0 * 0.001
    )
    assert out["ret"].iloc[0] == pytest.approx(expect, abs=1e-15)
    assert out["traded"].iloc[0] == pytest.approx(3.0) and out.index[0] == IDX[1]


def test_unchanged_pair_is_not_traded_and_drifts() -> None:
    r = _returns([[0.10, -0.10, 0.0], [0.0, 0.0, 0.0]])
    cash = pd.Series(0.0, index=IDX)
    out = run_long_short(_choice([("A", "B"), ("A", "B")]), r, cash, 1.5, "per_leg", NONE).monthly
    r1 = 1.5 * 0.10 + 1.5 * 0.10
    assert out["ret"].iloc[0] == pytest.approx(r1)
    assert out["traded"].iloc[1] == 0.0
    assert out["long_size"].iloc[1] == pytest.approx(1.5 * 1.10 / (1 + r1))
    assert out["short_size"].iloc[1] == pytest.approx(1.5 * 0.90 / (1 + r1))
    reset = run_long_short(_choice([("A", "B"), ("A", "B")]), r, cash, 1.5, "reset", NONE).monthly
    assert reset["long_size"].iloc[1] == 1.5 and reset["traded"].iloc[1] == pytest.approx(
        abs(1.5 - out["long_size"].iloc[1]) + abs(1.5 - out["short_size"].iloc[1])
    )


def test_only_the_changed_leg_is_traded() -> None:
    r = _returns([[0.05, 0.0, 0.02], [0.0, 0.0, 0.0]])
    cash = pd.Series(0.0, index=IDX)
    out = run_long_short(_choice([("A", "B"), ("A", "C")]), r, cash, 1.5, "per_leg", NONE).monthly
    r1 = 1.5 * 0.05  # B did not move, but equity did: both legs drift relative to it
    lw = 1.5 * 1.05 / (1 + r1)
    sw = 1.5 * 1.0 / (1 + r1)
    assert out["traded"].iloc[1] == pytest.approx(sw + 1.5)  # buy back B, sell C; the long A is untouched
    assert out["long_size"].iloc[1] == pytest.approx(lw) and out["short_size"].iloc[1] == 1.5
    assert out[["long", "short"]].iloc[1].tolist() == ["A", "C"]


def test_missing_ranking_keeps_the_book() -> None:
    r = _returns([[0.01, 0.0, 0.0], [0.01, 0.0, 0.0]])
    cash = pd.Series(0.0, index=IDX)
    ch = _choice([("A", "B"), ("A", "B")])
    ch.iloc[1] = np.nan
    out = run_long_short(ch, r, cash, 1.5, "per_leg", NONE).monthly
    assert len(out) == 2 and out["traded"].iloc[1] == 0.0 and out["long"].iloc[1] == "A"


def test_ruin_ends_the_series() -> None:
    r = _returns([[-0.40, 0.40, 0.0], [0.10, 0.0, 0.0]])
    cash = pd.Series(0.0, index=IDX)
    res = run_long_short(_choice([("A", "B"), ("A", "B")]), r, cash, 1.5, "per_leg", NONE)
    assert res.ruin == IDX[1] and len(res.monthly) == 1 and res.monthly["ret"].iloc[0] == -1.0
    assert res.monthly["drawdown"].iloc[0] == -1.0


def test_leverage_one_has_no_financing() -> None:
    r = _returns([[0.02, 0.01, 0.0]])
    cash = pd.Series(0.004, index=IDX)
    fr = Frictions(cost_bps=0.0, financing_spread=0.05, borrow={})
    out = run_long_short(_choice([("A", "B")]), r, cash, 1.0, "per_leg", fr).monthly
    assert out["financing"].iloc[0] == 0.0 and out["ret"].iloc[0] == pytest.approx(0.004 + 0.02 - 0.01)


def test_missing_return_of_a_held_class_is_an_error() -> None:
    r = _returns([[np.nan, 0.0, 0.0]])
    with pytest.raises(ValueError, match="missing return"):
        run_long_short(_choice([("A", "B")]), r, pd.Series(0.0, index=IDX), 1.5, "per_leg", NONE)
