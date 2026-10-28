"""Research round 4 (ADR 057, precised by ADR 058): the sleeve allocator v2 – walk-forward against baselines,
variants and signal tests.

Everything the allocator does at a decision date uses data up to that date and no parameter chosen on the data;
the whole window is out-of-sample with respect to the data and in-sample only with respect to the design. The
script follows ADR 057 (f)/(g) and ADR 058 to the letter:

* the window is computed from the rule run before anything else runs – it starts with the first decision at which
  every long sleeve that is ever active is active (the currency overlay joins when it can, ADR 058 e) and ends with
  the last return month every data group still delivers (`common_data_end`); a config that states another window
  stops the script;
* B1 is the passive risk parity of the long sleeves (no overlay, no selection, no filter) with the same target,
  caps, costs, financing and execution – sized exactly like the allocator's long book (ADR 058 d);
* the primary criterion is the paired Sharpe difference to B1; secondary, Holm at 10 %, the dollar-neutral rank
  portfolios of the sleeves whose signal is new evidence (EQ_INTL, FX); EQ_US repeats the industry signal of round
  3 on overlapping months and is reported as a replication (ADR 058);
* the deflated Sharpe takes N from the register (incl. this round) and the variance from the stored trials plus
  this round's runs.

Writes output/allocator_v2/WALKFORWARD.md and CSVs. Aufruf: python scripts/allocator_v2_walkforward.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, md_table, register, trials_variance  # noqa: E402

from rotationlab.config.models import GoldenRun, load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine import metrics  # noqa: E402
from rotationlab.engine.modes import GoldenReport, golden, research_factory  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    appraisal_residual,
    common_data_end,
    deflated_sharpe,
    holm,
    long_short_rank_returns,
    mean_ci,
    newey_west_t,
    one_sided_p,
    paired_diff,
    paired_sharpe_diff,
    sharpe_ci,
    spearman_rows,
)
from rotationlab.forecast.model import BlockBootstrap  # noqa: E402
from rotationlab.strategies.base import deep_merge  # noqa: E402

SID = "sleeve_allocator_v2"
OUT = os.path.join(ROOT, "output", "allocator_v2")
RULE = "Allokator v2 (ADR 057/058)"
B1 = "B1 passive Risikoparität"
PERIODS = [("Start–1989", 1900, 1989), ("1990–2007", 1990, 2007), ("2008–Ende", 2008, 2100)]
N_VARIANTS = 11  # ADR 057 (g)
BOOT = BlockBootstrap(2000, 12, 20261025)
Z80 = 1.645 + 0.842  # one-sided 5 % test with 80 % power
MDE_READING = 0.20  # ADR 057 (f): above this MDE a NEIN reads "test too weak"
HOLM_ALPHA = 0.10
NW_LAGS = 12
NEW_EVIDENCE = ("EQ_INTL", "FX")  # signals not tested before (ADR 058); EQ_US repeats round 3 (replication)


def with_params(gr: GoldenRun, **params: object) -> GoldenRun:
    return gr.model_copy(update={"params": {**gr.params, **params}})


def aligned(rep: GoldenReport, index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    res = rep.result
    r, c, t = res.returns.reindex(index), res.cash_returns.reindex(index), res.turnover.reindex(index)
    cost = res.decisions["cost"].shift(1).iloc[1:].reindex(index)
    if r.isna().any() or c.isna().any():
        raise RuntimeError(f"{rep.strategy}: return series does not cover the common sample")
    return r, c, t, cost


def row(label: str, r: pd.Series, c: pd.Series, t: pd.Series, cost: pd.Series) -> dict[str, object]:
    m = metrics.summary(r, c, t)
    return {
        "Lauf": label,
        "Monate": int(m["months"]),
        "Rendite p.a.": m["ann_return"],
        "Vol p.a.": m["ann_vol"],
        "Sharpe ex Cash": m["sharpe_ex_cash"],
        "Max Drawdown": m["max_drawdown"],
        "Calmar": m["calmar"],
        "Umsatz p.a.": m["turnover_ann"],
        "Kosten p.a.": float(cost.fillna(0.0).mean() * 12),
    }


def vol_matched(r: pd.Series, c: pd.Series, target: float) -> pd.Series:
    """r scaled ex post to an annualised volatility `target` of its excess return (display only)."""
    e = r - c
    return c + e * (target / float(e.std() * np.sqrt(12)))


def signal_frame(res, keys: list[str], decided: pd.DatetimeIndex) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    """One column per signal key, one row per non-warm-up decision in `decided` (NaN where not recorded)."""
    sc = pd.DataFrame(
        {
            pd.Timestamp(p.date): {k: p.signals.get(k, np.nan) for k in keys}
            for p in res.proposals
            if not p.warmup
        }
    ).T.sort_index()
    return sc[sc.index.isin(decided)].reindex(columns=keys)


def window(rule, long_sleeves: list[str]) -> tuple[pd.Timestamp, list[str], list[str]]:  # type: ignore[no-untyped-def]
    """ADR 058 (e): the first decision at which every long sleeve that is ever active is active; a long sleeve
    that is never active (emergency rule 057 h) is reported and not required."""
    act = pd.DataFrame(
        {
            pd.Timestamp(p.date): {s: p.signals.get(f"active:{s}", 0.0) for s in long_sleeves}
            for p in rule.proposals
        }
    ).T.sort_index()
    ever = [s for s in long_sleeves if (act[s] == 1.0).any()]
    never = [s for s in long_sleeves if s not in ever]
    if not ever:
        raise RuntimeError("no long sleeve is ever active – nothing to evaluate")
    full = act.index[(act[ever] == 1.0).all(axis=1)]
    return pd.Timestamp(full[0]), ever, never


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    scfg = b.strategies[SID]
    gr = scfg.golden_run
    assert gr is not None
    cal = make_calendar(b)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    params = deep_merge(scfg.params, scfg.long_history_params)
    sleeves = dict(params["sleeves"])
    cash_asset = next(a for a in scfg.long_history_universe if b.universe.assets[a].asset_class == "cash")
    inst = {k: list(v["instruments"]) for k, v in sleeves.items()}
    long_sleeves = [k for k, v in sleeves.items() if v["group"] != "overlay" and float(v["budget"]) > 0]
    overlay = [k for k, v in sleeves.items() if v["group"] == "overlay" and float(v["budget"]) > 0]
    costs = dict(gr.costs.per_asset)
    spread = dict(gr.costs.borrow_bps)

    # ---- the rule first: the window is fixed before anything else runs ------------------------------------------
    runs: dict[str, GoldenReport] = {RULE: golden(b, obs, SID, cal)}
    rule = runs[RULE].result
    first_full, ever, never = window(rule, long_sleeves)
    start = first_full + pd.offsets.MonthEnd(1)
    end_view = research_factory(b, obs, cal, gr.data_from).at(gr.end)
    groups = {k: [a for a in inst[k]] for k in ever}
    groups.update({k: inst[k] for k in overlay if inst[k]})
    groups["US-Markt (B3/B4)"] = ["US_EQ"]
    groups["Cash"] = [cash_asset]
    frames = {g: end_view.total_return(a, None) for g, a in groups.items()}
    if any(f.dropna(how="all").empty for g, f in frames.items() if g in overlay):  # an overlay never built
        frames = {g: f for g, f in frames.items() if g not in overlay or not f.dropna(how="all").empty}
    end, ends = common_data_end(frames, cal)
    if (start.date(), end.date()) != (gr.sample[0], gr.sample[1]):
        raise RuntimeError(
            f"config sample {gr.sample} differs from the window rule ({start.date()} … {end.date()}); data ends: "
            + ", ".join(f"{g} {e.date()}" for g, e in ends.items())
        )
    print(
        f"rule run and window {start.date()} … {end.date()} after {time.perf_counter() - t0:.0f} s",
        flush=True,
    )

    # ---- baselines and variants: same engine, costs, financing and execution -------------------------------------
    no_overlay = {
        k: {**v, "budget": 0.0 if v["group"] == "overlay" else v["budget"]} for k, v in sleeves.items()
    }
    runs[B1] = golden(
        b, obs, SID, cal, run=with_params(gr, xs_select=False, ts_filter=False, sleeves=no_overlay)
    )
    fw = b.strategies["fixed_weights"]
    fw_gr = fw.golden_run
    assert fw_gr is not None
    fw_gr = fw_gr.model_copy(
        update={
            "data_from": gr.data_from,
            "start": gr.start,
            "end": gr.end,
            "sample": gr.sample,
            "costs": gr.costs,
        }
    )

    def fixed(universe: list[str], weights: dict[str, float], rebalance: str = "monthly") -> GoldenReport:
        cfg = fw.model_copy(update={"universe": universe, "long_history_universe": universe})
        bb = b.model_copy(update={"strategies": {**b.strategies, "fixed_weights": cfg}})
        extra = {a: costs.get(inst["EQ_US"][0], 10.0) for a in universe if a not in costs and a != cash_asset}
        run = fw_gr.model_copy(
            update={"costs": gr.costs.model_copy(update={"per_asset": {**costs, **extra}})}
        )
        return golden(
            bb, obs, "fixed_weights", cal, run=with_params(run, weights=weights, rebalance=rebalance)
        )

    long_full = [*inst["EQ_US"], *inst["FI"], *inst["PM"]]
    runs[f"B2 Equal Weight ({len(long_full)} Long-Instrumente)"] = fixed(
        [*long_full, cash_asset], dict.fromkeys(long_full, 1 / len(long_full))
    )
    runs["B3 60/40 US-Markt/10-J."] = fixed(["US_EQ", "UST10_D", cash_asset], {"US_EQ": 0.6, "UST10_D": 0.4})
    runs["B4 Buy-and-Hold US-Markt"] = fixed(["US_EQ", cash_asset], {"US_EQ": 1.0}, "never")
    baselines = [k for k in runs if k != RULE]

    def one(name: str) -> dict[str, dict[str, object]]:
        return {k: {**v, "budget": float(v["budget"]) if k == name else 0.0} for k, v in sleeves.items()}

    monthly = {k: {**v, "vol": "monthly"} for k, v in sleeves.items()}
    double = gr.costs.model_copy(
        update={
            "per_asset": {k: 2 * v for k, v in costs.items()},
            "borrow_bps": {k: 2 * v for k, v in spread.items()},
        }
    )
    variants: dict[str, GoldenReport] = {
        "ohne Zeitreihenfilter": golden(b, obs, SID, cal, run=with_params(gr, ts_filter=False)),
        "ohne Querschnitt": golden(b, obs, SID, cal, run=with_params(gr, xs_select=False)),
        "ohne FX-Sleeve": golden(b, obs, SID, cal, run=with_params(gr, sleeves=no_overlay)),
        "Kosten und Finanzierung ×2": golden(b, obs, SID, cal, run=gr.model_copy(update={"costs": double})),
        "Ausführung zum Entscheidungskurs": golden(
            b, obs, SID, cal, run=gr.model_copy(update={"execution": "same_close"})
        ),
        "Vol überall monatlich": golden(b, obs, SID, cal, run=with_params(gr, sleeves=monthly)),
    }
    for name in sleeves:
        variants[f"nur Sleeve {name}"] = golden(b, obs, SID, cal, run=with_params(gr, sleeves=one(name)))
    assert len(variants) == N_VARIANTS

    r_all = rule.returns
    index = pd.DatetimeIndex(r_all[(r_all.index >= start) & (r_all.index <= end)].index)
    if not index.equals(pd.date_range(start, end, freq="ME")):
        raise RuntimeError(
            f"the rule's returns do not cover every month of the window {start.date()} … {end.date()}"
        )
    decided = pd.DatetimeIndex([d - pd.offsets.MonthEnd(1) for d in index])
    series = {label: aligned(rep, index) for label, rep in {**runs, **variants}.items()}
    cash = series[RULE][1]
    table = pd.DataFrame([row(label, *s) for label, s in series.items()]).set_index("Lauf")
    table.to_csv(os.path.join(OUT, "walkforward_metrics.csv"))
    pd.DataFrame({label: s[0] for label, s in series.items()} | {"cash": cash}).to_csv(
        os.path.join(OUT, "walkforward_monthly.csv")
    )
    rule.weights.to_csv(os.path.join(OUT, "walkforward_weights.csv"))
    r_main, r_b1 = series[RULE][0], series[B1][0]
    sig_main = float((r_main - cash).std() * np.sqrt(12))

    # ---- primary criterion and paired differences ------------------------------------------------------------------
    diffs = []
    for label in baselines:
        d_sh = paired_sharpe_diff(r_main, series[label][0], cash, BOOT, CONF)
        d_ret = paired_diff(r_main, vol_matched(series[label][0], cash, sig_main), BOOT, CONF)
        diffs.append(
            {
                "Baseline": label,
                "Δ Sharpe": d_sh.value,
                "low": d_sh.low,
                "high": d_sh.high,
                "Δ Rendite bei gleicher Vol p.a.": d_ret.mean,
                "low ": d_ret.low,
                "high ": d_ret.high,
            }
        )
    dtab = pd.DataFrame(diffs).set_index("Baseline")
    dtab.to_csv(os.path.join(OUT, "walkforward_paired.csv"))
    d1 = dtab.loc[B1]
    sh_rule, sh_b1 = float(table.loc[RULE, "Sharpe ex Cash"]), float(table.loc[B1, "Sharpe ex Cash"])
    c1 = sh_rule > sh_b1
    lo, hi, dv = float(d1["low"]), float(d1["high"]), float(d1["Δ Sharpe"])
    c2 = (lo > 0 or hi < 0) and dv > 0
    se = (hi - lo) / (2 * 1.645)
    mde = Z80 * se
    verdict = c1 and c2

    # ---- secondary: rank portfolios – new evidence (Holm at 10 %) and the replication of round 3 -----------------
    every = [a for v in inst.values() for a in v]
    nxt = end_view.total_return(every, "ME").pct_change(fill_method=None).shift(-1)
    sec_rows, pvals, ls_series = [], {}, {}
    xs = [k for k, v in sleeves.items() if v["mode"] != "long_ts" and float(v["budget"]) > 0 and inst[k]]
    for k in xs:
        sc = signal_frame(rule, [f"score:{a}" for a in inst[k]], decided).set_axis(inst[k], axis=1)
        if sc.dropna(how="all").empty:
            sec_rows.append({"Sleeve": k, "Rolle": "nie aktiv (ADR 057 h)", "Monate": 0})
            continue
        ls = long_short_rank_returns(sc, nxt.reindex(columns=inst[k]))
        ls_series[k] = ls
        mean, t = newey_west_t(ls, NW_LAGS)
        p = one_sided_p(t)
        if k in NEW_EVIDENCE:
            pvals[k] = p
        ic = mean_ci(spearman_rows(sc, nxt.reindex(index=sc.index, columns=inst[k])).dropna(), BOOT, CONF)
        sec_rows.append(
            {
                "Sleeve": k,
                "Rolle": "neu (Holm)" if k in NEW_EVIDENCE else "Replikation Runde 3",
                "Monate": int(ls.notna().sum()),
                "Rang-L/S p.a.": mean * 12,
                "t (Newey-West)": t,
                "p einseitig": p,
                "Rang-IC": ic.mean,
                "IC low": ic.low,
                "IC high": ic.high,
            }
        )
    adj = holm(pvals, HOLM_ALPHA) if pvals else {}
    sec = pd.DataFrame(sec_rows).set_index("Sleeve")
    sec["p Holm"] = [adj[k][0] if k in adj else np.nan for k in sec.index]
    sec["belegt"] = [("ja" if adj[k][1] else "nein") if k in adj else "–" for k in sec.index]
    sec.to_csv(os.path.join(OUT, "walkforward_signals.csv"))
    pd.DataFrame(ls_series).to_csv(os.path.join(OUT, "walkforward_rank_portfolios.csv"))

    # ---- reported, not deciding ------------------------------------------------------------------------------------
    n_trials, _ = register(include_planned=True)
    own = {}
    for label in [RULE, *variants]:
        a = appraisal_residual(series[label][0], r_b1, cash)
        own[label] = float(a.mean() / a.std(ddof=1) * np.sqrt(12))
    resid = appraisal_residual(r_main, r_b1, cash)
    sr_a, sr0_a, psr_a = deflated_sharpe(resid, n_trials, trials_variance(pd.Series(own)))
    fx_live = pd.Series(False, index=index)
    if "nur Sleeve FX" in variants:
        g_fx = signal_frame(variants["nur Sleeve FX"].result, ["gross_overlay"], decided)["gross_overlay"]
        on = g_fx.fillna(0.0) > 0
        if on.any():
            fx_live = pd.Series(index >= on[on].index[0] + pd.offsets.MonthEnd(1), index=index)
    fx_only = (
        sharpe_ci(series["nur Sleeve FX"][0][fx_live], cash[fx_live], BOOT, CONF)
        if bool(fx_live.any())
        else None
    )
    keys = [
        "book_vol_predicted",
        "cap_physical",
        "cap_rates",
        "cap_overlay",
        "gross_physical",
        "gross_rates",
        "gross_overlay",
        "pre_filter_physical",
        "pre_filter_rates",
        "pre_filter_overlay",
    ]
    sg = signal_frame(rule, keys, decided)
    sg_b1 = signal_frame(runs[B1].result, keys, decided)
    pred = sg["book_vol_predicted"].reindex(decided)
    held = pred > 0.005  # a book (almost) all in cash has no risk to calibrate
    z = (((r_main - cash).set_axis(decided)) / (pred / np.sqrt(12)))[held]
    yrs = pd.Series(index.year, index=index)

    def dsh(mask: pd.Series) -> str:
        if int(mask.sum()) < 24:  # a period the window barely touches carries no statement
            return f"– ({int(mask.sum())} Monate)"
        d = paired_sharpe_diff(r_main[mask], r_b1[mask], cash[mask], BOOT, CONF)
        return f"{d.value:+.3f} [{d.low:+.3f}, {d.high:+.3f}] ({int(mask.sum())} Monate)"

    contrib = ((r_main - cash) - (r_b1 - cash)).groupby(yrs).sum()  # sum of monthly excess-return differences
    best = int(contrib.idxmax())
    calib = {
        name: float(z[(z.index.year >= a) & (z.index.year <= e)].std())
        for name, a, e in PERIODS
        if int(((z.index.year >= a) & (z.index.year <= e)).sum()) >= 24
    }
    in_cash = int((~held).sum())
    lag_cost = float(table.loc["Ausführung zum Entscheidungskurs", "Sharpe ex Cash"]) - sh_rule
    fx_months = int((sg["gross_overlay"].fillna(0) > 0).sum())
    disp = pd.DataFrame(
        [
            row(
                f"{k} (Vol {sig_main:.1%})",
                vol_matched(series[k][0], cash, sig_main),
                cash,
                series[k][2],
                series[k][3],
            )
            for k in baselines[1:]
        ]
    ).set_index("Lauf")
    mix = pd.DataFrame(
        {
            f"{lab} {stage}": [
                frame[f"{pre}physical"].mean(),
                frame[f"{pre}rates"].mean(),
                frame[f"{pre}overlay"].mean(),
            ]
            for lab, frame in ((RULE, sg), (B1, sg_b1))
            for stage, pre in (("vor Filter", "pre_filter_"), ("gehalten", "gross_"))
        },
        index=pd.Index(["physisch", "Zinsen", "Overlay brutto"], name="Ø Gewicht"),
    ).T

    lines = [
        f"# Sleeve-Allokator v2 (Forschungsrunde 4, ADR 057/058): Walk-forward {index[0]:%Y-%m} bis {index[-1]:%Y-%m}",
        "",
        f"Stand {date.today().isoformat()}. Allokator, Baselines und Varianten durch dieselbe Engine, Ausführung `{gr.execution}` "
        "(Tagesreihen am Folgetag, Länder zum Entscheidungskurs), Kosten je Instrument und Finanzierung des Hebels zum Cash-Index "
        f"`{cash_asset}` +{spread.get('CASH', 0):.0f} bp (ADR 057 d, 058; Annahmen). Fenster nach ADR 058 (e): Renditemonate "
        f"{index[0]:%Y-%m} bis {index[-1]:%Y-%m} ({len(index)} Monate); erste Entscheidung mit allen Long-Sleeves {first_full:%Y-%m}; "
        f"Datenende je Gruppe: {', '.join(f'{g} {e:%Y-%m}' for g, e in ends.items())}. Währungs-Overlay in {fx_months} von "
        f"{len(index)} Monaten (handelbar ab 1991, ADR 058 f). "
        + (f"Nie aktiv (ADR 057 h, Budget bleibt Cash): {', '.join(never)}. " if never else "")
        + f"Intervalle: {int(CONF * 100)}-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025), gepaart. Alle "
        "Zahlen aus `scripts/allocator_v2_walkforward.py`.",
        "",
        "**Einordnung:** null freie Parameter, jede Grösse am Entscheidungstag nur aus Daten bis dahin; Design, Kriterien, "
        "Varianten und Notfallregeln vor dem Download der Daten fixiert (ADR 057, 058). Out-of-sample bezüglich der Daten, "
        "in-sample bezüglich der Literaturwahl und der Erfahrung aus drei Runden auf überlappender Historie – deshalb der "
        "Deflated Sharpe mit dem ganzen Versuchsregister.",
        "",
        "## Kennzahlen",
        "",
        md_table(table.loc[[RULE, *baselines]]),
        "",
        "B2–B4 ex post auf die Vol des Allokators skaliert (nur Darstellung):",
        "",
        md_table(disp),
        "",
        "Mittlere Gewichte über das Fenster: „vor Filter“ ist die konstruierte Mischung nach den Kappen (bei Allokator und B1 "
        "gleich gebaut; ein Rest kommt aus konzentrierteren Körben der Auswahl, ADR 058 d), „gehalten“ nach dem Trendfilter:",
        "",
        md_table(mix),
        "",
        "## Gepaarte Differenzen Allokator − Baseline",
        "",
        md_table(dtab),
        "",
        "## Sekundär: die Signale je Querschnitts-Sleeve",
        "",
        "Dollar-neutrales Rang-Portfolio ∝ (N+1)/2 − Rang (Σ|w| = 1, vor Kosten), Score am Monatsende, Rendite des Folgemonats; "
        f"einseitiger t-Test mit Newey-West-Standardfehler ({NW_LAGS} Lags). Holm auf 10 % über die neuen Signale "
        f"({', '.join(NEW_EVIDENCE)}); EQ_US wiederholt das Industrie-Signal von Runde 3 auf überlappenden Monaten und ist "
        "eine Replikation ohne eigene Beweiskraft (ADR 058).",
        "",
        md_table(sec),
        "",
        "## Varianten (ADR 057 g: vorab benannt, berichtet, entscheiden nicht)",
        "",
        md_table(table.loc[list(variants)]),
        "",
        "## Berichtet, nicht entscheidend",
        "",
        "- Teilperioden Δ Sharpe zu B1: "
        + "; ".join(f"{n} {dsh((yrs >= a) & (yrs <= e))}" for n, a, e in PERIODS)
        + f"; ohne das Kalenderjahr mit der grössten Summe der monatlichen Überschussrendite-Differenz ({best}): {dsh(yrs != best)}.",
        "- Vol-Kalibrierung (Standardabweichung der standardisierten Folgemonatsrendite, 1 = treffend): "
        + "; ".join(f"{n} {v:.2f}" for n, v in calib.items())
        + f" ({in_cash} Monate mit fast leerem Buch – vorhergesagte Vol unter 0.5 % – ausgenommen)"
        + f"; Anteil Entscheidungen mit gebundener Kappe – physisch {sg['cap_physical'].mean():.0%}, Zinsen "
        f"{sg['cap_rates'].mean():.0%}, Overlay {sg['cap_overlay'].mean():.0%} (B1: Zinsen {sg_b1['cap_rates'].mean():.0%}).",
        f"- Verzögerungskosten der Ausführung (Sharpe am Entscheidungskurs minus Folgetag): {lag_cost:+.3f}.",
        *(
            [
                f"- FX-Sleeve allein (ab seinem ersten Monat, {int(fx_live.sum())} Monate): Sharpe {fx_only.value:+.3f} "
                f"[{fx_only.low:+.3f}, {fx_only.high:+.3f}]."
            ]
            if fx_only
            else []
        ),
        f"- Deflated Sharpe (Residualrendite gegen B1, N = {n_trials} inkl. dieser Runde, Varianz aus dem Register und den "
        f"{len(own)} Läufen dieser Runde): {sr_a * 12**0.5:+.3f} p.a., Hürde {sr0_a * 12**0.5:+.3f}, Wahrscheinlichkeit "
        f"**{psr_a:.3f}** (≥ 0.95 überlebt die Mehrfachprüfung).",
        "",
        "## Urteil nach ADR 057 (f) – Kriterien vorab festgelegt",
        "",
        f"1. Sharpe ex Cash des Allokators ({sh_rule:+.3f}) über B1 ({sh_b1:+.3f}): **{'ja' if c1 else 'nein'}**",
        f"2. Gepaarte Sharpe-Differenz zu B1 positiv und Intervall ohne Null: **{'ja' if c2 else 'nein'}** ({dv:+.3f} [{lo:+.3f}, {hi:+.3f}])",
        f"→ Vorteil des Allokators belegt: **{'JA' if verdict else 'NEIN'}**"
        + (
            ""
            if verdict
            else (
                f" – Standardfehler {se:.3f}, MDE (80 % Power) {mde:.2f}: "
                + (
                    "nicht belegt – Test zu schwach für Effekte unter der MDE"
                    if mde > MDE_READING
                    else "nicht belegt – Effekte über der MDE sind unwahrscheinlich"
                )
            )
        ),
        "",
        f"Laufzeit {time.perf_counter() - t0:.0f} s.",
    ]
    with open(os.path.join(OUT, "WALKFORWARD.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
