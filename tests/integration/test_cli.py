"""The data commands end to end on a temporary store (static provider only, no network)."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest
import yaml

from rotationlab.cli import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def configs(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("cli")
    cfg = tmp / "configs"
    shutil.copytree(ROOT / "configs", cfg)
    system = yaml.safe_load((cfg / "system.yaml").read_text())
    system["store_path"] = str(tmp / "store")
    system["raw_path"] = str(ROOT / "data" / "raw")
    (cfg / "system.yaml").write_text(yaml.safe_dump(system))
    return cfg


def test_validate(configs) -> None:
    assert main(["--configs", str(configs), "validate"]) == 0


def test_ingest_store_asof_cycle(configs) -> None:
    c = ["--configs", str(configs)]
    assert main([*c, "ingest", "--full", "--provider", "static", "--date", "2026-10-28"]) == 0
    assert main([*c, "ingest", "--provider", "static", "--date", "2026-10-29"]) == 0  # unchanged → skipped
    assert main([*c, "store", "verify"]) == 0
    assert main([*c, "store", "status"]) == 0
    assert main([*c, "asof", "--date", "2008-06-30", "--series", "static:fredmd:CPIAUCSL"]) == 0
    assert main([*c, "asof", "--date", "2026-10-24", "--asset", "CASH", "--role", "yield"]) == 0
    assert main([*c, "calendar", "--year", "2026"]) == 0
    store = Path(yaml.safe_load((configs / "system.yaml").read_text())["store_path"])
    f = next((store / "observations").glob("*.csv.gz"))
    raw = gzip.decompress(f.read_bytes()).replace(b"static:usmkt:TR", b"static:usmkt:XX", 1)
    f.write_bytes(gzip.compress(raw))
    assert main([*c, "store", "verify"]) == 3  # tampering → data error


def test_the_never_built_phase_commands_are_gone(configs) -> None:
    """Phases 3/4 (live portfolio, scenarios, relationships, report) were never built and were removed on
    2026-10-28 (ADR 062); argparse rejects them like any unknown command."""
    for cmd in ("live", "scenarios", "relationships", "report", "dashboard"):
        with pytest.raises(SystemExit):
            main(["--configs", str(configs), cmd])


@pytest.fixture(scope="module")
def engine_configs(tmp_path_factory) -> Path:
    """A fresh store with the research panel, for the engine commands (the data test above tampers with its own)."""
    tmp = tmp_path_factory.mktemp("cli_engine")
    cfg = tmp / "configs"
    shutil.copytree(ROOT / "configs", cfg)
    system = yaml.safe_load((cfg / "system.yaml").read_text())
    system["store_path"] = str(tmp / "store")
    system["raw_path"] = str(ROOT / "data" / "raw")
    (cfg / "system.yaml").write_text(yaml.safe_dump(system))
    assert (
        main(["--configs", str(cfg), "ingest", "--full", "--provider", "static", "--date", "2026-10-28"]) == 0
    )
    return cfg


def test_engine_commands(engine_configs, tmp_path, capsys) -> None:
    c = ["--configs", str(engine_configs)]
    out = tmp_path / "runs"
    assert (
        main(
            [
                *c,
                "backtest",
                "--strategy",
                "commodity_trend",
                "--costs",
                "research",
                "--execution",
                "same_close",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "sharpe_ex_cash" in printed and "run record" in printed
    run = next(out.iterdir())
    assert (run / "record.json").exists() and (run / "weights.csv").exists()
    assert main([*c, "golden", "--strategy", "commodity_trend"]) == 0
    assert "research" in capsys.readouterr().out
    assert main([*c, "backtest", "--strategy", "nope"]) == 2
    assert main([*c, "walkforward", "--strategy", "commodity_trend"]) == 2  # no walkforward section
