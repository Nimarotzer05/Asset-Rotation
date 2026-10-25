"""Series catalog: one `SeriesSpec` for every series the store may hold.

Merges (1) explicit entries of configs/series.yaml, (2) series referenced by universe.yaml from
providers listed in ``derive_from_universe`` and (3) the static provider's built-in catalog.
`check_catalog` is part of ``rotationlab validate``: every series an asset refers to must exist,
chains must be homogeneous (same frequency, both levels or both values), and roles must have the
kind they claim.
"""
from __future__ import annotations

from rotationlab.config.models import Bundle
from rotationlab.core.types import AssetId, Frequency, SeriesId, SeriesKind, SeriesSpec
from rotationlab.data.providers.static import static_specs

PROVIDERS = ("static", "yahoo", "stooq", "fred", "french", "cftc", "bls", "shiller")


def _provider_code(series_id: str) -> tuple[str, str]:
    provider, rest = series_id.split(":", 1)
    return provider, rest


def build_catalog(bundle: Bundle) -> dict[str, SeriesSpec]:
    cat: dict[str, SeriesSpec] = {str(k): v for k, v in static_specs().items()}
    cfg = bundle.series
    # (1) explicit
    for sid, sc in cfg.series.items():
        provider, code = _provider_code(sid)
        cat[sid] = SeriesSpec(
            series_id=SeriesId(sid), provider=provider, provider_code=code, kind=SeriesKind(sc.kind),
            frequency=Frequency(sc.frequency), unit=sc.unit, lag=sc.lag, vintages=sc.vintages,
            required=sc.required, revision_tolerance=sc.revision_tolerance if sc.revision_tolerance is not None else 1e-9,
            name=sc.name, params=tuple(sorted(sc.params.items())),
        )
    # (2) derived from universe roles
    for aid, a in bundle.universe.assets.items():
        for role in a.series:
            chain = a.chain(role)
            for pos, sid in enumerate(chain):
                provider, code = _provider_code(sid)
                if sid in cat or provider not in cfg.derive_from_universe:
                    continue
                kind = cfg.role_kinds.get(role)
                if kind is None:
                    continue
                d = cfg.derive_from_universe[provider]
                required = bool(a.tradable and role in cfg.required_roles and pos == 0)
                cat[sid] = SeriesSpec(
                    series_id=SeriesId(sid), provider=provider, provider_code=code, kind=SeriesKind(kind),
                    frequency=Frequency(d.frequency), asset_id=AssetId(aid), lag=d.lag, required=required,
                    revision_tolerance=d.revision_tolerance, name=f"{a.name} {role}",
                )
    return cat


def _chain_problems(label: str, chain: list[str], catalog: dict[str, SeriesSpec]) -> list[str]:
    problems = [f"{label}: series {sid} not in catalog" for sid in chain if sid not in catalog]
    specs = [catalog[sid] for sid in chain if sid in catalog]
    if problems or not specs:
        return problems
    if len({s.frequency for s in specs}) > 1:
        problems.append(f"{label}: chain mixes frequencies {[str(s.frequency) for s in specs]}")
    if len({s.kind.is_level for s in specs}) > 1:
        problems.append(f"{label}: chain mixes levels and values")
    return problems


def check_catalog(bundle: Bundle, catalog: dict[str, SeriesSpec]) -> list[str]:
    """Problems that make the configuration unusable (empty list = ok)."""
    problems: list[str] = []
    role_kinds = bundle.series.role_kinds
    for sid, spec in catalog.items():
        if spec.provider not in PROVIDERS:
            problems.append(f"{sid}: unknown provider '{spec.provider}'")
    for cid, members in bundle.series.chains.items():
        problems += _chain_problems(f"chain {cid}", members, catalog)
    for aid, a in bundle.universe.assets.items():
        for role in a.series:
            chain = a.chain(role)
            found = _chain_problems(f"asset {aid}.{role}", chain, catalog)
            problems += found
            specs = [catalog[sid] for sid in chain if sid in catalog]
            if found or not specs:
                continue
            expected = role_kinds.get(role)
            if expected and role in ("dividend", "split", "return", "yield"):
                wrong = [s.series_id for s in specs if s.kind != SeriesKind(expected)]
                if wrong:
                    problems.append(f"asset {aid}.{role}: series {wrong} are not of kind '{expected}'")
        if not any(r in a.series for r in ("total_return", "return", "close", "yield")):
            problems.append(f"asset {aid}: no role from which a total return can be built")
    return problems
