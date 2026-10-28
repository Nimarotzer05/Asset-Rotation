"""P5 input: a frozen month-end snapshot of the live store (branch `data` of the GitHub repo).

Reads the observation files of a live store (Yahoo ETFs/futures, FRED daily yields) and writes
data/raw/p5_live_monthend.csv.gz with one month-end value per series: the last daily close of the month
(latest vintage per observation), total-return indices for ETFs with dividends (closes plus cash
dividends, `rotationlab.data.view._close_tr`), and the month-end 10-year constant-maturity yield (DGS10).
The snapshot is the reproducible input of scripts/forecast_investability.py.

Aufruf: python scripts/p5_extract_live_monthend.py --store /path/to/data/store
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.data.view import _close_tr  # noqa: E402

CLOSES = ["SPY", "IEF", "TLT", "GLD", "SLV", "USO", "DBC", "CPER", "UNG", "CL=F", "HG=F", "GC=F", "SI=F"]
WITH_DIVIDENDS = ["SPY", "IEF", "TLT"]
OUT = os.path.join(ROOT, "data", "raw", "p5_live_monthend.csv.gz")


def latest_vintage(df: pd.DataFrame, sid: str) -> pd.Series:
    s = df[df["series_id"] == sid].sort_values(["obs_date", "vintage_date"])
    s = s.drop_duplicates("obs_date", keep="last")
    return pd.Series(s["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(s["obs_date"])).sort_index()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="path of the live data/store directory")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.store, "observations", "*.csv.gz")))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["vintage_date"] = pd.to_datetime(df["vintage_date"])
    out = {}
    for t in CLOSES:
        px = latest_vintage(df, f"yahoo:{t}:close")
        if px.empty:
            print(f"missing yahoo:{t}:close")
            continue
        if t in WITH_DIVIDENDS:
            div = latest_vintage(df, f"yahoo:{t}:dividend")
            out[f"{t}_TR"] = _close_tr(px, div).resample("ME").last()
        out[f"{t}_CLOSE"] = px.resample("ME").last()
    for code in (
        "DGS10",
        "DGS2",
        "DGS3MO",
    ):  # month-end CMT yields (ADR 047: DGS10; ADR 052: DGS2 for UST2_ME)
        out[f"{code}_ME"] = latest_vintage(df, f"fred:{code}").resample("ME").last()
    frame = pd.DataFrame(out)
    # the running month is not a month-end: its last close must not be labelled as if the month were complete.
    # A month counts as complete only when *every* extracted series has reached its month-end (FRED's DGS10
    # arrives a day after the Yahoo closes: on a month-end evening the yield of the last session is not in yet)
    used = [f"yahoo:{t}:close" for t in CLOSES] + ["fred:DGS10", "fred:DGS2", "fred:DGS3MO"]
    last_obs = df[df["series_id"].isin(used)].groupby("series_id")["obs_date"].max().min()
    complete_through = (
        last_obs if last_obs == last_obs + pd.offsets.MonthEnd(0) else last_obs - pd.offsets.MonthEnd(1)
    )
    frame = frame[frame.index <= complete_through]
    frame.index.name = "month_end"
    frame.to_csv(OUT, float_format="%.10g")
    print(f"wrote {OUT}: {frame.shape[0]} months, columns {list(frame.columns)}")
    print(frame.notna().idxmax().to_string())


if __name__ == "__main__":
    main()
