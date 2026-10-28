"""The forecast journal (ADR 043, step P6): append-only, time-stamped, tamper-evident.

Two JSON-lines files in the journal directory:

    forecasts.jsonl   one line per forecast (decision date × horizon × model), written the moment it is made
    outcomes.jsonl    one line per settled forecast, written the moment its outcome window is known

Every line carries `seq`, `prev_hash` and `hash` = SHA-256 over (prev_hash + canonical record). A line can
only be appended, never changed: `verify()` recomputes the chain and reports the first broken link, and
nothing is appended to a chain that does not verify. A forecast is identified by (decision_date,
horizon_months, model_id, model_version); writing the same one twice is a no-op, so a daily run that calls
`append` every day is safe.

What the chain can and cannot do (second review 2026-10-26): it detects a line edited, deleted or reordered
*inside* the file and a forged line appended without the secret-free recipe. It cannot detect a file cut
off at the tail (the shorter chain is still consistent), nor a complete rewrite that re-hashes every line –
there is no secret and no signature. The guard against both is an anchor kept *outside* the file: the
`head()` of each chain (last seq and hash), printed by `forecast run` into the Actions log, and the git
history of the data branch; `verify(anchors=...)` checks the file against such an anchor.

Nothing here reads prices. The journal knows what was said and what came of it; `live.py` decides when.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from rotationlab.forecast.types import Forecast

GENESIS = "0" * 64
Head = tuple[int, str]  # (seq, hash) of the last line of a chain
_ANCHOR = re.compile(r"(?P<name>[\w.-]+\.jsonl) seq (?P<seq>\d+) hash (?P<hash>[0-9a-f]{64})")


class JournalError(RuntimeError):
    """The chain does not verify: nothing is appended to it."""


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def chain_hash(prev_hash: str, record: Mapping[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(record)).encode()).hexdigest()


@dataclass(frozen=True)
class Outcome:
    """What came of a forecast, written once the horizon has passed.

    relative: realised relative excess return per ranked class (return minus the mean of the ranked classes)
    realised_rank: 1 = best realised relative return
    hit: 1.0 where the event `target` happened (`top_half`: the class ended in the upper half, ADR 045 b);
         the target is the forecast's own (`params.probability.target`), not the configuration of the day
         the outcome was settled
    ic: Spearman correlation between the forecast scores and the realised relative returns
    top_beats_bottom: 1.0 if the class ranked first beat the class ranked last
    brier: mean squared error of the probabilities against `hit`; brier_const = the same for 0.5
    ic_prev_month: the previous-month-rank baseline's IC for the same month (NaN if unknown)
    trend_hit: trend-only classes: 1.0 if the class's own return over its window had the sign of its trend;
         every trend-only class of the forecast is present (the outcome waits for their data)
    """

    decision_date: date
    horizon_months: int
    model_id: str
    model_version: int
    settled_through: date  # the month-end whose data settled this forecast
    relative: Mapping[str, float]
    realised_rank: Mapping[str, int]
    hit: Mapping[str, float]
    ic: float | None
    top_beats_bottom: float | None
    brier: float | None
    brier_const: float | None
    ic_prev_month: float | None
    trend_hit: Mapping[str, float]
    target: str = "top_half"  # the event behind `hit`; lines written before the field existed were top_half
    # paper track of the derived weights (ADR 048): return of the forecast's weights over the horizon with the
    # remainder in cash, of equal weight over the ranked classes, and of cash – month-end to month-end, before
    # costs; None when the forecast carried no weights or the cash level was missing
    portfolio_return: float | None = None
    ew_return: float | None = None
    cash_return: float | None = None

    def key(self) -> tuple[str, int, str, int]:
        return (self.decision_date.isoformat(), self.horizon_months, self.model_id, self.model_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date.isoformat(),
            "horizon_months": self.horizon_months,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "settled_through": self.settled_through.isoformat(),
            "relative": dict(self.relative),
            "realised_rank": dict(self.realised_rank),
            "hit": dict(self.hit),
            "target": self.target,
            "ic": self.ic,
            "top_beats_bottom": self.top_beats_bottom,
            "brier": self.brier,
            "brier_const": self.brier_const,
            "ic_prev_month": self.ic_prev_month,
            "trend_hit": dict(self.trend_hit),
            "portfolio_return": self.portfolio_return,
            "ew_return": self.ew_return,
            "cash_return": self.cash_return,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Outcome:
        return cls(
            decision_date=date.fromisoformat(d["decision_date"]),
            horizon_months=int(d["horizon_months"]),
            model_id=d["model_id"],
            model_version=int(d["model_version"]),
            settled_through=date.fromisoformat(d["settled_through"]),
            relative={k: float(v) for k, v in d["relative"].items()},
            realised_rank={k: int(v) for k, v in d["realised_rank"].items()},
            hit={k: float(v) for k, v in d["hit"].items()},
            ic=d.get("ic"),
            top_beats_bottom=d.get("top_beats_bottom"),
            brier=d.get("brier"),
            brier_const=d.get("brier_const"),
            ic_prev_month=d.get("ic_prev_month"),
            trend_hit={k: float(v) for k, v in d.get("trend_hit", {}).items()},
            target=str(d.get("target", "top_half")),
            portfolio_return=d.get("portfolio_return"),
            ew_return=d.get("ew_return"),
            cash_return=d.get("cash_return"),
        )


def forecast_key(f: Forecast) -> tuple[str, int, str, int]:
    return (f.decision_date.isoformat(), f.horizon_months, f.model_id, f.model_version)


class _Chain:
    """One append-only JSON-lines file with a hash chain.

    The parsed lines are cached by content digest: a run parses each file once, however many times it
    lists, verifies or appends (the bytes are re-read and hashed on every call – cheap for a journal of a
    few hundred lines, and a change on disk by anyone else is seen immediately, whatever the mtime says)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._key: str | None = None  # digest of the file's bytes; None = no file
        self._lines: list[dict[str, Any]] = []

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            self._key, self._lines = None, []
            return self._lines
        key = hashlib.blake2b(raw, digest_size=16).hexdigest()
        if key != self._key:
            self._lines = [
                json.loads(text) for line in raw.decode("utf-8").splitlines() if (text := line.strip())
            ]
            self._key = key
        return self._lines

    def state_key(self) -> str | None:
        """Identity of the file's content for caches built on top of it."""
        self._load()
        return self._key

    def lines(self) -> Iterator[dict[str, Any]]:
        return iter(list(self._load()))

    def last(self) -> dict[str, Any] | None:
        lines = self._load()
        return lines[-1] if lines else None

    def head(self) -> Head | None:
        """(seq, hash) of the last line – the value to keep outside the file; None for an empty chain."""
        last = self.last()
        return None if last is None else (int(last["seq"]), str(last["hash"]))

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Append one line – after verifying the chain: a broken chain is never extended (JournalError)."""
        ok, message = self.verify()
        if not ok:
            raise JournalError(message)
        prev = self.last()
        seq = 0 if prev is None else int(prev["seq"]) + 1
        prev_hash = GENESIS if prev is None else str(prev["hash"])
        body = {"seq": seq, "written_at": now_iso(), "record": dict(record)}
        line = {**body, "prev_hash": prev_hash, "hash": chain_hash(prev_hash, body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(canonical(line) + "\n")
        self._key = None  # re-read on the next call: the cache never trusts its own bookkeeping
        return line

    def verify(self, anchor: Head | None = None) -> tuple[bool, str]:
        """Recompute the chain; with an `anchor` (a head recorded earlier, outside the file) also require that
        the file still contains that line with that hash – the only way to notice a cut-off tail."""
        prev_hash, expect_seq = GENESIS, 0
        anchored = False
        for line in self._load():
            body = {"seq": line["seq"], "written_at": line["written_at"], "record": line["record"]}
            if line["seq"] != expect_seq:
                return False, f"{self.path.name}: seq {line['seq']} where {expect_seq} was expected"
            if line["prev_hash"] != prev_hash:
                return False, f"{self.path.name}: seq {line['seq']} does not link to the previous line"
            if chain_hash(prev_hash, body) != line["hash"]:
                return False, f"{self.path.name}: seq {line['seq']} was altered after writing"
            if anchor is not None and line["seq"] == anchor[0]:
                if line["hash"] != anchor[1]:
                    return False, f"{self.path.name}: seq {anchor[0]} does not carry the anchored hash"
                anchored = True
            prev_hash, expect_seq = line["hash"], expect_seq + 1
        if anchor is not None and not anchored:
            return False, (
                f"{self.path.name}: {expect_seq} lines, but the anchor names seq {anchor[0]} – the tail was cut off"
            )
        suffix = ", anchor found" if anchor is not None else ""
        return True, f"{self.path.name}: {expect_seq} lines, chain intact{suffix}"


class ForecastJournal:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self._forecasts = _Chain(self.dir / "forecasts.jsonl")
        self._outcomes = _Chain(self.dir / "outcomes.jsonl")
        self._parsed_f: tuple[str | None, list[Forecast]] | None = None
        self._parsed_o: tuple[str | None, list[Outcome]] | None = None

    # -- forecasts ---------------------------------------------------------------
    def forecasts(self) -> list[Forecast]:
        key = self._forecasts.state_key()
        if self._parsed_f is None or self._parsed_f[0] != key:
            self._parsed_f = (key, [Forecast.from_dict(line["record"]) for line in self._forecasts.lines()])
        return list(self._parsed_f[1])

    def has_forecast(self, f: Forecast) -> bool:
        key = forecast_key(f)
        return any(forecast_key(x) == key for x in self.forecasts())

    def append_forecast(self, f: Forecast) -> bool:
        """Write the forecast with a wall-clock stamp; False if the same forecast is already in the journal."""
        if self.has_forecast(f):
            return False
        stamped = f.stamped(now_iso())
        self._forecasts.append(stamped.to_dict())
        return True

    # -- outcomes ----------------------------------------------------------------
    def outcomes(self) -> list[Outcome]:
        key = self._outcomes.state_key()
        if self._parsed_o is None or self._parsed_o[0] != key:
            self._parsed_o = (key, [Outcome.from_dict(line["record"]) for line in self._outcomes.lines()])
        return list(self._parsed_o[1])

    def settled_keys(self) -> set[tuple[str, int, str, int]]:
        return {o.key() for o in self.outcomes()}

    def append_outcome(self, o: Outcome) -> bool:
        if o.key() in self.settled_keys():
            return False
        self._outcomes.append(o.to_dict())
        return True

    def unsettled(self) -> list[Forecast]:
        done = self.settled_keys()
        return [f for f in self.forecasts() if forecast_key(f) not in done]

    # -- integrity ---------------------------------------------------------------
    def verify(self, anchors: Mapping[str, Head] | None = None) -> tuple[bool, list[str]]:
        """Both chains; `anchors` = {file name: (seq, hash)} recorded earlier (see `anchor_line`)."""
        a = anchors or {}
        ok1, m1 = self._forecasts.verify(a.get(self._forecasts.path.name))
        ok2, m2 = self._outcomes.verify(a.get(self._outcomes.path.name))
        return ok1 and ok2, [m1, m2]

    def heads(self) -> dict[str, Head | None]:
        return {c.path.name: c.head() for c in (self._forecasts, self._outcomes)}

    def anchor_line(self) -> str:
        """One line to keep outside the repository (Actions log, a note): the heads of both chains."""
        parts = [
            f"{name} seq {h[0]} hash {h[1]}" if h is not None else f"{name} empty"
            for name, h in self.heads().items()
        ]
        return "journal head: " + "; ".join(parts)


def parse_anchor(text: str) -> dict[str, Head]:
    """The anchors in a line written by `anchor_line` (empty chains carry no anchor)."""
    return {m["name"]: (int(m["seq"]), m["hash"]) for m in _ANCHOR.finditer(text)}


__all__ = [
    "ForecastJournal",
    "JournalError",
    "Outcome",
    "canonical",
    "chain_hash",
    "forecast_key",
    "now_iso",
    "parse_anchor",
]
