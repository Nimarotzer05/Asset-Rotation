"""ADR 069: trend filter and turn-of-the-month rule on hand-checked inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rotationlab.forecast.fresh_data import (
    month_end_levels,
    monthly,
    trend_filter,
    turn_of_month,
    turn_of_month_days,
)


def test_month_end_levels_take_the_last_close() -> None:
    idx = pd.to_datetime(["2000-01-28", "2000-01-31", "2000-02-01", "2000-02-29"])
    out = month_end_levels(pd.Series([1.0, 2.0, 3.0, 4.0], index=idx))
    assert out.tolist() == [2.0, 4.0] and out.index[0] == pd.Timestamp("2000-01-31")


def test_trend_filter_decides_at_t_and_earns_t_plus_1() -> None:
    idx = pd.date_range("2000-01-31", periods=6, freq="ME")
    lv = pd.Series([100.0, 110.0, 120.0, 90.0, 80.0, 100.0], index=idx)
    cash = pd.Series(0.01, index=idx)
    out = trend_filter(lv, cash, window=2)
    # decision at 02-29: 110 > mean(100, 110) → invested in March (+9.09 %); at 04-30: 90 < 105 → cash in May
    assert out.loc["2000-03-31", "invested"] == 1.0 and out.loc["2000-03-31", "ret"] == pytest.approx(
        120 / 110 - 1
    )
    assert out.loc["2000-05-31", "invested"] == 0.0 and out.loc["2000-05-31", "ret"] == pytest.approx(0.01)
    assert out.loc["2000-04-30", "invested"] == 1.0  # 120 > 115 at 03-31
    assert out.loc["2000-05-31", "switch"] == 1.0 and out.loc["2000-04-30", "switch"] == 0.0
    assert out.loc["2000-03-31", "switch"] == 1.0  # the first investment is a trade


def test_trend_filter_has_no_lookahead() -> None:
    idx = pd.date_range("2000-01-31", periods=30, freq="ME")
    lv = pd.Series(100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.05, 30)), index=idx)
    cash = pd.Series(0.0, index=idx)
    a = trend_filter(lv, cash)
    lv2 = lv.copy()
    lv2.iloc[20:] *= 3.0  # the future changes from month 20 on
    b = trend_filter(lv2, cash)
    # the position held in month 20 was decided at the close of month 19: everything up to it is the same
    assert a["invested"].loc[: idx[20]].equals(b["invested"].loc[: idx[20]])
    assert not a["invested"].loc[idx[21] :].equals(b["invested"].loc[idx[21] :])


def test_turn_of_month_days() -> None:
    idx = pd.bdate_range("2000-01-03", "2000-02-29")
    tom = turn_of_month_days(idx)
    on = tom[tom].index.strftime("%m-%d").tolist()
    assert on == ["01-03", "01-04", "01-05", "01-31", "02-01", "02-02", "02-03", "02-29"]


def test_turn_of_month_returns_switch_between_equity_and_cash() -> None:
    idx = pd.bdate_range("2000-01-03", "2000-02-28")
    eq = pd.Series(100 * 1.01 ** np.arange(len(idx)), index=idx)  # +1 % every day
    rf = pd.Series(1.0001 ** np.arange(len(idx)), index=idx)  # +0.01 % every day
    out = turn_of_month(eq, rf).loc["2000-01-10":]
    inm = out[out["in_market"] == 1].index.strftime("%m-%d").tolist()
    assert inm == ["01-31", "02-01", "02-02", "02-03", "02-28"]
    assert out.loc["2000-01-31", "ret"] == pytest.approx(0.01) and out.loc[
        "2000-01-28", "ret"
    ] == pytest.approx(0.0001)
    assert out.loc[:"2000-02-25", "switch"].sum() == 2.0  # one entry (01-31), one exit (02-04)
    m = monthly(out["ret"])
    # February: 3 equity days, 17 cash days (02-04 … 02-25), the last day (02-28) equity again
    assert m.loc["2000-02-29"] == pytest.approx(1.01**4 * 1.0001**16 - 1)
