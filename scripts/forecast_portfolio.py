"""P8 (ADR 048): the pre-registered portfolio rule on the forecast, in-sample window, against baselines.

Rule (fixed before this script first ran): the two best-ranked classes of the forecast, equal-weighted,
a pick below its 10-month average to cash, the sleeve scaled to a 10 % volatility target (12-month sample
volatility of the sleeve, floor 5 %, no leverage), traded `next_tradable` at the golden cost convention.
Baselines through the same engine, costs and timing: equal weight of the ranked classes (monthly), 60/40
US_EQ/Treasury (monthly), buy-and-hold US_EQ. Treasury leg: `UST10_ME` (month-end yields, ADR 047).
Named sensitivities (not the verdict): a leverage cap of 1.5; round 1 also the research series `UST10`.

Verdict (ADR 048 e): Sharpe ex cash above equal weight AND the 90 % block-bootstrap interval of the paired
Sharpe difference to equal weight excludes zero. Writes output/<config>/PORTFOLIO.md and CSVs. Round 2
(`--config forecast_v2`, ADR 052) runs the same rule as `forecast_portfolio_v2` on five classes.

Aufruf: python scripts/forecast_portfolio.py [--config forecast|forecast_v2]
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

from _forecast_common import (  # noqa: E402
    CONF,
    bond_class,
    display_decades,
    load,
    md_table,
    parse_args,
    register,
    trials_variance,
    years,
)
from rotationlab.config.models import GoldenRun  # noqa: E402
from rotationlab.core.types import Frequency  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.data.catalog import build_catalog  # noqa: E402
from rotationlab.engine import metrics  # noqa: E402
from rotationlab.engine.modes import GoldenReport, golden, research_factory  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    appraisal_residual,
    deflated_sharpe,
    paired_diff,
    paired_sharpe_diff,
)
from rotationlab.forecast.model import BlockBootstrap, composite, feature_panel, ranks_of  # noqa: E402
from rotationlab.strategies import build_strategy  # noqa: E402

RULE = "Regel (Top-2, Trend, Vol-Ziel 10 %)"


def baselines(ranked: list[str], bond: str) -> dict[str, dict[str, object]]:
    n = len(ranked)
    return {
        f"Equal Weight ({n} Klassen)": {"weights": dict.fromkeys(ranked, 1.0 / n), "rebalance": "monthly"},
        f"60/40 US_EQ/{bond}": {"weights": {"US_EQ": 0.6, bond: 0.4}, "rebalance": "monthly"},
        "Buy-and-Hold US_EQ": {"weights": {"US_EQ": 1.0}, "rebalance": "never"},
    }


def with_params(gr: GoldenRun, **params: object) -> GoldenRun:
    return gr.model_copy(update={"params": {**gr.params, **params}})


def aligned(rep: GoldenReport, index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return, cash return, one-way turnover and cost of a run on the common sample."""
    res = rep.result
    r = res.returns.reindex(index)
    c = res.cash_returns.reindex(index)
    t = res.turnover.reindex(index)
    cost = res.decisions["cost"].shift(1).iloc[1:].reindex(index)
    if r.isna().any() or c.isna().any():
        raise RuntimeError(f"{rep.strategy}: return series does not cover the common sample")
    return r, c, t, cost


def decade_table(
    rows: dict[str, tuple[pd.Series, pd.Series]], decades: list[tuple[str, int, int]]
) -> pd.DataFrame:
    out = []
    for name, a, b in decades:
        rec: dict[str, object] = {"decade": name}
        for label, (r, c) in rows.items():
            years = pd.DatetimeIndex(r.index).year
            sel = (years >= a) & (years <= b)
            if sel.sum() == 0:
                continue
            m = metrics.summary(r[sel], c[sel])
            rec[f"{label}: Rendite p.a."] = m["ann_return"]
            rec[f"{label}: Sharpe"] = m["sharpe_ex_cash"]
        rec["Monate"] = int(sel.sum())
        out.append(rec)
    return pd.DataFrame(out).set_index("decade")


