"""Configuration schemas (pydantic). Unknown keys are errors; every run hashes the loaded config."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# system.yaml
# ---------------------------------------------------------------------------
class ProviderConfig(_Strict):
    enabled: bool = True
    refetch_buffer_days: int = 10  # incremental ingest refetches this many days before the last obs
    late_tolerance_days: int = 5  # a new obs arriving later than lag vintage + this is dated on arrival
    timeout_s: float = 30.0
    retries: int = 3
    min_interval_s: float = 0.0  # politeness delay between requests to the same provider
    urls: list[str] = Field(default_factory=list)  # source URLs tried in order (providers whose files move)


class QualityConfig(_Strict):
    stale_trading_days: int = 2  # daily series: trading days behind the last completed session
    stale_periods: int = 3  # weekly/monthly series: periods behind (on top of the lag)
    outlier_sigma: float = 8.0
    outlier_window: int = 250
    revision_warn: float = 0.005  # relative change of an already stored price that triggers a warning
    cross_source_warn: float = 0.01  # daily return difference primary vs fallback source
    gap_warn_days: int = 3  # missing trading days in a daily series before a warning
    revision_cluster_days: int = 7  # window for counting small revisions of stored prices
    revision_cluster_min: int = 5  # that many revisions in the window -> warn (provider unstable)


class SystemConfig(_Strict):
    store_path: str = "data/store"
    raw_path: str = "data/raw"
    journal_path: str = "journal"
    reports_path: str = "reports"
    calendar: Literal["XNYS", "weekday"] = "XNYS"
    timezone: str = "America/New_York"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    log_level: Literal["DEBUG", "INFO", "WARNING"] = "INFO"


# ---------------------------------------------------------------------------
# universe.yaml
# ---------------------------------------------------------------------------
class AssetConfig(_Strict):
    name: str
    asset_class: Literal[
        "equity",
        "bond",
        "precious",
        "energy",
        "base_metal",
        "agri",
        "cash",
        "commodity_basket",
        "real_estate",
    ]
    instrument: Literal["etf", "spot", "future", "index"]
    tradable: bool = True
    cost_bps: float = 10.0
    borrow_bps: float = 0.0
    proxy_of: str | None = None
    # role -> series id, or a chain [primary, fallback, ...]: the view uses the primary and splices the
    # next one in only where the primary has no data (history before it starts, or days after it stops).
    series: dict[str, str | list[str]] = Field(default_factory=dict)

    def chain(self, role: str) -> list[str]:
        v = self.series.get(role)
        if v is None:
            return []
        return [v] if isinstance(v, str) else list(v)


class UniverseConfig(_Strict):
    assets: dict[str, AssetConfig]
    cash: str = "CASH"

    @model_validator(mode="after")
    def _proxies_exist(self) -> UniverseConfig:
        for aid, a in self.assets.items():
            if a.proxy_of and a.proxy_of not in self.assets:
                raise ValueError(f"{aid}.proxy_of={a.proxy_of} is not an asset")
        return self


# ---------------------------------------------------------------------------
# series.yaml
# ---------------------------------------------------------------------------
_KINDS = Literal[
    "price", "dividend", "split", "total_return", "return", "yield", "index", "macro", "positioning"
]


class SeriesConfig(_Strict):
    kind: _KINDS
    frequency: Literal["D", "W", "M", "Q"]
    lag: str = "0D"
    vintages: Literal["none", "alfred"] = "none"
    unit: str = ""
    name: str = ""
    required: bool = False
    revision_tolerance: float | None = None
    params: dict[str, str] = Field(default_factory=dict)

    @field_validator("lag")
    @classmethod
    def _lag(cls, v: str) -> str:
        if not re.match(r"^\d+[DM]$", v.strip().upper()):
            raise ValueError(f"lag '{v}' must look like '0D', '14D' or '1M'")
        return v.strip().upper()


class DerivedSeriesDefaults(_Strict):
    """Defaults for series that are only referenced from universe.yaml (ETF closes, dividends)."""

    frequency: Literal["D", "W", "M", "Q"] = "D"
    lag: str = "0D"
    revision_tolerance: float = 1e-6


class SeriesCatalogConfig(_Strict):
    # provider -> defaults for series referenced only from universe.yaml
    derive_from_universe: dict[str, DerivedSeriesDefaults] = Field(default_factory=dict)
    role_kinds: dict[str, _KINDS] = Field(default_factory=dict)  # asset role -> kind
    # roles of tradable assets whose primary series is required (staleness blocks)
    required_roles: list[str] = Field(default_factory=list)
    series: dict[str, SeriesConfig] = Field(default_factory=dict)
    # virtual series "<name>:<code>" = [primary, fallback, ...], read with view.series(); spliced like asset chains
    chains: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("chains")
    @classmethod
    def _chains(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for cid, members in v.items():
            if not cid.startswith("macro:") or len(members) < 2:
                raise ValueError(f"chain '{cid}' must be called 'macro:<NAME>' and list at least two series")
        return v

    @field_validator("series")
    @classmethod
    def _ids(cls, v: dict[str, SeriesConfig]) -> dict[str, SeriesConfig]:
        for sid in v:
            if sid.count(":") < 1 or sid.split(":", 1)[0] == "":
                raise ValueError(f"series id '{sid}' must be '<provider>:<code>[:<field>]'")
        return v


# ---------------------------------------------------------------------------
# strategies/*.yaml
# ---------------------------------------------------------------------------
class ConfidenceRule(_Strict):
    kind: Literal["score_dispersion", "fraction_in_trend", "abs_z", "percentile"]
    floor: float = 0.5
    params: dict[str, Any] = Field(default_factory=dict)


class CostSpec(_Strict):
    """Transaction costs of a run in bp per side on traded weight. `default_bps=None` takes each asset's
    `cost_bps` from universe.yaml; `cash_bps` charges the cash leg too (some studies did, see golden runs)."""

    default_bps: float | None = None
    cash_bps: float = 0.0
    per_asset: dict[str, float] = Field(default_factory=dict)


class GoldenRun(_Strict):
    """How the research figures in `golden` were produced, so the engine can reproduce them.

    `data_from`: the research panel started here; observations before it are invisible (rolling windows
    restart). `sample`: returns dated in this window enter the metrics. `count_warmup`: months in which
    the module had no signal yet (all cash) count, as in studies that kept them, or are skipped, as in
    studies that dropped them. `execution`: `same_close` = research convention (trade at the decision
    close); `next_close` = production (ADR 011). `params`: overrides for this run (deep-merged)."""

    universe: Literal["long_history", "live"] = "long_history"
    data_from: date | None = None
    start: date
    end: date
    sample: tuple[date, date]
    count_warmup: bool = True
    execution: Literal["same_close", "next_close"] = "same_close"
    costs: CostSpec = Field(default_factory=CostSpec)
    params: dict[str, Any] = Field(default_factory=dict)


class WalkForwardConfig(_Strict):
    """Parameter choice without hindsight: every `refit_every_months` the grid point with the best Sharpe
    (ex cash, net) on all months so far is chosen; the first choice after `min_train_months`."""

    grid: dict[str, list[Any]]
    refit_every_months: int = 12
    min_train_months: int = 120
    golden: dict[str, float] = Field(default_factory=dict)
    golden_tolerance: dict[str, float] = Field(default_factory=dict)
    golden_sample: tuple[date, date] | None = None
    golden_chosen: dict[str, Any] = Field(default_factory=dict)  # the grid point research chose every year


class StrategyConfig(_Strict):
    id: str
    version: int
    role: Literal["core", "satellite", "overlay"]
    cadence: Literal["monthly", "weekly"] = "monthly"
    universe: list[str]
    long_history_universe: list[str] = Field(default_factory=list)  # for golden tests
    warmup_months: int
    params: dict[str, Any]
    long_history_params: dict[str, Any] = Field(default_factory=dict)  # deep-merged over params
    confidence: ConfidenceRule
    stops: list[dict[str, Any]] = Field(default_factory=list)
    golden: dict[str, float] = Field(default_factory=dict)  # metric -> expected value
    golden_tolerance: dict[str, float] = Field(default_factory=dict)
    golden_run: GoldenRun | None = None
    walkforward: WalkForwardConfig | None = None

    @field_validator("universe")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("universe must not be empty")
        return v


# ---------------------------------------------------------------------------
# portfolio.yaml
# ---------------------------------------------------------------------------
class RiskRuleConfig(_Strict):
    name: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class PortfolioConfig(_Strict):
    vol_target: float = 0.10
    max_gross: float = 1.5
    max_asset_weight: float = 0.35
    max_class_weight: float = 0.60
    risk_budgets: dict[str, float]  # strategy id -> share of vol target (core + satellite)
    overlay_limit: float = 0.30  # max hedge size relative to core equity exposure
    confidence_floor: float = 0.5
    cov_halflife_days: int = 60
    vol_floor: float = 0.05
    rules: list[RiskRuleConfig]

    @model_validator(mode="after")
    def _budgets_sum(self) -> PortfolioConfig:
        s = sum(self.risk_budgets.values())
        if abs(s - 1.0) > 1e-6:
            raise ValueError(f"risk_budgets must sum to 1, got {s:.4f}")
        return self


# ---------------------------------------------------------------------------
# live.yaml
# ---------------------------------------------------------------------------
class LiveConfig(_Strict):
    strategy_versions: dict[str, int]  # strategy id -> version that is live
    portfolio_version: str
    notify_on: list[
        Literal["targets", "risk_action", "quality", "regime_change", "signal_health_red", "drift"]
    ]
    min_weight_change_to_notify: float = 0.02
    execution_price: Literal["next_close"] = "next_close"


# ---------------------------------------------------------------------------
# scenarios/*.yaml
# ---------------------------------------------------------------------------
class AnalogSpec(_Strict):
    rule: Literal["equity_drawdown", "ratio_change", "regime", "dates"]
    threshold: float | None = None
    measure: Literal["peak_to_trough", "window"] = "peak_to_trough"
    dates: list[list[str]] = Field(default_factory=list)  # [[start, end], ...]
    regime: dict[str, Any] = Field(default_factory=dict)


class BootstrapSpec(_Strict):
    block_months: int = 6
    draws: int = 5000
    regime_filter: dict[str, Any] = Field(default_factory=dict)


class ScenarioConfig(_Strict):
    id: str
    description: str = ""
    horizon_months: int
    analog: AnalogSpec | None = None
    factor_shock: dict[str, float] | None = None
    bootstrap: BootstrapSpec | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> ScenarioConfig:
        if not (self.analog or self.factor_shock or self.bootstrap):
            raise ValueError("scenario needs at least one method")
        return self


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def config_hash(*models: BaseModel) -> str:
    payload = json.dumps([m.model_dump(mode="json") for m in models], sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


class Bundle(_Strict):
    system: SystemConfig
    universe: UniverseConfig
    series: SeriesCatalogConfig = Field(default_factory=SeriesCatalogConfig)
    portfolio: PortfolioConfig
    strategies: dict[str, StrategyConfig]
    scenarios: dict[str, ScenarioConfig]
    live: LiveConfig | None = None

    def hash(self) -> str:
        parts: list[BaseModel] = [
            self.system,
            self.universe,
            self.series,
            self.portfolio,
            *self.strategies.values(),
            *self.scenarios.values(),
        ]
        if self.live:
            parts.append(self.live)
        return config_hash(*parts)


def load_bundle(root: str | Path = "configs") -> Bundle:
    root = Path(root)
    strategies = {
        p.stem: StrategyConfig(**load_yaml(p)) for p in sorted((root / "strategies").glob("*.yaml"))
    }
    scenarios = {p.stem: ScenarioConfig(**load_yaml(p)) for p in sorted((root / "scenarios").glob("*.yaml"))}
    live_path = root / "live.yaml"
    series_path = root / "series.yaml"
    bundle = Bundle(
        system=SystemConfig(**load_yaml(root / "system.yaml")),
        universe=UniverseConfig(**load_yaml(root / "universe.yaml")),
        series=SeriesCatalogConfig(**load_yaml(series_path))
        if series_path.exists()
        else SeriesCatalogConfig(),
        portfolio=PortfolioConfig(**load_yaml(root / "portfolio.yaml")),
        strategies=strategies,
        scenarios=scenarios,
        live=LiveConfig(**load_yaml(live_path)) if live_path.exists() else None,
    )
    _cross_check(bundle)
    return bundle


def _cross_check(b: Bundle) -> None:
    assets = set(b.universe.assets)
    for sid, s in b.strategies.items():
        if s.id != sid:
            raise ValueError(f"strategies/{sid}.yaml has id '{s.id}' (file name and id must match)")
        unknown = (set(s.universe) | set(s.long_history_universe)) - assets
        if unknown:
            raise ValueError(f"strategy {sid}: unknown assets {sorted(unknown)}")
        for name, uni in (("universe", s.universe), ("long_history_universe", s.long_history_universe)):
            cash = [a for a in uni if b.universe.assets[a].asset_class == "cash"]
            if len(cash) > 1:
                raise ValueError(f"strategy {sid}: {name} lists more than one cash asset {cash}")
    budget_ids = set(b.portfolio.risk_budgets)
    core_ids = {sid for sid, s in b.strategies.items() if s.role in ("core", "satellite")}
    if budget_ids != core_ids:
        raise ValueError(
            f"risk_budgets {sorted(budget_ids)} must match core/satellite strategies {sorted(core_ids)}"
        )
    if b.live:
        for sid, v in b.live.strategy_versions.items():
            if sid not in b.strategies:
                raise ValueError(f"live.yaml references unknown strategy {sid}")
            if b.strategies[sid].version != v:
                raise ValueError(f"live.yaml pins {sid} v{v} but config is v{b.strategies[sid].version}")
