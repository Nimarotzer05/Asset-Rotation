"""Sleeve allocator (ADR 054, research round 3): breadth inside asset classes, risk parity across them.

    1. sleeves   fixed groups of instruments (EQ: ten industries, FI: two Treasury maturities, PM: gold and
                 silver), each with a fixed risk budget (1/3 each)
    2. select    inside a sleeve: equal-weighted z-scores (sample SD over the sleeve's instruments, clip ±3)
                 of the sleeve's signal families (12-1 momentum everywhere, plus carry = month-end yield
                 in FI); the ⌈n/2⌉ highest scores are selected (ties by configuration order, rank 'first')
    3. filter    an instrument is investable only while its 12-month excess return over cash is positive
                 (`excess_mom_12m` > 0, Moskowitz/Ooi/Pedersen 2012); otherwise its share stays in cash
    4. inside    inverse EWMA volatility (half-life 12 months, ≥ 24 returns, floor 2 % p.a.) over the
                 selected, investable instruments, normalised to one: the sleeve basket
    5. across    sleeve weight = budget / σ_basket, σ_basket = EWMA volatility of the history of today's
                 basket; a sleeve without an investable instrument leaves its budget in cash (no
                 redistribution); sum of sleeve weights before scaling = sum of invested budgets
    6. scale     the whole book is scaled by min(vol_target / σ_portfolio, max_exposure) with σ_portfolio the
                 EWMA volatility of the history of today's whole portfolio; no sleeve above `max_sleeve`
                 (1.0) of the book; gross exposure ≤ max_exposure (1.5), negative cash = financing at the
                 cash index
    7. band      an instrument is traded only when its target moves by ≥ `band` (2 pp) from the last
                 target; otherwise the last target stands (state `extra["targets"]`)

Role `paper`. Every number is fixed in `configs/strategies/sleeve_allocator.yaml` before the first run;
nothing adapts to the data. Live and long-history universes differ only in the instrument names per sleeve.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from rotationlab.core import registry
from rotationlab.core.protocols import MarketView
from rotationlab.core.types import AssetId, Proposal, StrategyState
from rotationlab.strategies.base import BaseStrategy, weighted_composite, zscore

FAMILIES = ("mom_12_1", "mom_12", "carry_yield", "value_rev_60m")


@dataclass(frozen=True)
class Sleeve:
    name: str
    instruments: tuple[str, ...]
    families: Mapping[str, float]  # feature name -> weight in the sleeve's composite
    budget: float


TIE_DECIMALS = 12  # composite z-scores that agree to 1e-12 are a tie (float sums leave ±1e-15 residues)


def select_top_half(score: pd.Series) -> list[str]:
    """The ⌈n/2⌉ highest scores of a sleeve; ties by configuration order (rank method 'first'), as ADR 054 (b)
    fixes it. Scores are rounded to 1e-12 first: with two instruments and two families that disagree both
    composites are exactly 0, and float rounding must not decide (ADR 056, finding 1 of the second review)."""
    k = math.ceil(len(score) / 2)
    r = score.round(TIE_DECIMALS).rank(ascending=False, method="first")
    return [str(a) for a in score.index if r[a] <= k]


def inverse_vol_weights(vol: pd.Series) -> pd.Series:
    inv = 1.0 / vol
    return inv / inv.sum()


@registry.strategy
class SleeveAllocator(BaseStrategy):
    strategy_id = "sleeve_allocator"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        p = self.params
        raw = dict(p["sleeves"])
        self.sleeves: list[Sleeve] = []
        for name, cfg in raw.items():
            fam = {str(k): float(v) for k, v in dict(cfg["families"]).items()}
            unknown = set(fam) - set(FAMILIES)
            if unknown:
                raise ValueError(f"sleeve_allocator: sleeve {name}: unsupported families {sorted(unknown)}")
            instruments = tuple(str(a) for a in cfg["instruments"])
            if not instruments:
                raise ValueError(f"sleeve_allocator: sleeve {name} has no instruments")
            self.sleeves.append(Sleeve(name, instruments, fam, float(cfg["budget"])))
        listed = [a for s in self.sleeves for a in s.instruments]
        if len(set(listed)) != len(listed):
            raise ValueError("sleeve_allocator: an instrument belongs to more than one sleeve")
        if set(listed) != {str(a) for a in self.assets}:
            raise ValueError("sleeve_allocator: the sleeves must cover exactly the universe without cash")
        if abs(sum(s.budget for s in self.sleeves) - 1.0) > 1e-9:
            raise ValueError("sleeve_allocator: the sleeve budgets must sum to one")
        self.feature_params = {k: dict(v) for k, v in dict(p.get("feature_params", {})).items()}
        self.clip = float(p.get("zscore_clip", 3.0))
        self.xs_select = bool(p.get("xs_select", True))
        self.ts_filter = bool(p.get("ts_filter", True))
        self.half_life = int(p.get("half_life", 12))
        self.min_obs = int(p.get("min_obs", 24))
        self.vol_floor = float(p.get("vol_floor", 0.02))
        self.vol_target = float(p.get("vol_target", 0.10))
        self.max_exposure = float(p.get("max_exposure", 1.5))
        self.max_sleeve = float(p.get("max_sleeve", 1.0))
        self.band = float(p.get("band", 0.02))
        if not (self.vol_target > 0 and self.vol_floor > 0 and self.max_exposure > 0 and self.max_sleeve > 0):
            raise ValueError(
                "sleeve_allocator: vol_target, vol_floor, max_exposure, max_sleeve must be positive"
            )
        if self.half_life < 1 or self.min_obs < 2 or self.band < 0:
            raise ValueError("sleeve_allocator: half_life ≥ 1, min_obs ≥ 2, band ≥ 0")

    # -- pieces --------------------------------------------------------------------
    def _vol_kw(self) -> dict[str, float | int]:
        return {"half_life": self.half_life, "min_obs": self.min_obs, "floor": self.vol_floor}

    def sleeve_score(self, sleeve: Sleeve, view: MarketView) -> pd.Series:
        assets = list(sleeve.instruments)
        z = {
            k: zscore(self.feature(k, view, assets, **self.feature_params.get(k, {})), self.clip)
            for k in sleeve.families
        }
        return weighted_composite(z, sleeve.families).rename(f"score:{sleeve.name}")

    def sleeve_basket(
        self, sleeve: Sleeve, view: MarketView, signals: dict[str, float], notes: list[str]
    ) -> pd.Series | None:
        """Inverse-vol weights (sum 1) over the selected, investable instruments; empty series = the sleeve
        stays in cash; None = warm-up (a score, trend or volatility is still missing)."""
        assets = list(sleeve.instruments)
        score = self.sleeve_score(sleeve, view)
        if score.isna().any():
            return None
        signals.update({f"score:{a}": float(v) for a, v in score.items()})
        picks = select_top_half(score) if self.xs_select else assets
        if self.ts_filter:
            ex = self.feature("excess_mom_12m", view, picks, cash=str(self.cash))
            if ex.isna().any():
                return None
            signals.update({f"excess12:{a}": float(v) for a, v in ex.items()})
            out = [a for a in picks if not bool(ex[a] > 0)]
            if out:
                notes.append(f"{sleeve.name}: 12-month excess return ≤ 0, in cash: {', '.join(out)}")
            picks = [a for a in picks if bool(ex[a] > 0)]
        if not picks:
            return pd.Series(dtype=float)
        vol = self.feature("vol_ewma", view, picks, **self._vol_kw())
        if vol.isna().any():
            return None
        signals.update({f"vol:{a}": float(v) for a, v in vol.items()})
        return inverse_vol_weights(vol)

    def propose(self, view: MarketView, state: StrategyState) -> tuple[Proposal, StrategyState]:
        signals: dict[str, float] = {}
        notes: list[str] = []
        baskets: dict[str, pd.Series] = {}
        for s in self.sleeves:
            b = self.sleeve_basket(s, view, signals, notes)
            if b is None:
                return self.warmup_proposal(view, f"sleeve {s.name}: not every signal is available"), state
            baskets[s.name] = b
        # across sleeves: budget / sigma of the basket; an empty basket leaves its budget in cash
        raw: dict[str, float] = {}
        for s in self.sleeves:
            b = baskets[s.name]
            if b.empty or s.budget <= 0:  # a zero budget (single-sleeve variant) is never invested
                continue
            sig = float(self.feature("basket_vol_ewma", view, None, weights=b.to_dict(), **self._vol_kw()))
            if math.isnan(sig):
                return self.warmup_proposal(view, f"sleeve {s.name}: no basket volatility yet"), state
            signals[f"sleeve_vol:{s.name}"] = sig
            raw[s.name] = s.budget / sig
        if not raw:
            notes.append("every sleeve in cash")
            return self._banded(view, {}, signals, notes, state)
        targets = self._scaled_book(view, baskets, raw, signals, notes)
        if targets is None:
            return self.warmup_proposal(view, "no portfolio volatility yet"), state
        return self._banded(view, targets, signals, notes, state)

    def _scaled_book(
        self,
        view: MarketView,
        baskets: Mapping[str, pd.Series],
        raw: Mapping[str, float],
        signals: dict[str, float],
        notes: list[str],
    ) -> dict[str, float] | None:
        """Sleeve weights ∝ budget/σ, normalised so the invested budgets keep their share of one; then the
        book is scaled to the volatility target within the exposure caps."""
        invested = sum(s.budget for s in self.sleeves if s.name in raw)
        total = sum(raw.values())
        sleeve_w = {k: v / total * invested for k, v in raw.items()}
        book: dict[str, float] = {}
        for name, w_s in sleeve_w.items():
            for a, x in baskets[name].items():
                book[str(a)] = float(x) * w_s
        sig_p = float(self.feature("basket_vol_ewma", view, None, weights=book, **self._vol_kw()))
        if math.isnan(sig_p):
            return None
        scale = min(self.vol_target / sig_p, self.max_exposure)
        cap = max(sleeve_w.values())
        if cap * scale > self.max_sleeve:  # no sleeve above max_sleeve of the book
            scale = self.max_sleeve / cap
        signals["portfolio_vol"] = sig_p
        signals["scale"] = scale
        signals.update({f"sleeve_weight:{k}": v * scale for k, v in sleeve_w.items()})
        targets = {a: x * scale for a, x in book.items()}
        if scale > 1.0:
            notes.append(f"gross exposure {sum(targets.values()):.2f} (financed at the cash index)")
        return targets

    def _banded(
        self,
        view: MarketView,
        targets: Mapping[str, float],
        signals: dict[str, float],
        notes: list[str],
        state: StrategyState,
    ) -> tuple[Proposal, StrategyState]:
        """Trade an instrument only when its target moved by at least `band` from the last target."""
        last = {str(k): float(v) for k, v in dict(state.extra.get("targets", {})).items()}
        final: dict[str, float] = {}
        held = 0
        for a in sorted(set(targets) | set(last)):
            t, prev = float(targets.get(a, 0.0)), float(last.get(a, 0.0))
            if a in last and abs(t - prev) < self.band:
                final[a] = prev
                held += 1
            else:
                final[a] = t
        if held:
            notes.append(f"{held} target(s) within the {self.band:.0%} band kept at the last target")
        gross = float(sum(final.values()))
        if gross > self.max_exposure:  # kept targets may add up past the cap: scale the book back to it
            final = {a: w * self.max_exposure / gross for a, w in final.items()}
            notes.append(f"gross {gross:.2f} after the band: scaled back to {self.max_exposure:.2f}")
        signals["gross"] = float(sum(final.values()))
        new_state = StrategyState(
            state.strategy_id,
            positions={AssetId(a): w for a, w in final.items() if abs(w) > 1e-15},
            entries=state.entries,
            extra={"targets": {a: w for a, w in final.items() if abs(w) > 1e-15}},
        )
        strength = min(1.0, signals.get("gross", 0.0) / max(self.max_exposure, 1e-9))
        return self.proposal(view, final, strength, signals, tuple(notes)), new_state
