"""Kenneth French Data Library: zipped CSV files, one download per file and run.

Series ids ``french:<group>:<NAME>`` with ``params.file`` (zip name), ``params.column`` and optional
``params.section`` (header line that precedes the wanted monthly block). Returns are decimals.
Vintage = obs_date (returns of public portfolios, ADR 022); French revises history when CRSP
updates – the store records those as revisions with today's vintage.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd

from rotationlab.core.errors import DataError
from rotationlab.core.types import SeriesSpec
from rotationlab.data.providers.base import BaseProvider, empty_frame, frame_from_series
from rotationlab.data.providers.http import HttpClient
from rotationlab.data.providers.static import read_french_section

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"


def unzip_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise DataError("french: zip contains no CSV")
        return z.read(names[0]).decode("latin-1")


class FrenchProvider(BaseProvider):
    name = "french"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._text: dict[str, str] = {}

    def fetch_frame(self, spec: SeriesSpec, since: date | None) -> pd.DataFrame:
        p = dict(spec.params)
        file, column = p.get("file"), p.get("column")
        if not file or not column:
            raise DataError(f"{spec.series_id}: params.file and params.column are required")
        if file not in self._text:
            self._text[file] = unzip_text(self.http.get(BASE_URL + file))
        df = read_french_section(self._text[file], p.get("section") or None)
        if column not in df.columns:
            raise DataError(f"{spec.series_id}: column '{column}' not in {file} ({list(df.columns)})")
        s = df[column].dropna()
        return empty_frame() if s.empty else frame_from_series(s, spec, since)
