"""P6 (ADR 043): the live run end to end – forecast, settlement, report, idempotency, data guard, CLI."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.cli import main
from rotationlab.config.models import ForecastUniverseConfig
from rotationlab.engine.modes import research_factory
from rotationlab.forecast.journal import ForecastJournal
from rotationlab.forecast.live import (
    class_windows,
    data_complete,
    decision_date_for,
    month_end_after,
    price_series,
    run,
    settle,
    track_record,
)
from rotationlab.forecast.model import BlockBootstrap, ForecastModel
from rotationlab.forecast.types import ClassForecast, Forecast
from tests.fixtures.toy import Toy
from tests.lookahead.test_audit_phase2 import truncate

pytestmark = [pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")]


def test_decision_date_is_the_month_end_before_the_run() -> None:
    assert decision_date_for(date(2026, 10, 1)) == date(2026, 9, 30)
    assert decision_date_for(date(2026, 10, 31)) == date(2026, 9, 30)  # that day's close is not in yet
    assert decision_date_for(date(2026, 11, 1)) == date(2026, 10, 31)
    assert month_end_after(date(2026, 9, 30), 3) == date(2026, 12, 31)


@pytest.fixture(scope="module")
def obs(static_store):
    o = static_store.observations()
    return o[o["series_id"].str.startswith("static:")].reset_index(drop=True)


def test_live_run_on_the_research_store(tmp_path, bundle, obs, cal) -> None:
    factory = research_factory(bundle, obs, cal, date(1972, 12, 31))
    journal = ForecastJournal(tmp_path / "journal")
    reports = tmp_path / "reports"
    r1 = run(bundle, factory, journal, date(2010, 2, 3), "long_history", reports)
    assert r1.decision_date == date(2010, 1, 31) and r1.forecasts_written == 3 and r1.outcomes_written == 0
    assert r1.skipped is None and r1.late is None
    assert (reports / "2010-01.md").exists() and (reports / "latest.md").exists()
    f1 = next(f for f in journal.forecasts() if f.horizon_months == 1)
    assert f1.status in ("signal", "no_clear_signal") and len(f1.ranking()) == 4
    # a second run on the same day changes nothing
    r1b = run(bundle, factory, journal, date(2010, 2, 3), "long_history", reports)
    assert r1b.forecasts_written == 0 and r1b.outcomes_written == 0 and len(journal.forecasts()) == 3
    # a month later: the February forecast is written; the January forecast is not settled yet, because
    # the long-history universe carries World Bank averages whose honest window ends a month later (decision 5)
    assert class_windows(f1)["WB_BASEMETALS"] == (date(2010, 2, 28), date(2010, 3, 31))
    assert class_windows(f1)["US_EQ"] == (date(2010, 1, 31), date(2010, 2, 28))
    r2 = run(bundle, factory, journal, date(2010, 3, 2), "long_history", reports)
    assert r2.decision_date == date(2010, 2, 28) and r2.forecasts_written == 3 and r2.outcomes_written == 0
    r3 = run(bundle, factory, journal, date(2010, 4, 2), "long_history", reports)
    assert r3.decision_date == date(2010, 3, 31) and r3.forecasts_written == 3 and r3.outcomes_written == 1
    o = journal.outcomes()[0]
    assert (
        o.decision_date == date(2010, 1, 31)
        and o.horizon_months == 1
        and o.settled_through == date(2010, 2, 28)
    )
    assert sorted(o.realised_rank.values()) == [1, 2, 3, 4] and sum(o.hit.values()) == 2.0
    assert (
        o.ic is not None and -1 <= o.ic <= 1 and o.brier is not None and o.brier_const == pytest.approx(0.25)
    )
    assert set(o.trend_hit) == {"WB_BASEMETALS"} and o.target == "top_half"  # energy dropped (ADR 047)
    # the paper track: weights of the forecast × realised returns, remainder at the cash index
    lv_c = factory.at(date(2010, 4, 2)).total_return(["TBILL"], "ME")["TBILL"]
    cash_ret = float(lv_c.loc["2010-02-28"] / lv_c.loc["2010-01-31"] - 1)
    assert o.cash_return == pytest.approx(cash_ret)
    # the outcome equals what the research panel says
    lv = factory.at(date(2010, 4, 2)).total_return(["US_EQ", "UST10", "GOLD", "SILVER"], "ME")
    ret = lv.loc["2010-02-28"] / lv.loc["2010-01-31"] - 1
    rel = ret - ret.mean()
    for a in rel.index:
        assert o.relative[a] == pytest.approx(float(rel[a]))
    assert o.ew_return == pytest.approx(float(ret.mean()))
    invested = sum(f1.weights.values())  # type: ignore[union-attr]
    expected_port = sum(w * float(ret[a]) for a, w in f1.weights.items()) + (1 - invested) * cash_ret  # type: ignore[union-attr]
    assert o.portfolio_return == pytest.approx(expected_port)
    # the forecast in the journal is byte-identical to the model's forecast at that date (no drift) – plus
    # the derived paper weights of the 1-month forecast (ADR 048), which the model itself does not carry
    model = ForecastModel(bundle.forecast, "long_history", averaged=["WB_BASEMETALS"])
    fresh = model.forecast(factory.at(date(2010, 1, 31)), factory.data_snapshot())[0]
    assert fresh.to_json() == f1.stamped(None).with_weights(None).to_json()  # type: ignore[arg-type]
    assert f1.weights is not None and set(f1.weights) <= set(f1.ranking()[:2])
    assert 0 < sum(f1.weights.values()) <= 1.0 + 1e-12
    f3 = next(f for f in journal.forecasts() if f.horizon_months == 3)
    assert f3.weights is None  # the rule is monthly: only the 1-month forecast carries weights
    ok, _ = journal.verify()
    assert ok
    text = (reports / "2010-03.md").read_text()
    assert "Letztes Ergebnis" in text and "2010-01-31" in text and "P(obere Hälfte)" in text


def test_no_forecast_when_prices_are_not_complete(tmp_path, bundle, obs, cal) -> None:
    """The month-end's closes are not in the store yet (an ingest that failed): no forecast, a reason."""
    cut = truncate(obs, date(2010, 1, 20))
    factory = research_factory(bundle, cut, cal, date(1972, 12, 31))
    journal = ForecastJournal(tmp_path / "journal")
    r = run(bundle, factory, journal, date(2010, 2, 3), "long_history", tmp_path / "reports")
    assert r.forecasts_written == 0 and r.skipped is not None and "not complete" in r.skipped
    assert journal.forecasts() == []
    assert "Keine Prognose geschrieben" in (tmp_path / "reports" / "2010-01.md").read_text()
    full = research_factory(bundle, obs, cal, date(1972, 12, 31))
    assert data_complete(full.at(date(2010, 1, 31)), ["US_EQ", "GOLD"], cal, date(2010, 1, 31)) == []


