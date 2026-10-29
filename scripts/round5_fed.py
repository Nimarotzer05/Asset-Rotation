"""Research round 5 (ADR 063 b): does the Fed category improve the monthly ranking?

Compares, decision by decision, the round-1 composite on the month-end classes (base) with the same composite
blended 50/50 with the Fed component (`configs/forecast_fed.yaml`). Every score is computed pointwise: one view
per decision date, so the ridge, its standardisation and every macro value are what was known at that date.

Pre-registered (ADR 063 b), nothing chosen after the run:
  criterion 1  1978-01 … 2018-11 (outcomes to 2018-12): mean paired difference of the monthly rank IC
               (Fed − base), 90 % moving-block bootstrap (block 12, 2000 draws, seed 20261025): interval > 0
  criterion 2  2019-01 … 2025-11 (already seen in rounds 1 and 2, not a clean holdout): mean difference > 0
  reading      both met = the Fed category adds to the ranking; 1 only = in-sample only; else not established
  reported     IC of each model with interval, by decade, the Fed component alone (ablation), slopes of the last
               fit, the minimum detectable difference

Writes output/forecast_fed/ROUND5.md, ic_monthly.csv, scores_fed.csv (pointwise ranking for the long-short
study), coefficients.csv.

Aufruf: python scripts/round5_fed.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, md_table  # noqa: E402
from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import averaged_assets, research_factory  # noqa: E402
from rotationlab.forecast.evaluation import by_decade, mean_ci, spearman_rows  # noqa: E402
from rotationlab.forecast.macro import ridge_coefficients, state_panel  # noqa: E402
from rotationlab.forecast.model import (  # noqa: E402
    BlockBootstrap,
    ForecastModel,
    complete_months,
    forward_returns,
    ranks_of,
    relative,
    zscore_rows,
)

CONFIG = "forecast_fed"
IN_END = date(2018, 11, 30)  # last decision whose 1-month outcome (December 2018) lies before the holdout
SEEN = (date(2019, 1, 31), date(2025, 11, 30))  # decisions of the already-seen period, outcomes to 2025-12
LABELS = {
    "d_fedfunds_3m": "Zinsentscheide (Δ Fed Funds 3 M)",
    "real_policy_rate": "Realer Leitzins (Fed Funds − Inflation)",
    "d_cpi_yoy_3m": "Inflation (Δ CPI-Jahresrate 3 M)",
    "sahm": "Arbeitsmarkt (Sahm-Indikator)",
    "d_curve_3m": "Zinskurve (Δ GS10 − T-Bill 3 M)",
}


def months(a: date, z: date) -> list[date]:
    return [d.date() for d in pd.date_range(a, z, freq="ME")]


def main() -> None:
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    fc = b.forecasts[CONFIG]
    assert fc.model.macro is not None
    base_fc = fc.model_copy(
        update={"model": fc.model.model_copy(update={"id": "composite_me", "macro": None})}
    )
    out = os.path.join(ROOT, "output", CONFIG)
    os.makedirs(out, exist_ok=True)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, make_calendar(b), fc.evaluation.data_from)
    avg = averaged_assets(b)
    fed, base = ForecastModel(fc, averaged=avg), ForecastModel(base_fc, averaged=avg)
    ranked = fed.ranked
    boot = BlockBootstrap(fc.calibration.draws, fc.calibration.block_months, fc.calibration.seed)

    # ---- pointwise scores: one view per decision ---------------------------------------------------------
    decisions = months(fc.evaluation.start, SEEN[1])
    rows_fed, rows_base, rows_macro = {}, {}, {}
    for d in decisions:
        v = f.at(d)
        hist_base = base.score_history(v)
        m = fed.macro_predictions(v, hist_base.index)
        ts = pd.Timestamp(d)
        rows_base[ts] = hist_base.iloc[-1]
        rows_fed[ts] = fed.score_history(v).iloc[-1]
        rows_macro[ts] = zscore_rows(m.iloc[[-1]], fed.clip).iloc[0]
        assert hist_base.index[-1] == ts and m.index[-1] == ts
    s_fed, s_base, s_macro = (
        pd.DataFrame(r).T.reindex(columns=ranked) for r in (rows_fed, rows_base, rows_macro)
    )
    end = f.at(date(2025, 12, 31))
    levels = complete_months(end, end.total_return(ranked, "ME").reindex(columns=ranked))
    rel = relative(forward_returns(levels, 1)).reindex(s_fed.index)
    ic = pd.DataFrame(
        {
            "base": spearman_rows(s_base, rel),
            "fed": spearman_rows(s_fed, rel),
            "nur_fed": spearman_rows(s_macro, rel),
        }
    )
    ic["diff"] = ic["fed"] - ic["base"]
    missing = s_fed.index[s_fed.isna().any(axis=1)]
    if len(missing):
        raise SystemExit(f"round 5: {len(missing)} decisions without a Fed score, first {missing[0].date()}")

    # ---- statistics --------------------------------------------------------------------------------------
    periods = {
        f"In-sample {fc.evaluation.start:%Y-%m} … {IN_END:%Y-%m}": (fc.evaluation.start, IN_END),
        f"Gesehen {SEEN[0]:%Y-%m} … {SEEN[1]:%Y-%m}": SEEN,
        f"Gesamt {fc.evaluation.start:%Y-%m} … {SEEN[1]:%Y-%m}": (fc.evaluation.start, SEEN[1]),
    }
    table, cis = [], {}
    for name, (a, z) in periods.items():
        sl = ic.loc[pd.Timestamp(a) : pd.Timestamp(z)]
        row = {"Monate": len(sl)}
        for col, lab in [
            ("base", "IC Basis"),
            ("fed", "IC Basis + Fed"),
            ("nur_fed", "IC nur Fed"),
            ("diff", "Δ IC (Fed − Basis)"),
        ]:
            c = mean_ci(sl[col], boot, CONF)
            cis[(name, col)] = c
            row[lab] = f"{c.mean:+.4f} [{c.low:+.4f}, {c.high:+.4f}]"
        table.append(pd.Series(row, name=name))
    stats = pd.DataFrame(table)
    stats.index.name = "Zeitraum"
    k_in, k_seen = list(periods)[0], list(periods)[1]
    d_in, d_seen = cis[(k_in, "diff")], cis[(k_seen, "diff")]
    c1, c2 = d_in.low > 0, d_seen.mean > 0
    se = (d_in.high - d_in.low) / (2 * 1.645)
    reading = (
        "**erfüllt: die Fed-Kategorie verbessert die Rangfolge**"
        if c1 and c2
        else "**nur in-sample** (Kriterium 1 erfüllt, 2 nicht)"
        if c1
        else "**nicht belegt** (Kriterium 1 nicht erfüllt)"
    )
    decades = by_decade(ic["diff"].loc[: pd.Timestamp(IN_END)], fc.evaluation.decades)

    # ---- slopes of the last fit before the holdout and at the end ----------------------------------------
    coef = []
    for d in (IN_END, SEEN[1]):
        v = f.at(d)
        idx = base.score_history(v).index
        x = state_panel(v, fc.model.macro.features, fc.model.macro.fill_gaps_months).reindex(idx)
        y = fed.outcomes(v, 1).reindex(index=idx, columns=ranked)
        beta = ridge_coefficients(x.iloc[:-1], y.iloc[:-1], fc.model.macro.ridge_lambda)
        beta.index = [f"{d:%Y-%m}: {LABELS.get(i, i)}" for i in beta.index]
        coef.append(beta * 100)
    coefs = pd.concat(coef)
    coefs.index.name = "Fit / Variable (Steigung in %-Punkten relativer Monatsrendite je SD)"

    # ---- files -------------------------------------------------------------------------------------------
    ic.to_csv(os.path.join(out, "ic_monthly.csv"), float_format="%.6f")
    s_fed.to_csv(os.path.join(out, "scores_fed.csv"), float_format="%.8f")
    s_base.to_csv(os.path.join(out, "scores_base.csv"), float_format="%.8f")
    coefs.to_csv(os.path.join(out, "coefficients.csv"), float_format="%.5f")
    rk = ranks_of(s_fed)
    agree = float((rk.idxmin(axis=1) == ranks_of(s_base).idxmin(axis=1)).mean())
    lines = [
        "# Forschungsrunde 5: Fed-Kategorie in der Monatsprognose",
        "",
        f"Stand {date.today().isoformat()}. Vorregistrierung ADR 063 (b); Konfiguration `configs/{CONFIG}.yaml`; "
        f"Skript `scripts/round5_fed.py`. Gerankt: {ranked}; Ergebnisse = relative Monatsrenditen auf Monatsendpreisen.",
        f"Jeder Score punktweise aus der Sicht am Entscheidungstag ({len(decisions)} Sichten); "
        f"{int(CONF * 100)}-%-Moving-Block-Bootstrap (Block {fc.calibration.block_months}, {fc.calibration.draws} Ziehungen, "
        f"Seed {fc.calibration.seed}). Laufzeit {time.perf_counter() - t0:.0f} s.",
        "",
        "**Basis** = Komposit von Runde 1 auf denselben Klassen (Monatsend-Treasury `UST10_ME` statt `UST10`, ADR 063 b). "
        "**Basis + Fed** = 0.5 · Komposit + 0.5 · z(Ridge-Vorhersage aus Zinsentscheiden, realem Leitzins, Inflation, "
        "Arbeitsmarkt, Zinskurve). **Nur Fed** = die Fed-Komponente allein (Ablation, berichtet, entscheidet nicht).",
        "",
        "## Rang-IC (1 Monat)",
        "",
        md_table(stats),
        "",
        "## Vorab-Kriterien (ADR 063 b)",
        "",
        f"1. In-sample: Δ IC {d_in.mean:+.4f} [{d_in.low:+.4f}, {d_in.high:+.4f}] → Intervall über null: **{'ja' if c1 else 'nein'}** "
        f"(Standardfehler ≈ {se:.4f}, kleinste nachweisbare Differenz bei 80 % Power ≈ {2.487 * se:.4f}).",
        f"2. Gesehener Zeitraum 2019–2025: Δ IC {d_seen.mean:+.4f} [{d_seen.low:+.4f}, {d_seen.high:+.4f}] → über null: **{'ja' if c2 else 'nein'}**.",
        "",
        f"Lesart: {reading}.",
        "",
        f"Rang 1 stimmt in {agree:.0%} der Monate zwischen Basis und Basis + Fed überein.",
        "",
        "## Δ IC je Jahrzehnt (in-sample)",
        "",
        md_table(decades),
        "",
        "## Steigungen der Fed-Komponente (letzter Fit vor dem Holdout und am Ende)",
        "",
        "Standardisierte Ridge-Steigungen (λ = 1) in Prozentpunkten relativer Monatsrendite je Standardabweichung der "
        "Variable; positiv = die Klasse schneidet relativ besser ab, wenn die Variable hoch ist. Beschreibend, kein Test.",
        "",
        md_table(coefs, "{:+.3f}"),
        "",
    ]
    with open(os.path.join(out, "ROUND5.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
