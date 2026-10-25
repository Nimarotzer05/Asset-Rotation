"""CFTC Commitments of Traders, legacy futures-only report, via the Socrata API (dataset 6dca-aqww).

Series ids ``cftc:<market code>:<field>`` with ``field`` in ``noncomm_net`` (non-commercial long −
short), ``noncomm_long``, ``noncomm_short``, ``open_interest``. Positions are as of Tuesday and
published on Friday; the catalog uses a 7-day lag (holiday weeks are published a few days later).
Field names follow the CFTC variable list for legacy reports.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series
from rotationlab.data.providers.http import HttpClient

URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
FIELDS = {
    "noncomm_long": "noncomm_positions_long_all",
    "noncomm_short": "noncomm_positions_short_all",
    "open_interest": "open_interest_all",
}


def parse_cot(raw: bytes) -> pd.DataFrame:
    rows = json.loads(raw)
    if isinstance(rows, dict) and rows.get("error"):
        raise DataError(f"cftc: {rows.get('message', rows)}")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"].str[:10])
    for v in FIELDS.values():
        df[v] = pd.to_numeric(df[v], errors="coerce") if v in df.columns else np.nan
    df["noncomm_net"] = df[FIELDS["noncomm_long"]] - df[FIELDS["noncomm_short"]]
    return df.sort_values("date").drop_duplicates("date", keep="last").set_index("date")


class CftcProvider(BaseProvider):
    name = "cftc"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._cache: dict[tuple[str, date | None], pd.DataFrame] = {}

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        p = dict(spec.params)
        market, field = p.get("market"), p.get("field")
        if not market or field not in ("noncomm_net", *FIELDS):
            raise DataError(f"{spec.series_id}: params.market and a known params.field are required")
        key = (market, since)
        if key not in self._cache:
            params = {"cftc_contract_market_code": market, "$order": "report_date_as_yyyy_mm_dd", "$limit": "50000"}
            if since is not None:
                params["$where"] = f"report_date_as_yyyy_mm_dd >= '{since.isoformat()}T00:00:00'"
            self._cache[key] = parse_cot(self.http.get(URL, params))
        df = self._cache[key]
        col = field if field == "noncomm_net" else FIELDS[field]
        if df.empty or col not in df.columns:
            return empty_frame()
        return frame_from_series(df[col], spec, since, normalise=False)
