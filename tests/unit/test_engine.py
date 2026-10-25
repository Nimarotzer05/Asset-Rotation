"""Engine, book, costs, metrics, combiners, recorder and episodes."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rotationlab.config.models import CostSpec
from rotationlab.core.clock import MonthEndClock, WeekdayCalendar
from rotationlab.core.errors import ConfigError, DataError
from rotationlab.core.types import (
    CASH,
    AssetId,
    Mode,
    Proposal,
    RiskAction,
    StrategyId,
    StrategyState,
    Targets,
)
from rotationlab.engine import metrics
from rotationlab.engine.core import Engine, prices_at, target_weights
from rotationlab.engine.recorder import RunRecorder, git_sha
from rotationlab.portfolio.book import Book
from rotationlab.portfolio.combine import CapitalWeights, SingleStrategy
from rotationlab.portfolio.costs import CostModel
from rotationlab.stats import change_over, drawdown_episodes
from rotationlab.strategies.base import BaseStrategy
from src import metrics as research_metrics
from tests.fixtures.toy import Toy, spec

D0 = date(2026, 1, 30)


def targets(w: dict[str, float], d: date = D0) -> Targets:
    return Targets(d, {AssetId(a): x for a, x in w.items()}, {}, 1.0)


# ---------------------------------------------------------------------------- costs
def test_cost_model_rates_cash_leg_and_borrow(bundle) -> None:
    c = CostModel({"A": 5.0}, default_bps=10.0, cash_bps=2.0, borrow_bps={"S": 365.0})
    assert c.cost({"A": 0.5, "B": -0.2, CASH: -0.3}) == pytest.approx((0.5 * 5 + 0.2 * 10 + 0.3 * 2) / 1e4)
    assert c.carry({"S": -0.5, "A": 0.5}, days=10) == pytest.approx(0.5 * 365 / 1e4 * 10 / 365)
    assert c.turnover_cost({"A": 1.0}, {"A": 0.5, CASH: 0.5}) == pytest.approx((0.5 * 5 + 0.5 * 2) / 1e4)
    u = CostModel.from_config(CostSpec(), bundle.universe)
    assert u.bps("SPY") == 5 and u.bps("SLV") == 10 and u.bps(CASH) == 0
    assert u.carry({"SLV": -1.0}, 365) == pytest.approx(150 / 1e4)
    r = CostModel.from_config(
        CostSpec(default_bps=7.5, cash_bps=7.5, per_asset={"SPY": 1.0}), bundle.universe
    )
    assert r.bps("GLD") == 7.5 and r.bps("SPY") == 1.0 and r.bps(CASH) == 7.5


# ---------------------------------------------------------------------------- book
def test_book_rebalances_marks_and_pays_costs() -> None:
    b = Book("BIL", CostModel(default_bps=10.0), capital=100.0)
    b.mark({"A": 10.0, "B": 20.0, "BIL": 1.0}, D0)
    cost = b.rebalance(targets({"A": 0.6, "B": 0.3}), {}, D0)
    assert cost == pytest.approx(100 * 0.9 * 10 / 1e4)
    w = b.weights()
    assert w["A"] == pytest.approx(0.6) and w["B"] == pytest.approx(0.3) and w[CASH] == pytest.approx(0.1)
    e0 = b.equity()
    b.mark({"A": 11.0, "B": 20.0, "BIL": 1.001}, date(2026, 2, 27))
    assert b.equity() == pytest.approx(e0 * (1 + 0.6 * 0.1 + 0.1 * 0.001))
    b.rebalance(targets({"A": 0.6, "B": 0.3}), {}, date(2026, 2, 27))  # drift back to target costs a little
    assert 0 < b.trades[-1]["turnover"] < 0.05
    assert b.drawdown() <= 0 and b.snapshot()["weights"][CASH] == pytest.approx(0.1)
    with pytest.raises(DataError, match="no price"):
        b.rebalance(targets({"Z": 0.1}), {}, date(2026, 2, 27))


def test_book_shorts_carry_and_risk_actions() -> None:
    c = CostModel(default_bps=0.0, borrow_bps={"S": 365.0})
    b = Book("BIL", c, capital=100.0)
    b.rebalance(targets({"G": 0.5, "S": -0.5}), {"G": 10.0, "S": 10.0, "BIL": 1.0}, D0)
    assert b.weights()[CASH] == pytest.approx(1.0)
    b.mark({"G": 10.0, "S": 10.0, "BIL": 1.0}, date(2026, 2, 9))  # 10 days of borrow on 50 %
    assert b.equity() == pytest.approx(100 - 100 * 0.5 * 365 / 1e4 * 10 / 365)
    before = b.weights()
    b.apply(
        RiskAction(date(2026, 2, 9), "stop", "halve", (AssetId("G"), AssetId("S")), "ratio"),
        {},
        date(2026, 2, 9),
    )
    assert b.weights()["G"] == pytest.approx(before["G"] / 2) and b.weights()["S"] == pytest.approx(
        before["S"] / 2
    )
    b.apply(RiskAction(date(2026, 2, 9), "stop", "close", (), "all"), {}, date(2026, 2, 9))
    assert set(b.weights()) == {CASH}


def test_book_before_the_cash_asset_has_a_price() -> None:
    b = Book("BIL", CostModel(default_bps=0.0), capital=50.0)
    b.mark({}, D0)
    assert b.equity() == 50.0 and b.weights() == {CASH: 1.0}
    b.mark({"BIL": 2.0}, date(2026, 2, 2))
    assert b.cash_units == 25.0


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.floats(-0.6, 0.6), min_size=1, max_size=4),
    st.lists(st.floats(1.0, 500.0), min_size=4, max_size=4),
    st.floats(0.0, 50.0),
)
def test_rebalance_hits_the_targets_and_loses_exactly_the_cost(ws, prices, bps) -> None:
    names = ["A", "B", "C", "D"][: len(ws)]
    px = {**dict(zip(["A", "B", "C", "D"], prices, strict=True)), "BIL": 1.0}
    b = Book("BIL", CostModel(default_bps=bps), capital=100.0)
    b.rebalance(targets({"A": 0.3}), px, D0)
    e = b.equity()
    cost = b.rebalance(targets(dict(zip(names, ws, strict=True))), px, D0)
    assert b.equity() == pytest.approx(e - cost, rel=1e-12)
    w = b.weights()
    for n, x in zip(names, ws, strict=True):
        assert w.get(AssetId(n), 0.0) == pytest.approx(x, abs=1e-12)
    assert sum(w.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------- combiners
class Hold(BaseStrategy):
    strategy_id = "hold"

    def propose(self, view, state: StrategyState) -> tuple[Proposal, StrategyState]:
        n = int(state.extra.get("n", 0))
        if n < self.params.get("warm", 0):
            return self.warmup_proposal(view, "toy"), StrategyState(state.strategy_id, extra={"n": n + 1})
        return self.proposal(view, dict(self.params["w"]), 1.0), StrategyState(
            state.strategy_id, extra={"n": n + 1}
        )


def test_combiners() -> None:
    v = Toy().monthly("A", [1.0, 2.0]).factory().at(date(2000, 2, 29))
    p1 = Proposal(StrategyId("x"), v.date, {AssetId("A"): 0.5}, 1.0, 1)
    p2 = Proposal(StrategyId("y"), v.date, {AssetId("B"): 1.0}, 1.0, 1)
    t = SingleStrategy().combine([p1], v)
    assert t.weights == {"A": 0.5, CASH: 0.5} and target_weights(p1) == t.weights
    with pytest.raises(ConfigError):
        SingleStrategy().combine([p1, p2], v)
    c = CapitalWeights({"x": 3, "y": 1}).combine([p1, p2], v)
    assert c.weights["A"] == pytest.approx(0.375) and c.weights["B"] == pytest.approx(0.25)
    assert c.weights[CASH] == pytest.approx(0.375) and set(c.by_strategy) == {"x", "y"}
    with pytest.raises(ConfigError):
        CapitalWeights({"x": 0})


# ---------------------------------------------------------------------------- engine
def _monthly_world():
    a = [100 * 1.02**k for k in range(24)]
    return Toy().monthly("A", a).cash("RF", 0.001, n=24).factory()


def test_engine_books_the_research_monthly_return() -> None:
    f = _monthly_world()
    s = Hold(spec("hold", ["A", "RF"], {"cash": "RF", "w": {"A": 0.5}, "warm": 2}))
    clock = MonthEndClock(f.cal, date(2000, 1, 31), date(2001, 12, 31))
    res = Engine(
        f, clock, [s], SingleStrategy(), Book("RF", CostModel(default_bps=0.0)), execution="same_close"
    ).run()
    r, c = res.returns, res.cash_returns
    assert len(r) == 23 and c.iloc[-1] == pytest.approx(0.001)
    assert r.iloc[0] == pytest.approx(0.001) and r.iloc[1] == pytest.approx(0.001)  # warm-up: cash
    assert r.iloc[2] == pytest.approx(0.5 * 0.02 + 0.5 * 0.001, rel=1e-9)  # ½ A + ½ cash, no drift cost
    assert res.active.tolist()[:3] == [False, False, True]
    m_all, m_active = res.metrics(), res.metrics(count_warmup=False)
    assert m_all["months"] == 23 and m_active["months"] == 21
    assert res.weights["A"].iloc[-1] == 0.5 and res.decisions["warmup"].sum() == 2
    nxt = Engine(
        f, clock, [s], SingleStrategy(), Book("RF", CostModel(default_bps=0.0)), execution="next_close"
    ).run()
    assert np.allclose(nxt.returns, r)  # monthly data: the next session prices at month-end


def test_next_close_uses_the_following_session_for_daily_data() -> None:
    days = pd.bdate_range("2000-01-03", "2000-04-28")
    px = pd.Series(100 * 1.001 ** np.arange(len(days)), index=days)
    f = Toy().daily("A", px).cash("RF", 0.0, n=4).factory()
    s = Hold(spec("hold", ["A", "RF"], {"cash": "RF", "w": {"A": 1.0}}))
    clock = MonthEndClock(WeekdayCalendar(), date(2000, 1, 31), date(2000, 4, 30))
    same = Engine(
        f, clock, [s], SingleStrategy(), Book("RF", CostModel(default_bps=0.0)), execution="same_close"
    ).run()
    nxt = Engine(
        f, clock, [s], SingleStrategy(), Book("RF", CostModel(default_bps=0.0)), execution="next_close"
    ).run()
    assert same.returns.iloc[0] == pytest.approx(px["2000-02-29"] / px["2000-01-31"] - 1)
    assert nxt.returns.iloc[0] == pytest.approx(px["2000-02-29"] / px["2000-02-01"] - 1)
    assert nxt.decisions["execution"].iloc[0] == pd.Timestamp("2000-02-01")
    assert prices_at(f.at(date(2000, 1, 4)), ["A", "RF"]) == {
        "A": pytest.approx(px["2000-01-04"])
    }  # RF not yet
    assert prices_at(f.at(date(2000, 2, 1)), []) == {}


def test_recorder_writes_a_reproducible_record(tmp_path) -> None:
    f = _monthly_world()
    s = Hold(spec("hold", ["A", "RF"], {"cash": "RF", "w": {"A": 1.0}}))
    rec = RunRecorder(
        Mode.BACKTEST, "cfg123", f.data_snapshot(), date(2000, 1, 31), date(2000, 6, 30), label="toy"
    )
    clock = MonthEndClock(f.cal, date(2000, 1, 31), date(2000, 6, 30))
    res = Engine(f, clock, [s], SingleStrategy(), Book("RF", CostModel()), recorder=rec).run()
    out = rec.write(tmp_path, res.decisions, res.weights, res.metrics())
    record = json.loads((out / "record.json").read_text())
    assert record["mode"] == "backtest" and record["config_hash"] == "cfg123" and record["status"] == "ok"
    assert record["run_id"].endswith("-backtest-toy") and record["metrics"]["months"] == 5
    lines = (out / "proposals.jsonl").read_text().splitlines()
    assert len(lines) == 6 and json.loads(lines[0])["weights"] == {"A": 1.0}
    assert (out / "decisions.csv").exists() and (out / "weights.csv").exists()
    rec.risk_event(D0, RiskAction(D0, "x", "flag", (), "toy"))
    assert rec.risk_events[0]["rule"] == "x" and isinstance(git_sha(tmp_path), str)


# ---------------------------------------------------------------------------- metrics, episodes
def test_metrics_equal_the_research_definitions() -> None:
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.008, 0.04, 240))
    c = pd.Series(rng.normal(0.003, 0.001, 240))
    m = metrics.summary(r, c, pd.Series(0.1, index=r.index))
    ref = research_metrics.summary(r, cash=c)
    assert m["ann_return"] == pytest.approx(ref["Ann. Return"]) and m["ann_vol"] == pytest.approx(
        ref["Ann. Vol"]
    )
    assert m["sharpe_ex_cash"] == pytest.approx(ref["Sharpe (ex Cash)"])
    assert m["max_drawdown"] == pytest.approx(ref["Max Drawdown"]) and m["calmar"] == pytest.approx(
        ref["Calmar"]
    )
    assert m["hit_rate"] == pytest.approx(ref["Hit Rate"]) and m["turnover_ann"] == pytest.approx(1.2)
    assert np.isnan(metrics.sharpe(pd.Series([0.01]))) and np.isnan(
        metrics.ann_return(pd.Series(dtype=float))
    )
    assert metrics.METRICS["mean_excess_ann"](r, c) == pytest.approx(m["mean_excess_ann"])


def test_drawdown_episodes() -> None:
    lvl = pd.Series(
        [100, 110, 90, 80, 100, 109, 120, 100, 95],
        index=pd.date_range("2000-01-31", periods=9, freq="ME"),
        dtype=float,
    )
    eps = drawdown_episodes(lvl, threshold=-0.15, recovery=-0.02)
    assert [(e.peak.month, e.trough.month) for e in eps] == [(2, 4), (7, 9)]  # the second is still open
    assert eps[0].depth == pytest.approx(80 / 110 - 1)
    other = lvl * 0 + pd.Series(np.arange(9.0) + 1, index=lvl.index)
    assert change_over(other, eps).tolist() == pytest.approx([4 / 2 - 1, 9 / 7 - 1])
    assert drawdown_episodes(pd.Series(dtype=float)) == []


# ---------------------------------------------------------------------------- modes (short windows of the real panel)
def test_modes_backtest_golden_report_and_recorder(bundle, static_store, static_factory, cal) -> None:
    from rotationlab.engine.modes import GoldenReport, backtest, golden, recorder_for

    res = backtest(
        bundle,
        static_factory,
        "commodity_trend",
        "long_history",
        date(2000, 1, 31),
        date(2002, 12, 31),
        "same_close",
        CostSpec(default_bps=10, cash_bps=10),
    )
    assert len(res.returns) == 35 and set(res.weights.columns) >= {CASH}
    gr = bundle.strategies["commodity_trend"].golden_run
    short = gr.model_copy(
        update={
            "start": date(1999, 12, 31),
            "end": date(2003, 12, 31),
            "sample": (date(2000, 1, 31), date(2003, 12, 31)),
        }
    )
    rep = golden(bundle, static_store.observations(), "commodity_trend", cal, run=short)
    assert rep.measured["months"] == 48 and set(rep.table().index) == {
        "sharpe_ex_cash",
        "ann_return",
        "max_drawdown",
    }
    assert isinstance(rep.failures(), list)
    fake = GoldenReport(
        "x", "same_close", {"a": 1.0, "b": 2.0}, {"a": 1.01, "b": 3.0, "c": 0.0}, {"a": 0.02}, res
    )
    assert fake.failures() == ["x.b: 2.0000 vs 3.0000 ± 0.0"] and list(fake.table().index) == ["a", "b"]
    with pytest.raises(ValueError, match="no golden_run"):
        golden(
            bundle.model_copy(
                update={
                    "strategies": {
                        **bundle.strategies,
                        "commodity_trend": bundle.strategies["commodity_trend"].model_copy(
                            update={"golden_run": None}
                        ),
                    }
                }
            ),
            static_store.observations(),
            "commodity_trend",
            cal,
        )
    rec = recorder_for(bundle, static_factory, Mode.BACKTEST, date(2000, 1, 31), date(2002, 12, 31), "t")
    assert rec.record.config_hash == bundle.hash()


def test_equity_exposure_with_valuation_scaling(bundle, static_factory) -> None:
    from rotationlab.strategies import build_strategy

    s = build_strategy(
        bundle,
        "us_equity_exposure",
        "long_history",
        {"valuation_scaling": {"enabled": True, "pct_start": "1926-07-31"}},
    )
    p, _ = s.propose(static_factory.at(date(1990, 6, 30)), s.initial_state())
    assert 0.0 <= p.signals["ecy_percentile"] <= 1.0
    if p.weights:
        assert p.weights["FF_MKT"] == pytest.approx(
            p.signals["votes"] * (0.75 + 0.25 * p.signals["ecy_percentile"])
        )
    early, _ = s.propose(static_factory.at(date(1930, 6, 30)), s.initial_state())
    assert early.warmup and "valuation" in early.notes[0]
