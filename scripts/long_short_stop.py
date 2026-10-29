"""ADR 065: the long-short rule, closed and reopened every month, with a 20 % stop on daily closes.

Rule (Nima, 2026-10-29 07:11): at every month-end both legs are closed and opened again – rank 1 of the round-1
forecast long 1.5 × equity, the last rank short 1.5 × equity – with full costs on the sale and the purchase, also
when the class stays (decision 07:15). A stop at 20 % price move against a leg (long −20 %, short +20 % from the
entry close), checked on daily closes; when it fires, **both** legs are closed at that close and the book stays
in cash for the rest of the month. Accounting: rotationlab/forecast/long_short.py::run_long_short_stop.

Daily data (total-return or price levels): US equities `static:usmkt:TR`, 10-year Treasury `UST10_D` (par bond on
the daily CMT yield – the daily twin of UST10_ME), gold and silver LBMA fixings. Frictions as ADR 063 (a).

Pre-registered (ADR 065), fixed before the first run:
  runs       rule with stop; the same rule without stop (2 trials). Reference only, not new: the runs of ADR 064
  criterion  rule, 1974-01 … 2018-12: Sharpe ex cash with 90 % block-bootstrap interval > 0 and 2019–2025 > 0
  reported   max drawdown, worst month, stops (count, leg, loss at the stop), paired Sharpe difference stop − no
             stop, cost drag, deflated Sharpe against equal weight with N = register

Writes output/long_short_stop/STOP.md, monthly.csv, detail.csv.

Aufruf: python scripts/long_short_stop.py
"""

from __future__ import annotations

import math
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, md_table, register, trials_variance  # noqa: E402
from long_short_check import EW, FRICTIONS, IN, SEEN, TRADED, equal_weight, round1_choice, stats  # noqa: E402
from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import research_factory  # noqa: E402
from rotationlab.forecast.evaluation import appraisal_residual, deflated_sharpe, paired_sharpe_diff, sharpe_ci  # noqa: E402
from rotationlab.forecast.long_short import run_long_short_stop  # noqa: E402
from rotationlab.forecast.model import BlockBootstrap  # noqa: E402

OUT_FILE = "output/long_short_stop/monthly.csv"
DAILY = {"US_EQ": "US_EQ", "UST10_D": "UST10_ME", "GOLD_D": "GOLD", "SILVER": "SILVER"}  # daily twin → class
STOP = 0.20
MAIN = "LS 1.5× monatlich neu, Stop 20 % (Regel)"
NO_STOP = "LS 1.5× monatlich neu, ohne Stop"
CLEAN = "LS 1.5× monatlich neu, Stop 20 %, ohne Wochenend-Fixing (ADR 066)"
# found after the first run (ADR 066): LBMA silver carries one Saturday print, 1983-02-05 (403.6 between 757.6 and
# 732.9) – LBMA does not fix on weekends. The pre-registered run keeps the data as frozen; this run uses the same rule
# on the daily path Monday–Friday only, and is counted as an extra trial.


