"""Response builders in the providers' wire formats.

The build environment of this repository cannot reach Yahoo, FRED, Stooq, CFTC or the French
library, so recorded responses do not exist yet. These builders reproduce the documented formats:

* Yahoo chart API v8: ``chart.result[0]`` with ``meta.exchangeTimezoneName``, ``timestamp`` (session
  open, epoch seconds), ``indicators.quote[0].close`` (nulls allowed), ``events.dividends`` and
  ``events.splits`` keyed by epoch strings;
* FRED ``series/observations`` JSON: ``count/offset/limit`` and ``observations`` rows with
  ``realtime_start, realtime_end, date, value`` (``"."`` = missing);
* ``fredgraph.csv``: ``observation_date,<CODE>``;
* Stooq: ``Date,Open,High,Low,Close,Volume``;
* CFTC Socrata JSON (legacy futures-only, dataset 6dca-aqww);
* Kenneth French: a zip with one CSV in the library's text layout.

`build_fixtures.py` writes one static example per provider; integration tests use the builders as
fake servers whose answers change from one simulated day to the next. `pytest -m network` checks
the parsers against the real services (CI only).
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _open_ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp())


def yahoo_chart(
    symbol: str,
    days: Sequence[date],
    closes: Sequence[float | None],
    dividends: Mapping[date, float] | None = None,
    splits: Mapping[date, tuple[int, int]] | None = None,
) -> bytes:
    events: dict[str, dict[str, dict[str, object]]] = {}
    if dividends:
        events["dividends"] = {
            str(_open_ts(d)): {"amount": a, "date": _open_ts(d)} for d, a in dividends.items()
        }
    if splits:
        events["splits"] = {
            str(_open_ts(d)): {
                "date": _open_ts(d),
                "numerator": n,
                "denominator": m,
                "splitRatio": f"{n}:{m}",
            }
            for d, (n, m) in splits.items()
        }
    result = {
        "meta": {
            "currency": "USD",
            "symbol": symbol,
            "exchangeName": "PCX",
            "instrumentType": "ETF",
            "gmtoffset": -14400,
            "timezone": "EDT",
            "exchangeTimezoneName": "America/New_York",
            "dataGranularity": "1d",
            "range": "",
        },
        "timestamp": [_open_ts(d) for d in days],
        "indicators": {
            "quote": [
                {
                    "open": list(closes),
                    "high": list(closes),
                    "low": list(closes),
                    "close": list(closes),
                    "volume": [1_000_000] * len(days),
                }
            ],
            "adjclose": [{"adjclose": list(closes)}],
        },
    }
    if events:
        result["events"] = events
    return json.dumps({"chart": {"result": [result], "error": None}}).encode()


def fred_observations(
    rows: Sequence[tuple[str, str, str, str]],
    offset: int = 0,
    limit: int = 100000,
    count: int | None = None,
    realtime: tuple[str, str] = ("1776-07-04", "9999-12-31"),
) -> bytes:
    """rows: (realtime_start, realtime_end, date, value) as strings, value '.' for missing."""
    page = rows[offset : offset + limit]
    return json.dumps(
        {
            "realtime_start": realtime[0],
            "realtime_end": realtime[1],
            "observation_start": "1600-01-01",
            "observation_end": "9999-12-31",
            "units": "lin",
            "output_type": 1,
            "file_type": "json",
            "order_by": "observation_date",
            "sort_order": "asc",
            "count": len(rows) if count is None else count,
            "offset": offset,
            "limit": limit,
            "observations": [
                {"realtime_start": a, "realtime_end": b, "date": c, "value": v} for a, b, c, v in page
            ],
        }
    ).encode()


def fredgraph_csv(
    code: str, dates: Sequence[date], values: Sequence[float | None], header: str = "observation_date"
) -> bytes:
    lines = [f"{header},{code}"] + [
        f"{d.isoformat()},{'.' if v is None else v}" for d, v in zip(dates, values, strict=True)
    ]
    return ("\n".join(lines) + "\n").encode()


def stooq_csv(days: Sequence[date], closes: Sequence[float]) -> bytes:
    lines = ["Date,Open,High,Low,Close,Volume"] + [
        f"{d.isoformat()},{c},{c},{c},{c},1000" for d, c in zip(days, closes, strict=True)
    ]
    return ("\n".join(lines) + "\n").encode()


def cftc_json(
    market: str, rows: Sequence[tuple[date, int, int, int]], name: str = "GOLD - COMMODITY EXCHANGE INC."
) -> bytes:
    """rows: (report date, noncomm long, noncomm short, open interest)."""
    return json.dumps(
        [
            {
                "market_and_exchange_names": name,
                "report_date_as_yyyy_mm_dd": f"{d.isoformat()}T00:00:00.000",
                "cftc_contract_market_code": market,
                "open_interest_all": str(oi),
                "noncomm_positions_long_all": str(lo),
                "noncomm_positions_short_all": str(sh),
                "noncomm_postions_spread_all": "0",
                "comm_positions_long_all": "0",
                "comm_positions_short_all": "0",
            }
            for d, lo, sh, oi in rows
        ]
    ).encode()


def french_zip(csv_text: str, inner_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo(inner_name, date_time=(2026, 9, 1, 0, 0, 0))
        z.writestr(info, csv_text.encode("latin-1"))
    return buf.getvalue()


def bls_json(series: dict[str, list[tuple[int, int, str]]], status: str = "REQUEST_SUCCEEDED") -> bytes:
    """BLS API v2 timeseries response; rows (year, month 1-13, value), month 13 = annual average."""
    return json.dumps(
        {
            "status": status,
            "responseTime": 31,
            "message": [],
            "Results": {
                "series": [
                    {
                        "seriesID": sid,
                        "data": [
                            {
                                "year": str(y),
                                "period": f"M{m:02d}",
                                "periodName": "x",
                                "latest": "false",
                                "value": v,
                                "footnotes": [{}],
                            }
                            for y, m, v in sorted(rows, reverse=True)
                        ],
                    }
                    for sid, rows in series.items()
                ]
            },
        }
    ).encode()