def test_settlement_numbers_on_a_toy_world() -> None:
    lv = {
        "A": [100, 110, 121],
        "B": [100, 100, 105],
        "C": [100, 95, 100],
        "D": [100, 90, 85],
    }
    w = Toy()
    for a, v in lv.items():
        w.monthly(a, [float(x) for x in v], start="2000-01-31")
    w.monthly("E", [50.0, 55.0, 60.0], start="2000-01-31")
    w.cash("RF", 0.0, n=3, start="2000-01-31")
    factory = w.factory()
    from rotationlab.config.models import load_bundle

    b = load_bundle("configs")
    fc = b.forecast.model_copy(
        update={
            "universe": {
                "long_history": ForecastUniverseConfig(
                    ranked=["A", "B", "C", "D"], trend_only=["E"], cash="RF"
                )
            }
        }
    )
    ForecastModel(fc, "long_history")  # the configuration is valid for this toy universe
    classes = (
        ClassForecast("A", True, "up", 0.1, 1.0, 2, 0.0, (-0.01, 0.01), 0.55),
        ClassForecast("B", True, "up", 0.1, 2.0, 1, 0.0, (-0.01, 0.01), 0.60),
        ClassForecast("C", True, "down", -0.1, -1.0, 3, 0.0, (-0.01, 0.01), 0.45),
        ClassForecast("D", True, "down", -0.1, -2.0, 4, 0.0, (-0.01, 0.01), 0.40),
        ClassForecast("E", False, "down", -0.1),
    )
    f = Forecast(date(2000, 2, 29), 1, "signal", "composite", 1, {}, "s", classes, 100)
    assert settle(f, factory.at(date(2000, 3, 31)), factory.cal) is None  # window not closed
    o = settle(f, factory.at(date(2000, 4, 3)), factory.cal)
    assert o is not None
    ret = {"A": 0.1, "B": 0.05, "C": 100 / 95 - 1, "D": 85 / 90 - 1}
    mean = sum(ret.values()) / 4
    for a, value in ret.items():
        assert o.relative[a] == pytest.approx(value - mean)
    assert o.realised_rank == {"A": 1, "B": 3, "C": 2, "D": 4}  # C: +5.3 % beats B: +5.0 %
    assert o.hit == {"A": 1.0, "B": 0.0, "C": 1.0, "D": 0.0}
    # scores (B 2, A 1, C −1, D −2) vs realised (A, C, B, D): Spearman of ranks (2,1,3,4) vs (1,3,2,4)
    assert o.ic == pytest.approx(np.corrcoef([2, 1, 3, 4], [1, 3, 2, 4])[0, 1])
    assert o.top_beats_bottom == 1.0  # B (rank 1) beat D (rank 4)
    assert o.brier == pytest.approx(
        np.mean([(0.55 - 1) ** 2, (0.60 - 0) ** 2, (0.45 - 1) ** 2, (0.40 - 0) ** 2])
    )
    assert o.brier_const == pytest.approx(0.25)
    # previous-month baseline: January→February returns (+10 %, 0 %, −5 %, −10 %) ranked vs realised
    assert o.ic_prev_month == pytest.approx(np.corrcoef([1, 2, 3, 4], [1, 3, 2, 4])[0, 1])
    assert o.trend_hit == {"E": 0.0}  # trend down, E rose 55 → 60
    tr = track_record([o], 1, BlockBootstrap(100, 1, 1))
    assert tr["n"] == 1 and tr["hit_rate"] == 1.0 and tr["trend_hit"] == {"E": 0.0} and "ic_low" not in tr
    # the forecast's own target decides the hit, not the configuration of the settlement day
    f_bm = Forecast(
        date(2000, 2, 29),
        1,
        "signal",
        "composite",
        1,
        {"probability": {"target": "beats_mean"}},
        "s",
        classes,
        100,
    )
    o_bm = settle(f_bm, factory.at(date(2000, 4, 3)), factory.cal)
    assert o_bm is not None and o_bm.target == "beats_mean"
    assert o_bm.hit == {a: float(v > 0) for a, v in o.relative.items()}


