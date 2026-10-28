"""P4 (ADR 044): historical evaluation of the asset-class forecast on the pre-registered window, holdout untouched.

Writes output/<config>/EVALUATION.md, summary.json and CSVs. Every number in the report comes from this run;
the criteria it is judged against were fixed before it ran (ADR 044 f; round 2: ADR 052 d/e with the same
criteria, the ablations of ADR 052 e reported, not decided).

Aufruf: python scripts/forecast_evaluation.py [--config forecast|forecast_v2]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import (  # noqa: E402
    CONF,
    bond_class,
    ci_text,
    display_decades,
    load,
    md_table,
    p_text,
    parse_args,
    years,
)
from rotationlab.core import registry  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import averaged_assets, research_factory  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    assert_outside_holdout,
    brier,
    by_class,
    by_decade,
    climatology,
    derived_portfolio,
    mean_ci,
    paired_diff,
    perf,
    permutation_pvalue,
    previous_month_scores,
    reliability,
    spearman_rows,
    top_bottom,
    window,
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

# round 1 only – config.py REGIME_TILTS restricted to the ranked classes; quadrant labels of the registered feature
REGIME_TILTS = {
    "high_low": {"US_EQ": 0.3},
    "high_high": {"SILVER": 0.2},
    "low_high": {"GOLD": 0.4, "SILVER": 0.2},
    "low_low": {"UST10": 0.4, "GOLD": 0.1},
}


def main(config: str) -> None:
    t0 = time.perf_counter()
    b, fc, out = load(config)
    v1 = config == "forecast"  # round 1 carries two extras: the regime-tilt variant and its in-sample caveat
    cal = make_calendar(b)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, cal, fc.evaluation.data_from)
    model = ForecastModel(fc, averaged=averaged_assets(b))
    boot = BlockBootstrap(fc.calibration.draws, fc.calibration.block_months, fc.calibration.seed)
    ranked, cash = model.ranked, model.cash
    n_cls = len(ranked)
    decades = display_decades(fc)
    complete = [d[0] for d in fc.evaluation.decades]

    # ---- the evaluation window and the guard --------------------------------------------------------
    first, last1 = window(fc, 1, fc.evaluation.start)
    end_view = f.at(last1 + pd.offsets.MonthEnd(1))  # the last outcome month of the 1-month horizon
    assert end_view.date < fc.holdout.start
    levels = complete_months(end_view, end_view.total_return([*ranked, cash], "ME"))
    returns = levels / levels.shift(1) - 1
    cash_r = returns[cash]
    lines = [
        f"# Prognose der Anlageklassen: historische Evaluation {years(first, last1)}"
        + ("" if v1 else f" (Forschungsrunde 2, `{config}`)"),
        "",
        f"Stand {date.today().isoformat()}. Modell `{model.model_id}` v{model.version}, gerankte Klassen {ranked}, Cash {cash}; "
        f"Panel ab {fc.evaluation.data_from}.",
        f"Entscheidungen {first} bis {last1} (1 M); Ergebnisfenster enden vor dem Pseudo-Holdout ({fc.holdout.start}).",
        f"Kennzahlen mit {int(CONF * 100)}-%-Moving-Block-Bootstrap (Block {fc.calibration.block_months}, {fc.calibration.draws} Ziehungen, Seed {fc.calibration.seed}).",
        f"Kriterien vorab in ADR 044 (f){'' if v1 else ', übernommen in ADR 052 (d/e)'}. Alle Zahlen aus "
        f"`scripts/forecast_evaluation.py --config {config}`.",
        "",
        (
            "**Einordnung (Zweitprüfung 2026-10-26):** Features und Gewichte des Basismodells stammen aus der Forschungsphase "
            "(`src/signals.py`, Komposit der multi_asset_rotation) und wurden auf demselben Zeitraum gefunden; diese Evaluation ist "
            "deshalb **in-sample bezüglich der Modellwahl** – vorab fixiert sind die Kriterien und die Auswertung, nicht das Modell. "
            "Als Robustheitsargument dient die Variante „12-1-Momentum allein“ (keine angepassten Gewichte, ein Standardfeature der "
            "Literatur); echte Out-of-Sample-Evidenz liefern nur der unberührte Pseudo-Holdout 2019–2025 (einmalig, am Schluss) und "
            "die Live-Bilanz ab November 2026."
            if v1
            else "**Einordnung:** Familien, Gewichte (gleich), Klassen und Fenster sind in ADR 052 vor dem ersten Lauf fixiert und "
            "nicht auf diesen Daten gewählt; die Ablationen unten werden berichtet und entscheiden nicht. Die Wahl der drei "
            "Standardfamilien ist aber im Wissen um die Literatur und um Runde 1 getroffen, und derselbe Zeitraum wurde in Runde 1 "
            "bereits ausgewertet – ein zweiter Blick auf dieselben Jahre ist keine unabhängige Stichprobe. Echte Out-of-Sample-"
            "Evidenz liefern der einmalige Blick auf 2019–2025 (ADR 052 f) und die Live-Bilanz."
        ),
        "",
    ]
    results: dict[str, object] = {}

    # ---- scores: panel at the end of the window (= pointwise scores, proved in P3) ------------------
    feats = {k: feature_panel(end_view, k, ranked, **model.feature_params.get(k, {})) for k in model.weights}
    scores = composite(feats, model.weights, model.clip).reindex(columns=ranked)
    scores = scores[(scores.index >= pd.Timestamp(first)) & (scores.index <= pd.Timestamp(last1))]
    trend = feature_panel(end_view, "trend_10m", ranked).reindex(scores.index)
    # months scored on fewer than all features: `composite` keeps the sum of the available ones (research
    # formula); at the start of the panel the longer look-backs are not there yet (second review, finding 5)
    n_feat = sum((feats[k].reindex(scores.index).notna().all(axis=1)).astype(int) for k in model.weights)
    no_score = n_feat[n_feat == 0]  # no feature at all: NaN score, never in any sample
    incomplete = n_feat[(n_feat > 0) & (n_feat < len(model.weights))]
    results["incomplete_months"] = incomplete
    span = f"{incomplete.index.min():%Y-%m} bis {incomplete.index.max():%Y-%m}" if len(incomplete) else "–"
    lines += [
        f"Feature-Satz: {len(model.weights)} Features. {len(no_score)} Entscheidungsmonate am Panelanfang haben keinen Score "
        f"(kein Feature berechenbar) und sind in keiner Stichprobe; {len(incomplete)} Monate ({span}) sind mit "
        f"unvollständigem Satz bewertet ({int(incomplete.min()) if len(incomplete) else 0}–{int(incomplete.max()) if len(incomplete) else 0} Features, "
        "Forschungsformel: Summe der verfügbaren). Sie bleiben in der vorab festgelegten Stichprobe; die Sensitivität ohne sie "
        "steht beim 1-Monats-Horizont.",
        "",
    ]

    for h in fc.horizons:
        _, last = window(fc, h)
        s = scores[scores.index <= pd.Timestamp(last)]
        assert_outside_holdout(s.index, fc, h)
        rel = relative(forward_returns(levels[ranked], h)).reindex(s.index)
        ranks = ranks_of(s)
        ic = spearman_rows(s, rel)
        tb = top_bottom(ranks, rel)
        ic_ci = mean_ci(ic, boot, CONF)
        hit_ci = mean_ci(tb["hit"], boot, CONF)
        spread_ci = mean_ci(tb["spread"] * 12 / h, boot, CONF)  # an h-month spread, annualised
        p_val, null95, _ = permutation_pvalue(s, rel, fc.calibration.draws, fc.calibration.seed)
        prev = previous_month_scores(levels[ranked]).reindex(s.index)
        ic_prev = spearman_rows(prev, rel)
        prev_ci = mean_ci(ic_prev, boot, CONF)
        dec = by_decade(ic, decades)
        results[f"h{h}"] = {
            "ic": ic_ci,
            "hit": hit_ci,
            "spread": spread_ci,
            "p": p_val,
            "null95": null95,
            "prev": prev_ci,
            "decades": dec,
        }
        lines += [
            f"## Horizont {h} Monat{'e' if h > 1 else ''} ({'Hauptprognose' if h == 1 else 'Nebenauswertung'})",
            "",
            f"- Rang-IC (Spearman, Mittel je Monat): **{ci_text(ic_ci)}**; Anteil Monate mit IC > 0: {float((ic.dropna() > 0).mean()):.3f}",
            f"- Zufälliger Rang (Permutation, {fc.calibration.draws} Ziehungen): p = **{p_text(p_val, fc.calibration.draws)}**, 95. Perzentil des Null-Mittels {null95:+.4f}"
            + (
                " – der Test permutiert jeden Monat unabhängig; bei überlappenden Ergebnisfenstern ist seine Nullverteilung zu eng, massgeblich ist hier das Block-Bootstrap-Intervall"
                if h > 1
                else ""
            ),
            f"- Vormonatsrang als Prognose: IC {ci_text(prev_ci)}",
            f"- Trefferquote Rang 1 schlägt Rang {len(ranked)}: **{hit_ci.mean:.3f}** [{hit_ci.low:.3f}, {hit_ci.high:.3f}] (Zufall 0.5)",
            f"- Top-minus-Bottom-Spread über {h} Monat{'e' if h > 1 else ''}, annualisiert (×12/{h}): {ci_text(spread_ci)}",
            *(
                [
                    f"- Sensitivität ohne die {len(incomplete)} Monate mit unvollständigem Feature-Satz: IC {ci_text(mean_ci(ic.drop(incomplete.index, errors='ignore'), boot, CONF))}"
                ]
                if h == 1 and len(incomplete)
                else []
            ),
            "",
            "Je Jahrzehnt (IC):",
            "",
            md_table(dec),
            "",
        ]
        dec.to_csv(os.path.join(out, f"ic_by_decade_h{h}.csv"))
        pd.DataFrame({"ic": ic, "ic_prev_month": ic_prev, **tb}).to_csv(
            os.path.join(out, f"monthly_h{h}.csv")
        )
        if h == 1:
            bc = by_class(ranks, rel)
            bc.to_csv(os.path.join(out, "by_class_h1.csv"), index=False)
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
            scores1, rel1, ranks1, trend1 = s, rel, ranks, trend.reindex(s.index)

    # ---- probabilities and status: point-in-time loop (1 month), every model on the configured target ---
    target = fc.probability.target
    hit1 = hit_matrix(rel1, target)
    hit_old = hit_matrix(rel1, "beats_mean")
    clim = climatology(hit1, fc.calibration.min_months).reindex(columns=ranked)
    models = ["logistic_tophalf", "rank_class", "rank_frequency", "logistic_score"]
    prob_tables: dict[str, pd.DataFrame] = {}
    status_by_model: dict[str, pd.Series] = {}
    for name in models:
        cfg_m = fc.model_copy(update={"probability": fc.probability.model_copy(update={"model": name})})
        model_m = ForecastModel(cfg_m, averaged=averaged_assets(b))
        rows = []
        for d in scores1.index:
            fm = model_m.forecast(f.at(d.date()), "eval", [1])[0]
            rows += [
                {"date": d, "asset": c.asset, "prob": c.probability, "status": fm.status}
                for c in fm.classes
                if c.ranked
            ]
        pit = pd.DataFrame(rows)
        prob_tables[name] = pit.pivot(index="date", columns="asset", values="prob").reindex(columns=ranked)
        status_by_model[name] = pit.groupby("date")["status"].first()
    prob = prob_tables[fc.probability.model]
    status = status_by_model[fc.probability.model]
    known = prob.notna().all(axis=1)
    b_const = brier(prob.notna() * 0.5, hit1).where(known)
    b_clim = brier(clim, hit1).where(known)
    bc0, bcl = float(b_const.dropna().mean()), float(b_clim.dropna().mean())
    prow = []
    skills: dict[str, tuple] = {}
    for name, pt_ in prob_tables.items():
        bm_ = brier(pt_, hit1).where(known)
        sk0 = paired_diff(b_const / 12, bm_ / 12, boot, CONF)
        skc = paired_diff(b_clim / 12, bm_ / 12, boot, CONF)
        skills[name] = (sk0, skc)
        prow.append(
            {
                "Modell": name,
                "Brier": float(bm_.dropna().mean()),
                "Skill vs 0.5": sk0.mean,
                "low": sk0.low,
                "high": sk0.high,
                "Skill vs Klimatologie": skc.mean,
                "low ": skc.low,
                "high ": skc.high,
            }
        )
        reliability(pt_, hit1).to_csv(os.path.join(out, f"reliability_{name}_h1.csv"), index=False)
    ptab = pd.DataFrame(prow).set_index("Modell")
    ptab.to_csv(os.path.join(out, "probability_models_h1.csv"))
    rel_tab = reliability(prob, hit1)
    # ADR 044 (c) "alles je Jahrzehnt und je Klasse" also for the probabilities (second review, finding 8):
    # Brier of the primary model, the climatology and 0.5 per decade and per class
    bm_primary = brier(prob, hit1).where(known)
    brier_dec = pd.DataFrame(
        {
            "Modell": by_decade(bm_primary, decades)["mean"],
            "Klimatologie": by_decade(b_clim, decades)["mean"],
            "0.5": by_decade(b_const, decades)["mean"],
        }
    )
    brier_dec["Monate"] = by_decade(bm_primary, decades)["months"].astype(int)
    hk = hit1.reindex(index=prob.index)[known]
    brier_cls = pd.DataFrame(
        {
            "Modell": ((prob[known] - hk) ** 2).mean(),
            "Klimatologie": ((clim.reindex(index=prob.index)[known] - hk) ** 2).mean(),
            "0.5": ((0.5 - hk) ** 2).mean(),
        }
    )
    brier_cls.index.name = "Klasse"
    brier_dec.to_csv(os.path.join(out, "brier_by_decade_h1.csv"))
    brier_cls.to_csv(os.path.join(out, "brier_by_class_h1.csv"))
    # the old target for reference (ADR 044): the primary model of ADR 044 on "beats the mean"
    clim_old = climatology(hit_old, fc.calibration.min_months).reindex(columns=ranked)
    b_clim_old = brier(clim_old, hit_old).where(known)
    tb1 = top_bottom(ranks1, rel1)
    st = pd.DataFrame(
        {"status": status.reindex(tb1.index), "hit": tb1["hit"], "ic": spearman_rows(scores1, rel1)}
    ).dropna()
    tb_status = st.groupby("status").agg(
        months=("hit", "size"), hit_rate=("hit", "mean"), mean_ic=("ic", "mean")
    )
    skill_const, skill_clim = skills[fc.probability.model]
    results["prob"] = {
        "const": bc0,
        "clim": bcl,
        "skill_const": skill_const,
        "skill_clim": skill_clim,
        "status": tb_status,
        "table": ptab,
    }
    base_rates = hit1.mean().round(3).to_dict()
    lines += [
        f"## Wahrscheinlichkeiten (1 Monat, Hauptausgabe) – Ziel `{target}`",
        "",
        f"Ziel „{f'landet in der oberen Hälfte (Rang 1–{n_cls // 2} von {n_cls})' if target == 'top_half' else 'schlägt den Durchschnitt'}“ (ADR 045 b). Grundraten je Klasse {years(first, last1)}: {base_rates}.",
        f"Primäres Modell `{fc.probability.model}`; alle Modelle punkt-in-Zeit über {int(known.sum())} Monatsenden; Prior {fc.probability.prior_months} Monate; Status-Marge {fc.probability.no_signal_margin:.2f} (beschreibend).",
        f"Baselines: Konstante 0.5 Brier {bc0:.4f}; Klimatologie (expandierende Häufigkeit je Klasse) Brier {bcl:.4f}. Skill = Brier(Baseline) − Brier(Modell), positiv = Modell besser; Kriterium ADR 045: Skill gegen Klimatologie mit Intervall ohne Null.",
        "",
        md_table(ptab, "{:.5f}"),
        "",
        "Reliability des primären Modells (vorhergesagt vs. beobachtet):",
        "",
        md_table(rel_tab.set_index("bin"), "{:.3f}"),
        "",
        "Brier je Jahrzehnt (primäres Modell, Klimatologie, 0.5):",
        "",
        md_table(brier_dec, "{:.4f}"),
        "",
        "Brier je Klasse:",
        "",
        md_table(brier_cls, "{:.4f}"),
        "",
        f"Zum Vergleich das alte Ziel „schlägt den Durchschnitt“ (ADR 044): Klimatologie Brier {float(b_clim_old.dropna().mean()):.4f}, Grundraten {hit_old.mean().round(3).to_dict()}.",
        "",
        f"Status (beschreibend, ADR 045 c) und Trefferquote (Rang 1 schlägt Rang {n_cls}) bzw. IC:",
        "",
        md_table(tb_status, "{:.3f}"),
        "",
    ]
    # status variant A: calibration within the tercile of today's top-bottom score gap
    gap = (scores1.max(axis=1) - scores1.min(axis=1)).dropna()
    terc = pd.Series(index=gap.index, dtype=object)
    for i, t in enumerate(gap.index):
        past = gap.iloc[:i]
        if len(past) < 60:
            continue
        q1, q2 = past.quantile([1 / 3, 2 / 3])
        terc[t] = "low" if gap[t] <= q1 else ("mid" if gap[t] <= q2 else "high")
    st_a = pd.DataFrame({"tercile": terc, "hit": tb1["hit"], "ic": spearman_rows(scores1, rel1)}).dropna()
    t_a = (
        st_a.groupby("tercile")
        .agg(months=("hit", "size"), hit_rate=("hit", "mean"), mean_ic=("ic", "mean"))
        .reindex(["low", "mid", "high"])
    )
    lines += [
        f"Variante A (Terzil des heutigen Score-Abstands Rang 1 – Rang {n_cls}, Terzile aus der Vergangenheit):",
        "",
        md_table(t_a, "{:.3f}"),
        "",
    ]
    results["terciles"] = t_a

    # ---- variants: the configured ones (feature subsets), round 1 also the regime tilts (1 month, paired) ---
    rel = rel1
    ic_base = spearman_rows(scores1, rel)
    variants = {}
    labels = {"mom_12_1": "12-1-Momentum allein"}  # round-1 report wording
    for vname, vcfg in fc.variants.items():
        vw = dict(vcfg.feature_weights)
        vfeats = {
            k: feats[k]
            if k in feats
            else feature_panel(end_view, k, ranked, **model.feature_params.get(k, {}))
            for k in vw
        }
        variants[labels.get(vname, vname)] = composite(vfeats, vw, model.clip).reindex(
            index=scores1.index, columns=ranked
        )
    qlab = pd.Series(dtype=object)
    if v1:
        quad = registry.get_feature("quadrant")
        qpanel = quad.panel_input(end_view, None, **dict(quad.params))
        qlab = pd.Series(quad.call_panel(qpanel), index=qpanel.index).reindex(scores1.index)
        tilt = pd.DataFrame(0.0, index=scores1.index, columns=ranked)
        for lab, bonus in REGIME_TILTS.items():
            m = qlab == lab
            for a, v in bonus.items():
                tilt.loc[m, a] += v
        variants["Basismodell + Regime-Tilts"] = scores1 + tilt
    lines += [
        "## Varianten (1 Monat, gepaarte Differenz des IC zum Basismodell)"
        + ("" if v1 else " – Ablationen, berichtet, entscheiden nicht (ADR 052 e)"),
        "",
    ]
    vrows = []
    for name, sc in variants.items():
        icv = spearman_rows(sc, rel)
        d = mean_ci(icv - ic_base, boot, CONF)
        own = mean_ci(icv, boot, CONF)
        vrows.append(
            {
                "Variante": name,
                "IC": own.mean,
                "IC low": own.low,
                "IC high": own.high,
                "Δ zum Basismodell": d.mean,
                "Δ low": d.low,
                "Δ high": d.high,
            }
        )
        results[name] = {"ic": own, "diff": d}
    vt = pd.DataFrame(vrows).set_index("Variante")
    lines += [
        md_table(vt),
        "",
        *(
            [
                f"Regime-Labels bekannt in {int(qlab.notna().sum())} von {len(qlab)} Monaten (unbekannt = kein Tilt)."
            ]
            if v1
            else []
        ),
        "",
    ]
    vt.to_csv(os.path.join(out, "variants_h1.csv"))

    # ---- derived weights vs portfolio baselines (before costs, research timing) ---------------------
    r4 = returns[ranked].reindex(scores1.index.union(scores1.index + pd.offsets.MonthEnd(1)))
    cash_s = cash_r.reindex(r4.index)
    der = derived_portfolio(ranks1, trend1, r4, cash_s)
    ew = r4.mean(axis=1).reindex(der.dropna().index)
    bond = bond_class(b, ranked)
    sixty = (0.6 * r4["US_EQ"] + 0.4 * r4[bond]).reindex(der.dropna().index)
    bh = r4["US_EQ"].reindex(der.dropna().index)
    der = der.dropna()
    cs = cash_s.reindex(der.index)
    prow = {
        "Abgeleitet: Top-2 + Trendfilter": perf(der, cs),
        f"Equal Weight ({n_cls} Klassen)": perf(ew, cs),
        f"60/40 US_EQ/{bond}": perf(sixty, cs),
        "Buy-and-Hold US_EQ": perf(bh, cs),
    }
    pt = pd.DataFrame(prow).T
    diffs = {
        k: paired_diff(der, v, boot, CONF)
        for k, v in (("Equal Weight", ew), ("60/40", sixty), ("Buy-and-Hold", bh))
    }
    lines += [
        "## Abgeleitete Gewichte gegen Portfolio-Baselines (vor Kosten, Umsetzung zum Entscheidungsschluss)",
        "",
        "Nur zur Einordnung – die Portfolio-Schicht mit Kosten, ehrlichem Timing und Vol-Ziel ist Schritt P8 und wird nur gebaut, wenn die Kriterien erfüllt sind.",
        "",
        md_table(pt),
        "",
        "Gepaarte Differenz der Monatsrendite (annualisiert), abgeleitet minus Baseline:",
        "",
        *[f"- {k}: {ci_text(v)}" for k, v in diffs.items()],
        "",
    ]
    pt.to_csv(os.path.join(out, "derived_vs_baselines.csv"))

    # ---- the verdict against ADR 044 (f) -------------------------------------------------------------
    h1 = results["h1"]
    n_dec = len(complete)
    dec_pos = int((h1["decades"].reindex(complete)["mean"] > 0).sum())
    c1, c2, c3 = h1["ic"].low > 0, h1["p"] < 0.05, dec_pos >= n_dec - 1
    prob_ok = skill_clim.low > 0
    keep = {}
    for h in (3, 6):
        if f"h{h}" in results:
            r = results[f"h{h}"]
            keep[h] = r["ic"].low > 0 and r["ic"].mean > r["prev"].mean
    rec = {name: results[name]["diff"].low > 0 for name in variants}
    status_ok = None
    if tb_status is not None and {"signal", "no_clear_signal"} <= set(tb_status.index):
        status_ok = tb_status.loc["signal", "hit_rate"] > tb_status.loc["no_clear_signal", "hit_rate"]
    lines += [
        "## Urteil nach ADR 044 (f) – Kriterien vorab festgelegt",
        "",
        f"1. IC-Intervall (1 M) schliesst die Null aus: **{'ja' if c1 else 'nein'}** ({h1['ic'].low:+.4f} … {h1['ic'].high:+.4f})",
        f"2. Permutations-p < 0.05: **{'ja' if c2 else 'nein'}** (p = {p_text(h1['p'], fc.calibration.draws)})",
        f"3. IC positiv in ≥ {n_dec - 1} der {n_dec} vollständigen Jahrzehnte: **{'ja' if c3 else 'nein'}** ({dec_pos} von {n_dec})",
        f"→ Prognosevorteil nach den vorab fixierten Kriterien: **{'JA' if (c1 and c2 and c3) else 'NEIN'}**"
        + (
            " (in-sample bezüglich der Modellwahl, siehe Einordnung oben)"
            if v1
            else " (Modell vorab fixiert, siehe Einordnung oben)"
        ),
        "",
        f"- Wahrscheinlichkeiten informativ (ADR 045: Brier-Skill gegen die Klimatologie > 0, Intervall ohne Null): primäres Modell `{fc.probability.model}` **{'ja' if prob_ok else 'nein'}**; alle Modelle: "
        + ", ".join(f"{k} {'ja' if v[1].low > 0 else 'nein'}" for k, v in skills.items()),
        *[
            f"- Horizont {h} M behalten (IC-Intervall ohne Null und IC über Vormonatsrang): **{'ja' if v else 'nein'}**"
            for h, v in keep.items()
        ],
        *[
            f"- {name} {'empfehlen' if v1 else 'besser als das Basismodell'} (Δ-Intervall ohne Null): **{'ja' if v else 'nein'}**"
            + ("" if v1 else " – berichtet, entscheidet nicht")
            for name, v in rec.items()
        ],
        f"- Status brauchbar (Trefferquote in „signal“ > in „no_clear_signal“): **{'ja' if status_ok else 'nein' if status_ok is not None else 'nicht messbar (nur ein Status)'}**",
        "",
        f"Laufzeit {time.perf_counter() - t0:.0f} s.",
    ]
    with open(os.path.join(out, "EVALUATION.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    # the in-sample numbers the holdout script quotes (ADR 049 d): from this run, not typed in
    summary = {
        "config": config,
        "decisions": [str(first), str(last1)],
        "ic_h1": {"mean": h1["ic"].mean, "low": h1["ic"].low, "high": h1["ic"].high, "n": h1["ic"].n},
        "hit_h1": {"mean": h1["hit"].mean, "low": h1["hit"].low, "high": h1["hit"].high},
        "brier_skill_clim_h1": {"mean": skill_clim.mean, "low": skill_clim.low, "high": skill_clim.high},
        "verdict": bool(c1 and c2 and c3),
        "prob_ok": bool(prob_ok),
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print("\n".join(lines))


if __name__ == "__main__":
    main(parse_args(__doc__).config)
