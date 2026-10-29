"""ADR 063 (a): is "rank 1 long 1.5×, last rank short 1.5×, hold unless the forecast changes" profitable?

The rule is Nima's (2026-10-29); gross exposure 3.0 lies above the engine's limit, so it is accounted explicitly
in rotationlab/forecast/long_short.py (cash rebate on short proceeds, financing spread on the leveraged part,
lending fee on the short, costs per unit traded, ruin). Rankings: round 1's frozen composite (published
forecast; its Treasury class UST10 is traded as the month-end series UST10_ME, as in the round-1 paper rule) and,
as a secondary run, round 5's Fed model (output/forecast_fed/scores_fed.csv – run scripts/round5_fed.py first).
Trades at the decision month-end close, returns of the following month (monthly data; ≈ +0.01 Sharpe optimistic
against next-session execution, output/execution).

Pre-registered (ADR 063 a): runs, frictions, periods and the reading below were fixed before the first run.
  criterion   main run, 1974-01 … 2018-12: Sharpe of the excess return over T-bills, 90 % block-bootstrap
              interval > 0; 2019-01 … 2025-12 (seen period) Sharpe > 0
  reading     both = profitable in both periods; first only = in-sample only; else not established
  reported    1× version, monthly reset, no frictions, round-5 ranking; max drawdown, worst month, ruin, turnover,
              cost drag, leg drift; deflated Sharpe of the appraisal residual against equal weight (N = register)

Writes output/long_short/LONG_SHORT.md, monthly.csv, metrics.csv.

Aufruf: python scripts/long_short_check.py
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
from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import research_factory  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    appraisal_residual,
    deflated_sharpe,
    newey_west_t,
    sharpe_ci,
)
from rotationlab.forecast.long_short import Frictions, picks, run_long_short  # noqa: E402
from rotationlab.forecast.model import BlockBootstrap, composite, feature_panel, ranks_of  # noqa: E402

OUT_FILE = "output/long_short/monthly.csv"
TRADED = ["US_EQ", "UST10_ME", "GOLD", "SILVER"]
TO_TRADED = {"UST10": "UST10_ME"}  # round 1 ranks the averaged-yield series, the rule trades month-end prices
CASH = "TBILL"
LEVERAGE = 1.5
FRICTIONS = Frictions(  # ADR 063 a – assumptions for an ETF implementation, stated, not estimated
    cost_bps=7.5,
    financing_spread=0.0030,
    borrow={"US_EQ": 0.0030, "UST10_ME": 0.0030, "GOLD": 0.0050, "SILVER": 0.0150},
)
NONE = Frictions(cost_bps=0.0, financing_spread=0.0, borrow={})
IN = (date(1974, 1, 31), date(2018, 12, 31))  # return months
SEEN = (date(2019, 1, 31), date(2025, 12, 31))
EW = "Equal Weight (4 Klassen)"
MAIN = "LS 1.5× Runde 1 (Regel)"


def round1_choice(b, f) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    """Round 1's ranking at every month-end, on the as-of panel at the end (= pointwise for unrevised prices,
    tests/lookahead/test_forecast_model.py), mapped to the traded instruments."""
    fc = b.forecasts["forecast"]
    ranked = list(fc.universe["long_history"].ranked)
    v = f.at(date(2025, 12, 31))
    feats = {
        k: feature_panel(v, k, ranked, **fc.model.feature_params.get(k, {})) for k in fc.model.feature_weights
    }
    scores = composite(feats, fc.model.feature_weights, fc.model.zscore_clip).reindex(columns=ranked)
    return picks(ranks_of(scores)).replace(TO_TRADED)


def round5_choice() -> pd.DataFrame:
    path = os.path.join(ROOT, "output", "forecast_fed", "scores_fed.csv")
    if not os.path.exists(path):
        raise SystemExit(
            "output/forecast_fed/scores_fed.csv missing: run scripts/round5_fed.py first (ADR 063)"
        )
    s = pd.read_csv(path, index_col=0, parse_dates=True)
    return picks(ranks_of(s))


def equal_weight(r: pd.DataFrame, cost_bps: float) -> pd.Series:
    """Monthly rebalanced equal weight of the traded classes, costs on the turnover back to equal weights."""
    w = np.full(r.shape[1], 1.0 / r.shape[1])
    out = {}
    for t, row in r.iterrows():
        x = row.to_numpy(float)
        g = float(w @ x)
        drift = w * (1 + x) / (1 + g)
        out[t] = g - cost_bps / 1e4 * float(np.abs(drift - w).sum())
    return pd.Series(out)


def stats(
    r: pd.Series, cash: pd.Series, boot: BlockBootstrap, detail: pd.DataFrame | None
) -> dict[str, object]:
    r = r.dropna()
    c = cash.reindex(r.index)
    lvl = (1 + r).cumprod()
    s = sharpe_ci(r, c, boot, CONF)
    m, t = newey_west_t(r - c)
    row: dict[str, object] = {
        "Monate": len(r),
        "Rendite p.a.": float(lvl.iloc[-1] ** (12 / len(r)) - 1) if lvl.iloc[-1] > 0 else -1.0,
        "Vol p.a.": float(r.std(ddof=1) * math.sqrt(12)),
        "Sharpe ex Cash": f"{s.value:+.3f} [{s.low:+.3f}, {s.high:+.3f}]",
        "t (NW, Überrendite)": round(t, 2),
        "Max DD": float((lvl / lvl.cummax() - 1).min()),
        "schlechtester Monat": float(r.min()),
    }
    if detail is not None:
        d = detail.reindex(r.index)
        row["Monate mit Handel"] = float((d["traded"] > 0).mean())
        row["Umschlag p.a."] = float(d["traded"].sum() / len(d) * 12)
        row["Reibung p.a."] = float((d["cost"] + d["financing"] + d["borrow"]).sum() / len(d) * 12)
        row["max. Bein"] = float(d[["long_size", "short_size"]].max().max())
    return row


def main() -> None:
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    out = os.path.join(ROOT, "output", "long_short")
    os.makedirs(out, exist_ok=True)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, make_calendar(b), date(1972, 12, 31))
    v = f.at(date(2025, 12, 31))
    lv = v.total_return([*TRADED, CASH], "ME")
    ret = (lv / lv.shift(1) - 1).loc[pd.Timestamp("1973-01-31") : pd.Timestamp(SEEN[1])]
    cash = ret[CASH]
    boot = BlockBootstrap(2000, 12, 20261025)

    c1 = round1_choice(b, f).loc[pd.Timestamp("1973-12-31") : pd.Timestamp("2025-11-30")]
    c5 = round5_choice().loc[: pd.Timestamp("2025-11-30")]
    runs = {
        MAIN: (c1, LEVERAGE, "per_leg", FRICTIONS),
        "LS 1.0× Runde 1": (c1, 1.0, "per_leg", FRICTIONS),
        "LS 1.5× Runde 1, monatlich neu gewichtet": (c1, LEVERAGE, "reset", FRICTIONS),
        "LS 1.5× Runde 1, ohne Reibung": (c1, LEVERAGE, "per_leg", NONE),
        "LS 1.5× Runde 5 (Fed-Modell)": (c5, LEVERAGE, "per_leg", FRICTIONS),
    }
    results, details, ruins = {}, {}, {}
    for name, (ch, lev, hold, fr) in runs.items():
        res = run_long_short(ch, ret[TRADED], cash, lev, hold, fr)  # type: ignore[arg-type]
        results[name] = res.monthly["ret"]
        details[name] = res.monthly
        ruins[name] = res.ruin
    ew = equal_weight(ret[TRADED].loc[pd.Timestamp(IN[0]) :], 7.5)
    monthly = pd.DataFrame({**results, EW: ew, "cash": cash}).loc[pd.Timestamp(IN[0]) :]
    monthly.index.name = "month"
    monthly.to_csv(os.path.join(ROOT, OUT_FILE), float_format="%.8f")
    details[MAIN].to_csv(os.path.join(out, "main_detail.csv"), float_format="%.8f")

    periods = {
        "1974–2018 (in-sample)": IN,
        "2019–2025 (gesehen)": SEEN,
        "1974–2025 (gesamt)": (IN[0], SEEN[1]),
    }
    tables, main_sh = [], {}
    for pname, (a, z) in periods.items():
        rows = []
        for name in [*runs, EW]:
            r = monthly[name].loc[pd.Timestamp(a) : pd.Timestamp(z)]
            if r.dropna().empty:
                continue
            row = stats(r, cash, boot, details.get(name))
            rows.append(pd.Series(row, name=name))
            if name == MAIN:
                main_sh[pname] = sharpe_ci(r.dropna(), cash.reindex(r.dropna().index), boot, CONF)
        t = pd.DataFrame(rows)
        t.index.name = pname
        tables.append(t)
    metrics = pd.concat(tables, keys=list(periods))
    metrics.to_csv(os.path.join(out, "metrics.csv"))

    s_in, s_seen = main_sh[list(periods)[0]], main_sh[list(periods)[1]]
    k1, k2 = s_in.low > 0, s_seen.value > 0
    reading = (
        "**profitabel in beiden Zeiträumen**"
        if k1 and k2
        else "**nur in-sample profitabel** (2019–2025 nicht)"
        if k1
        else "**nicht belegt** (Intervall 1974–2018 schliesst null ein)"
    )
    n_trials, _ = register(include_planned=True, own_file=OUT_FILE)
    sl = monthly.loc[pd.Timestamp(IN[0]) : pd.Timestamp(IN[1])]
    own = pd.Series(
        {
            name: float(
                (a := appraisal_residual(sl[name], sl[EW], sl["cash"])).mean() / a.std(ddof=1) * math.sqrt(12)
            )
            for name in runs
            if sl[name].notna().sum() > 24
        }
    )
    resid = appraisal_residual(sl[MAIN], sl[EW], sl["cash"])
    _, _, dsr = deflated_sharpe(resid, n_trials, trials_variance(own, own_file=OUT_FILE))
    pct = {
        "Rendite p.a.",
        "Vol p.a.",
        "Max DD",
        "schlechtester Monat",
        "Monate mit Handel",
        "Umschlag p.a.",
        "Reibung p.a.",
    }

    def fmt(t: pd.DataFrame) -> str:
        t = t.copy()
        for col in t.columns:
            if col in pct:
                t[col] = [f"{x:.1%}" if isinstance(x, float) and not np.isnan(x) else "–" for x in t[col]]
            elif col == "t (NW, Überrendite)":
                t[col] = [f"{x:+.2f}" for x in t[col]]
            elif col == "max. Bein":
                t[col] = [f"{x:.2f}" if isinstance(x, float) and not np.isnan(x) else "–" for x in t[col]]
        return md_table(t)

    lines = [
        "# Long-Short-Regel auf der Monatsprognose (ADR 063 a)",
        "",
        f"Stand {date.today().isoformat()}. Skript `scripts/long_short_check.py`, Buchhaltung "
        "`rotationlab/forecast/long_short.py`. Regel: Rang 1 long mit 1.5 × Eigenkapital, letzter Rang short mit "
        "1.5 × Eigenkapital, Entscheid am Monatsende, Halten für einen Monat; ein Bein, dessen Klasse sich nicht "
        "ändert, wird nicht gehandelt (es driftet). Handel zum Schlusskurs des Entscheidungstags (Monatsdaten).",
        "Reibung (Annahmen für eine ETF-Umsetzung, vorab fixiert): 7.5 bp je gehandelter Einheit, Finanzierung "
        "T-Bill + 30 bp auf den fremdfinanzierten Teil des Long-Beins, Leihgebühr p.a. Aktien 0.30 %, Treasury 0.30 %, "
        "Gold 0.50 %, Silber 1.50 %; Short-Erlöse verzinst zum T-Bill-Satz.",
        f"{int(CONF * 100)}-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Laufzeit "
        f"{time.perf_counter() - t0:.0f} s.",
        "",
        "**Vorwissen, offen gesagt:** Der unverschuldete Top-minus-Bottom-Spread von Runde 1 ist bekannt "
        "(`output/forecast/EVALUATION.md`: +11 % p.a. [+2.7 %, +19 %] 1973–2018; `HOLDOUT.md`: −3.8 % p.a. 2019–2025). "
        "Neu sind hier Hebel, Halteregel, Reibung, Monatsend-Treasury, Drawdown und Ruinrisiko.",
        "",
    ]
    for (pname, _), t in zip(periods.items(), tables, strict=True):
        lines += [f"## {pname}", "", fmt(t), ""]
    lines += [
        "## Vorab-Kriterium (ADR 063 a)",
        "",
        f"- 1974–2018: Sharpe ex Cash {s_in.value:+.3f} [{s_in.low:+.3f}, {s_in.high:+.3f}] → Intervall über null: **{'ja' if k1 else 'nein'}**",
        f"- 2019–2025: Sharpe ex Cash {s_seen.value:+.3f} → über null: **{'ja' if k2 else 'nein'}**",
        "- Ruin (Eigenkapital ≤ 0 in einem Monat): "
        + "; ".join(
            f"{n}: {'ja, ' + r.strftime('%Y-%m') if r is not None else 'nein'}" for n, r in ruins.items()
        ),
        f"- Deflationierte Sharpe der Hauptregel (Appraisal-Residuum gegen Equal Weight, 1974–2018, N = {n_trials}): {dsr:.3f}",
        "",
        f"Lesart: {reading}.",
        "",
    ]
    with open(os.path.join(out, "LONG_SHORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
