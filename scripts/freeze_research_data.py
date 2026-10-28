"""Freeze a pinned commit of branch `research-data` into data/raw (ADR 057), verified against its manifest.

Input: a checkout of the branch (folder that contains research_data/MANIFEST.json) and the commit SHA. Every
file is checked against the SHA-256 the download recorded; a mismatch or a missing required source stops the
freeze. Outputs (compact, deterministic, the raw files stay on the branch for provenance):

    data/raw/r4_fred_daily.csv.gz          H.10 spot rates (as FRED quotes them) and CMT yields (percent), daily
    data/raw/r4_oecd_rates_monthly.csv.gz  OECD 3-month interbank and call money rates (percent, monthly)
    data/raw/ff_10_industry_daily.csv.gz   French 10 industries, value-weighted daily returns (decimals)
    data/raw/ff_intl_countries_monthly.csv.gz  French country market returns (decimals, monthly) – see
                                           `parse_international_countries`
    data/raw/r4_PROVENANCE.json            commit, manifest, and per output: rows, first/last date, SHA-256

Which commit (ADR 058): the earliest commit of branch `research-data` whose manifest has every required source –
a later download is never chosen because its data look different. The countries enter by rule, not by choice:
every country column of the file in its order (ADR 057 a), a United States column left out (the US equity sleeve
is EQ_US), and per country the market return `Mkt` with dividends of the broader portfolio group (all firms with
B/M data – the group that reports `Firms`), or the only market column if there is one (ADR 058 c).

Aufruf: python scripts/freeze_research_data.py --src <checkout> --commit <sha> [--out data/raw]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.core.errors import DataError  # noqa: E402
from rotationlab.data.providers.fred import parse_graph_csv, parse_observations  # noqa: E402
from rotationlab.data.providers.french import unzip_text  # noqa: E402
from rotationlab.data.providers.static import read_french_section  # noqa: E402

DAILY_SECTION = "Average Value Weighted Returns -- Daily"


def load_manifest(src: Path) -> dict:  # type: ignore[type-arg]
    path = src / "research_data" / "MANIFEST.json"
    if not path.exists():
        raise DataError(f"{path} not found – is --src a checkout of branch research-data?")
    doc: dict = json.loads(path.read_text())  # type: ignore[type-arg]
    return doc


def raw_bytes(src: Path, key: str, entry: dict) -> bytes:  # type: ignore[type-arg]
    """The verified raw bytes of one manifest entry."""
    raw = gzip.decompress((src / "research_data" / entry["file"]).read_bytes())
    if hashlib.sha256(raw).hexdigest() != entry["sha256"] or len(raw) != entry["bytes"]:
        raise DataError(f"{key}: checksum or size differs from the manifest")
    return raw


def fred_series(raw: bytes, entry: dict) -> pd.Series:  # type: ignore[type-arg]
    code = str(entry["code"])
    if entry["format"] == "fred_api_json":
        rows, _ = parse_observations(raw)
        s = pd.Series(rows["value"].to_numpy(), index=pd.DatetimeIndex(rows["date"]), name=code)
        return s.dropna()
    if entry["format"] == "fredgraph_csv":
        return parse_graph_csv(raw, code)
    raise DataError(f"{code}: unknown format {entry['format']}")


def parse_industries_daily(raw: bytes) -> pd.DataFrame:
    df = read_french_section(unzip_text(raw), DAILY_SECTION)
    if df.empty or len(df.columns) != 10:
        raise DataError(f"10 industries daily: unexpected block ({df.shape})")
    return df


def describe_zip(raw: bytes, lines: int = 12) -> str:
    """Members and the first lines of each – what to look at before writing a parser for an unknown layout."""
    out = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for n in z.namelist():
            text = z.read(n).decode("latin-1", errors="replace").splitlines()
            out.append(f"== {n} ({len(text)} lines)")
            out += [f"   {t[:160]}" for t in text[:lines]]
    return "\n".join(out)


def parse_international_countries(raw: bytes) -> pd.DataFrame:
    """Country market returns from F-F_International_Countries.zip (rule in the module docstring, ADR 058 c). The
    Data Library does not document the layout; the parser is written against the downloaded file and its first
    lines are printed by `describe_zip` when this raises (ADR 057 h: without a market column with dividends in
    USD the country sleeve is dropped – the dollar test is gate G5 of scripts/r4_data_check.py)."""
    raise NotImplementedError(
        "layout of F-F_International_Countries.zip not inspected yet:\n" + describe_zip(raw)
    )


def write_csv(df: pd.DataFrame, path: Path) -> dict[str, object]:
    df = df.sort_index()
    df.index.name = "date"
    text = df.to_csv(float_format="%.10g", date_format="%Y-%m-%d")
    path.write_bytes(gzip.compress(text.encode(), mtime=0))
    return {
        "file": path.name,
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "first": str(df.index.min().date()) if len(df) else None,
        "last": str(df.index.max().date()) if len(df) else None,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def freeze(src: Path, commit: str, out: Path, countries: bool = True) -> dict[str, object]:
    manifest = load_manifest(src)
    files = manifest["files"]
    missing = sorted(k for k, v in files.items() if v["required"] and v["status"] != "ok")
    if missing:
        raise DataError(f"required sources missing on research-data@{commit[:12]}: {missing}")
    daily, monthly = {}, {}
    for key, e in sorted(files.items()):
        if e["kind"] != "fred" or e["status"] != "ok":
            continue
        s = fred_series(raw_bytes(src, key, e), e)
        (monthly if str(e["code"]).startswith(("IR3TIB01", "IRSTCI01")) else daily)[str(e["code"])] = s
    out.mkdir(parents=True, exist_ok=True)
    prov: dict[str, object] = {
        "adr": "057",
        "branch": "research-data",
        "commit": commit,
        "manifest": manifest,
    }
    outputs: dict[str, object] = {}
    outputs["fred_daily"] = write_csv(pd.DataFrame(daily), out / "r4_fred_daily.csv.gz")
    mdf = pd.DataFrame(monthly)
    mdf.index = mdf.index + pd.offsets.MonthEnd(
        0
    )  # FRED dates monthly values on the 1st: label the month-end
    outputs["oecd_rates_monthly"] = write_csv(mdf, out / "r4_oecd_rates_monthly.csv.gz")
    k = "french/10_Industry_Portfolios_daily_CSV.zip"
    outputs["industries_daily"] = write_csv(
        parse_industries_daily(raw_bytes(src, k, files[k])), out / "ff_10_industry_daily.csv.gz"
    )
    if countries:
        k = "french/F-F_International_Countries.zip"
        outputs["countries_monthly"] = write_csv(
            parse_international_countries(raw_bytes(src, k, files[k])),
            out / "ff_intl_countries_monthly.csv.gz",
        )
    prov["outputs"] = outputs
    (out / "r4_PROVENANCE.json").write_text(json.dumps(prov, indent=1, sort_keys=True) + "\n")
    return prov


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument(
        "--describe", action="store_true", help="print the layout of the French country zip and stop"
    )
    args = ap.parse_args()
    src = Path(args.src)
    if args.describe:
        m = load_manifest(src)
        k = "french/F-F_International_Countries.zip"
        print(describe_zip(raw_bytes(src, k, m["files"][k])))
        return 0
    prov = freeze(src, args.commit, Path(args.out))
    for name, o in dict(prov["outputs"]).items():  # type: ignore[call-overload]
        print(f"{name}: {o['rows']} rows {o['first']} … {o['last']} ({len(o['columns'])} columns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