def main(config: str) -> None:
    t0 = time.perf_counter()
    b, fc, out = load(config)
    v1 = config == "forecast"
    sid = fc.paper_rule
    assert sid is not None
    scfg = b.strategies[sid]
    cal = make_calendar(b)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    boot = BlockBootstrap(fc.calibration.draws, fc.calibration.block_months, fc.calibration.seed)
    gr = scfg.golden_run
    gr_fw = b.strategies["fixed_weights"].golden_run
    assert gr is not None and gr_fw is not None
    # the baselines trade the rule's classes over the rule's window (round 1: identical to their own config)
    gr_fw = gr_fw.model_copy(
        update={"data_from": gr.data_from, "start": gr.start, "end": gr.end, "sample": gr.sample}
    )
    fw_cfg = b.strategies["fixed_weights"].model_copy(
        update={"universe": scfg.universe, "long_history_universe": scfg.long_history_universe}
    )
    b = b.model_copy(update={"strategies": {**b.strategies, "fixed_weights": fw_cfg}})
    assert gr.sample[1] < fc.holdout.start and gr.end < fc.holdout.start, "P8 must stay outside the holdout"
    # the classes the rule trades (round 1: UST10_ME in place of the published research series UST10, ADR 048 c)
    cash_id = fc.universe["long_history"].cash
    ranked = [a for a in scfg.long_history_universe if a != cash_id]
    assert len(ranked) == len(fc.universe["long_history"].ranked)
    bond = bond_class(b, ranked)
    base = baselines(ranked, bond)
    ew_label = next(iter(base))
    # which legs trade at the next day's price and which at the month-end itself (monthly series)
    catalog = build_catalog(b)
    roles = b.universe.assets
    daily = [
        a
        for a in scfg.long_history_universe
        if any(catalog[s].frequency == Frequency.DAILY for s in roles[a].series.values())
    ]
    monthly = [a for a in scfg.long_history_universe if a not in daily]

    # ---- runs through the engine ------------------------------------------------------------------
    runs: dict[str, GoldenReport] = {RULE: golden(b, obs, sid, cal)}
    for label, params in base.items():
        runs[label] = golden(b, obs, "fixed_weights", cal, run=with_params(gr_fw, **params))
    sens: dict[str, GoldenReport] = {
        "Regel, Hebel bis 1.5": golden(b, obs, sid, cal, run=with_params(gr, max_exposure=1.5)),
    }
    if v1:  # round 1 ranks the research series UST10 in the published forecast (ADR 047/048 c)
        cfg_alt = scfg.model_copy(
            update={"long_history_universe": ["US_EQ", "UST10", "GOLD", "SILVER", "TBILL"]}
        )
        b_alt = b.model_copy(update={"strategies": {**b.strategies, sid: cfg_alt}})
        sens["Regel mit Forschungsreihe UST10"] = golden(b_alt, obs, sid, cal)
    for rep in [*runs.values(), *sens.values()]:
        assert rep.result.decisions.index.max() <= pd.Timestamp(gr.end)

    # ---- the common sample: months with a signal of the rule ----------------------------------------
    rule = runs[RULE].result
    r_rule, _ = rule.sample(gr.sample[0], gr.sample[1], count_warmup=False)
    index = pd.DatetimeIndex(r_rule.index)
    series = {label: aligned(rep, index) for label, rep in {**runs, **sens}.items()}
    cash = series[RULE][1]
    rows = []
    for label, (r, c, t, cost) in series.items():
        m = metrics.summary(r, c, t)
        rows.append(
            {
                "Lauf": label,
                "Monate": int(m["months"]),
                "Rendite p.a.": m["ann_return"],
                "Vol p.a.": m["ann_vol"],
                "Sharpe ex Cash": m["sharpe_ex_cash"],
                "Max Drawdown": m["max_drawdown"],
                "Calmar": m["calmar"],
                "Trefferquote": m["hit_rate"],
                "Umsatz p.a.": m["turnover_ann"],
                "Kosten p.a.": float(cost.fillna(0.0).mean() * 12),
            }
        )
    table = pd.DataFrame(rows).set_index("Lauf")
    table.to_csv(os.path.join(out, "portfolio_metrics.csv"))
    pd.DataFrame({label: s[0] for label, s in series.items()} | {"cash": cash}).to_csv(
        os.path.join(out, "portfolio_monthly.csv")
    )
    rule.weights.to_csv(os.path.join(out, "portfolio_weights.csv"))

    # ---- paired differences against the baselines (block bootstrap, paired draws) --------------------
    r_main = series[RULE][0]
    diffs = []
    for label in base:
        r_b = series[label][0]
        d_ret = paired_diff(r_main, r_b, boot, CONF)
        d_sh = paired_sharpe_diff(r_main, r_b, cash, boot, CONF)
        diffs.append(
            {
                "Baseline": label,
                "Δ Rendite p.a.": d_ret.mean,
                "low": d_ret.low,
                "high": d_ret.high,
                "Δ Sharpe": d_sh.value,
                "low ": d_sh.low,
                "high ": d_sh.high,
            }
        )
    dtab = pd.DataFrame(diffs).set_index("Baseline")
    dtab.to_csv(os.path.join(out, "portfolio_paired.csv"))

    # ---- exposure and the vol target in action -----------------------------------------------------
    # the decisions behind the sample: each return month is shaped by the decision one month earlier
    decided = pd.DatetimeIndex([d - pd.offsets.MonthEnd(1) for d in index])
    w = rule.weights.reindex(decided).fillna(0.0)
    risky = w.drop(columns=["CASH"], errors="ignore").sum(axis=1)
    sig = {pd.Timestamp(p.date): p.signals for p in rule.proposals if "scale" in p.signals}
    scale = np.array([sig[d]["scale"] for d in decided if d in sig])
    vol = np.array([sig[d]["sleeve_vol_12m"] for d in decided if d in sig])
    expo = {
        f"Entscheidungen {decided[0]:%Y-%m} bis {decided[-1]:%Y-%m}: mittlere Risikoquote": float(
            risky.mean()
        ),
        "Anteil Entscheidungen ganz in Cash": float((risky == 0).mean()),
        "Anteil Entscheidungen mit Vol-Skalierung < 1 (von denen mit Risikoteil)": float((scale < 1).mean())
        if len(scale)
        else float("nan"),
        "mittlere Skalierung (dito)": float(scale.mean()) if len(scale) else float("nan"),
        "Median Sleeve-Vol (dito)": float(np.median(vol)) if len(vol) else float("nan"),
    }
    first_dec = decided[0].date()
    fac = research_factory(b, obs, cal, gr.data_from)
    end_view = fac.at(gr.end)
    strat_me = build_strategy(b, sid, "long_history")

    def top2(assets: list[str]) -> pd.DataFrame:
        feats = {
            k: feature_panel(end_view, k, assets, **strat_me.feature_params.get(k, {}))
            for k in strat_me.weights
        }
        sc = composite(feats, strat_me.weights, strat_me.clip).reindex(columns=assets)
        sc = sc[(sc.index >= pd.Timestamp(first_dec)) & (sc.index <= decided[-1])]
        return ranks_of(sc) <= 2

    n_diff = n_cmp = 0
    if (
        v1
    ):  # (6) the evaluated ranking (treasury leg UST10_ME) against the published one (research series UST10)
        t_me = top2(["US_EQ", "UST10_ME", "GOLD", "SILVER"]).rename(columns={"UST10_ME": "UST10"})
        t_pub = top2(["US_EQ", "UST10", "GOLD", "SILVER"])
        both = t_me.notna().all(axis=1) & t_pub.notna().all(axis=1)
        n_diff = int((t_me[both] != t_pub[both]).any(axis=1).sum())
        n_cmp = int(both.sum())
    # (7) is the first decision of the sample scored on fewer than all features?
    feats_first = {
        k: feature_panel(end_view, k, ranked, **strat_me.feature_params.get(k, {})).loc[
            pd.Timestamp(first_dec)
        ]
        for k in strat_me.weights
    }
    n_feat_first = sum(int(v.notna().all()) for v in feats_first.values())
    m_wo = {
        label: metrics.summary(series[label][0].iloc[1:], cash.iloc[1:])["sharpe_ex_cash"]
        for label in (RULE, ew_label)
    }

    dec = decade_table(
        {
            "Regel": (r_main, cash),
            "EW": (series[ew_label][0], cash),
            "60/40": (series[f"60/40 US_EQ/{bond}"][0], cash),
        },
        display_decades(fc),
    )

    # ---- the deflated Sharpe (ADR 056): the beta-adjusted residual against equal weight – what the rule adds beyond
    # the baseline without counting a different level of risk – deflated with N and the variance of the same
    # statistic over the trial register (docs/TRIALS.yaml)
    n_trials, _ = register()
    resid = appraisal_residual(r_main, series[ew_label][0], cash)
    sr_a, sr0_a, psr_a = deflated_sharpe(resid, n_trials, trials_variance())

    # ---- verdict (ADR 048 e) --------------------------------------------------------------------------
    sh_rule = table.loc[RULE, "Sharpe ex Cash"]
    sh_ew = table.loc[ew_label, "Sharpe ex Cash"]
    d_ew = next(d for d in diffs if d["Baseline"] == ew_label)
    c1 = bool(sh_rule > sh_ew)
    ci_lo, ci_hi, d_sh_ew = float(d_ew["low "]), float(d_ew["high "]), float(d_ew["Δ Sharpe"])
    excludes_zero = ci_lo > 0 or ci_hi < 0
    c2 = excludes_zero and d_sh_ew > 0
    verdict = c1 and c2

    lines = [
        f"# Prognose-Portfolio (P8): die vorab fixierte Regel gegen Baselines, {years(index[0], index[-1])}"
        + ("" if v1 else f" (Forschungsrunde 2, `{sid}`)"),
        "",
        f"Stand {date.today().isoformat()}. Regel und Baselines durch dieselbe Engine (`rotationlab.engine`), Ausführung "
        f"`{gr.execution}`, Kosten {gr.costs.default_bps} bp je Seite inkl. Cash-Bein, Daten ab {gr.data_from}; wirksame "
        f"Entscheidungen {decided[0]:%Y-%m} bis {decided[-1]:%Y-%m} (der Entscheid vom {gr.end} wird am nächsten "
        f"Handelstag gehandelt und nie bewertet); Kennzahlen über die {len(index)} Renditemonate {index[0]:%Y-%m} bis "
        f"{index[-1]:%Y-%m} (für alle Läufe identisch). Pseudo-Holdout ab {fc.holdout.start} unberührt.",
        f"Timing: `next_tradable` handelt tägliche Reihen ({', '.join(daily)}) am Handelstag nach der Entscheidung; "
        f"{', '.join(monthly)} sind im Langfrist-Panel Monatsreihen, ihr nächster Preis ist der Monatsendwert selbst – diese "
        "Beine werden also zum Entscheidungspreis gehandelt, für Regel und Baselines gleich (kein Blick in die Zukunft, "
        "aber auch kein Folgetagspreis).",
        f"Intervalle: {int(CONF * 100)}-%-Moving-Block-Bootstrap (Block {fc.calibration.block_months}, {fc.calibration.draws} "
        f"Ziehungen, Seed {fc.calibration.seed}), gepaart über dieselben Blockziehungen. Regel, Konventionen und Kriterium "
        f"vorab in ADR 048{'' if v1 else ', Runde 2 in ADR 052'}. Alle Zahlen aus `scripts/forecast_portfolio.py --config {config}`.",
        "",
        (
            "**Einordnung:** Die Rangfolge hinter der Regel ist in-sample bezüglich der Modellwahl (ADR 046 e); die Regel selbst "
            "(Top-2, Trendfilter, Vol-Ziel, kein Hebel) wurde vor diesem Lauf festgelegt und nicht auf den Daten gewählt. "
            f"Bewertet wird die Rangfolge auf dem handelbaren Treasury-Index `UST10_ME` (ADR 048 c); die veröffentlichte "
            f"Prognose rankt die Forschungsreihe `UST10` – die Top-2 unterscheiden sich in {n_diff} von {n_cmp} "
            "Entscheidungsmonaten; die Sensitivität „Forschungsreihe UST10“ unten ist die Regel auf der veröffentlichten "
            f"Rangfolge. Der erste Entscheid der Stichprobe ({decided[0]:%Y-%m}) ist mit {n_feat_first} von "
            f"{len(strat_me.weights)} Features bewertet (12-1-Momentum braucht 14 Monatsstände); ohne den Januar 1974: "
            f"Sharpe Regel {m_wo[RULE]:.3f}, Equal Weight {m_wo[ew_label]:.3f}."
            if v1
            else "**Einordnung:** Rangfolge (drei Familien, gleiche Gewichte) und Regel (Top-2 von 5, Trendfilter, Vol-Ziel, kein Hebel) "
            "sind in ADR 052 vor diesem Lauf fixiert und nicht auf den Daten gewählt; die Rangfolge der Regel ist dieselbe, die "
            f"die Prognose `{config}` veröffentlicht (gleiche Reihen, gleiche Formel). Der erste Entscheid der Stichprobe "
            f"({decided[0]:%Y-%m}) ist mit {n_feat_first} von {len(strat_me.weights)} Features bewertet; ohne ihn: "
            f"Sharpe Regel {m_wo[RULE]:.3f}, Equal Weight {m_wo[ew_label]:.3f}."
        ),
        "",
        "## Kennzahlen",
        "",
        md_table(table),
        "",
        "## Gepaarte Differenzen Regel − Baseline",
        "",
        md_table(dtab),
        "",
        "Δ Rendite p.a. = Mittel der Monatsdifferenz × 12; Δ Sharpe = Sharpe ex Cash der Regel minus Baseline, Intervall aus "
        "denselben Blockziehungen für beide Reihen (Perzentil-Intervall, nicht bias-korrigiert; der Bootstrap-Mittelwert "
        "liegt bei der Sharpe-Differenz leicht über dem Punktwert, die Basic-Variante läge entsprechend tiefer – das "
        "Urteil hängt davon nicht ab).",
        "",
        "## Was die Regel tut",
        "",
        *[f"- {k}: {v:.3f}" for k, v in expo.items()],
        "",
        "## Je Jahrzehnt",
        "",
        md_table(dec, "{:.3f}"),
        "",
        "## Sensitivitäten (vorab benannt, nicht urteilsrelevant)",
        "",
        md_table(table.loc[list(sens)]),
        "",
        "## Urteil nach ADR 048 (e) – Kriterium vorab festgelegt",
        "",
        f"1. Sharpe ex Cash der Regel ({sh_rule:+.3f}) über Equal Weight ({sh_ew:+.3f}): **{'ja' if c1 else 'nein'}**",
        f"2. Gepaarte Sharpe-Differenz zu Equal Weight positiv und Intervall ohne Null: **{'ja' if c2 else 'nein'}** "
        f"({d_sh_ew:+.3f} [{ci_lo:+.3f}, {ci_hi:+.3f}]; Intervall {'ohne' if excludes_zero else 'mit'} Null)",
        f"→ Portfolio-Vorteil gegen Equal Weight belegt: **{'JA' if verdict else 'NEIN'}**",
        "",
        "60/40 und Buy-and-Hold stehen zur Einordnung (anderes Universum, anderes Risiko) und entscheiden nicht.",
        "",
        f"Deflated Sharpe (Bailey/López de Prado 2014; ADR 056) der Residualrendite gegen Equal Weight (Überschuss abzüglich "
        f"Beta × EW-Überschuss: was die Regel über die Baseline hinaus bringt, ohne ein anderes Risikoniveau als Können zu "
        f"zählen): {sr_a * 12**0.5:+.3f} p.a.; Hürde aus N = {n_trials} Versuchen und der Varianz derselben Statistik über das "
        f"Register `docs/TRIALS.yaml` {sr0_a * 12**0.5:+.3f}; Wahrscheinlichkeit, dass die wahre Grösse darüber liegt: "
        f"**{psr_a:.3f}** (≥ 0.95 wäre ein Beleg, der die Mehrfachprüfung überlebt). Beschreibend, nicht Teil des vorab "
        "fixierten Kriteriums.",
        "",
        f"Laufzeit {time.perf_counter() - t0:.0f} s.",
    ]
    with open(os.path.join(out, "PORTFOLIO.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(parse_args(__doc__).config)
