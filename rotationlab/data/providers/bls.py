"""Bureau of Labor Statistics Public Data API v2: second source for the key labour and price series.

Used as the fallback member of macro chains (``configs/series.yaml``: ``macro:CPI`` = FRED/ALFRED, then
BLS): if FRED is unreachable, the newest months still arrive from the agency that publishes them.
BLS serves current values only, so vintages follow the lag model; in a chain these values only fill
months the primary does not have yet, which are first releases anyway.

Series ids ``bls:<BLS series id>`` (CUSR0000SA0 = CPI-U SA, CUSR0000SA0L1E = core CPI SA,
LNS14000000 = unemployment rate, CES0000000001 = nonfarm payrolls). Multiple-series POST with
``startyear``/``endyear``; without a key the API allows 10 years per request (20 with one) and a small
daily quota, hence one request per series per run and a ten-year window. Optional key: BLS_API_KEY.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series
from rotationlab.data.providers.http import HttpClient

URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
WINDOW_YEARS = 10


def parse_bls(raw: bytes, series_id: str) -> pd.Series:
    doc = json.loads(raw)
    if doc.get("status") != "REQUEST_SUCCEEDED":
        raise DataError(f"BLS: {doc.get('status')} {doc.get('message')}")
    series = {s.get("seriesID"): s for s in doc.get("Results", {}).get("series", [])}
    s = series.get(series_id)
    if s is None:
        raise DataError(f"BLS: series {series_id} missing in response")
    recs = {}
    for row in s.get("data", []):
        period = str(row.get("period", ""))
        if not (period.startswith("M") and period[1:].isdigit() and 1 <= int(period[1:]) <= 12):
            continue  # M13 = annual average
        try:
            value = float(str(row.get("value", "")).replace(",", ""))
        except ValueError:
            continue
        recs[pd.Timestamp(int(row["year"]), int(period[1:]), 1)] = value
    return pd.Series(recs, dtype=float).sort_index()


class BlsProvider(BaseProvider):
    name = "bls"

    def __init__(self, http: HttpClient, api_key: str | None = None, today: date | None = None) -> None:
        self.http = http
        self.api_key = api_key or None
        self.today = today or date.today()

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        end = self.today.year
        start = end - WINDOW_YEARS + 1 if since is None else max(since.year - 1, end - WINDOW_YEARS + 1)
        payload: dict[str, object] = {"seriesid": [spec.provider_code], "startyear": str(start), "endyear": str(end)}
        if self.api_key:
            payload["registrationkey"] = self.api_key
        s = parse_bls(self.http.post_json(URL, payload), spec.provider_code)
        return empty_frame() if s.empty else frame_from_series(s, spec, since)
