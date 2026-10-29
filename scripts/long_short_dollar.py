"""ADR 067: the long-short in dollars – $1000 per leg at 1.5×, no fees, stop at a $200 loss of one leg.

Rule (Nima, 2026-10-29 09:15): every month $1500 long the class the round-1 forecast ranks first and $1500 short
the class it ranks last ($1000 capital per leg, 1.5× leverage), opened at the decision close. If one leg has lost
$200 at a daily close (a 13.3 % price move against it), both legs are closed at that close until the month-end.
Next month again $1000 per leg – no compounding. Fees, borrow, financing and interest are left out. Accounting:
rotationlab/forecast/long_short.py::run_dollar_long_short. Daily data Monday–Friday (ADR 066: the Saturday silver
print of 1983-02-05 is a data error).

Pre-registered (ADR 067), fixed before the first run:
  runs       rule with the $200 stop; the same without stop (2 trials)
  criterion  1974-01 … 2018-12: Sharpe of the monthly P&L on $2000 with 90 % block-bootstrap interval > 0, and
             2019–2025 Sharpe > 0 – as ADR 063 (a)
  reported   total and yearly P&L in dollars, worst month, largest drawdown of the summed P&L, share of winning
             months, stops, P&L by decade and by year

Writes output/long_short_dollar/DOLLAR.md, monthly.csv, by_year.csv.

Aufruf: python scripts/long_short_dollar.py
"""

from __future__ import annotations

import math
import os
import sys
import time
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _forecast_common import CONF, md_table  # noqa: E402
from long_short_check import EW, IN, SEEN, TRADED, round1_choice  # noqa: E402
from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import research_factory  # noqa: E402
from rotationlab.forecast.evaluation import newey_west_t, sharpe_ci  # noqa: E402
from rotationlab.forecast.long_short import run_dollar_long_short  # noqa: E402
from rotationlab.forecast.model import BlockBootstrap  # noqa: E402

DAILY = {"US_EQ": "US_EQ", "UST10_D": "UST10_ME", "GOLD_D": "GOLD", "SILVER": "SILVER"}
CAPITAL, NOTIONAL, STOP = 2000.0, 1500.0, 200.0
MAIN = "LS $1500/$1500, Stop $200 (Regel)"
NO_STOP = "LS $1500/$1500, ohne Stop"


def summary(
    pnl: pd.Series, cash: pd.Series, boot: BlockBootstrap, stops: pd.Series | None
) -> dict[str, object]:
    """Dollar statistics; the Sharpe is that of the monthly P&L on $2000 (a self-financing long-short)."""
    cum = pnl.cumsum()
    r = pnl / CAPITAL
    s = sharpe_ci(r + cash.reindex(r.index), cash.reindex(r.index), boot, CONF)
    _, t = newey_west_t(r)
    return {
        "Monate": len(pnl),
        "P&L gesamt $": round(float(pnl.sum())),
        "P&L je Jahr $": round(float(pnl.mean() * 12)),
        "% p.a. auf $2000": f"{pnl.mean() * 12 / CAPITAL:+.1%}",
        "Vol p.a.": f"{r.std(ddof=1) * math.sqrt(12):.1%}",
        "Sharpe": f"{s.value:+.3f} [{s.low:+.3f}, {s.high:+.3f}]",
        "t (NW)": f"{t:+.2f}",
        "Gewinnmonate": f"{(pnl > 0).mean():.0%}",
        "bester Monat $": round(float(pnl.max())),
        "schlechtester Monat $": round(float(pnl.min())),
        "grösster Rückgang $": round(float((cum - cum.cummax().clip(lower=0)).min())),
        "Stops": int(stops.sum()) if stops is not None else "–",
    }


