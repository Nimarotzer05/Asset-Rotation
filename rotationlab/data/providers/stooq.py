"""Stooq daily CSV: second source for ETF closes (cross-source check and fallback in close chains).

Series ids: ``stooq:<TICKER>:close``; US tickers map to ``<ticker>.us``. Stooq's adjustment basis
can differ from Yahoo's, which is why chains splice by ratio at the junction and the cross-source
check compares daily *returns*, never levels.

Since March 2026 Stooq serves its CSV downloads only with an API key (free, requested on stooq.com); without
one it answers with an HTML page. The key comes from STOOQ_API_KEY and is sent as ``apikey``; without a key
the provider is not wired at all (`make_providers`), so close chains run on Yahoo alone and no daily run
logs a fetch failure per ETF.
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series
from rotationlab.data.providers.http import HttpClient

URL = "https://stooq.com/q/d/l/"


def stooq_symbol(ticker: str) -> str:
    t = ticker.lower()
    return t if "." in t or t.startswith("^") else f"{t}.us"


def parse_csv(raw: bytes) -> pd.Series:
    text = raw.decode("utf-8", errors="replace").strip()
    if text[:200].lower().lstrip().startswith(("<!doctype", "<html")):
        raise DataError("stooq: HTML page instead of CSV – API key missing or invalid (STOOQ_API_KEY)")
    if not text or text.lower().startswith(("no data", "brak danych")) or "Date" not in text.splitlines()[0]:
        raise DataError(f"stooq: no data ({text[:40]!r})")
    df = pd.read_csv(io.StringIO(text))
    if "Close" not in df.columns:
        raise DataError(f"stooq: unexpected columns {list(df.columns)}")
    return pd.Series(pd.to_numeric(df["Close"], errors="coerce").to_numpy(),
                     index=pd.to_datetime(df["Date"]), name="close").dropna().sort_index()


class StooqProvider(BaseProvider):
    name = "stooq"

    def __init__(self, http: HttpClient, api_key: str | None = None) -> None:
        self.http = http
        self.api_key = api_key

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        ticker, field = spec.provider_code.rsplit(":", 1)
        if field != "close":
            raise DataError(f"stooq provides only close, not {field}")
        params = {"s": stooq_symbol(ticker), "i": "d"}
        if self.api_key:
            params["apikey"] = self.api_key
        if since is not None:
            params["d1"] = since.strftime("%Y%m%d")
        s = parse_csv(self.http.get(URL, params))
        if s.empty:
            return empty_frame()
        return frame_from_series(s, spec, since, normalise=False)
