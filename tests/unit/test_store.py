"""Point-in-time store: diffing, commits, integrity, compaction."""

from __future__ import annotations

import gzip
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from rotationlab.core.errors import DataError
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.pit import PitIndex
from rotationlab.data.store import PointInTimeStore, utc_stamp
from rotationlab.data.view import as_of_pandas

PX = SeriesSpec(
    SeriesId("yahoo:XYZ:close"),
    "yahoo",
    "XYZ:close",
    SeriesKind.PRICE,
    Frequency.DAILY,
    revision_tolerance=1e-6,
)
CPI = SeriesSpec(
    SeriesId("fred:CPI"), "fred", "CPI", SeriesKind.MACRO, Frequency.MONTHLY, lag="1M", vintages="alfred"
)


def frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "obs_date": pd.to_datetime([r[0] for r in rows]),
            "vintage_date": pd.to_datetime([r[1] for r in rows]),
            "value": [r[2] for r in rows],
        }
    )


def ingest(
    store: PointInTimeStore,
    spec: SeriesSpec,
    f: pd.DataFrame,
    today: date,
    real: bool = False,
    stamp: str | None = None,
):
    d = store.diff(spec, f, today, real_vintages=real)
    store.commit(
        d.rows, stamp or utc_stamp(), series_state={spec.series_id: {"last_fetch": today.isoformat()}}
    )
    return d


@pytest.fixture(params=["memory", "disk"])
def store(request, tmp_path) -> PointInTimeStore:
    return PointInTimeStore(None if request.param == "memory" else tmp_path / "store")


def test_new_unchanged_revision_lag_model(store: PointInTimeStore) -> None:
    f1 = frame([("2026-01-05", "2026-01-05", 100.0), ("2026-01-06", "2026-01-06", 101.0)])
    d1 = ingest(store, PX, f1, date(2026, 1, 7), stamp="2026-01-07T06:30:00Z")
    assert (d1.new, d1.revised, d1.unchanged) == (2, 0, 0)
    # refetch: one value jitters below tolerance, one is revised, one is new
    f2 = frame(
        [
            ("2026-01-05", "2026-01-05", 100.00001),
            ("2026-01-06", "2026-01-06", 102.0),
            ("2026-01-07", "2026-01-07", 103.0),
        ]
    )
    d2 = ingest(store, PX, f2, date(2026, 1, 8), stamp="2026-01-08T06:30:00Z")
    assert (d2.new, d2.revised, d2.unchanged) == (1, 1, 1)
    rev = d2.rows[d2.rows["obs_date"] == pd.Timestamp("2026-01-06")].iloc[0]
    assert rev["vintage_date"] == pd.Timestamp("2026-01-08")  # revision known from the ingest date on
    obs = store.observations()
    assert len(obs) == 4
    # the past is preserved: as of Jan 7 the old value, as of Jan 8 the new one
    idx = PitIndex(obs)
    assert idx.as_of(PX.series_id, pd.Timestamp("2026-01-07")).loc["2026-01-06"] == 101.0
    assert idx.as_of(PX.series_id, pd.Timestamp("2026-01-08")).loc["2026-01-06"] == 102.0


def test_revision_before_visibility_overwrites_same_key(store: PointInTimeStore) -> None:
    """A lag-model value revised before its own vintage date replaces the row (nobody could see it yet)."""
    spec = SeriesSpec(SeriesId("fred:X"), "fred", "X", SeriesKind.MACRO, Frequency.MONTHLY, lag="1M")
    ingest(
        store,
        spec,
        frame([("2026-09-30", "2026-10-31", 1.0)]),
        date(2026, 10, 20),
        stamp="2026-10-20T06:30:00Z",
    )
    d = ingest(
        store,
        spec,
        frame([("2026-09-30", "2026-10-31", 1.5)]),
        date(2026, 10, 25),
        stamp="2026-10-25T06:30:00Z",
    )
    assert d.revised == 1 and d.rows["vintage_date"].iloc[0] == pd.Timestamp("2026-10-31")
    obs = store.observations()
    assert len(obs) == 1 and obs["value"].iloc[0] == 1.5


def test_late_arrivals_are_dated_on_arrival_but_initial_history_is_not(store: PointInTimeStore) -> None:
    hist = frame([("2026-01-05", "2026-01-05", 100.0), ("2026-01-07", "2026-01-07", 102.0)])
    first = ingest(store, PX, hist, date(2026, 3, 1))  # initial load weeks later: history
    assert first.late == 0 and first.rows["vintage_date"].tolist() == list(
        pd.to_datetime(["2026-01-05", "2026-01-07"])
    )
    fill = frame([("2026-01-06", "2026-01-06", 101.0), ("2026-02-27", "2026-02-27", 103.0)])
    d = ingest(store, PX, fill, date(2026, 3, 2))
    v = dict(zip(d.rows["obs_date"], d.rows["vintage_date"], strict=True))
    assert v[pd.Timestamp("2026-01-06")] == pd.Timestamp("2026-03-02") and d.late == 1  # gap filled late
    assert v[pd.Timestamp("2026-02-27")] == pd.Timestamp("2026-02-27")  # within tolerance


