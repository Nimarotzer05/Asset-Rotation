"""FRED and ALFRED.

Three modes per series:

* ``vintages: alfred`` with an API key – every real-time period from ALFRED
  (``output_type=1``: one row per observation and real-time period). ``realtime_start`` becomes the
  vintage date. A full fetch asks for the whole archive (1776-07-04 … 9999-12-31); an incremental
  fetch asks from a clip date and keeps only periods that *start after* it, because the API clips
  older periods to the requested start and would otherwise forge vintages.
  Two corrections, both conservative and counted in ``frame.attrs``:
    - *pre-archive backfill*: observations whose first archived vintage lies far beyond the
      publication lag (ALFRED archives start in the 1990s for many series) get an extra row at
      ``Lag.apply(obs_date)`` with the oldest archived value, so long backtests are not empty;
      the value is the oldest known, not the first release (residual risk, ADR 022);
    - *clamping*: releases dated before the end of their own period (preliminary Michigan readings
      stamped on the first of the month) are treated as known at period end.
* ``vintages: none`` – latest values with lag-model vintages, from the API with a key or from
  ``fredgraph.csv`` without one (the ingest reports the missing key once as a warning).

ALFRED series are never filled from the lag model when the key is missing: today's revised values
stamped with first-release dates would mix with real vintages later and leak revisions into the
past. Without a key they are skipped (fetch warning) until a key is configured.
"""
from __future__ import annotations

import io
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import Frequency, SeriesSpec
from rotationlab.data.lags import Lag
from rotationlab.data.providers.base import FRAME_COLUMNS, BaseProvider, empty_frame, frame_from_series, period_end
from rotationlab.data.providers.http import HttpClient

API_URL = "https://api.stlouisfed.org/fred/series/observations"
GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ARCHIVE_START = "1776-07-04"
ARCHIVE_END = "9999-12-31"
PAGE = 100000
BACKFILL_SLACK_DAYS = 31


def parse_observations(raw: bytes) -> tuple[pd.DataFrame, int]:
    """API JSON → frame [realtime_start, realtime_end, date, value] (value NaN for '.') and total count."""
    doc = json.loads(raw)
    if "error_message" in doc:
        raise DataError(f"FRED: {doc['error_message']}")
    obs = doc.get("observations", [])
    df = pd.DataFrame(obs, columns=["realtime_start", "realtime_end", "date", "value"])
    df["value"] = pd.to_numeric(df["value"].replace(".", np.nan), errors="coerce")
    for c in ("realtime_start", "date"):
        df[c] = pd.to_datetime(df[c], format="%Y-%m-%d")
    return df, int(doc.get("count", len(df)))


def parse_graph_csv(raw: bytes, code: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(raw.decode()))
    date_col = next((c for c in df.columns if c.lower() in ("observation_date", "date")), None)
    if date_col is None or code not in df.columns:
        raise DataError(f"fredgraph: unexpected columns {list(df.columns)} for {code}")
    vals = pd.to_numeric(df[code].replace(".", np.nan), errors="coerce")
    return pd.Series(vals.to_numpy(), index=pd.to_datetime(df[date_col]), name=code).dropna()


def alfred_frame(rows: pd.DataFrame, spec: SeriesSpec, clip: date | None) -> pd.DataFrame:
    """ALFRED real-time periods → store frame with real vintages (see module docstring)."""
    r = rows.dropna(subset=["value"]).copy()
    if clip is not None:
        r = r[r["realtime_start"] > pd.Timestamp(clip)]
    if r.empty:
        out = empty_frame()
        out.attrs.update(real_vintages=True, backfilled=0, clamped=0)
        return out
    obs = period_end(pd.DatetimeIndex(r["date"]), Frequency(spec.frequency))
    vint = pd.DatetimeIndex(r["realtime_start"])
    clamped = vint < obs
    vint = vint.where(~clamped, obs)
    f = pd.DataFrame({"obs_date": obs, "vintage_date": vint, "value": r["value"].to_numpy(dtype=float)})
    f = f.sort_values(["obs_date", "vintage_date"], kind="mergesort").drop_duplicates(["obs_date", "vintage_date"], keep="last")
    backfilled = 0
    if clip is None:
        # only observations whose first archived vintage IS the archive start are pre-archive; a release
        # delayed inside the archive era (a government shutdown) keeps its real, late vintage
        archive_start = r["realtime_start"].min()
        first = f.groupby("obs_date", as_index=False).first()
        lag_v = Lag.parse(spec.lag).apply_index(first["obs_date"])
        first_v = first["vintage_date"].to_numpy()
        late = (first_v > (lag_v + pd.Timedelta(days=BACKFILL_SLACK_DAYS)).to_numpy()) & (first_v == archive_start)
        if late.any():
            extra = pd.DataFrame({"obs_date": first["obs_date"][late].to_numpy(), "vintage_date": lag_v[late],
                                  "value": first["value"][late].to_numpy()})
            backfilled = len(extra)
            f = pd.concat([extra, f]).sort_values(["obs_date", "vintage_date"], kind="mergesort").drop_duplicates(
                ["obs_date", "vintage_date"], keep="last")
    out = f.loc[:, FRAME_COLUMNS].reset_index(drop=True)
    out.attrs.update(real_vintages=True, backfilled=backfilled, clamped=int(clamped.sum()))
    return out


class FredProvider(BaseProvider):
    name = "fred"

    def __init__(self, http: HttpClient, api_key: str | None) -> None:
        self.http = http
        self.api_key = api_key or None

    def _paginate(self, params: dict[str, str]) -> pd.DataFrame:
        frames, offset = [], 0
        while True:
            raw = self.http.get(API_URL, {**params, "api_key": self.api_key or "", "file_type": "json",
                                          "limit": str(PAGE), "offset": str(offset)})
            df, count = parse_observations(raw)
            frames.append(df)
            offset += len(df)
            if len(df) == 0 or offset >= count:
                break
        return pd.concat(frames, ignore_index=True)

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        code = spec.provider_code
        if self.api_key is None:
            if spec.vintages == "alfred":
                raise DataError(f"{spec.series_id}: ALFRED vintages need FRED_API_KEY; series skipped (never lag-modelled)")
            s = parse_graph_csv(self.http.get(GRAPH_URL, {"id": code}), code)
            f = frame_from_series(s, spec, since)
            f.attrs.update(real_vintages=False, note="no FRED_API_KEY: latest values with lag-model vintages")
            return f
        if spec.vintages == "alfred":
            clip = None if since is None else since
            rows = self._paginate({"series_id": code, "realtime_start": ARCHIVE_START if clip is None else clip.isoformat(),
                                   "realtime_end": ARCHIVE_END, "output_type": "1"})
            return alfred_frame(rows, spec, clip)
        params = {"series_id": code}
        if since is not None:
            params["observation_start"] = (since - timedelta(days=1)).isoformat()
        rows = self._paginate(params)
        s = pd.Series(rows["value"].to_numpy(), index=pd.DatetimeIndex(rows["date"]))
        f = frame_from_series(s, spec, since)
        f.attrs.update(real_vintages=False)
        return f
