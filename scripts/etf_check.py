"""Implementability check of research round 4 with exchange-traded funds (ADR 061), pre-registered.

Round 4 (ADR 060) found that its advantage over passive risk parity comes from the 12-month trend filter, measured on
research indices (French industries and countries, synthetic par bonds, LBMA fixings). This script rebuilds exactly
that ablation – risk parity across the long sleeves plus the trend filter, no cross-sectional selection – with the
ETFs of the live store and asks one question fixed before the run: does the filter still add Sharpe over the same
risk parity without the filter, on instruments one can buy, after their costs?

Runs (same engine, costs, financing, execution `next_tradable`):
  R   risk parity + trend filter (configs/strategies/trend_rp_etf.yaml)       – the one trial (docs/TRIALS.yaml)
  B1  the same without the trend filter                                        – primary baseline
  B2  equal weight of the long ETFs with history at the window start, monthly  – reported
  B3  60/40 SPY/IEF, monthly                                                   – reported
  B4  buy and hold SPY                                                         – reported
Primary (ADR 061 d): Sharpe ex cash of R above B1 and the 90 % moving-block bootstrap interval of the paired Sharpe
difference (block 12, 2000 draws, seed 20261025) above zero. Reported: the other differences, standard error and MDE,
and the correlation of R with the round-4 index version over the common months (does the index study describe what the
ETFs did?). Window: ADR 058 (e) – first decision with every long sleeve active, to the common data end.

Aufruf: python scripts/etf_check.py --store <checkout of branch data>/data/store --data-commit <sha>
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from _forecast_common import CONF, md_table  # noqa: E402
from allocator_v2_walkforward import aligned, row, window, with_params  # noqa: E402

from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar  # noqa: E402
from rotationlab.data.store import PointInTimeStore  # noqa: E402
from rotationlab.engine.modes import GoldenReport, golden, research_factory  # noqa: E402
from rotationlab.forecast.evaluation import common_data_end, paired_sharpe_diff  # noqa: E402
from rotationlab.forecast.model import BlockBootstrap  # noqa: E402

SID = "trend_rp_etf"
OUT = os.path.join(ROOT, "output", "etf_check")
RULE = "R Risikoparität + Trendfilter (ETF)"
B1 = "B1 Risikoparität ohne Filter (ETF)"
BOOT = BlockBootstrap(2000, 12, 20261025)
Z80 = 1.645 + 0.842
INDEX_FILE = os.path.join(ROOT, "output", "allocator_v2", "walkforward_monthly.csv")
INDEX_COLUMN = "ohne Querschnitt"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", required=True, help="data/store of a checkout of branch data")
    ap.add_argument("--data-commit", required=True, help="commit of branch data the store comes from")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    scfg = b.strategies[SID]
    gr = scfg.golden_run
    assert gr is not None
    cal = make_calendar(b)
    obs = PointInTimeStore(a.store).observations()
    sleeves = dict(scfg.params["sleeves"])
    inst = {k: list(v["instruments"]) for k, v in sleeves.items()}
    long_sleeves = [k for k, v in sleeves.items() if v["group"] != "overlay" and float(v["budget"]) > 0]
    cash_asset = str(scfg.params["cash"])

    # ---- the rule first: the window is fixed before anything is reported ----------------------------------------
    runs: dict[str, GoldenReport] = {RULE: golden(b, obs, SID, cal)}
    first_full, ever, never = window(runs[RULE].result, long_sleeves)
    start = first_full + pd.offsets.MonthEnd(1)
    end_view = research_factory(b, obs, cal, gr.data_from).at(gr.end)
    groups = {k: inst[k] for k in ever} | {"US-Markt (B3/B4)": ["SPY"], "Cash": [cash_asset]}
    end, ends = common_data_end({g: end_view.total_return(x, None) for g, x in groups.items()}, cal)
    if (start.date(), end.date()) != (gr.sample[0], gr.sample[1]):
        print(
            f"window rule: {start.date()} … {end.date()} (config sample {gr.sample}); data ends: "
            + ", ".join(f"{g} {e.date()}" for g, e in ends.items())
            + " – register the window and run again (no result is computed before)"
        )
        return 2

    # ---- baselines: same engine, costs, financing and execution --------------------------------------------------
    runs[B1] = golden(b, obs, SID, cal, run=with_params(gr, ts_filter=False))
    fw = b.strategies["fixed_weights"]
    fw_gr = fw.golden_run
    assert fw_gr is not None
    fw_gr = fw_gr.model_copy(
        update={
            "universe": "live",
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
        return golden(
            bb, obs, "fixed_weights", cal, run=with_params(fw_gr, weights=weights, rebalance=rebalance)
        )

    at_start = research_factory(b, obs, cal, gr.data_from).at(first_full.date())
    longs = [x for k in long_sleeves for x in inst[k]]
    full = [x for x in longs if at_start.total_return([x], None)[x].dropna().size > 0]
    runs[f"B2 Equal Weight ({len(full)} ETFs)"] = fixed(
        [*full, cash_asset], dict.fromkeys(full, 1 / len(full))
    )
    runs["B3 60/40 SPY/IEF"] = fixed(["SPY", "IEF", cash_asset], {"SPY": 0.6, "IEF": 0.4})
    runs["B4 Buy-and-Hold SPY"] = fixed(["SPY", cash_asset], {"SPY": 1.0}, "never")

    index = pd.date_range(start, end, freq="ME")
    series = {label: aligned(rep, index) for label, rep in runs.items()}
    cash = series[RULE][1]
    table = pd.DataFrame([row(label, *s) for label, s in series.items()]).set_index("Lauf")
    table.to_csv(os.path.join(OUT, "metrics.csv"))
    monthly = pd.DataFrame({label: s[0] for label, s in series.items()} | {"cash": cash})
    monthly.to_csv(os.path.join(OUT, "monthly.csv"))
    runs[RULE].result.weights.to_csv(os.path.join(OUT, "weights.csv"))

    r_main = series[RULE][0]
    diffs = []
    for label in [k for k in runs if k != RULE]:
        d = paired_sharpe_diff(r_main, series[label][0], cash, BOOT, CONF)
        diffs.append({"Baseline": label, "Δ Sharpe": d.value, "low": d.low, "high": d.high})
    dtab = pd.DataFrame(diffs).set_index("Baseline")
    dtab.to_csv(os.path.join(OUT, "paired.csv"))
    d1 = dtab.loc[B1]
    sh_rule, sh_b1 = float(table.loc[RULE, "Sharpe ex Cash"]), float(table.loc[B1, "Sharpe ex Cash"])
    c1, c2 = sh_rule > sh_b1, float(d1["low"]) > 0
    se = (float(d1["high"]) - float(d1["low"])) / (2 * 1.645)

    # the index study over the same months: does it describe what the ETFs did?
    idx = pd.read_csv(INDEX_FILE, index_col=0, parse_dates=True)
    common = idx.index.intersection(index)
    ex_etf = (r_main - cash).reindex(common)
    ex_idx = (idx[INDEX_COLUMN] - idx["cash"]).reindex(common)
    corr = float(ex_etf.corr(ex_idx))
    sh_idx = float(ex_idx.mean() / ex_idx.std(ddof=1) * np.sqrt(12))
    sh_etf_c = float(ex_etf.mean() / ex_etf.std(ddof=1) * np.sqrt(12))

    lines = [
        "# Umsetzbarkeits-Check mit ETFs (ADR 061): Risikoparität + Trendfilter",
        "",
        f"Stand {pd.Timestamp.today().date()}. Daten: Live-Store, Branch `data@{a.data_commit[:12]}` (Yahoo-Schlusskurse mit "
        f"Dividenden und Splits). Fenster nach ADR 058 (e): {start.date()} … {end.date()} ({len(index)} Monate); erste "
        f"Entscheidung mit allen Long-Sleeves {first_full.date()}"
        + (f"; nie aktiv: {', '.join(never)}" if never else "")
        + ". Ausführung `next_tradable`, Kosten je ETF aus `configs/universe.yaml`, Finanzierung zum Cash-ETF BIL "
        "+30 bp. Ein vorregistrierter Lauf (ADR 061), im Versuchsregister vor dem Lauf eingetragen. Alle Zahlen aus "
        "`scripts/etf_check.py`.",
        "",
        "**Einordnung:** Das Fenster überlappt die Teilperiode 2008–2025 von Runde 4, in der der Vorteil zu B1 auf "
        "Indizes +0.08 [−0.18, +0.28] betrug (ADR 060). Der Check prüft die Umsetzbarkeit, keine neue Hypothese, und "
        "ist keine unabhängige Evidenz für den Filter.",
        "",
        "## Kennzahlen",
        "",
        md_table(table),
        "",
        "## Gepaarte Sharpe-Differenzen R − Baseline (90-%-Block-Bootstrap)",
        "",
        md_table(dtab),
        "",
        "## Index-Studie gegen ETF-Umsetzung (gleiche Monate)",
        "",
        f"- Korrelation der monatlichen Überschussrenditen ETF-Version gegen Index-Version „{INDEX_COLUMN}“ (Runde 4): "
        f"**{corr:.2f}** über {len(common)} Monate.",
        f"- Sharpe ex Cash über diese Monate: ETF {sh_etf_c:+.3f}, Index {sh_idx:+.3f}.",
        "",
        "## Urteil nach ADR 061 (d) – vorab festgelegt",
        "",
        f"1. Sharpe ex Cash von R ({sh_rule:+.3f}) über B1 ({sh_b1:+.3f}): **{'ja' if c1 else 'nein'}**",
        f"2. Intervall der gepaarten Differenz über null: **{'ja' if c2 else 'nein'}** "
        f"({float(d1['Δ Sharpe']):+.3f} [{float(d1['low']):+.3f}, {float(d1['high']):+.3f}])",
        f"→ Trendfilter mit ETFs umsetzbar belegt: **{'JA' if c1 and c2 else 'NEIN'}** – Standardfehler {se:.3f}, "
        f"MDE (80 % Power) {Z80 * se:.2f}",
        "",
        f"Laufzeit {time.perf_counter() - t0:.0f} s.",
    ]
    with open(os.path.join(OUT, "ETF_CHECK.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