def test_real_vintages_are_idempotent(store: PointInTimeStore) -> None:
    f = frame(
        [
            ("2026-08-31", "2026-09-11", 320.0),
            ("2026-08-31", "2026-10-15", 320.4),
            ("2026-09-30", "2026-10-15", 321.0),
        ]
    )
    assert ingest(store, CPI, f, date(2026, 10, 20), real=True).new == 3
    again = ingest(store, CPI, f, date(2026, 10, 21), real=True)
    assert (again.new, again.revised, again.unchanged) == (0, 0, 3)
    assert len(store.observations()) == 3


def test_float_round_trip_is_exact(tmp_path) -> None:
    store = PointInTimeStore(tmp_path / "s")
    vals = [1 / 3, np.pi * 1e6, 1e-12, 123456789.123456789, 0.1 + 0.2]
    f = frame([(f"2026-01-{i + 5:02d}", f"2026-01-{i + 5:02d}", v) for i, v in enumerate(vals)])
    ingest(store, PX, f, date(2026, 2, 1))
    back = PointInTimeStore(tmp_path / "s").observations()["value"].tolist()
    assert back == vals


def test_files_are_deterministic(tmp_path) -> None:
    f = frame([("2026-01-05", "2026-01-05", 100.0)])
    names = []
    for k in ("a", "b"):
        s = PointInTimeStore(tmp_path / k)
        ingest(s, PX, f, date(2026, 1, 6), stamp="2026-01-06T06:30:00Z")
        names.append(s.manifest()["files"][0]["sha256"])
    assert names[0] == names[1]


def test_commit_refuses_impossible_rows(store: PointInTimeStore) -> None:
    bad = pd.DataFrame(
        {
            "series_id": ["x:y"],
            "obs_date": pd.to_datetime(["2026-01-05"]),
            "vintage_date": pd.to_datetime(["2026-01-04"]),
            "value": [1.0],
            "ingested_at": [""],
        }
    )
    with pytest.raises(DataError):
        store.commit(bad, utc_stamp())
    with pytest.raises(DataError):
        store.diff(PX, frame([("2026-01-05", "2026-01-04", 1.0)]), date(2026, 1, 6))


def test_verify_detects_tampering(tmp_path) -> None:
    s = PointInTimeStore(tmp_path / "s")
    ingest(s, PX, frame([("2026-01-05", "2026-01-05", 100.0)]), date(2026, 1, 6))
    assert s.verify() == []
    name = s.manifest()["files"][0]["name"]
    p = tmp_path / "s" / "observations" / name
    text = gzip.decompress(p.read_bytes()).decode().replace("100", "999")
    p.write_bytes(gzip.compress(text.encode()))
    assert any("checksum" in x for x in s.verify())
    (tmp_path / "s" / "observations" / "delta-orphan.csv.gz").write_bytes(b"")
    assert any("unlisted" in x for x in s.verify())
    p.unlink()
    assert any("missing" in x for x in s.verify())


def test_snapshot_changes_with_every_commit(store: PointInTimeStore) -> None:
    a = store.snapshot_id()
    ingest(store, PX, frame([("2026-01-05", "2026-01-05", 100.0)]), date(2026, 1, 6))
    b = store.snapshot_id()
    ingest(store, PX, frame([("2026-01-06", "2026-01-06", 101.0)]), date(2026, 1, 7))
    assert len({a, b, store.snapshot_id()}) == 3


def test_compaction_preserves_every_as_of_answer(tmp_path) -> None:
    rng = np.random.default_rng(3)
    s = PointInTimeStore(tmp_path / "s")
    days = pd.bdate_range("2026-01-01", periods=40)
    for k in range(6):  # six runs with revisions of random earlier days
        rows = [(str(d.date()), str(d.date()), 100 + float(rng.normal())) for d in days[: 20 + 4 * k]]
        ingest(
            s,
            PX,
            frame(rows),
            (days[19 + 4 * k] + pd.Timedelta(days=1)).date(),
            stamp=f"2026-03-0{k + 1}T06:30:00Z",
        )
    before = s.observations().copy()
    probes = pd.date_range("2026-01-01", "2026-04-01", freq="D")
    want = {p: PitIndex(before).as_of(PX.series_id, p) for p in probes}
    s.compact("2026-04-02T00:00:00Z")
    assert len(s.manifest()["files"]) == 1 and s.verify() == []
    after = PointInTimeStore(tmp_path / "s").observations()
    for p in probes:
        pd.testing.assert_series_equal(PitIndex(after).as_of(PX.series_id, p), want[p])