def main() -> None:
    t0 = time.perf_counter()
    b = load_bundle(os.path.join(ROOT, "configs"))
    out = os.path.join(ROOT, "output", "long_short_dollar")
    os.makedirs(out, exist_ok=True)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    f = research_factory(b, obs, make_calendar(b), date(1972, 12, 31))
    v = f.at(date(2025, 12, 31))
    daily = v.total_return(list(DAILY), None).rename(columns=DAILY).loc[pd.Timestamp("1973-01-01") :]
    daily = daily[daily.index.dayofweek < 5]
    lv = v.total_return([*TRADED, "TBILL"], "ME")
    ret = (lv / lv.shift(1) - 1).loc[pd.Timestamp("1974-01-31") : pd.Timestamp(SEEN[1])]
    cash = ret["TBILL"]
    boot = BlockBootstrap(2000, 12, 20261025)

    choice = round1_choice(b, f).loc[pd.Timestamp("1973-12-31") : pd.Timestamp("2025-11-30")]
    runs = {
        MAIN: run_dollar_long_short(choice, daily, NOTIONAL, STOP),
        NO_STOP: run_dollar_long_short(choice, daily, NOTIONAL, None),
    }
    ew = ret[TRADED].mean(axis=1)  # equal weight, no fees (reference)
    monthly = pd.DataFrame({k: v_["pnl"] / CAPITAL + cash for k, v_ in runs.items()} | {EW: ew, "cash": cash})
    monthly = monthly.loc[pd.Timestamp(IN[0]) : pd.Timestamp(SEEN[1])]
    monthly.index.name = "month"
    monthly.to_csv(os.path.join(out, "monthly.csv"), float_format="%.8f")
    detail = runs[MAIN]
    detail.to_csv(os.path.join(out, "detail.csv"), float_format="%.4f")

    periods = {
        "1974–2018 (in-sample)": IN,
        "2019–2025 (gesehen)": SEEN,
        "1974–2025 (gesamt)": (IN[0], SEEN[1]),
    }
    tables, crit = [], {}
    for pname, (a, z) in periods.items():
        sl = slice(pd.Timestamp(a), pd.Timestamp(z))
        rows = []
        for name, res in runs.items():
            d = res.loc[sl]
            rows.append(pd.Series(summary(d["pnl"], cash, boot, d["stopped"]), name=name))
            if name == MAIN:
                r = d["pnl"] / CAPITAL
                crit[pname] = sharpe_ci(r + cash.reindex(r.index), cash.reindex(r.index), boot, CONF)
        ew_p = (
            monthly[EW].loc[sl] - cash.loc[sl]
        ) * CAPITAL  # equal weight $2000, excess over cash, for scale
        rows.append(pd.Series(summary(ew_p, cash, boot, None), name="Equal Weight $2000 (Überrendite)"))
        tbl = pd.DataFrame(rows)
        tbl.index.name = pname
        tables.append(tbl)

    s_in, s_seen = crit[next(iter(periods))], crit[list(periods)[1]]
    k1, k2 = s_in.low > 0, s_seen.value > 0
    reading = (
        "**profitabel in beiden Zeiträumen**"
        if k1 and k2
        else "**nur in-sample profitabel** (2019–2025 nicht)"
        if k1
        else "**nicht belegt** (Intervall 1974–2018 schliesst null ein)"
    )
    years = pd.DataFrame(
        {
            "P&L Regel $": detail["pnl"].groupby(detail.index.year).sum(),
            "P&L ohne Stop $": runs[NO_STOP]["pnl"].groupby(runs[NO_STOP].index.year).sum(),
            "Stops": detail["stopped"].groupby(detail.index.year).sum().astype(int),
        }
    )
    years.index.name = "Jahr"
    years.round(0).to_csv(os.path.join(out, "by_year.csv"))
    dec = years.groupby((years.index // 10) * 10).sum()
    dec.index = [f"{d}er" for d in dec.index]
    dec.index.name = "Jahrzehnt"
    stops = detail[detail["stopped"]]
    worst = detail.nsmallest(5, "pnl")[["long", "short", "stopped", "pnl_long", "pnl_short", "pnl"]]
    lines = [
        "# Long-Short in Dollar: $1000 je Bein mit 1.5× Hebel, Stop bei $200 (ADR 067)",
        "",
        f"Stand {date.today().isoformat()}. Skript `scripts/long_short_dollar.py`, Buchhaltung "
        "`rotationlab/forecast/long_short.py::run_dollar_long_short`. Jeden Monat $1500 long auf Rang 1 und $1500 short auf "
        "den letzten Rang der Prognose von Runde 1 ($1000 Kapital je Bein, Hebel 1.5), Einstieg zum Schlusskurs am "
        "Monatsende. Hat ein Bein an einem Tagesschluss $200 verloren (13.3 % Kursbewegung), werden beide Beine zu diesem "
        "Kurs geschlossen bis Monatsende. Danach wieder $1000 je Bein – kein Zinseszins. **Ohne Gebühren, Leihe, "
        "Finanzierung und Zinsen** (Vorgabe). Tagesdaten Montag–Freitag (ADR 066). Sharpe = monatlicher P&L auf $2000, "
        f"90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Laufzeit {time.perf_counter() - t0:.0f} s.",
        "",
        "**Einordnung:** vierte Fassung der Long-Short-Idee auf derselben Geschichte (ADR 063–066), formuliert nach dem "
        "Blick auf deren Ergebnisse; 2019–2025 ist gesehen. Ohne Kosten sind die Zahlen eine Obergrenze.",
        "",
    ]
    for (pname, _), tbl in zip(periods.items(), tables, strict=True):
        lines += [f"## {pname}", "", md_table(tbl), ""]
    lines += [
        "## P&L je Jahrzehnt ($)",
        "",
        md_table(dec, "{:+,.0f}"),
        "",
        f"Stops 1974–2025: {len(stops)} (Long-Bein {int((stops['stop_leg'] == 'long').sum())}, Short-Bein "
        f"{int((stops['stop_leg'] == 'short').sum())}); Ø Verlust des auslösenden Beins "
        f"${stops[['pnl_long', 'pnl_short']].min(axis=1).mean():,.0f}, Ø P&L des Monats ${stops['pnl'].mean():,.0f}.",
        "",
        "Schlechteste Monate der Regel ($):",
        "",
        md_table(worst.rename_axis("Monat"), "{:+,.0f}"),
        "",
        "## Vorab-Kriterium (ADR 067)",
        "",
        f"- 1974–2018: Sharpe {s_in.value:+.3f} [{s_in.low:+.3f}, {s_in.high:+.3f}] → Intervall über null: **{'ja' if k1 else 'nein'}**",
        f"- 2019–2025: Sharpe {s_seen.value:+.3f} → über null: **{'ja' if k2 else 'nein'}**",
        "",
        f"Lesart: {reading}. Jahr für Jahr: `output/long_short_dollar/by_year.csv`.",
        "",
    ]
    with open(os.path.join(out, "DOLLAR.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
