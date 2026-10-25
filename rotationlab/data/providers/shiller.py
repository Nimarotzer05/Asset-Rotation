"""Robert Shiller's ``ie_data.xls``: S&P price, dividends, earnings, CPI, 10y rate and CAPE, monthly since 1871.

The GitHub mirror in ``data/raw`` stops reporting earnings in 2023-06, so a live CAPE / excess CAPE
yield needs the original workbook. Layout (sheet ``Data``): a few title rows, then a header row with
``Date, P, D, E, CPI, Date Fraction, Rate GS10, …, CAPE``; dates are floats ``YYYY.MM`` where October
is written ``1871.1`` – parsed with two decimals, never as a fraction of the year.

Series ids ``shiller:<P|D|E|CPI|GS10|CAPE>``; lags as in the static copy (ADR 022, audit 2026-10-24):
price and rate ``0D``, CPI ``1M``, dividends, earnings and CAPE ``6M`` (quarterly figures interpolated).
Needs ``xlrd`` (legacy .xls). Source URLs are configurable (``providers.shiller.urls``), tried in order.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series
from rotationlab.data.providers.http import HttpClient

DEFAULT_URLS = ("http://www.econ.yale.edu/~shiller/data/ie_data.xls",)
COLUMNS = {"P": "P", "D": "D", "E": "E", "CPI": "CPI", "GS10": "Rate GS10", "CAPE": "CAPE"}


def shiller_date(x: object) -> pd.Timestamp | None:
    """1871.01 → 1871-01, 1871.1 → 1871-10 (the workbook's convention), month-end."""
    try:
        f = float(str(x))
    except ValueError:
        return None
    if not np.isfinite(f):
        return None
    year, month = divmod(round(f * 100), 100)
    if not 1 <= month <= 12:
        return None
    return pd.Timestamp(int(year), int(month), 1) + pd.offsets.MonthEnd(0)


def parse_workbook(raw: bytes) -> pd.DataFrame:
    """Workbook bytes → monthly frame with columns P, D, E, CPI, GS10, CAPE (missing → NaN)."""
    try:
        sheet = pd.read_excel(io.BytesIO(raw), sheet_name="Data", header=None, engine="xlrd")
    except Exception as e:  # xlrd raises its own error types for non-xls content
        raise DataError(f"shiller: cannot read workbook ({e})") from e
    header_row = None
    for i in range(min(30, len(sheet))):
        cells = [str(c).strip() for c in sheet.iloc[i].tolist()]
        if "Date" in cells and "P" in cells and "E" in cells:
            header_row = i
            break
    if header_row is None:
        raise DataError("shiller: header row with Date, P, E not found")
    names = [str(c).strip() for c in sheet.iloc[header_row].tolist()]
    body = sheet.iloc[header_row + 1 :].copy().set_axis(names, axis=1)
    idx = [shiller_date(x) for x in body["Date"]]
    keep = [i for i, t in enumerate(idx) if t is not None]
    body = body.iloc[keep]
    out = pd.DataFrame(index=pd.DatetimeIndex([idx[i] for i in keep]))
    for key, col in COLUMNS.items():
        out[key] = pd.to_numeric(body[col], errors="coerce").to_numpy() if col in body.columns else np.nan
    return out[~out.index.duplicated(keep="last")].sort_index()


class ShillerProvider(BaseProvider):
    name = "shiller"

    def __init__(self, http: HttpClient, urls: Sequence[str] = DEFAULT_URLS) -> None:
        self.http = http
        self.urls = list(urls) or list(DEFAULT_URLS)
        self._frame: pd.DataFrame | None = None

    def _workbook(self) -> pd.DataFrame:
        if self._frame is None:
            errors = []
            for url in self.urls:
                try:
                    self._frame = parse_workbook(self.http.get(url))
                    break
                except DataError as e:
                    errors.append(f"{url}: {e}")
            if self._frame is None:
                raise DataError("shiller: no source answered – " + "; ".join(errors))
        return self._frame

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        key = spec.provider_code
        if key not in COLUMNS:
            raise DataError(f"shiller: unknown field {key} (use {', '.join(COLUMNS)})")
        s = self._workbook()[key].dropna()
        s = s[s != 0]  # the workbook leaves future months empty or zero
        return empty_frame() if s.empty else frame_from_series(s, spec, since)
