"""Data health over time: what the daily quality checks add up to (``rotationlab store health``).

A single run says whether today's data can be used. The trend says whether a provider is slowly
degrading: more fetch errors, more late arrivals, more revisions, more stale series. This module
condenses ``ingest_log.csv`` and ``quality_log.csv`` of the last N days into a short markdown report
(Phase 4 attaches it to the weekly Telegram summary).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from rotationlab.data.store import PointInTimeStore

NUMERIC = ("fetched", "new", "revised", "late", "rejected", "seconds")


def _cell(v: object) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int | float):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return str(v)


def _md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_keine Einträge_"
    cols = [str(c) for c in df.columns]
    head = "| " + " | ".join([str(df.index.name or ""), *cols]) + " |"
    sep = "|" + "---|" * (len(cols) + 1)
    rows = []
    for idx, r in df.iterrows():
        cells = [_cell(v) for v in r.tolist()]
        rows.append("| " + " | ".join([str(idx), *cells]) + " |")
    return "\n".join([head, sep, *rows])


def health_tables(store: PointInTimeStore, today: date, days: int = 30) -> dict[str, pd.DataFrame]:
    since = pd.Timestamp(today - timedelta(days=days))
    ing = store.read_log("ingest_log")
    ql = store.read_log("quality_log")
    out: dict[str, pd.DataFrame] = {}
    if not ing.empty:
        ing = ing[pd.to_datetime(ing["run_date"]) > since].copy()
        for c in NUMERIC:
            if c in ing.columns:
                ing[c] = pd.to_numeric(ing[c], errors="coerce").fillna(0)
        ing["fetch_error"] = ing["error"].fillna("").astype(str).str.len() > 0
        agg = {"runs": ("ingested_at", "nunique"), "series": ("series_id", "nunique"), "fetch_errors": ("fetch_error", "sum")}
        agg.update({c: (c, "sum") for c in ("new", "revised", "late", "rejected") if c in ing.columns})
        if "seconds" in ing.columns:
            agg["seconds_per_series"] = ("seconds", "mean")
        out["providers"] = ing.groupby("provider").agg(**agg)
    if not ql.empty:
        ql = ql[pd.to_datetime(ql["ingested_at"].str[:10]) > since]
        bad = ql[ql["status"].isin(["warn", "blocking"])]
        out["checks"] = bad.pivot_table(index="check", columns="status", values="series_id", aggfunc="count", fill_value=0)
        worst = bad.assign(series_id=bad["series_id"].replace("", "-")).groupby("series_id").size()
        out["series"] = worst.sort_values(ascending=False).head(10).rename("findings").to_frame()
        last_run = ql["ingested_at"].max() if len(ql) else None
        out["open"] = bad[bad["ingested_at"] == last_run][["series_id", "check", "status", "detail"]].set_index("series_id")
    return out


def health_report(store: PointInTimeStore, today: date, days: int = 30) -> str:
    t = health_tables(store, today, days)
    lines = [f"# Datenqualität der letzten {days} Tage (Stand {today})", "",
             f"Store-Stand `{store.snapshot_id()}`.", ""]
    sections = [("Provider", "providers", "Läufe, abgerufene Reihen, Abruffehler, neue/revidierte/verspätete/abgewiesene Werte."),
                ("Befunde je Check", "checks", "Warnungen und blockierende Ergebnisse."),
                ("Reihen mit den meisten Befunden", "series", ""),
                ("Offen im letzten Lauf", "open", "Was beim letzten Ingest nicht in Ordnung war.")]
    for title, key, note in sections:
        lines += [f"## {title}", ""] + ([note, ""] if note else []) + [_md(t.get(key, pd.DataFrame())), ""]
    return "\n".join(lines)