def test_settlement_waits_for_every_class(tmp_path) -> None:
    """A trend-only class valued at monthly averages needs one more month (decision 5); a class whose
    level at the window's edge is missing holds the whole outcome back instead of being dropped."""
    w = Toy()
    for a, v in {
        "A": [100, 110, 121, 130],
        "B": [100, 100, 105, 110],
        "C": [100, 95, 100, 90],
        "D": [100, 90, 85, 80],
    }.items():
        w.monthly(a, [float(x) for x in v], start="2000-01-31")
    w.monthly("E", [50.0, 55.0, 60.0, 65.0], start="2000-01-31")
    gap = pd.Series([50.0, 55.0, 65.0], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-04-30"]))
    w.monthly(
        "F", gap
    )  # March is missing although April is in: the completeness guard alone would not notice
    factory = w.factory()
    classes = (
        ClassForecast("A", True, "up", 0.1, 1.0, 1, 0.0, (-0.01, 0.01), 0.55),
        ClassForecast("B", True, "up", 0.1, 0.5, 2, 0.0, (-0.01, 0.01), 0.52),
        ClassForecast("C", True, "down", -0.1, -0.5, 3, 0.0, (-0.01, 0.01), 0.48),
        ClassForecast("D", True, "down", -0.1, -1.0, 4, 0.0, (-0.01, 0.01), 0.45),
        ClassForecast("E", False, "up", 0.1),
    )
    f = Forecast(date(2000, 1, 31), 1, "signal", "composite", 1, {"averaged": ["E"]}, "s", classes, 100)
    assert class_windows(f)["E"] == (date(2000, 2, 29), date(2000, 3, 31))
    assert settle(f, factory.at(date(2000, 3, 2)), factory.cal) is None  # E's window ends 2000-03-31
    o = settle(f, factory.at(date(2000, 4, 3)), factory.cal)
    assert o is not None and o.trend_hit == {"E": 1.0} and o.settled_through == date(2000, 2, 29)
    assert o.relative["A"] == pytest.approx(0.10 - (0.10 + 0.0 - 0.05 - 0.10) / 4)
    g = Forecast(
        date(2000, 1, 31),
        1,
        "signal",
        "composite",
        1,
        {},
        "s",
        (*classes[:4], ClassForecast("F", False, "up", 0.1)),
        100,
    )
    assert (
        settle(g, factory.at(date(2000, 3, 2)), factory.cal) is not None
    )  # F's window [Jan, Feb] is in the store
    h = Forecast(
        date(2000, 2, 29),
        1,
        "signal",
        "composite",
        1,
        {},
        "s",
        (*classes[:4], ClassForecast("F", False, "up", 0.1)),
        100,
    )
    assert (
        settle(h, factory.at(date(2000, 5, 3)), factory.cal) is None
    )  # F has no March level: wait, do not drop


def test_late_data_forecast_is_written_once_the_store_knows(tmp_path, bundle, obs, cal) -> None:
    """Prices through D that reach the store after D (dated by arrival) are invisible to the view at D. The
    run then forecasts from observations through D with vintages through the run date, notes it, and the
    result equals the on-time forecast when nothing was revised."""
    on_time = research_factory(bundle, obs, cal, date(1972, 12, 31))
    d = date(2010, 1, 31)
    sids = price_series(on_time.at(d), "US_EQ")
    late = obs.copy()
    sel = (
        (late["series_id"].isin(sids))
        & (pd.to_datetime(late["obs_date"]) > pd.Timestamp("2010-01-20"))
        & (pd.to_datetime(late["obs_date"]) <= pd.Timestamp(d))
    )
    assert sel.sum() > 0
    late.loc[sel, "vintage_date"] = pd.Timestamp("2010-02-10")
    factory = research_factory(bundle, late, cal, date(1972, 12, 31))
    journal = ForecastJournal(tmp_path / "journal")
    r = run(bundle, factory, journal, date(2010, 2, 3), "long_history", tmp_path / "reports")
    assert r.forecasts_written == 0 and r.skipped is not None and "US_EQ" in r.skipped  # not in the store yet
    r = run(bundle, factory, journal, date(2010, 2, 12), "long_history", tmp_path / "reports")
    assert r.forecasts_written == 3 and r.skipped is None and r.late is not None and "US_EQ" in r.late
    f = next(x for x in journal.forecasts() if x.horizon_months == 1)
    assert any(n.startswith("late data") for n in f.notes) and f.decision_date == d
    ref = ForecastModel(bundle.forecast, "long_history", averaged=["WB_BASEMETALS"]).forecast(
        on_time.at(d), on_time.data_snapshot()
    )[0]
    # … and the forecast equals the on-time one except for the note (and the snapshot id of the altered store)
    same = Forecast(
        **{
            **f.__dict__,
            "created_at": None,
            "notes": ref.notes,
            "data_snapshot": ref.data_snapshot,
            "weights": None,
        }
    )
    assert f.notes != ref.notes and same.to_json() == ref.to_json()
    # the knowledge view never admits an observation after D
    v = factory.at(d, knowledge=date(2010, 2, 12))
    assert v.total_return(["US_EQ"], "ME").index.max() == pd.Timestamp(d) and v.knowledge_date == date(
        2010, 2, 12
    )


def test_cli_forecast_run_and_verify(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import shutil

    from tests.conftest import ROOT

    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    shutil.copytree(ROOT / "data" / "raw", tmp_path / "data" / "raw")
    assert main(["ingest", "--provider", "static"]) == 0
    code = main(
        [
            "forecast",
            "run",
            "--date",
            "2009-02-02",
            "--universe",
            "long_history",
            "--provider",
            "static",
            "--journal",
            "j",
            "--reports",
            "r",
        ]
    )
    assert (
        code == 0
        and (tmp_path / "j" / "forecasts.jsonl").exists()
        and (tmp_path / "r" / "2009-01.md").exists()
    )
    assert main(["forecast", "verify", "--journal", "j"]) == 0
    # the round-2 forecast (ADR 052) runs under --config with a journal and a report of its own
    args = [
        "forecast",
        "run",
        "--config",
        "forecast_v2",
        "--date",
        "2009-02-02",
        "--universe",
        "long_history",
    ]
    assert main([*args, "--provider", "static", "--journal", "j2", "--reports", "r2"]) == 0
    f = ForecastJournal(tmp_path / "j2").forecasts()[0]
    assert f.model_id == "mcv" and f.params["feature_params"]["carry_yield"]["spec"]["GOLD"] == {
        "kind": "zero"
    }
    assert [c.asset for c in f.classes if c.ranked] == ["US_EQ", "UST10_ME", "UST2_ME", "GOLD", "SILVER"]
    assert f.weights is not None and set(f.weights) <= set(f.ranking()[:2])  # the paper rule's top-2 of 5
    assert (tmp_path / "r2" / "2009-01.md").exists()
    assert main(["forecast", "verify", "--config", "forecast_v2", "--journal", "j2"]) == 0
    path = tmp_path / "j" / "forecasts.jsonl"
    path.write_text(path.read_text().replace('"status":"', '"status":"x'))
    assert main(["forecast", "verify", "--journal", "j"]) == 3


def test_paper_weights_follow_the_published_ranking_also_for_a_variant(bundle, obs, cal) -> None:
    """Second review of P8 (finding 1): the paper rule scores with the forecast model's own feature weights,
    so a variant (pure 12-1 momentum) gets weights on *its* top two, and a contradiction would raise."""
    from rotationlab.forecast.live import paper_rule, paper_weights

    factory = research_factory(bundle, obs, cal, date(1972, 12, 31))
    v = factory.at(date(2010, 1, 31))
    base = ForecastModel(bundle.forecast, "long_history", averaged=["WB_BASEMETALS"])
    var = ForecastModel(bundle.forecast, "long_history", variant="mom_12_1", averaged=["WB_BASEMETALS"])
    f_base, f_var = base.forecast(v, "s", [1])[0], var.forecast(v, "s", [1])[0]
    rule_var = paper_rule(bundle, var)
    assert rule_var is not None and rule_var.weights == var.weights
    w_var = paper_weights(rule_var, v, f_var)
    assert w_var is not None and set(w_var) <= set(f_var.ranking()[:2])
    if f_base.ranking()[:2] != f_var.ranking()[:2]:
        with pytest.raises(RuntimeError, match="paper rule"):
            paper_weights(paper_rule(bundle, base), v, f_var)


def test_settlement_with_weights_waits_for_the_cash_level() -> None:
    """Second review of P8 (finding 5): a forecast that carries weights is not settled while the cash
    asset's level at the window's end is missing – the paper return would otherwise be lost for good."""
    w = Toy()
    for a, v in {"A": [100, 110, 121], "B": [100, 100, 105], "C": [100, 95, 100], "D": [100, 90, 85]}.items():
        w.monthly(a, [float(x) for x in v], start="2000-01-31")
    w.cash("RF", 0.001, n=2, start="2000-01-31")  # the cash index ends in February: no March level
    factory = w.factory()
    classes = (
        ClassForecast("A", True, "up", 0.1, 1.0, 1, 0.0, (-0.01, 0.01), 0.55),
        ClassForecast("B", True, "up", 0.1, 0.5, 2, 0.0, (-0.01, 0.01), 0.52),
        ClassForecast("C", True, "down", -0.1, -0.5, 3, 0.0, (-0.01, 0.01), 0.48),
        ClassForecast("D", True, "down", -0.1, -1.0, 4, 0.0, (-0.01, 0.01), 0.45),
    )
    params = {"cash": "RF"}
    plain = Forecast(date(2000, 2, 29), 1, "signal", "composite", 1, params, "s", classes, 100)
    with_w = plain.with_weights({"A": 0.5, "B": 0.5})
    view = factory.at(date(2000, 4, 3))
    o = settle(plain, view, factory.cal)
    assert o is not None and o.portfolio_return is None and o.cash_return is None and o.ew_return is not None
    assert settle(with_w, view, factory.cal) is None  # waits for the cash level
    w.cash("RF2", 0.001, n=3, start="2000-01-31")
    ok = with_w  # same forecast on a cash asset with the level
    ok = Forecast(**{**ok.__dict__, "params": {"cash": "RF2"}})
    o2 = settle(ok, w.factory().at(date(2000, 4, 3)), factory.cal)
    assert o2 is not None and o2.cash_return == pytest.approx(0.001)
    assert o2.portfolio_return == pytest.approx(0.5 * (121 / 110 - 1) + 0.5 * (105 / 100 - 1))


def test_backfilled_forecasts_are_kept_but_not_counted(tmp_path, bundle, obs, cal) -> None:
    """ADR 050: a forecast written more than `backfill_after_days` after its decision date (the first live run
    after a long pause) is correct and journaled, but it is not an out-of-sample point: it carries a note, the
    report says so, and the track record leaves it out."""
    from rotationlab.forecast.live import backfill_note, is_backfill

    assert backfill_note(date(2010, 1, 31), date(2010, 2, 7), 7) is None
    assert backfill_note(date(2010, 1, 31), date(2010, 2, 8), 7) is not None
    factory = research_factory(bundle, obs, cal, date(1972, 12, 31))
    journal = ForecastJournal(tmp_path / "journal")
    reports = tmp_path / "reports"
    r = run(bundle, factory, journal, date(2010, 2, 26), "long_history", reports)  # 26 days after D
    assert r.forecasts_written == 3
    late = [f for f in journal.forecasts() if f.decision_date == date(2010, 1, 31)]
    assert all(is_backfill(f) for f in late)
    assert "Nachgeholt (ADR 050)" in (reports / "2010-01.md").read_text()
    # the next months run on time: not backfilled
    run(bundle, factory, journal, date(2010, 3, 2), "long_history", reports)
    run(bundle, factory, journal, date(2010, 4, 2), "long_history", reports)
    r = run(bundle, factory, journal, date(2010, 5, 3), "long_history", reports)
    on_time = [f for f in journal.forecasts() if f.decision_date == date(2010, 2, 28)]
    assert on_time and not any(is_backfill(f) for f in on_time)
    settled_1m = [o for o in journal.outcomes() if o.horizon_months == 1]
    assert {o.decision_date for o in settled_1m} >= {date(2010, 1, 31), date(2010, 2, 28)}
    text = (reports / "2010-04.md").read_text()
    # the January outcome is in the journal but not in the 1-month track record
    n_counted = len([o for o in settled_1m if o.decision_date != date(2010, 1, 31)])
    assert f"| 1 M | {n_counted} |" in text and "Nicht in der Bilanz (nachgeholt" in text
    ok, _ = journal.verify()
    assert ok
