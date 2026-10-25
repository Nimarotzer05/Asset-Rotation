"""Real-time FRED-MD from genuine archived vintages (2019-09, 2021-04, 2026-10) and the archive download."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from rotationlab.data.providers.fredmd_archive import fetch_archive, vintage_date, zip_members
from rotationlab.data.providers.http import FixtureClient
from rotationlab.data.providers.static import STATIC_CATALOG, StaticProvider

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


def vintage(label: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / "fredmd_vintages" / f"{label}.csv", skiprows=[1]).dropna(subset=["sasdate"])
    df.index = pd.to_datetime(df.pop("sasdate"), format="%m/%d/%Y") + pd.offsets.MonthEnd(0)
    return df.apply(pd.to_numeric, errors="coerce")


def test_manifest_lists_three_genuine_vintages() -> None:
    v = StaticProvider(RAW).vintages()
    assert [e["label"] for e in v] == ["2019-09", "2021-04", "2026-10"]
    assert all(e["vintage_date"] > pd.Timestamp(f"{e['label']}-01") for e in v)


def test_realtime_series_show_what_each_vintage_said(static_factory) -> None:
    v19, v21 = vintage("2019-09"), vintage("2021-04")
    assert (
        static_factory.at(date(2019, 10, 6)).series("static:fredmd_rt:CPIAUCSL").empty
    )  # archive not yet there
    s = static_factory.at(date(2019, 10, 7)).series("static:fredmd_rt:CPIAUCSL")
    assert s.index[-1] == pd.Timestamp("2019-08-31")
    assert s.loc["2016-06-30"] == v19.loc["2016-06-30", "CPIAUCSL"]
    later = static_factory.at(date(2021, 5, 7)).series("static:fredmd_rt:CPIAUCSL")
    assert later.loc["2016-06-30"] == v21.loc["2016-06-30", "CPIAUCSL"]
    assert v19.loc["2016-06-30", "CPIAUCSL"] != v21.loc["2016-06-30", "CPIAUCSL"]  # a real seasonal revision
    assert (
        static_factory.at(date(2021, 5, 6)).series("static:fredmd_rt:CPIAUCSL").loc["2016-06-30"]
        == v19.loc["2016-06-30", "CPIAUCSL"]
    )


def test_one_row_per_change() -> None:
    f = StaticProvider(RAW).fetch_frame(STATIC_CATALOG["static:fredmd_rt:CPIAUCSL"].spec, None)
    v19, v21, v26 = (vintage(x)["CPIAUCSL"].dropna() for x in ("2019-09", "2021-04", "2026-10"))

    def changes(old: pd.Series, new: pd.Series) -> int:
        common = old.index.intersection(new.index)
        return int((new[common] != old[common]).sum()) + len(new.index.difference(old.index))

    expected = len(v19) + changes(v19, v21) + changes(v21, v26)
    assert len(f) == expected and f.attrs["real_vintages"] is True
    assert (f["vintage_date"] >= f["obs_date"]).all()


def test_realtime_and_research_series_never_mix(static_store) -> None:
    research = static_store.series_rows("static:fredmd:CPIAUCSL")
    assert research["vintage_date"].sub(research["obs_date"]).dt.days.max() <= 31  # lag model only
    rt = static_store.series_rows("static:fredmd_rt:CPIAUCSL")
    assert set(rt["vintage_date"].dt.date) <= {date(2019, 10, 7), date(2021, 5, 7), date(2026, 10, 10)}


def test_vintage_dates_are_conservative() -> None:
    assert vintage_date("2021-04") == date(2021, 5, 7)
    assert vintage_date("1999-12") == date(2000, 1, 7)


def test_fetch_archive_offline(tmp_path) -> None:
    csv = (RAW / "fredmd_vintages" / "2021-04.csv").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Historical FRED-MD Vintages/1999-08.csv", csv)
        z.writestr("Historical FRED-MD Vintages/1999-09.csv", csv)
    routes = {
        r"historical_fred-md\.zip": buf.getvalue(),
        r"monthly/2015-01-md\.csv": csv,
        r"monthly/2015-02\.csv": csv,  # older URL pattern
        r"monthly/2015-03": b"<html>moved</html>",  # not a FRED-MD file
    }
    http = FixtureClient(routes)
    raw = tmp_path / "raw"
    rep = fetch_archive(http, raw, start="1999-08", end="2015-03", log=lambda m: None)
    assert rep.added == ["1999-08", "1999-09", "2015-01", "2015-02"]
    assert "2015-03" in rep.missing and len(rep.missing) == 188 - 4
    m = yaml.safe_load((raw / "fredmd_vintages" / "vintages.yaml").read_text())
    assert [e["label"] for e in m["vintages"]] == ["1999-08", "1999-09", "2015-01", "2015-02"]
    assert m["vintages"][2]["source"].endswith("2015-01-md.csv")
    again = fetch_archive(FixtureClient(routes), raw, start="2015-01", end="2015-02", log=lambda m: None)
    assert again.added == [] and set(again.skipped) >= {"2015-01", "2015-02"}  # never overwritten
    assert [e["label"] for e in StaticProvider(raw).vintages()][:2] == ["1999-08", "1999-09"]


def test_zip_members_ignores_other_files() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a/2003-05.csv", b"sasdate,X\n")
        z.writestr("a/readme.txt", b"x")
        z.writestr("2004-01-md.csv", b"sasdate,X\n")
    assert sorted(zip_members(buf.getvalue())) == ["2003-05", "2004-01"]


@pytest.mark.parametrize("code", ["INDPRO", "PAYEMS", "UNRATE", "SP500"])
def test_every_realtime_series_is_in_the_catalog(code) -> None:
    assert f"static:fredmd_rt:{code}" in STATIC_CATALOG