def test_pit_index_equals_sql_semantics_on_random_revision_histories() -> None:
    """Property: the interval index answers exactly like the reference as-of query."""
    rng = np.random.default_rng(11)
    for trial in range(25):
        n_obs = int(rng.integers(1, 30))
        obs_dates = pd.to_datetime("2020-01-01") + pd.to_timedelta(
            np.sort(rng.choice(400, n_obs, replace=False)), unit="D"
        )
        rows = []
        for o in obs_dates:
            for _ in range(int(rng.integers(1, 4))):
                rows.append(
                    (
                        "s:a" if trial % 2 else "s:b",
                        o,
                        o + pd.Timedelta(days=int(rng.integers(0, 120))),
                        float(rng.normal()),
                    )
                )
        df = pd.DataFrame(rows, columns=["series_id", "obs_date", "vintage_date", "value"]).drop_duplicates(
            ["series_id", "obs_date", "vintage_date"]
        )
        idx = PitIndex(df)
        sid = df["series_id"].iloc[0]
        for d in pd.to_datetime("2019-12-01") + pd.to_timedelta(rng.choice(600, 15), unit="D"):
            ref = as_of_pandas(df, d.date())
            ref = pd.Series(
                ref["value"].to_numpy(), index=pd.DatetimeIndex(ref["obs_date"].to_numpy()), name=sid
            )
            got = idx.as_of(sid, d)
            pd.testing.assert_series_equal(got, ref, check_freq=False, check_index_type=False)


def test_manifest_is_human_readable(tmp_path) -> None:
    s = PointInTimeStore(tmp_path / "s")
    ingest(s, PX, frame([("2026-01-05", "2026-01-05", 100.0)]), date(2026, 1, 6))
    m = json.loads((tmp_path / "s" / "manifest.json").read_text())
    assert m["format"] == 1 and m["series"][PX.series_id]["last_fetch"] == "2026-01-06"


# ---------------------------------------------------------------------------- maintenance and logs
def test_format_version_is_checked(tmp_path) -> None:
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "manifest.json").write_text('{"format": 99, "files": []}')
    with pytest.raises(DataError, match="format 99"):
        PointInTimeStore(tmp_path / "s").manifest()


def test_state_only_commit_logs_and_quarantine(tmp_path) -> None:
    for s in (PointInTimeStore(None), PointInTimeStore(tmp_path / "s")):
        assert (
            s.commit(
                pd.DataFrame(),
                "2026-01-06T06:30:00Z",
                series_state={"x:y": {"last_fetch": "2026-01-06"}},
                sources={"static": "abc"},
            )
            is None
        )
        assert s.series_state("x:y")["last_fetch"] == "2026-01-06" and s.source_fingerprint("static") == "abc"
        assert s.read_log("quality_log").empty
        s.append_log("quality_log", pd.DataFrame({"check": ["gaps"], "status": ["ok"]}))
        s.append_log("quality_log", pd.DataFrame({"check": ["staleness"], "status": ["warn"]}))
        s.append_log("quality_log", pd.DataFrame())
        assert s.read_log("quality_log")["check"].tolist() == ["gaps", "staleness"]
        s.quarantine(pd.DataFrame(), "2026-01-06T06:30:00Z")
        s.quarantine(
            pd.DataFrame({"value": [-1.0], "reason": ["non-positive price"]}), "2026-01-06T06:30:00Z"
        )
        if s.path is not None:
            assert len(list((s.path / "quarantine").glob("*.csv"))) == 1
        assert s.series_ids() == [] and s.compact() is None and s.manifest()["files"] == []


def test_archive_fixes_are_reported_as_revisions(store: PointInTimeStore) -> None:
    ingest(store, CPI, frame([("2026-08-31", "2026-09-11", 320.0)]), date(2026, 9, 20), real=True)
    d = store.diff(CPI, frame([("2026-08-31", "2026-09-11", 320.5)]), date(2026, 9, 21), real_vintages=True)
    assert d.revised == 1 and d.revisions["new"].tolist() == [320.5]


def test_verify_reads_file_contents(tmp_path) -> None:
    import hashlib

    s = PointInTimeStore(tmp_path / "s")
    ingest(s, PX, frame([("2026-01-05", "2026-01-05", 100.0)]), date(2026, 1, 6))
    m = s.manifest()
    bad = "series_id,obs_date,vintage_date,value,ingested_at\nx:y,2026-01-05,2026-01-04,inf,t\nx:y,2026-01-06,2026-01-06,1,t\n"
    raw = gzip.compress(bad.encode())
    (tmp_path / "s" / "observations" / m["files"][0]["name"]).write_bytes(raw)
    m["files"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "s" / "manifest.json").write_text(json.dumps(m))
    problems = " | ".join(PointInTimeStore(tmp_path / "s").verify())
    assert "row count 2 != 1" in problems and "vintage before obs" in problems and "non-finite" in problems


def test_series_table_documents_coverage(tmp_path) -> None:
    s = PointInTimeStore(tmp_path / "s")
    ingest(
        s,
        PX,
        frame([("2026-01-05", "2026-01-05", 100.0), ("2026-01-06", "2026-01-06", 101.0)]),
        date(2026, 1, 7),
    )
    s.write_series_table([PX, CPI])
    t = pd.read_csv(tmp_path / "s" / "series.csv")
    row = t.set_index("series_id").loc[PX.series_id]
    assert (
        row["rows"] == 2
        and row["first_obs"] == "2026-01-05"
        and t.set_index("series_id").loc[CPI.series_id, "rows"] == 0
    )
