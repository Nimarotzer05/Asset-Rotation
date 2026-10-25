"""MarketView: the point-in-time read surface, and its factory over the store.

Guarantees (tests/unit/test_view.py, tests/lookahead/):
  1. no returned index exceeds ``view.date``;
  2. every value comes from a row with ``vintage_date <= view.date``;
  3. equal date and equal data snapshot ⇒ bit-identical frames.

Frequencies: ``None``/``"D"`` native, ``"ME"`` monthly (last value per month), ``"QE"`` quarterly.
Monthly labels are calendar month-ends; the month that contains ``view.date`` is labelled with
``view.date`` itself when the view is taken before the month is over (labels never point into the
future). At a decision date (a calendar month-end) both rules coincide.

Asset roles (universe.yaml) map to one series or a chain; `total_return` builds a total-return
index from whatever the asset provides: a level (``total_return``), periodic returns (``return``),
close plus dividends (``close``/``dividend``) or a yield (``yield``, research convention: month t
earns y(t-1)/1200).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from rotationlab.core.errors import DataError, LookaheadError
from rotationlab.core.protocols import TradingCalendar
from rotationlab.core.types import AssetId, Frequency, SeriesId, SeriesSpec
from rotationlab.data.pit import PitIndex

AS_OF_SQL = """
SELECT series_id, obs_date, value
FROM (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY series_id, obs_date ORDER BY vintage_date DESC) AS rn
  FROM observations
  WHERE obs_date <= $d AND vintage_date <= $d
)
WHERE rn = 1
ORDER BY series_id, obs_date
"""

TR_ROLES = ("total_return", "return", "close", "yield")


def as_of_pandas(observations: pd.DataFrame, d: date) -> pd.DataFrame:
    """Reference implementation of the as-of rule (the oracle the fast index is tested against).

    Returns columns [series_id, obs_date, value]: for each (series, obs_date) the latest vintage
    published on or before `d`, restricted to obs_date <= d.
    """
    df = observations
    d_ts = pd.Timestamp(d)
    df = df[(pd.to_datetime(df["obs_date"]) <= d_ts) & (pd.to_datetime(df["vintage_date"]) <= d_ts)]
    if df.empty:
        return df.loc[:, ["series_id", "obs_date", "value"]].copy()
    df = df.sort_values(["series_id", "obs_date", "vintage_date"])
    latest = df.groupby(["series_id", "obs_date"], as_index=False).tail(1)
    return latest.loc[:, ["series_id", "obs_date", "value"]].reset_index(drop=True)


def assert_no_lookahead(frame: pd.DataFrame | pd.Series, d: date) -> None:
    """Guard used inside every MarketView method before returning."""
    if len(frame.index) and pd.Timestamp(frame.index.max()) > pd.Timestamp(d):
        raise LookaheadError(f"view at {d} returned data dated {frame.index.max()}")


def resample_last(s: pd.Series, freq: str | None, d: pd.Timestamp) -> pd.Series:
    """Last value per period; period labels are period ends, capped at `d` (numpy, index must be sorted)."""
    if freq in (None, "D") or s.empty:
        return s
    if freq not in ("ME", "QE"):
        raise ValueError(f"unsupported frequency '{freq}' (use None, 'D', 'ME' or 'QE')")
    months = s.index.to_numpy(dtype="datetime64[ns]").astype("datetime64[M]")
    key = months.astype("int64") // (1 if freq == "ME" else 3)
    last = np.r_[key[1:] != key[:-1], True]
    if freq == "ME":
        end_month = months[last]
    else:
        end_month = (key[last] * 3 + 2).astype("datetime64[M]")
    labels = (end_month + np.timedelta64(1, "M")).astype("datetime64[D]") - np.timedelta64(1, "D")
    labels = np.minimum(labels.astype("datetime64[ns]"), np.datetime64(d, "ns"))
    return pd.Series(s.to_numpy()[last], index=pd.DatetimeIndex(labels), name=s.name)


class _Prefix:
    """A causal series known in full, read as its first k rows (simple series, total-return indices).

    Period resampling of a prefix = the complete periods of the full resample plus the running period,
    computed once per frequency instead of once per view date (ADR 028)."""

    def __init__(self, full: pd.Series) -> None:
        self.index = pd.DatetimeIndex(full.index)
        self.values = full.to_numpy()
        self.name = full.name
        self._groups: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def native(self, k: int) -> pd.Series:
        return pd.Series(self.values[:k].copy(), index=self.index[:k], name=self.name)

    def _group(self, freq: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if freq not in self._groups:
            months = self.index.to_numpy(dtype="datetime64[ns]").astype("datetime64[M]")
            key = months.astype("int64") // (1 if freq == "ME" else 3)
            is_last = np.r_[key[1:] != key[:-1], True] if len(key) else np.array([], dtype=bool)
            last_pos = np.flatnonzero(is_last)
            end_month = months[is_last] if freq == "ME" else (key[is_last] * 3 + 2).astype("datetime64[M]")
            labels = (
                (end_month + np.timedelta64(1, "M")).astype("datetime64[D]") - np.timedelta64(1, "D")
            ).astype("datetime64[ns]")
            gid = np.cumsum(np.r_[0, is_last[:-1]]) if len(key) else np.array([], dtype=np.int64)
            self._groups[freq] = (last_pos, labels, gid)
        return self._groups[freq]

    def periods(self, k: int, freq: str, d: pd.Timestamp) -> pd.Series:
        if k == 0:
            return pd.Series(
                self.values[:0], index=pd.DatetimeIndex([], dtype="datetime64[ns]"), name=self.name
            )
        last_pos, labels, gid = self._group(freq)
        g = int(gid[k - 1])
        vals = np.r_[self.values[last_pos[:g]], self.values[k - 1]]
        labs = np.r_[labels[:g], labels[g]].astype("datetime64[ns]")
        labs = np.minimum(labs, np.datetime64(d, "ns"))
        return pd.Series(vals, index=pd.DatetimeIndex(labs), name=self.name)


@dataclass(frozen=True)
class Segment:
    series_id: str
    start: date
    end: date
    scale: float


class StoreViewFactory:
    """ViewFactory over a frame of observations (from the store, or a test fixture)."""

    def __init__(
        self,
        observations: pd.DataFrame,
        catalog: Mapping[str, SeriesSpec],
        assets: Mapping[str, Mapping[str, Sequence[str]]],
        calendar: TradingCalendar,
        snapshot: str | None = None,
        chains: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self._index = PitIndex(observations)
        self.catalog = dict(catalog)
        self.assets = {a: {r: list(c) for r, c in roles.items()} for a, roles in assets.items()}
        self.chains = {k: list(v) for k, v in (chains or {}).items()}
        self.fast = True  # prefix caches; False = reference path (tests)
        self._prefix: dict[str, _Prefix] = {}
        self._tr_prefix: dict[str, tuple[_Prefix, str, int] | None] = {}
        self.cal = calendar
        self._snapshot = snapshot or _frame_digest(observations)
        self._cache: dict[tuple[str, pd.Timestamp], pd.Series] = {}

    # -- constructors -------------------------------------------------------
    @classmethod
    def from_store(
        cls,
        store: Any,
        catalog: Mapping[str, SeriesSpec],
        universe: Any,
        calendar: TradingCalendar,
        providers: Sequence[str] | None = None,
        chains: Mapping[str, Sequence[str]] | None = None,
    ) -> StoreViewFactory:
        """`providers` restricts the view to some sources (e.g. ["static"] for the frozen golden panel)."""
        obs = store.observations()
        if providers is not None:
            obs = obs[obs["series_id"].str.split(":").str[0].isin(list(providers))]
        return cls(obs, catalog, asset_roles(universe), calendar, snapshot=store.snapshot_id(), chains=chains)

    # -- ViewFactory protocol -----------------------------------------------
    def at(self, d: date) -> StoreView:
        return StoreView(self, pd.Timestamp(d).normalize())

    def precompute(self, dates: Sequence[date]) -> None:
        """Nothing to precompute: as-of reads are O(log n) on the interval index."""

    def data_snapshot(self) -> str:
        return self._snapshot

    # -- internals ------------------------------------------------------------
    def raw_as_of(self, series_id: str, d: pd.Timestamp) -> pd.Series:
        key = (series_id, d)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._index.as_of(series_id, d)
            if len(self._cache) > 20000:
                self._cache.clear()
            self._cache[key] = hit
        return hit

    def prefix(self, series_id: str) -> _Prefix | None:
        if not self.fast or not self._index.is_simple(series_id):
            return None
        if series_id not in self._prefix:
            self._prefix[series_id] = _Prefix(self._index.full(series_id))
        return self._prefix[series_id]

    def prefix_len(self, series_id: str, d: pd.Timestamp) -> int:
        return self._index.prefix_len(series_id, d)

    def tr_prefix(self, asset: str) -> tuple[_Prefix, str, int] | None:
        """Full total-return index of an asset whose TR depends causally on one simple series (+ dividends):
        (prefix, primary series, offset) – the TR as of D is the first k + offset rows, k = rows of the
        primary known at D (offset 1 for return series: their index starts with the base 100, k > 0)."""
        if not self.fast:
            return None
        if asset not in self._tr_prefix:
            self._tr_prefix[asset] = self._build_tr_prefix(asset)
        return self._tr_prefix[asset]

    def _build_tr_prefix(self, asset: str) -> tuple[_Prefix, str, int] | None:
        roles = self.assets.get(asset, {})
        role = next((r for r in TR_ROLES if r in roles), None)
        if role is None or len(roles[role]) != 1:
            return None
        primary = roles[role][0]
        if not self._index.is_simple(primary):
            return None
        s = self._index.full(primary)
        if role == "total_return":
            tr = s
        elif role == "return":
            tr = _return_index(s, self.spec(primary).frequency)
        elif role == "close":
            div_chain = roles.get("dividend", [])
            if len(div_chain) > 1 or self.spec(primary).lag != "0D":
                return None
            div = None
            if div_chain:
                if self.spec(div_chain[0]).lag != "0D" or (
                    div_chain[0] in self._index and not self._index.is_simple(div_chain[0])
                ):
                    return None
                div = self._index.full(div_chain[0]) if div_chain[0] in self._index else None
            tr = _close_tr(s, div)
        else:  # yield: only the monthly research formula is a causal function of the yield rows
            if self.spec(primary).frequency != Frequency.MONTHLY:
                return None
            tr = 100.0 * (1.0 + s.shift(1) / 1200.0).fillna(1.0).cumprod()
        return _Prefix(tr.rename(asset)), primary, int(role == "return")

    def spec(self, series_id: str) -> SeriesSpec:
        s = self.catalog.get(series_id)
        if s is None:
            raise DataError(f"series {series_id} is not in the catalog")
        return s

    def vintages_as_of(self, series_id: str, d: date) -> pd.Series:
        return self._index.vintage_as_of(series_id, pd.Timestamp(d))


class StoreView:
    """Immutable point-in-time view. All methods are pure functions of (store snapshot, date)."""

    def __init__(self, factory: StoreViewFactory, d: pd.Timestamp) -> None:
        self._f = factory
        self._d = d
        self.date: date = d.date()
        self._prov: dict[tuple[str, str], list[Segment]] = {}
        self._tr_memo: dict[tuple[tuple[str, ...], str | None], pd.DataFrame] = {}
        self.memo: dict[Any, Any] = {}  # feature results of this view (core/registry.py); pure, so safe

    # -- raw series --------------------------------------------------------------
    def series(self, series_id: SeriesId | str, freq: str | None = None) -> pd.Series:
        """A stored series, or a macro chain from series.yaml (``macro:CPI``: FRED/ALFRED, then BLS)."""
        sid = str(series_id)
        pre = None if sid in self._f.chains else self._f.prefix(sid)
        if pre is not None:
            k = self._f.prefix_len(sid, self._d)
            s = pre.periods(k, freq, self._d) if freq in ("ME", "QE") else pre.native(k)
            assert_no_lookahead(s, self.date)
            return s
        if sid in self._f.chains:
            raw, segs = self._splice(self._f.chains[sid])
            self._prov[(sid, "")] = segs
            raw = raw.rename(sid)
        else:
            raw = self._f.raw_as_of(sid, self._d)
        s = resample_last(raw, freq, self._d)
        assert_no_lookahead(s, self.date)
        return s.copy()

    def chain_provenance(self, chain_id: str) -> list[Segment]:
        if (chain_id, "") not in self._prov:
            self.series(chain_id)
        return list(self._prov[(chain_id, "")])

    def panel(self, series_ids: Sequence[SeriesId | str], freq: str | None = "ME") -> pd.DataFrame:
        cols = {str(s): self.series(s, freq) for s in series_ids}
        df = pd.DataFrame(cols) if cols else pd.DataFrame()
        assert_no_lookahead(df, self.date)
        return df

    def last_obs(self, series_id: SeriesId | str) -> date | None:
        s = (
            self.series(series_id)
            if str(series_id) in self._f.chains
            else self._f.raw_as_of(str(series_id), self._d)
        )
        return None if s.empty else s.index[-1].date()

    def calendar(self) -> TradingCalendar:
        return self._f.cal

    # -- asset roles ---------------------------------------------------------------
    def roles(self, asset: AssetId | str) -> Mapping[str, Sequence[str]]:
        r = self._f.assets.get(str(asset))
        if r is None:
            raise DataError(f"unknown asset {asset}")
        return r

    def asset_series(self, asset: AssetId | str, role: str) -> pd.Series:
        """Native-frequency series of an asset role, chain spliced (see `provenance`)."""
        chain = self.roles(asset).get(role)
        if not chain:
            raise DataError(f"asset {asset} has no role '{role}'")
        s, segs = self._splice(chain)
        self._prov[(str(asset), role)] = segs
        assert_no_lookahead(s, self.date)
        return s.rename(str(asset))

    def provenance(self, asset: AssetId | str, role: str) -> list[Segment]:
        if (str(asset), role) not in self._prov:
            self.asset_series(asset, role)
        return list(self._prov[(str(asset), role)])

    def close(self, assets: Sequence[AssetId | str], lookback_days: int | None = None) -> pd.DataFrame:
        df = pd.DataFrame({str(a): self.asset_series(a, "close") for a in assets})
        if lookback_days is not None and len(df):
            df = df[df.index >= self._d - pd.Timedelta(days=lookback_days)]
        assert_no_lookahead(df, self.date)
        return df

    def total_return(self, assets: Sequence[AssetId | str], freq: str | None = "ME") -> pd.DataFrame:
        """Total-return levels (memoised per view: features of one decision read the same panel several
        times; callers get a copy, so the memo cannot be altered)."""
        key = (tuple(str(a) for a in assets), freq)
        hit = self._tr_memo.get(key)
        if hit is None:
            hit = self._total_return(assets, freq)
            self._tr_memo[key] = hit
        return hit.copy()

    def _total_return(self, assets: Sequence[AssetId | str], freq: str | None) -> pd.DataFrame:
        cols = {}
        for a in assets:
            fast = self._f.tr_prefix(str(a)) if freq in (None, "D", "ME", "QE") else None
            if fast is not None and not (freq in (None, "D") and "yield" in self.roles(a)):
                pre, primary, offset = fast
                k = self._f.prefix_len(primary, self._d)
                k = k + offset if k else 0
                cols[str(a)] = pre.periods(k, freq, self._d) if freq in ("ME", "QE") else pre.native(k)
                continue
            idx = self._tr_index(str(a), freq)
            cols[str(a)] = resample_last(idx, freq, self._d)
        df = pd.DataFrame(cols)
        assert_no_lookahead(df, self.date)
        return df

    def returns(self, assets: Sequence[AssetId | str], freq: str | None = "ME") -> pd.DataFrame:
        """Simple period returns from `total_return` (first row of each asset is NaN)."""
        tr = self.total_return(assets, freq)
        return tr / tr.shift(1) - 1.0

    # -- internals -----------------------------------------------------------------
    def _splice(self, chain: Sequence[str]) -> tuple[pd.Series, list[Segment]]:
        primary = chain[0]
        level = self._f.spec(primary).kind.is_level
        out = self._f.raw_as_of(primary, self._d)
        segs = [Segment(primary, out.index[0].date(), out.index[-1].date(), 1.0)] if len(out) else []
        for sid in chain[1:]:
            s = self._f.raw_as_of(sid, self._d)
            if s.empty:
                continue
            if out.empty:
                out = s
                segs.append(Segment(sid, s.index[0].date(), s.index[-1].date(), 1.0))
                continue
            first, last = out.index[0], out.index[-1]
            before, after = s[s.index < first], s[s.index > last]
            if len(before):
                scale = _anchor_scale(out, s, first) if level else 1.0
                if np.isfinite(scale):
                    out = pd.concat([before * scale, out])
                    segs.insert(0, Segment(sid, before.index[0].date(), before.index[-1].date(), scale))
            if len(after):
                scale = _anchor_scale(out, s, last) if level else 1.0
                if np.isfinite(scale):
                    out = pd.concat([out, after * scale])
                    segs.append(Segment(sid, after.index[0].date(), after.index[-1].date(), scale))
        return out.sort_index(), segs

    def _tr_index(self, asset: str, freq: str | None) -> pd.Series:
        roles = self.roles(asset)
        if "total_return" in roles:
            return self.asset_series(asset, "total_return")
        if "return" in roles:
            r = self.asset_series(asset, "return")
            return _return_index(r, self._f.spec(roles["return"][0]).frequency)
        if "close" in roles:
            px = self.asset_series(asset, "close")
            div = self.asset_series(asset, "dividend") if "dividend" in roles else None
            return _close_tr(px, div)
        if "yield" in roles:
            y = self.asset_series(asset, "yield")
            spec = self._f.spec(roles["yield"][0])
            return _yield_index(y, spec, freq, self._f.cal, self._d)
        raise DataError(f"asset {asset} has no total-return role ({', '.join(TR_ROLES)})")


def _return_index(r: pd.Series, freq: Frequency) -> pd.Series:
    """Index from periodic returns: 100 at the end of the period before the first return, so the first
    return is not lost (a return for July is the change from the June close to the July close). The base
    point carries no information: it exists only once the first return is known."""
    if r.empty:
        return r
    first = pd.Timestamp(r.index[0])
    if freq == Frequency.MONTHLY:
        base = first - pd.offsets.MonthEnd(1)
    elif freq == Frequency.QUARTERLY:
        base = first - pd.offsets.QuarterEnd(1)
    elif freq == Frequency.WEEKLY:
        base = first - pd.Timedelta(days=7)
    else:
        base = first - pd.Timedelta(days=1)
    lvl = 100.0 * (1.0 + r).cumprod()
    head = pd.Series([100.0], index=pd.DatetimeIndex([base]).as_unit(pd.DatetimeIndex(r.index).unit))
    return pd.Series(pd.concat([head, lvl]), name=r.name)


def _close_tr(px: pd.Series, div: pd.Series | None) -> pd.Series:
    """Total-return index from closes and cash dividends; a dividend on a day without a close is paid on
    the next close. Causal: the first k values depend only on the first k closes."""
    if div is not None and len(div):
        div = div[div.index <= px.index[-1]] if len(px) else div.iloc[:0]
        pos = px.index.searchsorted(div.index, side="left")
        arr = np.zeros(len(px))
        np.add.at(arr, pos, div.to_numpy(dtype=float))
        cash = pd.Series(arr, index=px.index)
    else:
        cash = pd.Series(0.0, index=px.index)
    gross = (px + cash) / px.shift(1)
    gross.iloc[:1] = 1.0
    return 100.0 * gross.cumprod()


def _anchor_scale(out: pd.Series, other: pd.Series, at: pd.Timestamp) -> float:
    """Ratio that makes `other` continuous with `out` at date `at`.

    Exact date if `other` has it; otherwise the overlap date nearest to `at` (both series price the same
    asset, so any common session gives the ratio without inventing a flat return, Fable review
    2026-10-24); without any overlap the last `other` value before `at`, else the first after."""
    if at in other.index:
        ref_date = at
    else:
        common = pd.DatetimeIndex(out.index.intersection(other.index))
        if len(common):
            ns = common.to_numpy(dtype="datetime64[ns]").astype(np.int64)
            ref_date = common[int(np.argmin(np.abs(ns - at.value)))]
        else:
            prior = other[other.index <= at]
            if prior.empty:
                later = other[other.index >= at]
                if later.empty:
                    return float("nan")
                ref = later.iloc[0]
            else:
                ref = prior.iloc[-1]
            return float(out.loc[at] / ref) if ref != 0 else float("nan")
    ref = other.loc[ref_date]
    return float(out.loc[ref_date] / ref) if ref != 0 else float("nan")


def _yield_index(
    y: pd.Series, spec: SeriesSpec, freq: str | None, cal: TradingCalendar, d: pd.Timestamp
) -> pd.Series:
    """Cash index from a yield in percent p.a."""
    if y.empty:
        return y
    if spec.frequency == Frequency.MONTHLY:
        monthly = 1.0 + y.shift(1) / 1200.0  # research: TBILL_t = TBILL_{t-1} (1 + y_{t-1}/1200)
        idx = 100.0 * monthly.fillna(1.0).cumprod()
        if freq in ("ME", "QE"):
            return idx
        # daily: spread each month's factor evenly over its sessions, so month-ends match the monthly index
        first, last = pd.Timestamp(y.index[0]), pd.Timestamp(d)
        month_sessions = _sessions(
            cal, (first - pd.offsets.MonthBegin(1)).date(), (last + pd.offsets.MonthEnd(0)).date()
        )
        lo = np.searchsorted(month_sessions, np.datetime64(first.date(), "D"))
        hi = np.searchsorted(month_sessions, np.datetime64(last.date(), "D"), side="right")
        day_arr = month_sessions[lo:hi]
        if day_arr.size == 0:
            return idx
        codes_all = month_sessions.astype("datetime64[M]").astype(np.int64)
        uniq, counts = np.unique(codes_all, return_counts=True)
        codes = day_arr.astype("datetime64[M]").astype(np.int64)
        n = counts[np.searchsorted(uniq, codes)].astype(float)
        rate = (y / 1200.0).groupby(pd.DatetimeIndex(y.index).to_period("M")).last()
        rate_codes = (
            (pd.PeriodIndex(rate.index).year.to_numpy() - 1970) * 12
            + pd.PeriodIndex(rate.index).month.to_numpy()
            - 1
        )
        applies = pd.Series(rate.to_numpy(), index=rate_codes + 1)  # month p earns the yield of p-1
        prev_rate = applies.reindex(codes).fillna(0.0).to_numpy()
        daily = np.power(1.0 + prev_rate, 1.0 / n)
        return pd.Series(100.0 * np.cumprod(daily), index=pd.DatetimeIndex(day_arr.astype("datetime64[ns]")))
    # daily yields: accrue act/365 between observations
    dt = y.index.to_series().diff().dt.days.fillna(0).to_numpy()
    growth = np.power(1.0 + y.shift(1).fillna(0).to_numpy() / 100.0, dt / 365.0)
    return pd.Series(100.0 * np.cumprod(growth), index=y.index)


_SESSIONS: dict[int, tuple[TradingCalendar, np.ndarray]] = {}


def _sessions(cal: TradingCalendar, start: date, end: date) -> np.ndarray:
    """Trading sessions in [start, end] as datetime64[D], from a per-calendar cache that grows by whole years
    (the daily cash index asks for decades of sessions at every view date)."""
    hit = _SESSIONS.get(id(cal))
    s64, e64 = np.datetime64(start, "D"), np.datetime64(end, "D")
    week = np.timedelta64(7, "D")
    cached = hit[1] if hit is not None and hit[0] is cal and hit[1].size > 0 else None
    if cached is None or s64 < cached[0] - week or e64 > cached[-1] + week:
        years = [start.year, end.year]
        if cached is not None:
            years += [int(str(cached[0])[:4]), int(str(cached[-1])[:4])]
        cached = np.array(
            cal.trading_days(date(min(years), 1, 1), date(max(years), 12, 31)), dtype="datetime64[D]"
        )
        _SESSIONS[id(cal)] = (cal, cached)
    arr = cached
    return arr[np.searchsorted(arr, s64) : np.searchsorted(arr, e64, side="right")]


def asset_roles(universe: Any) -> dict[str, dict[str, list[str]]]:
    """UniverseConfig (or mapping) → {asset: {role: [series ids]}}."""
    assets = universe.assets if hasattr(universe, "assets") else universe
    out: dict[str, dict[str, list[str]]] = {}
    for aid, a in assets.items():
        series = a.series if hasattr(a, "series") else a["series"]
        out[aid] = {role: ([v] if isinstance(v, str) else list(v)) for role, v in series.items()}
    return out


def _frame_digest(obs: pd.DataFrame) -> str:
    if obs.empty:
        return "empty"
    h = pd.util.hash_pandas_object(
        obs.loc[:, ["series_id", "obs_date", "vintage_date", "value"]], index=False
    )
    return "frame/" + hashlib.sha256(h.to_numpy().tobytes()).hexdigest()[:12]
