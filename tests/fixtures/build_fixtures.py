"""Builds the static provider fixtures in tests/fixtures/ (run: python -m tests.fixtures.build_fixtures).

The ALFRED fixture is modelled on real CPI-U (SA) values from FRED-MD with a realistic release
pattern: first release on the 15th of the following month, the annual seasonal-factor revision every
20 February (previous year), the current value from 2009-02-20 on, and an archive that starts on
2006-01-01, so observations released earlier only appear with that date (pre-archive backfill).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from rotationlab.data.calendar import NYSECalendar
from tests.fixtures import fakes

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
ARCHIVE_START = date(2006, 1, 1)
LAST_KNOWLEDGE = date(2009, 12, 31)


def real_cpi() -> pd.Series:
    fm = pd.read_csv(ROOT / "data/raw/fred_md_2026-10.csv", skiprows=[1])
    idx = pd.to_datetime(fm["sasdate"], format="%m/%d/%Y")
    s = pd.Series(pd.to_numeric(fm["CPIAUCSL"], errors="coerce").to_numpy(), index=idx)
    return s.loc["2004-01-01":"2008-12-01"]


def cpi_vintages() -> dict[date, list[tuple[date, float]]]:
    """obs month (first day) -> [(vintage date, value)] as it really happened in this fixture world."""
    out: dict[date, list[tuple[date, float]]] = {}
    for k, (ts, final) in enumerate(real_cpi().items()):
        m = ts.date()
        nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        v1 = round(final * (1 + 0.0006 * math.sin(k + 1)), 3)
        v2 = round(final * (1 + 0.0002 * math.cos(k + 1)), 3)
        steps = [
            (nxt.replace(day=15), v1),
            (date(m.year + 1, 2, 20), v2),
            (date(2009, 2, 20), round(final, 3)),
        ]
        steps = sorted({d: v for d, v in steps if d <= LAST_KNOWLEDGE}.items())
        dedup: list[tuple[date, float]] = []
        for d, v in steps:
            if not dedup or dedup[-1][1] != v:
                dedup.append((d, v))
        out[m] = dedup
    return out


def alfred_rows(
    vintages: dict[date, list[tuple[date, float]]],
    archive_start: date = ARCHIVE_START,
    clip: date | None = None,
) -> list[tuple[str, str, str, str]]:
    """ALFRED output_type=1 rows: archive starts at `archive_start`; with `clip` (incremental request)
    periods are clipped to start at `clip`, as the API does."""
    rows = []
    start_floor = max(archive_start, clip) if clip else archive_start
    for m, steps in sorted(vintages.items()):
        for i, (d, v) in enumerate(steps):
            end = steps[i + 1][0] - timedelta(days=1) if i + 1 < len(steps) else date(9999, 12, 31)
            if end < start_floor:
                continue
            start = max(d, start_floor)
            rows.append((start.isoformat(), end.isoformat(), m.isoformat(), f"{v:.3f}"))
    rows.sort(key=lambda r: (r[2], r[0]))
    return rows


def spy_2024() -> tuple[list[date], list[float | None], dict[date, float]]:
    days = list(NYSECalendar().trading_days(date(2024, 1, 2), date(2024, 12, 31)))
    rng = np.random.default_rng(7)
    px = 470.0 * np.exp(np.cumsum(rng.normal(0.0008, 0.009, len(days))))
    closes: list[float | None] = [round(float(x), 4) for x in px]
    closes[-1] = None  # Yahoo sends null closes for sessions without a print
    divs = {
        date(2024, 3, 15): 1.5949,
        date(2024, 6, 21): 1.7590,
        date(2024, 9, 20): 1.7458,
        date(2024, 12, 20): 1.9663,
    }
    return days, closes, divs


def shiller_xls(path: Path) -> None:
    """ie_data.xls layout: title rows, header row 7, float dates (October = YYYY.1), empty recent earnings."""
    import xlwt  # only needed to regenerate the fixture

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Data")
    ws.write(0, 0, 'Stock Market Data Used in "Irrational Exuberance"')
    ws.write(1, 0, "Updated by Robert J. Shiller")
    header = [
        "Date",
        "P",
        "D",
        "E",
        "CPI",
        "Date Fraction",
        "Rate GS10",
        "Real Price",
        "Real Dividend",
        "Real Total Return Price",
        "Real Earnings",
        "Real TR Scaled Earnings",
        "CAPE",
    ]
    for j, h in enumerate(header):
        ws.write(7, j, h)
    rows = [
        (1871.01, 4.44, 0.26, 0.40, 12.46, 5.32, "NA"),
        (1871.02, 4.50, 0.26, 0.40, 12.84, 5.32, "NA"),
        (1871.1, 4.64, 0.30, 0.40, 12.08, 5.32, "NA"),
        (1871.11, 4.74, 0.30, 0.40, 11.90, 5.32, "NA"),
        (1871.12, 4.86, 0.30, 0.40, 11.69, 5.32, "NA"),
        (2025.08, 6408.95, 77.2, 228.1, 323.976, 4.26, 37.9),
        (2025.09, 6584.02, 77.5, 230.6, 324.8, 4.12, 38.6),
        (2025.1, 6735.69, 77.8, "", 325.5, 4.06, 39.4),
        (2025.11, 6740.0, "", "", "", 4.09, ""),
    ]
    for i, (d, p_, dv, e, cpi, gs, cape) in enumerate(rows):
        r = 8 + i
        for j, v in enumerate([d, p_, dv, e, cpi, d, gs]):
            ws.write(r, j, v)
        ws.write(r, 12, cape)
    wb.save(str(path))


def main() -> None:
    days, closes, divs = spy_2024()
    (HERE / "yahoo_SPY_2024.json").write_bytes(fakes.yahoo_chart("SPY", days, closes, dividends=divs))
    stooq_closes = [c if c is not None else closes[-2] for c in closes]
    (HERE / "stooq_spy.csv").write_bytes(fakes.stooq_csv(days, stooq_closes))
    (HERE / "alfred_CPIAUCSL.json").write_bytes(fakes.fred_observations(alfred_rows(cpi_vintages())))
    months = [date(2025, m, 1) for m in range(1, 10)]
    (HERE / "fredgraph_UNRATE.csv").write_bytes(
        fakes.fredgraph_csv("UNRATE", months, [4.0, 4.1, 4.2, 4.2, 4.3, None, 4.3, 4.3, 4.4])
    )
    tuesdays = [date(2024, 1, 2) + timedelta(weeks=i) for i in range(12)]
    (HERE / "cftc_gold.json").write_bytes(
        fakes.cftc_json(
            "088691", [(d, 250_000 + 1000 * i, 50_000 + 500 * i, 500_000) for i, d in enumerate(tuesdays)]
        )
    )
    ff3 = (ROOT / "data/raw/ff_3_factors_monthly.csv").read_text(encoding="latin-1")
    (HERE / "F-F_Research_Data_Factors_CSV.zip").write_bytes(
        fakes.french_zip(ff3, "F-F_Research_Data_Factors.csv")
    )
    shiller_xls(HERE / "shiller_ie_data.xls")
    print("fixtures written to", HERE)


if __name__ == "__main__":
    main()
