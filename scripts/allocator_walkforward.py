"""Research round 3 (ADR 054): the sleeve allocator, walk-forward 1979–2026, against baselines and variants.

Everything the allocator does on a decision date uses data up to that date and no parameter chosen on the
data (ADR 054 b/c), so the whole history is out-of-sample with respect to the data and in-sample only with
respect to the design (literature). Baselines and variants run through the same engine, costs and timing.
Verdict (ADR 054 e): Sharpe ex cash above the signal-free risk-parity baseline AND the 90 % block-bootstrap
interval of the paired Sharpe difference excludes zero. Writes output/allocator/WALKFORWARD.md and CSVs.
Since the second review (ADR 056) the report also carries the reviewer's diagnostics, marked as computed after
the fact: sub-periods, the 1979–80 dependence, band, costs and financing for both sides, vol calibration,
test power and the deflated Sharpe on the beta-adjusted residual with the register's variance.

Aufruf: python scripts/allocator_walkforward.py
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, md_table, register, trials_variance  # noqa: E402
from rotationlab.config.models import GoldenRun, load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine import metrics  # noqa: E402
from rotationlab.engine.modes import GoldenReport, golden  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    appraisal_residual,
    deflated_sharpe,
    mean_ci,
    paired_diff,
    paired_sharpe_diff,
    spearman_rows,
)
from rotationlab.forecast.model import BlockBootstrap  # noqa: E402
from rotationlab.strategies.base import deep_merge  # noqa: E402

SID = "sleeve_allocator"
OUT = os.path.join(ROOT, "output", "allocator")
RULE = "Allokator (ADR 054)"
B1 = "B1 Risikoparität ohne Signale"
PERIODS = [
    ("1979–1989", 1979, 1989),
    ("1990s", 1990, 1999),
    ("2000s", 2000, 2009),
    ("2010s", 2010, 2019),
    ("2020–2026", 2020, 2026),
]
N_VARIANTS = 8  # ADR 054 (f): the variants below – registered before the run
BOOT = BlockBootstrap(2000, 12, 20261025)
Z80 = 1.645 + 0.842  # one-sided 5 % test with 80 % power: MDE = Z80 × standard error
MG_SAMPLE_END = 1995  # Moskowitz/Grinblatt (1999) used 1963–1995: later years are after the publication


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
        "Trefferquote": m["hit_rate"],
        "Umsatz p.a.": m["turnover_ann"],
        "Kosten p.a.": float(cost.fillna(0.0).mean() * 12),
    }


def period_table(rows: Mapping[str, tuple[pd.Series, pd.Series]]) -> pd.DataFrame:
    out = []
    for name, a, b in PERIODS:
        rec: dict[str, object] = {"Periode": name}
        n = 0
        for label, (r, c) in rows.items():
            years = pd.DatetimeIndex(r.index).year
            sel = (years >= a) & (years <= b)
            n = int(sel.sum())
            if n == 0:
                continue
            m = metrics.summary(r[sel], c[sel])
            rec[f"{label}: Rendite p.a."] = m["ann_return"]
            rec[f"{label}: Sharpe"] = m["sharpe_ex_cash"]
        rec["Monate"] = n
        out.append(rec)
    return pd.DataFrame(out).set_index("Periode")


def sleeve_ic(  # type: ignore[no-untyped-def]
    res,
    sleeves: Mapping[str, list[str]],
    returns: pd.DataFrame,
    decided: pd.DatetimeIndex,
    years: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Rank IC per sleeve: Spearman between the sleeve's scores at D and the instruments' returns in the month
    after D, mean over months with the block-bootstrap interval – only decisions inside the registered window
    (ADR 056: the first version also counted six warm-up decisions), optionally restricted to calendar years."""
    rows = []
    for name, instruments in sleeves.items():
        sc = pd.DataFrame(
            {
                pd.Timestamp(p.date): {a: p.signals.get(f"score:{a}", np.nan) for a in instruments}
                for p in res.proposals
                if not p.warmup
            }
        ).T.sort_index()
        sc = sc[sc.index.isin(decided)]
        if years is not None:
            sc = sc[(sc.index.year >= years[0]) & (sc.index.year <= years[1])]
        nxt = (
            returns.reindex(columns=instruments).shift(-1).reindex(sc.index)
        )  # the return of the month after D
        if len(instruments) > 2:
            stat = spearman_rows(sc, nxt).dropna()
            kind = "Rang-IC (Spearman)"
        else:  # two instruments: a rank correlation is ±1 – report whether the higher score did better
            both = sc.notna().all(axis=1) & nxt.notna().all(axis=1) & (sc.iloc[:, 0] != sc.iloc[:, 1])
            top = sc[both].idxmax(axis=1)
            bottom = sc[both].idxmin(axis=1)
            r_top = pd.Series([nxt.loc[d, a] for d, a in top.items()], index=top.index)
            r_bot = pd.Series([nxt.loc[d, a] for d, a in bottom.items()], index=bottom.index)
            stat = (r_top > r_bot).astype(float)
            kind = "Trefferquote (höherer Score schlägt den anderen; Zufall 0.5)"
        c = mean_ci(stat, BOOT, CONF)
        rows.append(
            {
                "Sleeve": name,
                "Instrumente": len(instruments),
                "Kennzahl": kind,
                "Wert": c.mean,
                "low": c.low,
                "high": c.high,
                "Monate": int(c.n),
            }
        )
    return pd.DataFrame(rows).set_index("Sleeve")


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
    sleeves = {k: list(v["instruments"]) for k, v in scfg.long_history_params["sleeves"].items()}
    instruments = [a for s in sleeves.values() for a in s]
    costs = dict(gr.costs.per_asset)

    # ---- baselines: the signal-free allocator, equal weight, 60/40, buy-and-hold (same engine) --------------
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

    def fixed(
        label: str, universe: list[str], weights: dict[str, float], rebalance: str = "monthly"
    ) -> GoldenReport:
        cfg = fw.model_copy(update={"universe": universe, "long_history_universe": universe})
        bb = b.model_copy(update={"strategies": {**b.strategies, "fixed_weights": cfg}})
        extra = {a: 5.0 for a in universe if a not in costs and a != "TBILL"}  # US_EQ at the equity rate
        run = fw_gr.model_copy(
            update={"costs": gr.costs.model_copy(update={"per_asset": {**costs, **extra}})}
        )
        return golden(
            bb, obs, "fixed_weights", cal, run=with_params(run, weights=weights, rebalance=rebalance)
        )

    runs: dict[str, GoldenReport] = {RULE: golden(b, obs, SID, cal)}
    runs[B1] = golden(b, obs, SID, cal, run=with_params(gr, xs_select=False, ts_filter=False))
    runs["B2 Equal Weight (14 Instrumente)"] = fixed(
        "ew", [*instruments, "TBILL"], dict.fromkeys(instruments, 1 / len(instruments))
    )
    runs["B3 60/40 US_EQ/UST10_ME"] = fixed(
        "6040", ["US_EQ", "UST10_ME", "TBILL"], {"US_EQ": 0.6, "UST10_ME": 0.4}
    )
    runs["B4 Buy-and-Hold US_EQ"] = fixed("bh", ["US_EQ", "TBILL"], {"US_EQ": 1.0}, "never")
    baselines = [k for k in runs if k != RULE]

    # ---- variants (ADR 054 f): reported, never the verdict ------------------------------------------------
    one = {k: 0.0 for k in sleeves}
    base_sleeves = deep_merge(scfg.params["sleeves"], scfg.long_history_params["sleeves"])
    variants: dict[str, GoldenReport] = {
        "ohne Zeitreihenfilter": golden(b, obs, SID, cal, run=with_params(gr, ts_filter=False)),
        "nur Zeitreihe + Risikoparität": golden(b, obs, SID, cal, run=with_params(gr, xs_select=False)),
        "Hebelgrenze 1.0": golden(b, obs, SID, cal, run=with_params(gr, max_exposure=1.0)),
        "Halbwertszeit 6": golden(b, obs, SID, cal, run=with_params(gr, half_life=6)),
        "Kosten ×2": golden(
            b,
            obs,
            SID,
            cal,
            run=gr.model_copy(
                update={
                    "costs": gr.costs.model_copy(update={"per_asset": {k: 2 * v for k, v in costs.items()}})
                }
            ),
        ),
    }
    for name in sleeves:
        budgets = {k: (1.0 if k == name else 0.0) for k in one}
        sl = {k: {**base_sleeves[k], "budget": budgets[k]} for k in sleeves}
        variants[f"nur Sleeve {name}"] = golden(b, obs, SID, cal, run=with_params(gr, sleeves=sl))
    assert len(variants) == N_VARIANTS

    # ---- the common sample --------------------------------------------------------------------------------
    rule = runs[RULE].result
    r_rule, _ = rule.sample(gr.sample[0], gr.sample[1], count_warmup=False)
    index = pd.DatetimeIndex(r_rule.index)
    series = {label: aligned(rep, index) for label, rep in {**runs, **variants}.items()}
    cash = series[RULE][1]
    table = pd.DataFrame([row(label, *s) for label, s in series.items()]).set_index("Lauf")
    table.to_csv(os.path.join(OUT, "walkforward_metrics.csv"))
    pd.DataFrame({label: s[0] for label, s in series.items()} | {"cash": cash}).to_csv(
        os.path.join(OUT, "walkforward_monthly.csv")
    )
    rule.weights.to_csv(os.path.join(OUT, "walkforward_weights.csv"))

    r_main = series[RULE][0]
    diffs = []
    for label in baselines:
        d_ret = paired_diff(r_main, series[label][0], BOOT, CONF)
        d_sh = paired_sharpe_diff(r_main, series[label][0], cash, BOOT, CONF)
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
    dtab.to_csv(os.path.join(OUT, "walkforward_paired.csv"))

    # ---- what the book did ----------------------------------------------------------------------------------
    decided = pd.DatetimeIndex([d - pd.offsets.MonthEnd(1) for d in index])
    sig = {pd.Timestamp(p.date): p.signals for p in rule.proposals if not p.warmup}
    gross = pd.Series({d: sig[d].get("gross", np.nan) for d in decided if d in sig})
    scale = pd.Series({d: sig[d].get("scale", np.nan) for d in decided if d in sig})
    sw = pd.DataFrame(
        {d: {k: sig[d].get(f"sleeve_weight:{k}", 0.0) for k in sleeves} for d in decided if d in sig}
    ).T
    expo = {
        f"Entscheidungen {decided[0]:%Y-%m} bis {decided[-1]:%Y-%m}: mittlere Bruttoquote": float(
            gross.mean()
        ),
        "Anteil Entscheidungen mit Hebel (brutto > 1)": float((gross > 1 + 1e-9).mean()),
        "Anteil Entscheidungen ganz in Cash": float((gross < 1e-9).mean()),
        "mittlere Skalierung (Vol-Ziel / Portfolio-Vol, gekappt)": float(scale.mean()),
        **{f"mittleres Gewicht Sleeve {k}": float(sw[k].mean()) for k in sleeves},
        **{f"Anteil Monate Sleeve {k} in Cash": float((sw[k] < 1e-9).mean()) for k in sleeves},
    }
    sw.to_csv(os.path.join(OUT, "walkforward_sleeve_weights.csv"))

    # ---- rank IC per sleeve ---------------------------------------------------------------------------------
    from rotationlab.engine.modes import research_factory  # noqa: PLC0415

    end_view = research_factory(b, obs, cal, gr.data_from).at(gr.end)
    levels = end_view.total_return(instruments, "ME")
    rets = levels.pct_change()
    ic_tab = sleeve_ic(rule, sleeves, rets, decided)
    ic_tab.to_csv(os.path.join(OUT, "walkforward_sleeve_ic.csv"))
    eq = {"EQ": sleeves["EQ"]}
    ic_before = sleeve_ic(rule, eq, rets, decided, (1900, MG_SAMPLE_END)).loc["EQ"]
    ic_after = sleeve_ic(rule, eq, rets, decided, (MG_SAMPLE_END + 1, 2100)).loc["EQ"]
    ic_periods = pd.DataFrame(
        {name: sleeve_ic(rule, eq, rets, decided, (a, z)).loc["EQ"] for name, a, z in PERIODS}
    ).T[["Wert", "low", "high", "Monate"]]
    ic_periods.index.name = "Periode"

    per = period_table(
        {
            "Allokator": (r_main, cash),
            "B1": (series[B1][0], cash),
            "B2": (series["B2 Equal Weight (14 Instrumente)"][0], cash),
        }
    )

    # ---- diagnostics of the second review (ADR 056) – computed after the fact, never the verdict -------------
    r_b1 = series[B1][0]

    def dsh(a: pd.Series, b_: pd.Series, mask: pd.Series | None = None) -> str:
        m = mask if mask is not None else pd.Series(True, index=a.index)
        d = paired_sharpe_diff(a[m], b_[m], cash[m], BOOT, CONF)
        return f"{d.value:+.3f} [{d.low:+.3f}, {d.high:+.3f}]"

    yrs = pd.Series(index.year, index=index)
    contrib = ((r_main - cash) - (r_b1 - cash)).groupby(yrs).sum()
    best = int(contrib.idxmax())
    diag_runs = {
        "Allokator ohne Band": golden(b, obs, SID, cal, run=with_params(gr, band=0.0)),
        "B1 ohne Band": golden(
            b, obs, SID, cal, run=with_params(gr, xs_select=False, ts_filter=False, band=0.0)
        ),
        "B1 Kosten ×2": golden(
            b,
            obs,
            SID,
            cal,
            run=with_params(gr, xs_select=False, ts_filter=False).model_copy(
                update={
                    "costs": gr.costs.model_copy(update={"per_asset": {k: 2 * v for k, v in costs.items()}})
                }
            ),
        ),
        "Allokator Finanzierung +50 bp": golden(
            b,
            obs,
            SID,
            cal,
            run=gr.model_copy(update={"costs": gr.costs.model_copy(update={"borrow_bps": {"CASH": 50.0}})}),
        ),
        "B1 Finanzierung +50 bp": golden(
            b,
            obs,
            SID,
            cal,
            run=with_params(gr, xs_select=False, ts_filter=False).model_copy(
                update={"costs": gr.costs.model_copy(update={"borrow_bps": {"CASH": 50.0}})}
            ),
        ),
    }
    dser = {k: aligned(v, index)[0] for k, v in diag_runs.items()}
    pd.DataFrame(dser).to_csv(os.path.join(OUT, "walkforward_diagnostics_monthly.csv"))
    sh = {k: float(metrics.summary(v, cash)["sharpe_ex_cash"]) for k, v in dser.items()}

    def vol_check(res) -> tuple[float, float, float]:  # type: ignore[no-untyped-def]
        """Predicted book vol (after scale) at D vs the realised excess return of the next month."""
        sg = {pd.Timestamp(p.date): p.signals for p in res.proposals if not p.warmup}
        pred = pd.Series(
            {d: sg[d].get("portfolio_vol", np.nan) * sg[d].get("scale", np.nan) for d in decided if d in sg}
        )
        nxt = (res.returns.reindex(index) - cash).set_axis(decided)
        z = nxt / (pred / np.sqrt(12))
        target = pd.Series({d: 0.10 / sg[d].get("portfolio_vol", np.nan) for d in decided if d in sg})
        sc = pd.Series({d: sg[d].get("scale", np.nan) for d in decided if d in sg})
        return float(z.std()), float(pred.mean()), float((sc < target - 1e-9).mean())

    vc_main, vc_b1 = vol_check(rule), vol_check(runs[B1].result)
    d1_full = paired_sharpe_diff(r_main, r_b1, cash, BOOT, CONF)
    se = (d1_full.high - d1_full.low) / (2 * 1.645)
    sig_a, sig_b = float((r_main - cash).std() * np.sqrt(12)), float((r_b1 - cash).std() * np.sqrt(12))
    matched = float((r_main - cash).mean() * 12 - (r_b1 - cash).mean() * 12 * sig_a / sig_b)
    trend_vs_nofilter = dsh(r_main, series["ohne Zeitreihenfilter"][0])
    trend_only_vs_b1 = dsh(series["nur Zeitreihe + Risikoparität"][0], r_b1)
    xs_vs_trend_only = dsh(r_main, series["nur Zeitreihe + Risikoparität"][0])
    sel_only_vs_b1 = dsh(series["ohne Zeitreihenfilter"][0], r_b1)

    # ---- deflated Sharpe on the beta-adjusted residual against B1 (register variance, ADR 056) ----------------
    n_trials, _ = register()
    resid = appraisal_residual(r_main, r_b1, cash)
    sr_a, sr0_a, psr_a = deflated_sharpe(resid, n_trials, trials_variance())

    # ---- verdict (ADR 054 e) ----------------------------------------------------------------------------------
    sh_rule, sh_b1 = table.loc[RULE, "Sharpe ex Cash"], table.loc[B1, "Sharpe ex Cash"]
    d1 = dtab.loc[B1]
    c1 = bool(sh_rule > sh_b1)
    lo, hi, dv = float(d1["low "]), float(d1["high "]), float(d1["Δ Sharpe"])
    c2 = (lo > 0 or hi < 0) and dv > 0
    verdict = c1 and c2
    monthly_legs = [a for a in [*instruments, "TBILL"] if a not in ("GOLD_D", "SILVER")]
    lines = [
        f"# Sleeve-Allokator (Forschungsrunde 3, ADR 054): Walk-forward {index[0]:%Y-%m} bis {index[-1]:%Y-%m}",
        "",
        f"Stand {date.today().isoformat()}. Allokator, Baselines und Varianten durch dieselbe Engine (`rotationlab.engine`), "
        f"Ausführung `{gr.execution}`, Kosten je Instrument (ADR 054 d, Annahmen: Industrien 5 bp, Treasuries 2 bp, Gold 5 bp, "
        f"Silber 10 bp je Seite), Panel ab {gr.data_from}; wirksame Entscheidungen {decided[0]:%Y-%m} bis {decided[-1]:%Y-%m}; "
        f"Kennzahlen über die {len(index)} Renditemonate {index[0]:%Y-%m} bis {index[-1]:%Y-%m} (für alle Läufe identisch). "
        f"Intervalle: {int(CONF * 100)}-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025), gepaart. "
        "Design, Kriterien und Varianten vorab in ADR 054. Alle Zahlen aus `scripts/allocator_walkforward.py`.",
        "",
        "**Korrigierte Fassung (Zweitprüfung, ADR 056).** Die erste Fassung entschied in zwei-Instrument-Sleeves Gleichstände "
        "(Momentum und Carry widersprechen sich, beide Scores exakt 0) nach Rundungsrauschen von ±1e-15 statt nach der "
        "Konfigurationsreihenfolge, die ADR 054 (b) vorschreibt; behoben (Scores auf 1e-12 gerundet), alle Läufe neu gerechnet. "
        "ADR 054 setzte den Hebel auf das ganze Buch (brutto ≤ 1.5, kein Sleeve über 1.0) – der Auftraggeber hatte Hebel für das "
        "Anleihe-Sleeve freigegeben; diese Abweichung des Designs wird hier nicht nachträglich korrigiert (das wäre ein neuer "
        "Versuch), sondern in Runde 4 umgesetzt. Abschnitte mit „Diagnose“ sind nach dem Lauf gerechnet und entscheiden nichts.",
        "",
        f"Timing: `next_tradable` handelt nur GOLD_D und SILVER am Folgetag; {len(monthly_legs)} Beine ({', '.join(monthly_legs)}) "
        "sind Monatsreihen und werden zum Kurs des Entscheidungstags gehandelt – derselbe Stand, der den Trendfilter speist "
        "(akademische Konvention, nicht umsetzbar; Runde 4 rechnet mit Tagesreihen).",
        "",
        "**Einordnung:** Null freie Parameter; jede Grösse am Entscheidungstag nur aus Daten bis dahin. Out-of-sample bezüglich "
        "der Daten, in-sample bezüglich des Designs (Literaturwahl, in Kenntnis der Runden 1 und 2 und der Periode 2019–2025). "
        "Kein Holdout-Blick mehr (Versuchsregister `docs/TRIALS.yaml`); echter Out-of-sample bleibt die Live-Bilanz. "
        "B1 ist das passive Gegenstück des Allokators (gleiche Sleeves, Budgets, inverse Vol, Vol-Ziel, Hebelgrenze, aber alle "
        "Instrumente immer gehalten): die Differenz zu B1 ist das, was die Signale leisten.",
        "",
        "## Kennzahlen",
        "",
        md_table(table.loc[[RULE, *baselines]]),
        "",
        "## Gepaarte Differenzen Allokator − Baseline",
        "",
        md_table(dtab),
        "",
        f"Δ Rendite vergleicht Läufe mit verschiedenem Risiko (Vol Allokator {sig_a:.1%}, B1 {sig_b:.1%}) und ist kein Beleg: "
        f"bei gleicher Volatilität (B1 auf {sig_a:.1%} skaliert) beträgt der Unterschied der Überschussrendite **{matched:+.2%} p.a.** "
        "Massgeblich ist die Sharpe-Differenz.",
        "",
        "## Was das Buch tut",
        "",
        *[f"- {k}: {v:.3f}" for k, v in expo.items()],
        "",
        "## Querschnitt je Sleeve (Score am Monatsende gegen die Rendite des Folgemonats innerhalb des Sleeves)",
        "",
        md_table(ic_tab),
        "",
        "Diagnose Industrie-Momentum (EQ) je Periode und vor/nach der Stichprobe der Originalstudie (Moskowitz/Grinblatt 1999, "
        f"bis {MG_SAMPLE_END}): bis {MG_SAMPLE_END} IC {ic_before['Wert']:+.4f} [{ic_before['low']:+.4f}, {ic_before['high']:+.4f}] "
        f"({int(ic_before['Monate'])} Monate), ab {MG_SAMPLE_END + 1} IC {ic_after['Wert']:+.4f} [{ic_after['low']:+.4f}, "
        f"{ic_after['high']:+.4f}] ({int(ic_after['Monate'])} Monate).",
        "",
        md_table(ic_periods, "{:.4f}"),
        "",
        "## Je Periode",
        "",
        md_table(per, "{:.3f}"),
        "",
        "## Varianten (ADR 054 f: vorab benannt, berichtet, entscheiden nicht)",
        "",
        md_table(table.loc[list(variants)]),
        "",
        "## Diagnosen der Zweitprüfung (nach dem Lauf gerechnet, entscheiden nichts)",
        "",
        f"- Ohne die Jahre 1979–80 (Silber-Episode): Δ Sharpe zu B1 {dsh(r_main, r_b1, (yrs < 1979) | (yrs > 1980))}; "
        f"ab 2000: {dsh(r_main, r_b1, yrs >= 2000)}; ohne das Jahr mit dem grössten Beitrag ({best}): "
        f"{dsh(r_main, r_b1, yrs != best)}.",
        f"- Trendfilter: Allokator gegen „ohne Zeitreihenfilter“ {trend_vs_nofilter}; „nur Zeitreihe + Risikoparität“ gegen B1 "
        f"{trend_only_vs_b1}. Querschnitt: Allokator gegen „nur Zeitreihe + Risikoparität“ {xs_vs_trend_only}; Auswahl ohne "
        f"Filter gegen B1 {sel_only_vs_b1}. Keine dieser Komponenten ist von Null zu trennen.",
        f"- Band: beide ohne Band – Allokator Sharpe {sh['Allokator ohne Band']:.3f}, B1 {sh['B1 ohne Band']:.3f} (B1 mit Band "
        f"{sh_b1:.3f}); Δ {dsh(dser['Allokator ohne Band'], dser['B1 ohne Band'])}. Das 2-Pp-Band friert die kleinen "
        "Industriegewichte von B1 über Jahre ein; die Engine handelt die Drift trotzdem zurück.",
        f"- Kosten ×2 für beide: Allokator {table.loc['Kosten ×2', 'Sharpe ex Cash']:.3f}, B1 {sh['B1 Kosten ×2']:.3f}. "
        f"Finanzierung des Hebels zum Cash-Index +50 bp: Allokator {sh['Allokator Finanzierung +50 bp']:.3f}, "
        f"B1 {sh['B1 Finanzierung +50 bp']:.3f}.",
        f"- Vol-Ziel: realisierte/vorhergesagte Vol (Standardabweichung der standardisierten Folgemonatsrendite, 1 = treffend) "
        f"Allokator {vc_main[0]:.2f}, B1 {vc_b1[0]:.2f}; mittlere vorhergesagte Vol {vc_main[1]:.1%} bzw. {vc_b1[1]:.1%}; "
        f"Anteil Entscheidungen, in denen eine Kappe das Vol-Ziel verhindert: {vc_main[2]:.0%} bzw. {vc_b1[2]:.0%}.",
        f"- Teststärke: Standardfehler der Sharpe-Differenz ≈ {se:.3f}; kleinster mit 80 % Power erkennbarer Effekt "
        f"≈ {Z80 * se:.2f} Sharpe. Ein realistischer Beitrag des Industrie-Momentums (≈ 0.05) war mit diesem Test nicht zu "
        "erkennen: „nicht belegt“ heisst hier fehlende Evidenz, nicht Evidenz für kein Effekt.",
        "",
        "## Urteil nach ADR 054 (e) – Kriterien vorab festgelegt",
        "",
        f"1. Sharpe ex Cash des Allokators ({sh_rule:+.3f}) über B1 Risikoparität ohne Signale ({sh_b1:+.3f}): **{'ja' if c1 else 'nein'}**",
        f"2. Gepaarte Sharpe-Differenz zu B1 positiv und Intervall ohne Null: **{'ja' if c2 else 'nein'}** ({dv:+.3f} [{lo:+.3f}, {hi:+.3f}])",
        f"→ Vorteil der Signale belegt: **{'JA' if verdict else 'NEIN'}**",
        "",
        f"Deflated Sharpe (Bailey/López de Prado 2014) der Residualrendite gegen B1 (Überschuss abzüglich Beta × B1-Überschuss, "
        f"Appraisal Ratio – belohnt kein höheres Risiko; ADR 056): {sr_a * 12**0.5:+.3f} p.a.; Hürde aus N = {n_trials} Versuchen "
        f"und der Varianz derselben Statistik über das Register (`docs/TRIALS.yaml`) {sr0_a * 12**0.5:+.3f}; Wahrscheinlichkeit "
        f"**{psr_a:.3f}** (≥ 0.95 überlebt die Mehrfachprüfung) – berichtet, nicht entscheidend. (Die erste Fassung nannte 0.933: "
        "falsche Varianz – absolute statt aktiver Sharpe-Werte – und eine Aktivrendite, die Hebel als Können zählte.)",
        "",
        "B2–B4 stehen zur Einordnung (anderes Universum, anderes Risiko) und entscheiden nicht. Finanzierung von Hebel zum "
        "Cash-Index ohne Aufschlag ist eine benannte Annahme (ADR 054 c).",
        "",
        f"Laufzeit {time.perf_counter() - t0:.0f} s.",
    ]
    with open(os.path.join(OUT, "WALKFORWARD.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
