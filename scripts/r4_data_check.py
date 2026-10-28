"""Research round 4 (ADR 058 g): the data gates – checked on the frozen files before the walk-forward runs.

The gates test the data and the constructions, never a strategy result; their thresholds were fixed before the
download. A failed gate stops round 4 (exit 1): the walk-forward must not run on data that failed a gate.

    G1  every required source is in the frozen manifest
    G2  the daily French industries compound to the monthly file of the same library (value-weighted section,
        right units): per industry correlation ≥ 0.999 and mean absolute difference ≤ 0.10 percentage points
    G3  the daily par bonds agree with the month-end par bonds of the static panel (UST10_D ~ UST10_ME,
        UST2_D ~ UST2_ME): correlation of the monthly returns ≥ 0.98
    G4  every currency is quoted the right way round: the monthly change of its dollar value correlates
        negatively (≤ −0.20) with the change of the trade-weighted dollar (DTWEXM, 1973–2019); the DEM→EUR splice
        moves by less than 5 % from the last DEM-implied value to the first euro quote
    G5  the country returns are in US dollars: for the home countries of the nine currencies that are in the file,
        the median correlation of the monthly country return with the change of the currency's dollar value is
        ≥ +0.10 (a dollar return contains the currency move, a local-currency return does not)
    G6  breadth: at least six currencies with a usable rate and at least six countries at some date – reported,
        not a stop (below that, the emergency rules of ADR 057 h apply)

Reported, not gating: coverage per series, rate splices (call money → 3M, DE → euro area) with the level step,
the stretch of every deposit index, internal gaps of the country series, daily moves beyond 10 σ.

Writes output/allocator_v2/DATA.md. Aufruf: python scripts/r4_data_check.py
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.data.providers import constructs_r4 as r4  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "output", "allocator_v2")
IND_CORR, IND_MAD = 0.999, 0.0010
UST_CORR = 0.98
FX_CORR = -0.20
EUR_SPLICE = 0.05
USD_CORR = 0.10
HOME = {  # country slug → currency whose dollar value a USD return of the country contains
    "JAPAN": "JPY", "UK": "GBP", "UNITEDKINGDOM": "GBP", "GREATBRITAIN": "GBP", "SWITZERLAND": "CHF",
    "CANADA": "CAD", "AUSTRALIA": "AUD", "NEWZEALAND": "NZD", "SWEDEN": "SEK", "NORWAY": "NOK", "GERMANY": "EUR",
}  # fmt: skip


def read(raw_dir: str, name: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(raw_dir, name), index_col=0, parse_dates=True)
    out: pd.DataFrame = df.apply(pd.to_numeric, errors="coerce").sort_index()
    return out


def monthly(level: pd.Series) -> pd.Series:
    """Calendar-month returns of a level series (last value per month)."""
    m = level.dropna().resample("ME").last()
    return m.pct_change(fill_method=None).dropna()


def references(raw_dir: str) -> dict[str, pd.Series | pd.DataFrame]:
    """The comparison series of the static panel: monthly industries, month-end par bonds, the dollar index."""
    from rotationlab.data.providers.static import StaticProvider

    sp = StaticProvider(raw_dir)
    cons = sp._group("constructs")
    return {
        "ind10": sp._group("ind10"),
        "UST10_ME": cons["UST10_ME"],
        "UST2_ME": cons["UST2_ME"],
        "DTWEXM": sp._group("usd")["DTWEXM"],
    }


def check(
    raw_dir: str = RAW, reference: Mapping[str, pd.Series | pd.DataFrame] | None = None
) -> tuple[list[tuple[str, bool, str]], list[str]]:
    """(gates: name, passed, detail), report lines."""
    ref = dict(reference) if reference is not None else references(raw_dir)
    gates: list[tuple[str, bool, str]] = []
    with open(os.path.join(raw_dir, "r4_PROVENANCE.json"), encoding="utf-8") as fh:
        prov = json.load(fh)
    files = prov["manifest"]["files"]
    missing = sorted(k for k, v in files.items() if v["required"] and v["status"] != "ok")
    optional = sorted(k for k, v in files.items() if not v["required"] and v["status"] != "ok")
    gates.append(
        (
            "G1 Pflichtquellen",
            not missing,
            f"fehlend: {missing or 'keine'}; optional nicht verfügbar: {optional or 'keine'}",
        )
    )

    fred = read(raw_dir, "r4_fred_daily.csv.gz")
    rates = read(raw_dir, "r4_oecd_rates_monthly.csv.gz")
    ind = read(raw_dir, "ff_10_industry_daily.csv.gz")
    countries = read(raw_dir, "ff_intl_countries_monthly.csv.gz")

    # G2 industries: daily compounded to calendar months against the monthly file of the library
    ind_m = ref["ind10"]
    assert isinstance(ind_m, pd.DataFrame)
    det, ok = [], True
    for col in ind.columns:
        d = (1.0 + ind[col].dropna()).resample("ME").prod() - 1.0
        both = pd.concat([d, ind_m[col]], axis=1, keys=["d", "m"], sort=True).dropna()
        corr = float(both["d"].corr(both["m"])) if len(both) > 2 else float("nan")
        mad = float((both["d"] - both["m"]).abs().mean()) if len(both) else float("nan")
        det.append(f"{col} {corr:.5f}/{mad * 100:.3f} Pp ({len(both)} M)")
        ok &= bool(corr >= IND_CORR and mad <= IND_MAD)
    gates.append(("G2 Industrien täglich = Monatsdatei", ok, "; ".join(det)))

    # G3 daily par bonds against the month-end par bonds
    daily = r4.build_daily(fred, rates, ind)
    det, ok = [], True
    for d_name, m_name in (("UST10_D", "UST10_ME"), ("UST2_D", "UST2_ME")):
        m_ref = ref[m_name]
        assert isinstance(m_ref, pd.Series)
        both = pd.concat(
            [monthly(daily[d_name]), m_ref.pct_change(fill_method=None)], axis=1, keys=["d", "m"], sort=True
        ).dropna()
        corr = float(both["d"].corr(both["m"])) if len(both) > 2 else float("nan")
        det.append(f"{d_name}~{m_name} {corr:.4f} ({len(both)} M)")
        ok &= bool(corr >= UST_CORR)
    gates.append(("G3 Par-Bonds täglich ~ Monatsende", ok, "; ".join(det)))

    # G4 quote conventions and the euro splice
    usd = ref["DTWEXM"]
    assert isinstance(usd, pd.Series)
    dl = np.log(usd.dropna().resample("ME").last()).diff()
    det, ok = [], True
    for ccy in r4.FX_SPOT:
        s = r4.spot_usd(fred, ccy).resample("ME").last()
        both = pd.concat([np.log(s).diff(), dl], axis=1, keys=["s", "d"], sort=True).dropna()
        corr = float(both["s"].corr(both["d"])) if len(both) > 2 else float("nan")
        det.append(f"{ccy} {corr:+.2f}")
        ok &= bool(corr <= FX_CORR)
    dem = r4.DEM_PER_EUR / fred["DEXGEUS"].dropna()
    eur = fred["DEXUSEU"].dropna()
    last_dem = dem[dem.index < eur.index[0]]
    step = float(eur.iloc[0] / last_dem.iloc[-1] - 1.0)
    ok &= abs(step) < EUR_SPLICE
    gates.append(
        (
            "G4 Notierung und Euro-Verkettung",
            ok,
            "Korrelation mit dem Dollar-Index: "
            + ", ".join(det)
            + f"; DEM→EUR {step:+.2%} ({last_dem.index[-1].date()} → {eur.index[0].date()})",
        )
    )

    # G5 the country file is in dollars
    slugs = {r4.country_slug(str(c)): c for c in countries.columns}
    cors = {}
    for slug, ccy in HOME.items():
        if slug not in slugs:
            continue
        fx = np.log(r4.spot_usd(fred, ccy).resample("ME").last()).diff()
        both = pd.concat([countries[slugs[slug]], fx], axis=1, keys=["c", "f"], sort=True).dropna()
        if len(both) > 24:
            cors[slug] = float(both["c"].corr(both["f"]))
    med = float(np.median(list(cors.values()))) if cors else float("nan")
    gates.append(
        (
            "G5 Länderrenditen in USD",
            bool(med >= USD_CORR),
            f"Median {med:+.2f} über {len(cors)} Heimatländer: "
            + ", ".join(f"{k} {v:+.2f}" for k, v in cors.items()),
        )
    )

    # G6 breadth for the emergency rules (reported, not a stop)
    fx_n = daily[[f"FX_{c}" for c in r4.FX_SPOT]].notna().sum(axis=1)
    ct = r4.build_countries(countries)
    ct_n = ct.notna().sum(axis=1)
    fx6 = fx_n[fx_n >= 6].index.min().date() if (fx_n >= 6).any() else "nie"
    ct6 = ct_n[ct_n >= 6].index.min().date() if (ct_n >= 6).any() else "nie"
    gates.append(
        (
            "G6 Breite (Notfallregeln h)",
            True,
            f"Währungen mit Index: max {int(fx_n.max())}, ≥ 6 ab {fx6}; "
            f"Länder in der Datei: {ct.shape[1]}, max gleichzeitig {int(ct_n.max()) if len(ct_n) else 0}, ≥ 6 ab {ct6}",
        )
    )
    return gates, report_lines(daily, ct, rates, countries)


def report_lines(
    daily: pd.DataFrame, ct: pd.DataFrame, rates: pd.DataFrame, countries: pd.DataFrame
) -> list[str]:
    lines = ["## Abdeckung", "", "| Reihe | erster Wert | letzter Wert | Werte |", "|---|---|---|---|"]
    for frame in (daily, ct):
        for col in frame.columns:
            s = frame[col].dropna()
            if len(s):
                lines.append(f"| {col} | {s.index.min().date()} | {s.index.max().date()} | {len(s)} |")
            else:
                lines.append(f"| {col} | – | – | 0 |")
    lines += ["", "## Zinsen je Währung: Verkettung und Spanne des Einlagenindex", ""]
    for ccy in r4.FX_SPOT:
        areas = ["DE", "EZ"] if ccy == "EUR" else [r4.RATE_AREA[ccy]]
        parts = []
        for a in areas:
            p3, pc = rates.get(f"IR3TIB01{a}M156N"), rates.get(f"IRSTCI01{a}M156N")
            f3 = p3.first_valid_index() if p3 is not None else None
            fc = pc.first_valid_index() if pc is not None else None
            step = ""
            if f3 is not None and pc is not None and f3 in pc.dropna().index:
                step = f", Sprung beim Wechsel {float(p3[f3] - pc[f3]):+.2f} Pp"
            parts.append(
                f"{a}: 3M ab {f3.date() if f3 is not None else '–'}, Tagesgeld ab {fc.date() if fc is not None else '–'}{step}"
            )
        idx = daily[f"FX_{ccy}"].dropna()
        parts.append(
            f"Index {idx.index.min().date() if len(idx) else '–'} … {idx.index.max().date() if len(idx) else '–'}"
        )
        lines.append(f"- {ccy}: " + "; ".join(parts))
    started = countries.notna().cumsum() > 0
    ended = countries[::-1].notna().cumsum()[::-1] > 0
    gaps = (started & ended & countries.isna()).sum()
    lines += [
        "",
        "## Länder: interne Lücken (beenden den Index, ADR 058 c)",
        "",
        ", ".join(f"{c} {int(n)} Monat(e)" for c, n in gaps.items() if n) or "keine",
        "",
        "## Tagesbewegungen über 10 σ (EWMA, Schwerpunkt 60) – zur Sichtprüfung, bleiben drin",
        "",
    ]
    big = []
    for col in daily.columns:
        r = daily[col].dropna().pct_change().dropna()
        z = (r / r.ewm(com=60, min_periods=120).std().shift(1)).abs()
        big += [f"{col} {d.date()} {r[d]:+.1%}" for d in z[z > 10].index[:5]]
    lines.append("; ".join(big) or "keine")
    return lines


def main() -> int:
    gates, lines = check()
    os.makedirs(OUT, exist_ok=True)
    head = ["# Datenprüfung Runde 4 (ADR 058 g)", "", "| Prüfung | bestanden | Befund |", "|---|---|---|"]
    head += [f"| {g} | {'ja' if ok else '**NEIN**'} | {d} |" for g, ok, d in gates]
    with open(os.path.join(OUT, "DATA.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join([*head, "", *lines]) + "\n")
    print("\n".join(head))
    failed = [g for g, ok, _ in gates if not ok]
    if failed:
        print(f"STOP: {len(failed)} Prüfung(en) nicht bestanden – Runde 4 läuft nicht (ADR 058 g)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
