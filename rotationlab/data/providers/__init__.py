"""Providers: one class per source, all returning frames (obs_date, vintage_date, value).

`make_providers` wires them to one HTTP client per provider (politeness interval and retries from
configs/system.yaml). API keys come from the environment: FRED_API_KEY (needed for ALFRED), BLS_API_KEY (optional),
STOOQ_API_KEY (Stooq is wired only with a key: since 2026-03 it serves CSV only to key holders).
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import date

from rotationlab.config.models import Bundle, ProviderConfig
from rotationlab.data.providers.base import BaseProvider
from rotationlab.data.providers.bls import BlsProvider
from rotationlab.data.providers.cftc import CftcProvider
from rotationlab.data.providers.fred import FredProvider
from rotationlab.data.providers.french import FrenchProvider
from rotationlab.data.providers.http import HttpClient, UrllibClient
from rotationlab.data.providers.shiller import DEFAULT_URLS, ShillerProvider
from rotationlab.data.providers.static import StaticProvider
from rotationlab.data.providers.stooq import StooqProvider
from rotationlab.data.providers.yahoo import YahooProvider

__all__ = ["BaseProvider", "make_providers"]


def make_providers(bundle: Bundle, today: date, env: Mapping[str, str] | None = None,
                   http_factory: Callable[[str, ProviderConfig], HttpClient] | None = None) -> dict[str, BaseProvider]:
    env = os.environ if env is None else env
    cfg = bundle.system.providers

    def http(name: str) -> HttpClient:
        pc = cfg.get(name, ProviderConfig())
        if http_factory is not None:
            return http_factory(name, pc)
        return UrllibClient(timeout_s=pc.timeout_s, retries=pc.retries, min_interval_s=pc.min_interval_s)

    out: dict[str, BaseProvider] = {
        "static": StaticProvider(bundle.system.raw_path),
        "yahoo": YahooProvider(http("yahoo"), today=today),
        "stooq": StooqProvider(http("stooq"), env.get("STOOQ_API_KEY")),
        "fred": FredProvider(http("fred"), env.get("FRED_API_KEY")),
        "french": FrenchProvider(http("french")),
        "cftc": CftcProvider(http("cftc")),
        "bls": BlsProvider(http("bls"), env.get("BLS_API_KEY"), today=today),
        "shiller": ShillerProvider(http("shiller"), cfg.get("shiller", ProviderConfig()).urls or DEFAULT_URLS),
    }
    if not env.get("STOOQ_API_KEY"):
        del out["stooq"]
    return {k: v for k, v in out.items() if cfg.get(k, ProviderConfig()).enabled}
