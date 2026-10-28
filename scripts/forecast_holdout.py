"""Pseudo-holdout 2019–2025 (ADR 049; round 2: ADR 052 f): the frozen forecast and the frozen paper rule, once.

Part A – the forecast (as in P4): decisions 2019-01-31 … 2025-11-30 (1 M), outcomes to 2025-12-31, on the
research series; probabilities point-in-time with calibration and climatology expanding from the panel start.
Part B – the paper rule (as in P8): rule and baselines through the engine over the full history, metrics over
the 84 return months 2019-01 … 2025-12.

Reading rule fixed in ADR 049 (d); the in-sample interval it compares against is read from
output/<config>/summary.json (written by scripts/forecast_evaluation.py). The script refuses a second run
unless `--again` is given, and every run is stamped into the report. Writes output/<config>/HOLDOUT.md and CSVs.

Aufruf: python scripts/forecast_holdout.py [--config forecast|forecast_v2] [--again]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, bond_class, ci_text, load, md_table, p_text, parse_args  # noqa: E402
from rotationlab.config.models import GoldenRun  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine import metrics  # noqa: E402
from rotationlab.engine.modes import GoldenReport, averaged_assets, golden, research_factory  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    brier,
    by_class,
    climatology,
    mean_ci,
    paired_diff,
    paired_sharpe_diff,
    permutation_pvalue,
    previous_month_scores,
    reliability,
    spearman_rows,
    top_bottom,
)
from rotationlab.forecast.model import (  # noqa: E402
    BlockBootstrap,
    ForecastModel,
    complete_months,
    composite,
    feature_panel,
    forward_returns,
    hit_matrix,
    ranks_of,
    relative,
)

RULE = "Regel (Top-2, Trend, Vol-Ziel 10 %)"
IN_SAMPLE_IC_V1 = (
    0.0978,
    0.0511,
    0.1409,
)  # P4, 1 M, output/forecast/EVALUATION.md (before summary.json existed)


def baselines(ranked: list[str], bond: str) -> dict[str, dict[str, object]]:
    n = len(ranked)
    return {
        f"Equal Weight ({n} Klassen)": {"weights": dict.fromkeys(ranked, 1.0 / n), "rebalance": "monthly"},
        f"60/40 US_EQ/{bond}": {"weights": {"US_EQ": 0.6, bond: 0.4}, "rebalance": "monthly"},
        "Buy-and-Hold US_EQ": {"weights": {"US_EQ": 1.0}, "rebalance": "never"},
    }


def in_sample_ic(out: str, config: str) -> tuple[float, float, float]:
    """The in-sample 1-month IC interval the reading rule compares against (ADR 049 d), from the evaluation run."""
    path = os.path.join(out, "summary.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            ic = json.load(fh)["ic_h1"]
        return float(ic["mean"]), float(ic["low"]), float(ic["high"])
    if config == "forecast":
        return IN_SAMPLE_IC_V1
    raise SystemExit(f"{path} missing: run scripts/forecast_evaluation.py --config {config} first")


def holdout_run(gr: GoldenRun, start: date, end: date, **params: object) -> GoldenRun:
    return gr.model_copy(update={"end": end, "sample": (start, end), "params": {**gr.params, **params}})


def main(config: str, again: bool) -> None:
    b, fc, out = load(config)
    v1 = config == "forecast"
    report = os.path.join(out, "HOLDOUT.md")
    if os.path.exists(report) and not again:
        print(
            f"{report} exists: the holdout has been run. A repetition needs --again and a note in the protocol."
        )
        sys.exit(2)
    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    t0 = time.perf_counter()
    is_ic = in_sample_ic(out, config)
    sid = fc.paper_rule
    assert sid is not None
    scfg = b.strategies[sid]
    cal = make_calendar(b)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, cal, fc.evaluation.data_from)
    model = ForecastModel(fc, averaged=averaged_assets(b))
    boot = BlockBootstrap(fc.calibration.draws, fc.calibration.block_months, fc.calibration.seed)
    ranked, cash = model.ranked, model.cash
    h_start, h_end = fc.holdout.start, fc.holdout.end
    end_view = f.at(h_end)
    assert end_view.date == h_end
    rule_classes = [a for a in scfg.long_history_universe if a != cash]  # round 1: UST10_ME for UST10
    bond = bond_class(b, rule_classes)
    base = baselines(rule_classes, bond)
    ew_label = next(iter(base))

    lines = [
        "# Pseudo-Holdout 2019–2025: die eingefrorene Prognose und die eingefrorene Regel, einmal gerechnet"
        + ("" if v1 else f" (Forschungsrunde 2, `{config}`)"),
        "",
        f"Lauf {stamp}{' (WIEDERHOLUNG mit --again)' if again else ' (erster und einziger Lauf)'}. Modell `{model.model_id}` "
        f"v{model.version}, gerankte Klassen {ranked}, Cash {cash}; Protokoll und Lesart vorab in ADR 049"
        f"{'' if v1 else ' (übernommen in ADR 052 f)'}. Daten: "
        f"Forschungspanel ab {fc.evaluation.data_from:%Y-%m}, Datenstand `{f.data_snapshot()}`.",
        "",
        "**Einordnung:** „Pseudo“, weil die Periode 2019–2025 bei der Gestaltung bekannt war (Forschungsphase, Allgemeinwissen "
        "über Corona-Crash, Zinswende, Goldrally) – nur die Zahlen wurden nie berechnet. Echtes Out-of-sample sind die "
        "Live-Prognosen ab November 2026. Mit ≈ 83 Monaten sind die Intervalle breit; die Lesart dafür steht in ADR 049 (d).",
        "",
    ]

    # ---- Part A: the forecast -------------------------------------------------------------------------
    levels = complete_months(end_view, end_view.total_return([*ranked, cash], "ME"))
    feats = {k: feature_panel(end_view, k, ranked, **model.feature_params.get(k, {})) for k in model.weights}
    scores_all = composite(feats, model.weights, model.clip).reindex(columns=ranked)
    results_a: dict[str, object] = {}
    lines += ["## A. Prognose (wie P4)", ""]
    for h in fc.horizons:
        last = (pd.Timestamp(h_end) - pd.offsets.MonthEnd(h)).date()
        s = scores_all[(scores_all.index >= pd.Timestamp(h_start)) & (scores_all.index <= pd.Timestamp(last))]
        rel = relative(forward_returns(levels[ranked], h)).reindex(s.index)
        ranks = ranks_of(s)
        ic = spearman_rows(s, rel)
        tb = top_bottom(ranks, rel)
        ic_ci = mean_ci(ic, boot, CONF)
        hit_ci = mean_ci(tb["hit"], boot, CONF)
        spread_ci = mean_ci(tb["spread"] * 12 / h, boot, CONF)
        p_val, null95, _ = permutation_pvalue(s, rel, fc.calibration.draws, fc.calibration.seed)
        prev = previous_month_scores(levels[ranked]).reindex(s.index)
        prev_ci = mean_ci(spearman_rows(prev, rel), boot, CONF)
        results_a[f"h{h}"] = {"ic": ic_ci, "hit": hit_ci, "p": p_val, "prev": prev_ci}
        pd.DataFrame({"ic": ic, **tb}).to_csv(os.path.join(out, f"holdout_monthly_h{h}.csv"))
        lines += [
            f"### Horizont {h} Monat{'e' if h > 1 else ''}: Entscheidungen {s.index[0]:%Y-%m} bis {s.index[-1]:%Y-%m}",
            "",
            f"- Rang-IC (Spearman, Mittel je Monat): **{ci_text(ic_ci)}**; Anteil Monate mit IC > 0: {float((ic.dropna() > 0).mean()):.3f}",
            f"- Zufälliger Rang (Permutation, {fc.calibration.draws} Ziehungen): p = **{p_text(p_val, fc.calibration.draws)}**, 95. Perzentil des Null-Mittels {null95:+.4f}"
            + (" – bei überlappenden Fenstern zu eng, massgeblich ist das Intervall" if h > 1 else ""),
            f"- Vormonatsrang als Prognose: IC {ci_text(prev_ci)}",
            f"- Trefferquote Rang 1 schlägt Rang {len(ranked)}: **{hit_ci.mean:.3f}** [{hit_ci.low:.3f}, {hit_ci.high:.3f}] (Zufall 0.5)",
            f"- Top-minus-Bottom-Spread über {h} Monat{'e' if h > 1 else ''}, annualisiert (×12/{h}): {ci_text(spread_ci)}",
            "",
        ]
        if h == 1:
            scores1, rel1, ranks1 = s, rel, ranks
            bc = by_class(ranks1, rel1)
            piv_hit = bc.pivot(index="class", columns="rank", values="hit_rate")
            piv_n = bc.pivot(index="class", columns="rank", values="months")
            lines += [
                "Je Klasse und Rang, 1 Monat: Trefferquote (relative Rendite > 0) und Monate:",
                "",
                md_table(piv_hit, "{:.3f}"),
                "",
                md_table(piv_n, "{:.0f}"),
                "",
            ]

    # probabilities point-in-time (primary model), climatology expanding from the start of the panel
    target = fc.probability.target
    rel_all = relative(forward_returns(levels[ranked], 1))
    hit_all = hit_matrix(rel_all, target)
    clim_all = climatology(hit_all, fc.calibration.min_months).reindex(columns=ranked)
    rows = []
    for d in scores1.index:
        fm = model.forecast(f.at(d.date()), "holdout", [1])[0]
        rows += [
            {"date": d, "asset": c.asset, "prob": c.probability, "status": fm.status}
            for c in fm.classes
            if c.ranked
        ]
    pit = pd.DataFrame(rows)
    prob = pit.pivot(index="date", columns="asset", values="prob").reindex(columns=ranked)
    status = pit.groupby("date")["status"].first()
    hit1 = hit_all.reindex(prob.index)
    clim = clim_all.reindex(prob.index)
    known = prob.notna().all(axis=1) & hit1.notna().all(axis=1)
    b_model = brier(prob, hit1).where(known)
    b_const = brier(prob.notna() * 0.5, hit1).where(known)
    b_clim = brier(clim, hit1).where(known)
    sk0 = paired_diff(b_const / 12, b_model / 12, boot, CONF)
    skc = paired_diff(b_clim / 12, b_model / 12, boot, CONF)
    rel_tab = reliability(prob, hit1, step=0.10)
    tb1 = top_bottom(ranks1, rel1)
    st = pd.DataFrame(
        {"status": status.reindex(tb1.index), "hit": tb1["hit"], "ic": spearman_rows(scores1, rel1)}
    ).dropna()
    tb_status = st.groupby("status").agg(
        months=("hit", "size"), hit_rate=("hit", "mean"), mean_ic=("ic", "mean")
    )
    prob.to_csv(os.path.join(out, "holdout_probabilities_h1.csv"))
    lines += [
        f"### Wahrscheinlichkeiten (1 Monat, `{fc.probability.model}`, Ziel `{target}`), {int(known.sum())} Monate",
        "",
        f"- Brier Modell {float(b_model.dropna().mean()):.4f}; Konstante 0.5 {float(b_const.dropna().mean()):.4f}; Klimatologie {float(b_clim.dropna().mean()):.4f}",
        f"- Skill gegen 0.5: {ci_text(sk0)}; **Skill gegen Klimatologie: {ci_text(skc)}** (positiv = Modell besser)",
        f"- Grundraten im Holdout: {hit1[known].mean().round(3).to_dict()}",
        "",
        "Reliability (Zehn-Prozent-Schritte, wegen der kleinen Stichprobe):",
        "",
        md_table(rel_tab.set_index("bin"), "{:.3f}"),
        "",
        "Status (beschreibend) und Trefferquote/IC:",
        "",
        md_table(tb_status, "{:.3f}"),
        "",
    ]

    # ---- Part B: the paper rule ---------------------------------------------------------------------
    gr = scfg.golden_run
    gr_fw = b.strategies["fixed_weights"].golden_run
    assert gr is not None and gr_fw is not None
    gr_fw = gr_fw.model_copy(update={"data_from": gr.data_from, "start": gr.start})
    fw_cfg = b.strategies["fixed_weights"].model_copy(
        update={"universe": scfg.universe, "long_history_universe": scfg.long_history_universe}
    )
    b = b.model_copy(update={"strategies": {**b.strategies, "fixed_weights": fw_cfg}})
    runs: dict[str, GoldenReport] = {RULE: golden(b, obs, sid, cal, run=holdout_run(gr, h_start, h_end))}
    for label, params in base.items():
        runs[label] = golden(b, obs, "fixed_weights", cal, run=holdout_run(gr_fw, h_start, h_end, **params))
    rule = runs[RULE].result
    r_rule, _ = rule.sample(h_start, h_end, count_warmup=True)
    index = pd.DatetimeIndex(r_rule.index)
    series = {}
    for label, rep in runs.items():
        res = rep.result
        r, c, t = res.returns.reindex(index), res.cash_returns.reindex(index), res.turnover.reindex(index)
        assert not r.isna().any() and not c.isna().any(), label
        series[label] = (r, c, t)
    cash_r = series[RULE][1]
    prow = []
    for label, (r, c, t) in series.items():
        m = metrics.summary(r, c, t)
        prow.append(
            {
                "Lauf": label,
                "Monate": int(m["months"]),
                "Rendite p.a.": m["ann_return"],
                "Vol p.a.": m["ann_vol"],
                "Sharpe ex Cash": m["sharpe_ex_cash"],
                "Max Drawdown": m["max_drawdown"],
                "Trefferquote": m["hit_rate"],
                "Umsatz p.a.": m["turnover_ann"],
            }
        )
    ptab = pd.DataFrame(prow).set_index("Lauf")
    ptab.to_csv(os.path.join(out, "holdout_portfolio_metrics.csv"))
    pd.DataFrame({k: v[0] for k, v in series.items()} | {"cash": cash_r}).to_csv(
        os.path.join(out, "holdout_portfolio_monthly.csv")
    )
    r_main = series[RULE][0]
    drows = []
    for label in base:
        d_ret = paired_diff(r_main, series[label][0], boot, CONF)
        d_sh = paired_sharpe_diff(r_main, series[label][0], cash_r, boot, CONF)
        drows.append(
            {
                "Baseline": label,
                "Δ Rendite p.a.": d_ret.mean,
                "low": d_ret.low,
                "high": d_ret.high,
                "Δ Sharpe": d_sh.value,
                "Sharpe low": d_sh.low,
                "Sharpe high": d_sh.high,
            }
        )
    dtab = pd.DataFrame(drows).set_index("Baseline")
    dtab.to_csv(os.path.join(out, "holdout_portfolio_paired.csv"))
    w = rule.weights.reindex(pd.DatetimeIndex([d - pd.offsets.MonthEnd(1) for d in index])).fillna(0.0)
    risky = w.drop(columns=["CASH"], errors="ignore").sum(axis=1)
    lines += [
        f"## B. Paper-Regel (wie P8), {len(index)} Renditemonate {index[0]:%Y-%m} bis {index[-1]:%Y-%m}",
        "",
        f"Regel und Baselines durch dieselbe Engine über die volle Geschichte ab {gr.data_from} (Ausführung `{gr.execution}`, "
        f"Kosten {gr.costs.default_bps} bp je Seite), Kennzahlen nur über den Holdout. Mittlere Risikoquote der Regel "
        f"{float(risky.mean()):.3f}, Anteil Entscheidungen ganz in Cash {float((risky == 0).mean()):.3f}.",
        "",
        md_table(ptab),
        "",
        "Gepaarte Differenzen Regel − Baseline (90 %, Block 12 auf 84 Monaten – breit):",
        "",
        md_table(dtab),
        "",
    ]

    # ---- reading per ADR 049 (d) ------------------------------------------------------------------------
    ic1 = results_a["h1"]["ic"]  # type: ignore[index]
    lo_is, hi_is = is_ic[1], is_ic[2]
    if ic1.mean <= 0:
        verdict = "GESCHEITERT (mittlerer IC ≤ 0)"
    elif ic1.mean >= lo_is:
        verdict = "GELUNGEN (positiv, im oder über dem In-sample-Intervall)"
    else:
        verdict = "SCHWACH (positiv, unter dem In-sample-Intervall)"
    sh_rule = ptab.loc[RULE, "Sharpe ex Cash"]
    sh_ew = ptab.loc[ew_label, "Sharpe ex Cash"]
    d_ew = dtab.loc[ew_label]
    lines += [
        "## Lesart nach ADR 049 (d) – vorab festgelegt",
        "",
        f"- In-sample {fc.evaluation.start.year}–2018 (P4): IC {is_ic[0]:+.4f} [{lo_is:+.4f}, {hi_is:+.4f}]; Holdout 2019–2025: IC "
        f"**{ic1.mean:+.4f}** [{ic1.low:+.4f}, {ic1.high:+.4f}] über {ic1.n} Monate; Vormonatsrang-Baseline "
        f"{results_a['h1']['prev'].mean:+.4f}.",  # type: ignore[index]
        f"- Replikation der Rangfolge: **{verdict}**.",
        f"- Wahrscheinlichkeiten: Skill gegen Klimatologie {skc.mean:+.4f} [{skc.low:+.4f}, {skc.high:+.4f}] – "
        f"{'Intervall ohne Null' if skc.low > 0 or skc.high < 0 else 'nicht von Null zu trennen'} (in-sample ebenfalls nicht).",
        f"- Regel gegen Equal Weight: Sharpe {sh_rule:+.3f} gegen {sh_ew:+.3f}, Δ {d_ew['Δ Sharpe']:+.3f} "
        f"[{d_ew['Sharpe low']:+.3f}, {d_ew['Sharpe high']:+.3f}] – berichtet ohne Pass/Fail (84 Monate).",
        "",
        f"Nach diesem Lauf wird an Modell und Regel nichts mehr geändert (ADR 049 a{'' if v1 else ' / ADR 052 f'}).",
        "",
        f"Laufzeit {time.perf_counter() - t0:.0f} s.",
    ]
    with open(report, "a" if again else "w", encoding="utf-8") as fh:
        fh.write(("\n\n---\n\n" if again else "") + "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    a = parse_args(__doc__, ("--again", {"action": "store_true", "help": "repeat a holdout already run"}))
    main(a.config, a.again)
