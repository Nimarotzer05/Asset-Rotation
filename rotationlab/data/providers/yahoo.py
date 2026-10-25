"""Yahoo Finance chart API (v8): daily close, dividends and splits in one request per symbol.

Series ids: ``yahoo:<SYMBOL>:close|dividend|split``. ``close`` is Yahoo's split-adjusted, not
dividend-adjusted close; dividends are cash amounts on the ex-date on the same split basis; split
factors are numerator/denominator. Total return is built in the view from close and dividends, so
a later dividend correction shows up as a dividend revision instead of silently rewriting history.

Session dates: timestamps are converted to the exchange time zone (``meta.exchangeTimezoneName``)
before taking the date. The bar of a session that has not closed yet is dropped by the schema check.

Splits: Yahoo re-bases the whole history (closes and dividends) when a split happens. An incremental
window that contains a split event is therefore widened to the full history of that symbol, so the
store records one uniform rescaling instead of a fake jump at the start of the window.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series
from rotationlab.data.providers.http import HttpClient

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
EARLIEST = -2208988800  # 1900-01-01


def parse_chart(raw: bytes) -> dict[str, pd.Series]:
    """Chart JSON → {"close", "dividend", "split"} series indexed by session date."""
    doc = json.loads(raw)
    chart = doc.get("chart", {})
    if chart.get("error"):
        raise DataError(f"yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise DataError("yahoo: empty result")
    r = results[0]
    meta = r.get("meta", {})
    tzname = meta.get("exchangeTimezoneName")
    try:
        tz = ZoneInfo(tzname) if tzname else None
    except Exception:  # unknown zone name: fall back to the fixed offset
        tz = None
    offset = int(meta.get("gmtoffset", 0))

    def to_date(ts: int) -> pd.Timestamp:
        if tz is not None:
            return pd.Timestamp(datetime.fromtimestamp(int(ts), tz).date())
        return pd.Timestamp(datetime.fromtimestamp(int(ts) + offset, UTC).date())

    stamps = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    idx = pd.DatetimeIndex([to_date(t) for t in stamps])
    close = pd.Series(np.array([np.nan if c is None else float(c) for c in closes], dtype=float), index=idx)
    close = close[~close.index.duplicated(keep="last")].dropna()
    events = r.get("events") or {}
    divs = events.get("dividends") or {}
    div = pd.Series({to_date(v.get("date", k)): float(v["amount"]) for k, v in divs.items() if v.get("amount") is not None},
                    dtype=float)
    splits = events.get("splits") or {}
    spl = pd.Series({to_date(v.get("date", k)): float(v["numerator"]) / float(v["denominator"])
                     for k, v in splits.items() if v.get("denominator")}, dtype=float)
    div = div.groupby(level=0).sum().sort_index() if len(div) else div
    spl = spl.groupby(level=0).prod().sort_index() if len(spl) else spl
    return {"close": close.sort_index(), "dividend": div, "split": spl}


class YahooProvider(BaseProvider):
    name = "yahoo"

    def __init__(self, http: HttpClient, today: date | None = None) -> None:
        self.http = http
        self.today = today or date.today()
        self._cache: dict[tuple[str, int], dict[str, pd.Series]] = {}
        self.widened: set[str] = set()

    def _get(self, symbol: str, p1: int) -> dict[str, pd.Series]:
        p2 = int(datetime(self.today.year, self.today.month, self.today.day, tzinfo=UTC).timestamp()) + 86400
        raw = self.http.get(CHART_URL.format(symbol=symbol),
                            {"period1": str(p1), "period2": str(p2), "interval": "1d",
                             "events": "div,splits", "includeAdjustedClose": "true"})
        return parse_chart(raw)

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        symbol, field = spec.provider_code.rsplit(":", 1)
        if symbol in self.widened:
            since = None
        p1 = EARLIEST if since is None else int(datetime(since.year, since.month, since.day, tzinfo=UTC).timestamp())
        key = (symbol, p1)
        if key not in self._cache:
            data = self._get(symbol, p1)
            if since is not None and len(data["split"]) and data["split"].index.max() >= pd.Timestamp(since):
                self.widened.add(symbol)                     # history was re-based: take all of it
                since, p1 = None, EARLIEST
                key = (symbol, p1)
                data = self._get(symbol, p1)
            self._cache[key] = data
        s = self._cache[key].get(field)
        if s is None:
            raise DataError(f"yahoo: unknown field '{field}' in {spec.series_id}")
        if s.empty:
            return empty_frame()
        return frame_from_series(s, spec, since, normalise=False)
