"""Run records (principle 6): every run is reproducible from what it writes.

`RunRecorder` collects the decisions of a run and writes, under `<out>/<run_id>/`:

    record.json     run id, mode, git SHA, config hash, data snapshot, period, status, metrics
    decisions.csv   per decision date: equity, cash level, warm-up, turnover, cost, execution date
    weights.csv     target weights per decision date (incl. CASH)
    proposals.jsonl every module proposal (weights, confidence, signals, notes, stops)
"""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from rotationlab.core.types import Mode, Proposal, RiskAction, RiskReport, RunId, RunRecord, Targets


def git_sha(root: str | Path = ".") -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _json(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, Mapping):
        return {str(k): _json(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_json(v) for v in x]
    return x


class RunRecorder:
    def __init__(
        self,
        mode: Mode,
        config_hash: str,
        data_snapshot: str,
        start: date,
        end: date,
        label: str = "",
        seed: int | None = None,
    ) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.record = RunRecord(
            run_id=RunId(f"{stamp}-{mode}{'-' + label if label else ''}"),
            mode=mode,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            git_sha=git_sha(),
            config_hash=config_hash,
            data_snapshot=data_snapshot,
            start=start,
            end=end,
            seed=seed,
        )
        self.proposals: list[dict[str, Any]] = []
        self.risk_events: list[dict[str, Any]] = []
        self.status = "running"

    def decision(
        self,
        d: date,
        proposals: Sequence[Proposal],
        targets: Targets,
        risk: RiskReport,
        book_snapshot: Mapping[str, Any],
    ) -> None:
        for p in proposals:
            self.proposals.append(_json(asdict(p)))

    def risk_event(self, d: date, action: RiskAction) -> None:
        self.risk_events.append(_json(asdict(action)))

    def finish(self, status: str) -> None:
        self.status = status

    def write(
        self,
        out: str | Path,
        decisions: Any = None,
        weights: Any = None,
        metrics: Mapping[str, float] | None = None,
    ) -> Path:
        d = Path(out) / self.record.run_id
        d.mkdir(parents=True, exist_ok=True)
        rec = {**_json(asdict(self.record)), "status": self.status, "metrics": _json(dict(metrics or {}))}
        (d / "record.json").write_text(json.dumps(rec, indent=1, sort_keys=True))
        if decisions is not None:
            decisions.to_csv(d / "decisions.csv", lineterminator="\n")
        if weights is not None:
            weights.to_csv(d / "weights.csv", float_format="%.6f", lineterminator="\n")
        with open(d / "proposals.jsonl", "w", encoding="utf-8") as fh:
            for p in self.proposals:
                fh.write(json.dumps(p, sort_keys=True) + "\n")
        return d
