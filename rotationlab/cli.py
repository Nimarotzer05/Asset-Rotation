"""Command-line entry point: rotationlab <command> [options].

Phase 1 added the data commands (ingest, store, asof, calendar), phase 2 the engine commands (backtest,
walkforward, golden). Commands of later phases raise NotImplementedError naming the phase that delivers
them. Exit codes: 0 ok, 2 config error,
3 data/quality error (blocking quality result, store integrity), 4 risk halt, 1 anything else.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from rotationlab import __version__
from rotationlab.config.models import load_bundle
from rotationlab.core.errors import ConfigError, DataError, QualityError, RiskHalt, RotationLabError

PHASE = {
    "live": 4,
    "scenarios": 3,
    "relationships": 3,
    "report": 4,
    "dashboard": 4,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rotationlab", description="Cross-asset rotation system")
    p.add_argument("--configs", default="configs", help="configuration directory")
    p.add_argument("--version", action="version", version=f"rotationlab {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="load and cross-check all configuration, print the config hash")

    ing = sub.add_parser("ingest", help="fetch data from providers into the point-in-time store")
    ing.add_argument(
        "--full", action="store_true", help="refetch complete histories (revisions become visible)"
    )
    ing.add_argument(
        "--provider", action="append", help="limit to provider(s): static yahoo stooq fred french cftc"
    )
    ing.add_argument("--series", action="append", help="limit to series id(s)")
    ing.add_argument(
        "--date", default=None, help="run date (default: today); sessions on this date count as unfinished"
    )

    st = sub.add_parser("store", help="inspect and maintain the store")
    st.add_argument("action", choices=["status", "verify", "compact", "quality", "health"])
    st.add_argument("--last", type=int, default=30, help="quality: number of most recent results")
    st.add_argument("--days", type=int, default=30, help="health: window in days")
    st.add_argument("--out", default=None, help="health: also write the markdown report to this file")

    ao = sub.add_parser("asof", help="what was known on a date: a series or an asset role, with vintages")
    ao.add_argument("--date", required=True)
    g = ao.add_mutually_exclusive_group(required=True)
    g.add_argument("--series")
    g.add_argument("--asset")
    ao.add_argument("--role", default="close")
    ao.add_argument("--freq", default=None, choices=[None, "D", "ME", "QE"])
    ao.add_argument("--tail", type=int, default=6)

    fa = sub.add_parser(
        "fredmd-archive", help="download missing FRED-MD vintages into data/raw/fredmd_vintages"
    )
    fa.add_argument("--start", default="1999-08")
    fa.add_argument("--end", default=None)

    rf = sub.add_parser("record-fixtures", help="record real provider answers for offline replay tests")
    rf.add_argument("--out", default="tests/fixtures/recorded")

    cal = sub.add_parser("calendar", help="NYSE holidays and decision dates of a year")
    cal.add_argument("--year", type=int, default=date.today().year)

    _add_engine_commands(sub)

    live = sub.add_parser("live", help="run the engine for the latest decision date and update the journal")
    live.add_argument("--force", action="store_true", help="treat today as a decision date")

    sub.add_parser("scenarios", help="evaluate the scenario library against current targets")
    sub.add_parser("relationships", help="recompute correlations, betas, regimes, ICs, drift")
    rep = sub.add_parser("report", help="render the daily markdown report")
    rep.add_argument("--date", default=None)
    sub.add_parser("dashboard", help="start the Streamlit dashboard")
    return p


def _add_engine_commands(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    for name in ("backtest", "walkforward"):
        s = sub.add_parser(name, help=f"run one strategy module through the engine ({name})")
        s.add_argument("--strategy", required=True)
        s.add_argument("--universe", choices=["live", "long_history"], default="long_history")
        s.add_argument("--start", default=None, help="first decision date (default: the module's golden run)")
        s.add_argument(
            "--end", default=None, help="last decision date (default: the module's golden run / today)"
        )
        s.add_argument("--execution", choices=["next_close", "same_close"], default="next_close")
        s.add_argument(
            "--costs",
            choices=["universe", "research"],
            default="universe",
            help="universe.yaml cost_bps, or the research convention of the golden run",
        )
        s.add_argument("--provider", action="append", help="read only these providers (default: all)")
        s.add_argument("--out", default="output/runs", help="directory for the run record")
    gd = sub.add_parser("golden", help="reproduce the research figures of the modules and compare")
    gd.add_argument("--strategy", action="append", help="limit to strategy id(s)")
    gd.add_argument(
        "--execution",
        choices=["same_close", "next_close"],
        default=None,
        help="default: the research convention of each golden run",
    )
    gd.add_argument("--walkforward", action="store_true", help="also run the walk-forward goldens")
    gd.add_argument(
        "--provider",
        action="append",
        default=["static"],
        help="providers to read (default: the frozen research panel, static)",
    )


def cmd_validate(args: argparse.Namespace) -> int:
    from rotationlab.data.catalog import build_catalog, check_catalog

    bundle = load_bundle(args.configs)
    catalog = build_catalog(bundle)
    problems = check_catalog(bundle, catalog)
    if problems:
        raise ConfigError("; ".join(problems))
    print(
        f"config ok · {len(bundle.universe.assets)} assets · {len(catalog)} series · {len(bundle.strategies)} strategies · "
        f"{len(bundle.scenarios)} scenarios · hash {bundle.hash()}"
    )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from rotationlab.data import make_calendar, open_store
    from rotationlab.data.catalog import build_catalog
    from rotationlab.data.ingest import run_ingest
    from rotationlab.data.providers import make_providers

    bundle = load_bundle(args.configs)
    run_date = date.fromisoformat(args.date) if args.date else date.today()
    store = open_store(bundle)
    rep = run_ingest(
        store,
        bundle,
        build_catalog(bundle),
        make_providers(bundle, run_date),
        make_calendar(bundle),
        run_date,
        full=args.full,
        only_providers=args.provider,
        only_series=args.series,
    )
    print(rep.summary())
    for r in rep.blocking + rep.warnings:
        print(f"  {r.status.upper():8s} {r.check:12s} {r.series_id or '-':28s} {r.detail}")
    if rep.blocking:
        raise QualityError(f"{len(rep.blocking)} blocking quality result(s); no live decision on this data")
    return 0


def cmd_store(args: argparse.Namespace) -> int:
    from rotationlab.data import open_store

    bundle = load_bundle(args.configs)
    store = open_store(bundle)
    if args.action == "verify":
        problems = store.verify()
        for p in problems:
            print(f"  {p}")
        print(f"store {store.path}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
        if problems:
            raise DataError("store integrity check failed")
        return 0
    if args.action == "compact":
        name = store.compact()
        print(f"compacted into {name}")
        return 0
    if args.action == "quality":
        ql = store.read_log("quality_log")
        print(ql.tail(args.last).to_string(index=False) if len(ql) else "no quality results yet")
        return 0
    if args.action == "health":
        from rotationlab.data.health import health_report

        md = health_report(store, date.today(), args.days)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(md, encoding="utf-8")
        print(md)
        return 0
    m = store.manifest()
    obs = store.observations()
    print(f"store {store.path}  snapshot {store.snapshot_id()}")
    print(
        f"files {len(m['files'])}  rows {len(obs):,}  series {obs['series_id'].nunique() if len(obs) else 0}"
    )
    if len(obs):
        prov = obs.assign(provider=obs["series_id"].str.split(":").str[0])
        agg = prov.groupby("provider").agg(
            series=("series_id", "nunique"),
            rows=("value", "size"),
            first=("obs_date", "min"),
            last=("obs_date", "max"),
        )
        print(agg.to_string())
    return 0


def cmd_asof(args: argparse.Namespace) -> int:
    from rotationlab.data import open_store, view_factory

    bundle = load_bundle(args.configs)
    fac = view_factory(bundle, open_store(bundle))
    d = date.fromisoformat(args.date)
    v = fac.at(d)
    if args.series:
        s = v.series(args.series, args.freq)
        vint = fac.vintages_as_of(args.series, d).reindex(s.index) if args.freq in (None, "D") else None
        out = pd.DataFrame({"value": s})
        if vint is not None:
            out["vintage_date"] = vint.dt.date
        print(f"{args.series} as known on {d} ({len(s)} observations):")
    else:
        s = v.asset_series(args.asset, args.role)
        out = pd.DataFrame({"value": s})
        print(
            f"{args.asset}.{args.role} as known on {d}; provenance: "
            + "; ".join(
                f"{p.series_id} {p.start}..{p.end} x{p.scale:.6g}"
                for p in v.provenance(args.asset, args.role)
            )
        )
    print(out.tail(args.tail).to_string())
    return 0


def cmd_calendar(args: argparse.Namespace) -> int:
    from rotationlab.data.calendar import NYSECalendar, nyse_holidays

    cal = NYSECalendar()
    y = args.year
    print(f"NYSE holidays {y}: " + ", ".join(f"{d:%a %d %b}" for d in sorted(nyse_holidays(y))))
    print("decision date → execution session:")
    for d in cal.month_ends(date(y, 1, 1), date(y, 12, 31)):
        print(f"  {d:%a %Y-%m-%d} → {cal.next_trading_day(d):%a %Y-%m-%d}")
    return 0


def cmd_fredmd_archive(args: argparse.Namespace) -> int:
    from rotationlab.data.providers.fredmd_archive import fetch_archive
    from rotationlab.data.providers.http import UrllibClient

    bundle = load_bundle(args.configs)
    rep = fetch_archive(
        UrllibClient(timeout_s=60, retries=2, min_interval_s=0.5),
        bundle.system.raw_path,
        args.start,
        args.end,
    )
    if rep.missing:
        print(f"not found: {', '.join(rep.missing[:12])}{' …' if len(rep.missing) > 12 else ''}")
    return 0


def cmd_record_fixtures(args: argparse.Namespace) -> int:
    from rotationlab.data.catalog import build_catalog
    from rotationlab.data.providers.recorder import record

    bundle = load_bundle(args.configs)
    rows = record(bundle, build_catalog(bundle), args.out, date.today())
    failed = [r for r in rows if r["error"]]
    for r in rows:
        status = f"{r['rows']} rows" if not r["error"] else f"ERROR {r['error']}"
        print(f"  {r['provider']!s:8s} {r['series_id']!s:28s} {status}")
    print(f"recorded into {args.out}: {len(rows) - len(failed)} ok, {len(failed)} failed")
    return 0


def _engine_inputs(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    from rotationlab.data import make_calendar, open_store

    bundle = load_bundle(args.configs)
    store = open_store(bundle)
    obs = store.observations()
    providers = getattr(args, "provider", None)
    if providers:
        obs = obs[obs["series_id"].str.split(":").str[0].isin(providers)]
    return bundle, obs, make_calendar(bundle), store.snapshot_id()


def cmd_run(args: argparse.Namespace) -> int:
    from rotationlab.config.models import CostSpec
    from rotationlab.core.clock import MonthEndClock
    from rotationlab.core.protocols import Strategy
    from rotationlab.core.types import Mode
    from rotationlab.engine.core import Engine
    from rotationlab.engine.modes import research_factory
    from rotationlab.engine.recorder import RunRecorder
    from rotationlab.portfolio.book import Book
    from rotationlab.portfolio.combine import SingleStrategy
    from rotationlab.portfolio.costs import CostModel
    from rotationlab.strategies import build_strategy, build_walkforward, strategy_spec

    bundle, obs, cal, snap = _engine_inputs(args)
    cfg = bundle.strategies.get(args.strategy)
    if cfg is None:
        raise ConfigError(f"unknown strategy {args.strategy}")
    gr = cfg.golden_run
    data_from = gr.data_from if (gr and args.universe == gr.universe) else None
    start = date.fromisoformat(args.start) if args.start else (gr.start if gr else date(1973, 1, 31))
    end = (
        date.fromisoformat(args.end)
        if args.end
        else (gr.end if gr and args.universe == "long_history" else date.today())
    )
    costs = gr.costs if (args.costs == "research" and gr) else CostSpec()
    factory = research_factory(bundle, obs, cal, data_from, snap)
    cost_model = CostModel.from_config(costs, bundle.universe)
    spec = strategy_spec(bundle, args.strategy, args.universe)
    strat: Strategy
    if args.command == "walkforward":
        strat = build_walkforward(bundle, args.strategy, args.universe, cost_model.turnover_cost)
    else:
        strat = build_strategy(bundle, args.strategy, args.universe)
    mode = Mode.WALKFORWARD if args.command == "walkforward" else Mode.BACKTEST
    rec = RunRecorder(mode, bundle.hash(), snap, start, end, args.strategy)
    res = Engine(
        factory,
        MonthEndClock(cal, start, end),
        [strat],
        SingleStrategy(),
        Book(str(spec.params["cash"]), cost_model),
        rec,
        args.execution,
    ).run()
    m = res.metrics(count_warmup=False)
    path = rec.write(args.out, res.decisions, res.weights, m)
    print(
        f"{args.command} {args.strategy} [{args.universe}, {args.execution}, costs={args.costs}] "
        f"{start} … {end}: {int(m['months'])} months"
    )
    for k in (
        "ann_return",
        "ann_vol",
        "sharpe_ex_cash",
        "max_drawdown",
        "calmar",
        "hit_rate",
        "turnover_ann",
    ):
        print(f"  {k:16s} {m[k]: .4f}")
    last = res.weights.iloc[-1] if len(res.weights) else pd.Series(dtype=float)
    print("  last targets     " + ", ".join(f"{a} {w:.1%}" for a, w in last.items() if abs(w) > 1e-9))
    print(f"  run record       {path}")
    return 0


def cmd_golden(args: argparse.Namespace) -> int:
    from rotationlab.engine.modes import golden, walkforward_golden

    bundle, obs, cal, _ = _engine_inputs(args)
    sids = args.strategy or [s for s, c in bundle.strategies.items() if c.golden_run]
    failures: list[str] = []
    for sid in sids:
        rep = golden(bundle, obs, sid, cal, args.execution)
        print(f"== {sid} [{rep.execution}] {int(rep.measured['months'])} months")
        print(rep.table().to_string(float_format=lambda x: f"{x: .4f}"))
        failures += rep.failures()
        if args.walkforward and bundle.strategies[sid].walkforward:
            wf = walkforward_golden(bundle, obs, sid, cal, args.execution)
            chosen = sorted({c["chosen"] for c in wf.extra["choices"]})
            print(f"== {wf.strategy} [{wf.execution}] choices: {len(wf.extra['choices'])} × {chosen}")
            print(wf.table().to_string(float_format=lambda x: f"{x: .4f}"))
            failures += wf.failures()
    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)
    return 1 if failures else 0


COMMANDS = {
    "backtest": "cmd_run",
    "walkforward": "cmd_run",
    "golden": "cmd_golden",
    "validate": "cmd_validate",
    "ingest": "cmd_ingest",
    "store": "cmd_store",
    "asof": "cmd_asof",
    "calendar": "cmd_calendar",
    "fredmd-archive": "cmd_fredmd_archive",
    "record-fixtures": "cmd_record_fixtures",
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command in COMMANDS:
            return int(globals()[COMMANDS[args.command]](args))
        load_bundle(args.configs)  # every command validates config first
        raise NotImplementedError(
            f"'{args.command}' arrives in phase {PHASE[args.command]} (see docs/ARCHITECTURE.md §12)"
        )
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except QualityError as e:
        print(f"quality error: {e}", file=sys.stderr)
        return 3
    except DataError as e:
        print(f"data error: {e}", file=sys.stderr)
        return 3
    except RiskHalt as e:
        print(f"RISK HALT: {e}", file=sys.stderr)
        return 4
    except (RotationLabError, NotImplementedError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
