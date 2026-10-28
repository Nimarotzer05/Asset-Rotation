"""Round 4 data cycle (ADR 057): the download script keeps raw bytes, records every failure, redacts the key
and reports missing required sources; the French parser reads daily blocks."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from rotationlab.core.errors import DataError
from rotationlab.data.providers.http import FixtureClient
from rotationlab.data.providers.static import read_french_section

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load_script("fetch_research_data")
NOW = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def _api(code: str) -> bytes:
    obs = [
        {"realtime_start": "2026-10-28", "realtime_end": "2026-10-28", "date": "1971-01-04", "value": "1.5"}
    ]
    return json.dumps({"count": 1, "observations": obs, "series": code}).encode()


def test_download_keeps_raw_bytes_and_records_failures(tmp_path) -> None:
    def fred(url: str) -> bytes:
        code = url.split("series_id=")[1].split("&", maxsplit=1)[0]
        if code.startswith("IRSTCI01"):  # optional fallbacks: pretend FRED does not know them
            raise DataError("HTTP 400")
        return _api(code)

    http = FixtureClient({r"api\.stlouisfed\.org": fred, r"ken\.french/ftp/": b"PK-zip-bytes"})
    m = fetch.fetch_all(http, tmp_path, "SECRETKEY", now=lambda: NOW)
    files = m["files"]
    assert fetch.missing_required(m) == []
    ok = files["fred/DEXJPUS"]
    raw = _api("DEXJPUS")
    assert ok["status"] == "ok" and ok["format"] == "fred_api_json" and ok["bytes"] == len(raw)
    assert ok["sha256"] == hashlib.sha256(raw).hexdigest()
    assert gzip.decompress((tmp_path / "fred/DEXJPUS.gz").read_bytes()) == raw  # byte for byte
    assert "SECRETKEY" not in json.dumps(m) and "api_key=***" in ok["url"]
    assert files["fred/IRSTCI01JPM156N"]["status"].startswith("error: HTTP 400")
    assert files["fred/IRSTCI01JPM156N"]["required"] is False
    assert files["french/F-F_International_Countries.zip"]["format"] == "french_zip"
    assert json.loads((tmp_path / "MANIFEST.json").read_text()) == m
    # every source of ADR 057 is listed exactly once
    keys = [s.key for s in fetch.sources()]
    assert len(keys) == len(set(keys)) == 9 + 1 + 3 + 10 + 10 + 2
    required = {s.code: s.required for s in fetch.sources()}
    assert required["DEXGEUS"] is False and required["DEXUSEU"] is True  # ADR 059


def test_missing_required_source_and_fredgraph_fallback(tmp_path) -> None:
    def graph(url: str) -> bytes:
        code = url.split("id=")[1]
        if code == "DGS5":
            raise DataError("HTTP 500 after retries")
        return f"observation_date,{code}\n1971-01-04,1.5\n".encode()

    http = FixtureClient({r"fredgraph\.csv": graph, r"ken\.french/ftp/": b"zip"})
    m = fetch.fetch_all(http, tmp_path, None, now=lambda: NOW)
    assert fetch.missing_required(m) == ["fred/DGS5"]
    assert m["fred_mode"] == "fredgraph" and m["files"]["fred/DGS10"]["format"] == "fredgraph_csv"


def test_multi_page_fred_answer_is_refused(tmp_path) -> None:
    big = json.dumps({"count": 200000, "observations": [{"date": "2000-01-03", "value": "1"}]}).encode()
    http = FixtureClient({r"api\.stlouisfed\.org": big, r"ken\.french/ftp/": b"zip"})
    m = fetch.fetch_all(http, tmp_path, "K", now=lambda: NOW)
    assert "more than one page" in m["files"]["fred/DGS2"]["status"]


def test_french_daily_block_is_read_and_the_monthly_one_unchanged() -> None:
    daily = (
        "header\n\n  Average Value Weighted Returns -- Daily\n,NoDur,Hlth \n"
        "19260701,   0.12,  -99.99\n19260702,   0.20,   0.30\n\n"
        "  Average Equal Weighted Returns -- Daily\n,NoDur,Hlth \n19260701,   9.99,   9.99\n"
    )
    d = read_french_section(daily, "Value Weighted Returns -- Daily")
    assert list(d.columns) == ["NoDur", "Hlth"] and len(d) == 2
    assert str(d.index[0].date()) == "1926-07-01" and d.iloc[0, 0] == pytest.approx(0.0012)
    assert d.iloc[0].isna().tolist() == [False, True]  # -99.99 = missing
    monthly = "x\n,Mkt-RF,RF\n192607,    2.96,    0.22\n192608,    2.64,    0.25\n\n Annual\n,Mkt-RF,RF\n  1927,   29.47,    3.12\n"
    m = read_french_section(monthly)
    assert [str(i.date()) for i in m.index] == ["1926-07-31", "1926-08-31"] and m.iloc[1, 1] == pytest.approx(
        0.0025
    )


freeze = _load_script("freeze_research_data")


def _daily_zip() -> bytes:
    import io
    import zipfile

    cols = ["NoDur", "Durbl", "Manuf", "Enrgy", "HiTec", "Telcm", "Shops", "Hlth ", "Utils", "Other"]
    head = (
        "created by CMPT_IND_RETS_DAILY\n\n  Average Value Weighted Returns -- Daily\n,"
        + ",".join(cols)
        + "\n"
    )
    rows = "".join(f"1926070{d},{','.join(['   0.10'] * 10)}\n" for d in (1, 2, 6))
    tail = (
        "\n  Average Equal Weighted Returns -- Daily\n,"
        + ",".join(cols)
        + "\n19260701,"
        + ",".join(["9"] * 10)
        + "\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("10_Industry_Portfolios_Daily.csv", head + rows + tail)
    return buf.getvalue()


def _fred_api(url: str) -> bytes:
    code = url.split("series_id=")[1].split("&", maxsplit=1)[0]
    monthly = code.startswith(("IR3TIB01", "IRSTCI01"))
    dates = ["1971-01-01", "1971-02-01"] if monthly else ["1971-01-04", "1971-01-05", "1971-01-06"]
    obs = [
        {
            "realtime_start": "2026-10-28",
            "realtime_end": "2026-10-28",
            "date": d,
            "value": "." if i == 1 and not monthly else "2.5",
        }
        for i, d in enumerate(dates)
    ]
    return json.dumps({"count": len(obs), "observations": obs}).encode()


def test_freeze_verifies_checksums_and_writes_compact_files(tmp_path) -> None:
    src = tmp_path / "branch"
    http = FixtureClient(
        {
            r"api\.stlouisfed\.org": _fred_api,
            r"10_Industry_Portfolios_daily": _daily_zip(),
            r"International": b"zip",
        }
    )
    fetch.fetch_all(http, src / "research_data", "K", now=lambda: NOW)
    out = tmp_path / "raw"
    prov = freeze.freeze(src, "abc123", out, countries=False)
    o = prov["outputs"]
    assert o["fred_daily"]["rows"] == 2 and "DEXJPUS" in o["fred_daily"]["columns"]  # '.' (holiday) dropped
    assert o["oecd_rates_monthly"]["first"] == "1971-01-31"  # FRED's first-of-month label → month-end
    ind = pd.read_csv(out / "ff_10_industry_daily.csv.gz", index_col=0, parse_dates=True)
    assert list(ind.columns)[7] == "Hlth" and ind.iloc[0, 0] == pytest.approx(0.001) and len(ind) == 3
    assert json.loads((out / "r4_PROVENANCE.json").read_text())["commit"] == "abc123"
    again = freeze.freeze(src, "abc123", tmp_path / "raw2", countries=False)  # deterministic bytes
    assert again["outputs"] == o
    p = src / "research_data" / "fred" / "DGS5.gz"  # one flipped byte in a raw file stops the freeze
    p.write_bytes(gzip.compress(gzip.decompress(p.read_bytes()).replace(b"2.5", b"2.6")))
    with pytest.raises(DataError, match="checksum"):
        freeze.freeze(src, "abc123", out, countries=False)


def test_freeze_refuses_a_branch_with_a_missing_required_source(tmp_path) -> None:
    src = tmp_path / "branch"

    def no_french(url: str) -> bytes:
        raise DataError("HTTP 404")

    http = FixtureClient({r"api\.stlouisfed\.org": _fred_api, r"ken\.french": no_french})
    fetch.fetch_all(http, src / "research_data", "K", now=lambda: NOW)
    with pytest.raises(DataError, match="required sources missing"):
        freeze.freeze(src, "abc", tmp_path / "raw", countries=False)


def _country_member(first: str, months: list[tuple[str, str]]) -> str:
    """One `<Country>.Dat` in the layout seen on 2026-10-28: dollar block (broader group) first, then local."""
    head = (
        "\n     Value-Weight Dollar Returns      All 4 Data Items Not Reqd\n"
        "                -- BE/ME --   --- E/P ---   --- CE/P --   ------  Yld  -----\n"
        "          Mkt   High    Low   High    Low   High    Low   High    Low   Zero\n"
    )
    body = "".join(
        f"   {ym} {mkt:>6}  1.00   1.00   1.00   1.00   1.00   1.00   1.00   1.00 -99.99\n"
        for ym, mkt in months
    )
    local = head.replace("Dollar", "Local ") + body.replace("  1.00", "  9.99")
    annual = "\n1975 111.57  1.0\n\nAverage of Annual Value-Weight Averages\n     Firms    B/M\n1975   179 219.86\n"
    return first + head + body + "\n" + local + annual


def _country_zip(members: dict[str, str]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in members.items():
            z.writestr(n, t)
    return buf.getvalue()


def test_country_parser_takes_the_dollar_market_column_of_every_member() -> None:
    months = [
        (f"{y}{m:02d}", "54.90" if (y, m) == (1975, 1) else "-99.99" if (y, m) == (1975, 3) else "1.50")
        for y in (1975, 1976, 1977)
        for m in range(1, 13)
    ]
    raw = _country_zip(
        {
            "UK.Dat": _country_member("", months),
            "Swtzrlnd.Dat": _country_member("", months[12:]),
            "US.Dat": _country_member("", months),  # a United States member is left out (EQ_US is its sleeve)
        }
    )
    df = freeze.parse_international_countries(raw)
    assert list(df.columns) == ["UK", "Switzerland"]  # zip order, abbreviations expanded, no US
    assert df.index[0] == pd.Timestamp("1975-01-31") and len(df) == 36
    assert df["UK"].iloc[0] == pytest.approx(0.549) and pd.isna(
        df["UK"].iloc[2]
    )  # percent → decimal, -99.99 → NaN
    assert df["UK"].iloc[1] == pytest.approx(0.015) and pd.isna(df["Switzerland"].iloc[0])  # entry by data
    assert df["Switzerland"].iloc[12] == pytest.approx(0.015)
    with pytest.raises(DataError, match="Mkt"):
        freeze.parse_international_countries(
            _country_zip({"X.Dat": _country_member("", months).replace("Mkt ", "Mky ")})
        )
    with pytest.raises(DataError, match="block"):
        freeze.parse_international_countries(_country_zip({"X.Dat": "no header\n"}))