def main() -> None:
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    out = os.path.join(ROOT, "output", "long_short_stop")
    os.makedirs(out, exist_ok=True)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, make_calendar(b), date(1972, 12, 31))
    v = f.at(date(2025, 12, 31))
    daily = v.total_return(list(DAILY), None).rename(columns=DAILY).loc[pd.Timestamp("1973-01-01") :]
    lv = v.total_return([*TRADED, "TBILL"], "ME")
    ret = (lv / lv.shift(1) - 1).loc[pd.Timestamp("1973-01-31") : pd.Timestamp(SEEN[1])]
    cash = ret["TBILL"]
    boot = BlockBootstrap(2000, 12, 20261025)

    choice = round1_choice(b, f).loc[pd.Timestamp("1973-12-31") : pd.Timestamp("2025-11-30")]
    weekday = daily[daily.index.dayofweek < 5]
    dropped = daily.index[daily.index.dayofweek >= 5]
    res = {
        MAIN: run_long_short_stop(choice, daily, cash, 1.5, STOP, FRICTIONS),
        NO_STOP: run_long_short_stop(choice, daily, cash, 1.5, None, FRICTIONS),
        CLEAN: run_long_short_stop(choice, weekday, cash, 1.5, STOP, FRICTIONS),
    }
    ew = equal_weight(ret[TRADED].loc[pd.Timestamp(IN[0]) :], 7.5)
    ref = pd.read_csv(
        os.path.join(ROOT, "output", "long_short", "monthly.csv"), index_col=0, parse_dates=True
    )
    refs = {
        "Referenz ADR 064: Halten je Bein": "LS 1.5× Runde 1 (Regel)",
        "Referenz ADR 064: monatlich neu gewichtet": "LS 1.5× Runde 1, monatlich neu gewichtet",
    }
    monthly = pd.DataFrame({**{k: r.monthly["ret"] for k, r in res.items()}, EW: ew, "cash": cash}).loc[
        pd.Timestamp(IN[0]) :
    ]
    monthly.index.name = "month"
    monthly.to_csv(os.path.join(ROOT, OUT_FILE), float_format="%.8f")
    detail = res[MAIN].monthly
    detail.to_csv(os.path.join(out, "detail.csv"), float_format="%.8f")

    periods = {
        "1974–2018 (in-sample)": IN,
        "2019–2025 (gesehen)": SEEN,
        "1974–2025 (gesamt)": (IN[0], SEEN[1]),
    }
    tables, main_sh = [], {}
    for pname, (a, z) in periods.items():
        sl = slice(pd.Timestamp(a), pd.Timestamp(z))
        rows = []
        for name in [*res, *refs, EW]:
            r = (monthly[name] if name in monthly else ref[refs[name]]).loc[sl].dropna()
            row = stats(r, cash, boot, None)
            if name in res:
                d = res[name].monthly.loc[sl]
                row["Monate mit Stop"] = int(d["stopped"].sum())
                row["Reibung p.a."] = float((d["cost"] + d["financing"] + d["borrow"]).sum() / len(d) * 12)
            rows.append(pd.Series(row, name=name))
            if name == MAIN:
                main_sh[pname] = sharpe_ci(r, cash.reindex(r.index), boot, CONF)
        t = pd.DataFrame(rows)
        t.index.name = pname
        tables.append(t)

    s_in, s_seen = main_sh[next(iter(periods))], main_sh[list(periods)[1]]
    k1, k2 = s_in.low > 0, s_seen.value > 0
    reading = (
        "**profitabel in beiden Zeiträumen**"
        if k1 and k2
        else "**nur in-sample profitabel** (2019–2025 nicht)"
        if k1
        else "**nicht belegt** (Intervall 1974–2018 schliesst null ein)"
    )
    ins = monthly.loc[pd.Timestamp(IN[0]) : pd.Timestamp(IN[1])]
    pair = paired_sharpe_diff(ins[MAIN], ins[NO_STOP], ins["cash"], boot, CONF)
    pair_c = paired_sharpe_diff(ins[CLEAN], ins[NO_STOP], ins["cash"], boot, CONF)
    s_clean_in = sharpe_ci(ins[CLEAN], ins["cash"], boot, CONF)
    seen = monthly.loc[pd.Timestamp(SEEN[0]) : pd.Timestamp(SEEN[1])]
    s_clean_seen = sharpe_ci(seen[CLEAN], seen["cash"], boot, CONF)
    n_trials, _ = register(include_planned=True, own_file=OUT_FILE)
    own = pd.Series(
        {
            n: float(
                (a := appraisal_residual(ins[n], ins[EW], ins["cash"])).mean() / a.std(ddof=1) * math.sqrt(12)
            )
            for n in res
        }
    )
    _, _, dsr = deflated_sharpe(
        appraisal_residual(ins[MAIN], ins[EW], ins["cash"]), n_trials, trials_variance(own, own_file=OUT_FILE)
    )
    stops = detail[detail["stopped"]]
    leg_tab = pd.DataFrame(
        {
            "Stops": stops.groupby("stop_leg").size(),
            "Ø Rendite Long-Bein bis Ausstieg": stops.groupby("stop_leg")["r_long"].mean(),
            "Ø Rendite Short-Bein bis Ausstieg": stops.groupby("stop_leg")["r_short"].mean(),
            "Ø gehaltener Monatsanteil": stops.groupby("stop_leg")["held"].mean(),
        }
    )
    leg_tab.index.name = "ausgelöst durch"
    cls = stops.apply(lambda r: r["long"] if r["stop_leg"] == "long" else r["short"], axis=1).value_counts()
    worst = detail.nsmallest(5, "ret")[["long", "short", "stopped", "stop_leg", "r_long", "r_short", "ret"]]
    pct = {"Rendite p.a.", "Vol p.a.", "Max DD", "schlechtester Monat", "Reibung p.a."}

    def fmt(t: pd.DataFrame) -> str:
        t = t.copy()
        for col in t.columns:
            if col in pct:
                t[col] = [f"{x:.1%}" if isinstance(x, float) and not np.isnan(x) else "–" for x in t[col]]
            elif col == "t (NW, Überrendite)":
                t[col] = [f"{x:+.2f}" for x in t[col]]
            elif col == "Monate mit Stop":
                t[col] = [
                    str(int(x)) if isinstance(x, (int, float)) and not np.isnan(x) else "–" for x in t[col]
                ]
        return md_table(t)

    lines = [
        "# Long-Short mit monatlichem Neuaufbau und 20-%-Stop (ADR 065)",
        "",
        f"Stand {date.today().isoformat()}. Skript `scripts/long_short_stop.py`, Buchhaltung "
        "`rotationlab/forecast/long_short.py::run_long_short_stop`. Regel: an jedem Monatsende beide Beine schliessen und neu "
        "eröffnen (volle Kosten auf Verkauf und Kauf, auch bei gleicher Klasse) – Rang 1 der Prognose von Runde 1 long "
        "1.5 × Eigenkapital, letzter Rang short 1.5 ×. Stop: Schlusskurs 20 % gegen ein Bein (long −20 %, short +20 % ab "
        "Einstieg) → **beide** Beine zu diesem Schlusskurs raus, Rest des Monats Cash. Geprüft auf Tagesschlusskursen "
        "(Gold/Silber: LBMA-Fixing); ein Sprung über den Stop wird zum schlechteren Kurs ausgeführt, Intraday-Kurse "
        "sind nicht modelliert.",
        "Reibung wie ADR 063 (a): 7.5 bp je gehandelter Einheit, Finanzierung T-Bill + 30 bp auf den fremdfinanzierten "
        "Teil, Leihgebühr p.a. Aktien/Treasury 0.30 %, Gold 0.50 %, Silber 1.50 %, Short-Erlöse zum T-Bill-Satz; "
        "Finanzierung und Leihe anteilig zur Haltedauer. 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed "
        f"20261025). Laufzeit {time.perf_counter() - t0:.0f} s.",
        "",
        "**Einordnung, offen gesagt:** Die Stop-Regel wurde nach dem Blick auf die Drawdowns von ADR 064 formuliert "
        "(März 1980: −60 % in einem Monat) – sie ist eine Reaktion auf gesehene Zahlen und deshalb schwache Evidenz, "
        "auch wenn ihre Parameter (20 %, beide Beine raus) vor diesem Lauf fixiert wurden. 2019–2025 ist gesehen.",
        "",
    ]
    for (pname, _), t in zip(periods.items(), tables, strict=True):
        lines += [f"## {pname}", "", fmt(t), ""]
    lines += [
        "## Stops (Regel, 1974–2025)",
        "",
        md_table(leg_tab, "{:+.3f}"),
        "",
        "Ausgelöst durch Klasse: " + ", ".join(f"{k} {v}" for k, v in cls.items()) + ".",
        "",
        "Schlechteste Monate der Regel:",
        "",
        md_table(worst.rename_axis("Monat"), "{:+.3f}"),
        "",
        "## Vorab-Kriterium (ADR 065)",
        "",
        f"- 1974–2018: Sharpe ex Cash {s_in.value:+.3f} [{s_in.low:+.3f}, {s_in.high:+.3f}] → Intervall über null: **{'ja' if k1 else 'nein'}**",
        f"- 2019–2025: Sharpe ex Cash {s_seen.value:+.3f} → über null: **{'ja' if k2 else 'nein'}**",
        f"- Stop gegen ohne Stop (gepaart, 1974–2018): Δ Sharpe {pair.value:+.3f} [{pair.low:+.3f}, {pair.high:+.3f}]",
        f"- Datenkorrektur (ADR 066, nach dem ersten Lauf gefunden; entfernt: {', '.join(str(d.date()) for d in dropped) or 'nichts'}): "
        f"Regel 1974–2018 Sharpe {s_clean_in.value:+.3f} [{s_clean_in.low:+.3f}, {s_clean_in.high:+.3f}], 2019–2025 {s_clean_seen.value:+.3f}; "
        f"gegen ohne Stop Δ {pair_c.value:+.3f} [{pair_c.low:+.3f}, {pair_c.high:+.3f}]",
        f"- Ruin: Regel {'ja, ' + res[MAIN].ruin.strftime('%Y-%m') if res[MAIN].ruin is not None else 'nein'}; ohne Stop "
        f"{'ja, ' + res[NO_STOP].ruin.strftime('%Y-%m') if res[NO_STOP].ruin is not None else 'nein'}",
        f"- Deflationierte Sharpe der Regel (Appraisal-Residuum gegen Equal Weight, 1974–2018, N = {n_trials}): {dsr:.3f}",
        "",
        f"Lesart: {reading}.",
        "",
    ]
    with open(os.path.join(out, "STOP.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
