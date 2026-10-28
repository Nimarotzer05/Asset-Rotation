"""P6 (ADR 043): the append-only forecast journal – idempotent writes, hash chain, tamper detection."""

from __future__ import annotations

import json
from datetime import date

import pytest

from rotationlab.forecast.journal import (
    GENESIS,
    ForecastJournal,
    JournalError,
    Outcome,
    canonical,
    chain_hash,
    parse_anchor,
)
from rotationlab.forecast.types import ClassForecast, Forecast


def _forecast(d: date = date(2026, 9, 30), h: int = 1, version: int = 1) -> Forecast:
    classes = (
        ClassForecast("SPY", True, "up", 0.06, 0.6, 1, 0.001, (-0.004, 0.006), 0.56),
        ClassForecast("IEF", True, "down", -0.04, 0.0, 2, 0.001, (-0.003, 0.004), 0.47),
        ClassForecast("GLD", True, "down", -0.08, -0.2, 3, -0.0005, (-0.004, 0.004), 0.51),
        ClassForecast("SLV", True, "down", -0.16, -0.5, 4, -0.001, (-0.005, 0.002), 0.45),
        ClassForecast("DBC", False, "up", 0.15),
    )
    return Forecast(d, h, "signal", "composite", version, {"x": 1}, "snap", classes, 200)


def _outcome(d: date = date(2026, 9, 30), h: int = 1) -> Outcome:
    return Outcome(
        d,
        h,
        "composite",
        1,
        date(2026, 10, 31),
        {"SPY": 0.01, "IEF": 0.0, "GLD": -0.005, "SLV": -0.005},
        {"SPY": 1, "IEF": 2, "GLD": 3, "SLV": 4},
        {"SPY": 1.0, "IEF": 1.0, "GLD": 0.0, "SLV": 0.0},
        0.8,
        1.0,
        0.24,
        0.25,
        -0.4,
        {"DBC": 1.0},
    )


def test_append_is_idempotent_and_stamped(tmp_path) -> None:
    j = ForecastJournal(tmp_path)
    f = _forecast()
    assert j.append_forecast(f) is True
    assert j.append_forecast(f) is False  # same decision date, horizon, model, version
    assert j.append_forecast(_forecast(h=3)) is True
    assert j.append_forecast(_forecast(version=2)) is True
    back = j.forecasts()
    assert len(back) == 3 and back[0].created_at is not None and back[0].created_at.endswith("Z")
    assert back[0].stamped(None).to_json() == f.to_json()  # type: ignore[arg-type]
    assert j.unsettled() == back
    assert j.append_outcome(_outcome()) is True and j.append_outcome(_outcome()) is False
    assert [x.horizon_months for x in j.unsettled()] == [3, 1]  # the h=1 v1 forecast is settled
    assert j.outcomes()[0] == _outcome()
    ok, msgs = j.verify()
    assert ok and "3 lines" in msgs[0] and "1 lines" in msgs[1]


def test_hash_chain_links_lines(tmp_path) -> None:
    j = ForecastJournal(tmp_path)
    j.append_forecast(_forecast())
    j.append_forecast(_forecast(h=3))
    lines = [json.loads(x) for x in (tmp_path / "forecasts.jsonl").read_text().splitlines()]
    assert lines[0]["prev_hash"] == GENESIS and lines[1]["prev_hash"] == lines[0]["hash"]
    body = {k: lines[1][k] for k in ("seq", "written_at", "record")}
    assert chain_hash(lines[0]["hash"], body) == lines[1]["hash"]
    assert canonical({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


@pytest.mark.parametrize("attack", ["edit", "delete_middle", "reorder", "append_forged"])
def test_changes_inside_the_file_are_detected(tmp_path, attack) -> None:
    """What the chain alone detects: an edited, deleted or reordered line, a line appended by hand."""
    j = ForecastJournal(tmp_path)
    for h in (1, 3, 6):
        j.append_forecast(_forecast(h=h))
    path = tmp_path / "forecasts.jsonl"
    lines = path.read_text().splitlines()
    if attack == "edit":
        lines[1] = lines[1].replace('"probability":0.56', '"probability":0.86')
    elif attack == "delete_middle":
        del lines[1]
    elif attack == "reorder":
        lines[1], lines[2] = lines[2], lines[1]
    else:
        forged = json.loads(lines[2])
        forged["seq"] = 3
        forged["record"]["decision_date"] = "2026-10-31"
        lines.append(json.dumps(forged))
    path.write_text("\n".join(lines) + "\n")
    ok, msgs = j.verify()
    assert not ok, msgs
    assert "forecasts.jsonl" in msgs[0]


def test_tail_truncation_needs_an_anchor(tmp_path) -> None:
    """What the chain alone does NOT detect (second review 2026-10-26): a file cut off at the end is a
    shorter but consistent chain. The head recorded outside the file is what notices it."""
    j = ForecastJournal(tmp_path)
    for h in (1, 3, 6):
        j.append_forecast(_forecast(h=h))
    anchor = j.anchor_line()
    anchors = parse_anchor(anchor)
    assert anchors["forecasts.jsonl"][0] == 2 and "outcomes.jsonl" not in anchors  # empty chain: no anchor
    path = tmp_path / "forecasts.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2]) + "\n")
    ok, _ = j.verify()
    assert ok  # the chain cannot know
    ok, msgs = j.verify(anchors)
    assert not ok and "cut off" in msgs[0]
    # a rewritten line at the anchored seq: the hash differs from the anchor
    path.write_text("\n".join(lines) + "\n")
    j2 = ForecastJournal(tmp_path / "other")
    for h in (1, 3, 6):
        j2.append_forecast(_forecast(h=h, version=2))
    ok, msgs = j2.verify(anchors)
    assert not ok and "anchored hash" in msgs[0]
    # the untouched file verifies against its own anchor
    ok, msgs = j.verify(anchors)
    assert ok and "anchor found" in msgs[0]


def test_a_broken_chain_is_never_extended(tmp_path) -> None:
    j = ForecastJournal(tmp_path)
    j.append_forecast(_forecast())
    path = tmp_path / "forecasts.jsonl"
    path.write_text(path.read_text().replace('"probability":0.56', '"probability":0.86'))
    with pytest.raises(JournalError):
        j.append_forecast(_forecast(h=3))
    assert len(path.read_text().splitlines()) == 1


def test_outcome_records_its_target(tmp_path) -> None:
    j = ForecastJournal(tmp_path)
    j.append_outcome(_outcome())
    line = json.loads((tmp_path / "outcomes.jsonl").read_text().splitlines()[0])
    assert line["record"]["target"] == "top_half"
    assert Outcome.from_dict({k: v for k, v in line["record"].items() if k != "target"}).target == "top_half"


def test_empty_journal_verifies(tmp_path) -> None:
    j = ForecastJournal(tmp_path / "nothing")
    assert j.forecasts() == [] and j.outcomes() == [] and j.unsettled() == []
    ok, _ = j.verify()
    assert ok
    assert j.anchor_line() == "journal head: forecasts.jsonl empty; outcomes.jsonl empty"
