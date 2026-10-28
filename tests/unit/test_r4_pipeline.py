"""Round 4 pipeline before the data (ADR 058): the data gates, the registration template and the window rule."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from rotationlab.config.models import StrategyConfig
from rotationlab.data.calendar import NYSECalendar
from rotationlab.data.providers import constructs_r4 as r4
from rotationlab.forecast.evaluation import common_data_end, last_full_month

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gates = _load_script("r4_data_check")
reg = _load_script("r4_register")

PER_USD = {"JPY": "DEXJPUS", "CHF": "DEXSZUS", "CAD": "DEXCAUS", "SEK": "DEXSDUS", "NOK": "DEXNOUS"}
USD_PER = {"GBP": "DEXUSUK", "AUD": "DEXUSAL", "NZD": "DEXUSNZ"}


def _gz(df: pd.DataFrame, path: Path) -> None:
    path.write_bytes(gzip.compress(df.rename_axis("date").to_csv(date_format="%Y-%m-%d").encode(), mtime=0))


def _world(tmp: Path, *, invert_gbp: bool = False, local_countries: bool = False) -> dict[str, object]:
    """A consistent little world 1971–1985 in the frozen formats, and the comparison series of the static panel."""
    rng = np.random.default_rng(5)
    days = pd.bdate_range("1971-01-04", "1985-12-31")
    dollar = np.cumsum(0.004 * rng.standard_normal(len(days)))  # common dollar factor (log)
    usd_per = {c: np.exp(-dollar + np.cumsum(0.003 * rng.standard_normal(len(days)))) for c in r4.FX_SPOT}
    fred = pd.DataFrame(index=days)
    for ccy, code in PER_USD.items():
        fred[code] = 1.0 / usd_per[ccy]
    for ccy, code in USD_PER.items():
        fred[code] = usd_per[ccy] if not (invert_gbp and ccy == "GBP") else 1.0 / usd_per[ccy]
    fred["DEXGEUS"] = r4.DEM_PER_EUR / usd_per["EUR"]
    fred["DEXUSEU"] = np.nan
    fred.loc[days >= pd.Timestamp("1980-01-02"), "DEXUSEU"] = usd_per["EUR"][
        days >= pd.Timestamp("1980-01-02")
    ]
    fred.loc[days >= pd.Timestamp("1980-01-02"), "DEXGEUS"] = np.nan
    y = 6.0 + np.cumsum(0.04 * rng.standard_normal(len(days)))
    fred["DGS2"], fred["DGS5"], fred["DGS10"] = y, y + 0.4, y + 0.9
    me = pd.date_range("1970-01-31", "1985-12-31", freq="ME")
    rates = pd.DataFrame(
        {f"IR3TIB01{a}M156N": 5.0 for a in ("JP", "GB", "CH", "CA", "AU", "NZ", "SE", "NO", "DE", "EZ")},
        index=me,
    )
    ind = pd.DataFrame(
        0.0004 + 0.01 * rng.standard_normal((len(days), 10)), index=days, columns=list(reg.INDUSTRIES)
    )
    cm = pd.date_range("1975-01-31", "1985-12-31", freq="ME")
    fx_m = {
        c: np.log(pd.Series(usd_per[c], index=days).resample("ME").last()).diff().reindex(cm)
        for c in ("JPY", "GBP", "EUR")
    }
    local = {
        k: pd.Series(0.008 + 0.04 * rng.standard_normal(len(cm)), index=cm)
        for k in ("Japan", "UK", "Germany")
    }
    countries = pd.DataFrame(
        {
            k: v if local_countries else v + fx_m[{"Japan": "JPY", "UK": "GBP", "Germany": "EUR"}[k]]
            for k, v in local.items()
        }
    )
    _gz(fred, tmp / "r4_fred_daily.csv.gz")
    _gz(rates, tmp / "r4_oecd_rates_monthly.csv.gz")
    _gz(ind, tmp / "ff_10_industry_daily.csv.gz")
    _gz(countries, tmp / "ff_intl_countries_monthly.csv.gz")
    files = {
        "fred/DGS2": {"required": True, "status": "ok"},
        "fred/IRSTCI01GBM156N": {"required": False, "status": "error: HTTP 400"},
    }
    (tmp / "r4_PROVENANCE.json").write_text(json.dumps({"manifest": {"files": files}}))
    daily = r4.build_daily(fred, rates, ind)
    return {
        "ind10": (1.0 + ind).resample("ME").prod() - 1.0,
        "UST10_ME": daily["UST10_D"].resample("ME").last(),
        "UST2_ME": daily["UST2_D"].resample("ME").last(),
        "DTWEXM": pd.Series(np.exp(dollar), index=days),
    }


def test_the_data_gates_pass_on_consistent_data(tmp_path) -> None:
    ref = _world(tmp_path)
    result, lines = gates.check(str(tmp_path), ref)
    assert [ok for _, ok, _ in result] == [True] * 6, result
    assert "fred/IRSTCI01GBM156N" in result[0][2]  # a missing optional source is reported
    assert any(ln.startswith("- EUR: DE: 3M ab") for ln in lines)


@pytest.mark.parametrize(
    ("kw", "failed"),
    [({"invert_gbp": True}, "G4"), ({"local_countries": True}, "G5")],
)
def test_the_data_gates_stop_on_a_wrong_convention(tmp_path, kw, failed) -> None:
    ref = _world(tmp_path, **kw)
    result, _ = gates.check(str(tmp_path), ref)
    bad = [g for g, ok, _ in result if not ok]
    assert len(bad) == 1 and bad[0].startswith(failed)


def test_the_data_gates_stop_on_the_wrong_industry_section(tmp_path) -> None:
    ref = _world(tmp_path)
    ref["ind10"] = (
        ref["ind10"] * 1.3
    )  # e.g. the equal-weighted block parsed instead of the value-weighted one
    result, _ = gates.check(str(tmp_path), ref)
    assert [g for g, ok, _ in result if not ok] == ["G2 Industrien täglich = Monatsdatei"]


def test_the_registration_template_is_the_pre_registered_rule() -> None:
    ctry = ["JAPAN", "UK"]
    cfg = StrategyConfig(**yaml.safe_load(reg.strategy_yaml(ctry, ("1977-01-31", "2025-11-30"))))
    p = cfg.params
    assert cfg.role == "paper" and set(cfg.universe) == set(cfg.long_history_universe)
    budgets = {k: v["budget"] for k, v in p["sleeves"].items()}
    assert budgets == {"EQ_US": 0.125, "EQ_INTL": 0.125, "FI": 0.25, "FX": 0.25, "PM": 0.25}
    assert p["sleeves"]["EQ_INTL"]["instruments"] == ["CTRY_JAPAN", "CTRY_UK"]
    assert p["sleeves"]["FX"]["mode"] == "long_short_xs" and p["sleeves"]["FX"]["group"] == "overlay"
    assert (
        p["caps"] == {"physical": 1.0, "physical_plus_rates": 1.5, "overlay_gross": 0.5} and p["band"] == 0.0
    )
    assert all(s["max_age_months"] == 3 for s in p["feature_params"]["carry_yield"]["spec"].values())
    gr = cfg.golden_run
    assert gr is not None and gr.execution == "next_tradable" and gr.costs.borrow_bps == {"CASH": 30.0}
    assert (
        p["cash"] == "TBILL_IY" and cfg.universe[-1] == "TBILL_IY" and gr.costs.per_asset["TBILL_IY"] == 0.0
    )
    costs = gr.costs.per_asset
    assert costs["IND_NODUR"] == 10.0 and costs["CTRY_UK"] == 20.0 and costs["UST5_D"] == 3.0
    assert costs["FX_EUR"] == 3.0 and costs["GOLD_D"] == 10.0 and costs["SILVER"] == 15.0
    block = reg.universe_block(ctry)
    assets = yaml.safe_load("assets:\n" + block)["assets"]
    assert len(assets) == 10 + 2 + 3 + 9 and assets["FX_JPY"]["asset_class"] == "currency"
    uni = "assets:\n  A: {}\n  # ---- tradable ETF universe (live), mapped to long-history proxies ----\n  B: {}\n"
    once = reg.universe_with_block(uni, block)
    assert reg.universe_with_block(once, block) == once  # idempotent: replaced, never duplicated


def test_window_end_is_the_earliest_complete_month_over_the_data_groups() -> None:
    cal = NYSECalendar()
    daily = pd.Series(1.0, index=pd.bdate_range("2025-01-02", "2026-02-25"))  # stops mid-month (LBMA)
    assert last_full_month(daily, cal) == pd.Timestamp("2026-01-31")
    full = pd.Series(1.0, index=pd.bdate_range("2025-01-02", "2026-08-31"))  # last NYSE session of August
    assert last_full_month(full, cal) == pd.Timestamp("2026-08-31")
    monthly = pd.Series(1.0, index=pd.date_range("2020-01-31", "2025-12-31", freq="ME"))
    assert last_full_month(monthly, cal) == pd.Timestamp("2025-12-31")
    countries = pd.DataFrame(
        {"A": monthly, "B": monthly[monthly.index <= "1998-08-31"]}
    )  # B leaves the data early
    end, per = common_data_end(
        {"PM": daily.to_frame("G"), "EQ_INTL": countries, "IND": full.to_frame("I")}, cal
    )
    assert per["EQ_INTL"] == pd.Timestamp("2025-12-31")  # an early exit does not cut the window
    assert end == pd.Timestamp("2025-12-31")
    with pytest.raises(ValueError, match="no data"):
        common_data_end({"X": pd.DataFrame({"A": [np.nan]})}, cal)


def test_the_bill_index_earns_the_investment_yield() -> None:
    """ADR 058 (h): TB3MS is a discount rate; a holder earns the investment yield (+0.13/0.40/0.71 pp at 5/10/14 %)."""
    from rotationlab.data.providers.static import bill_investment_yield

    y = bill_investment_yield(pd.Series([5.0, 10.0, 14.0]))
    assert (y - pd.Series([5.0, 10.0, 14.0])).tolist() == pytest.approx([0.134, 0.402, 0.715], abs=1e-3)
    d = 0.05
    assert y.iloc[0] / 100 == pytest.approx((1 / (1 - d * 91 / 360) - 1) * 365 / 91)


def test_the_round4_series_stay_out_of_the_catalog_until_the_data_is_frozen(tmp_path) -> None:
    """ADR 058: with `R4_COUNTRIES` empty the static catalog and its raw-file fingerprint are those of round 3; with
    the countries filled the catalog holds every round-4 series, and the loaders build them from the frozen files."""
    from rotationlab.core.types import Frequency, SeriesKind
    from rotationlab.data.providers import static as st

    assert st.R4_COUNTRIES == () and not [k for k in st.STATIC_CATALOG if k.startswith("static:r4:")]
    assert "r4_fred_daily.csv.gz" not in st.StaticProvider(tmp_path)._all_files()
    cat = st._build_catalog(("JAPAN", "UK"))
    r4ids = sorted(k for k in cat if k.startswith("static:r4:"))
    assert len(r4ids) == 9 + 3 + 10 + 9 + 2
    assert (
        cat["static:r4:RATE_JPY"].spec.lag == "1M" and cat["static:r4:RATE_JPY"].spec.kind == SeriesKind.YIELD
    )
    assert (
        cat["static:r4:CTRY_UK"].spec.frequency == Frequency.MONTHLY
        and cat["static:r4:FX_EUR"].spec.lag == "0D"
    )
    _world(tmp_path)
    prov = st.StaticProvider(tmp_path)
    daily, rates, ctry = prov._load_r4_daily(), prov._load_r4_rates(), prov._load_r4_countries()
    assert {e.column for e in cat.values() if e.group == "r4_daily"} <= set(daily.columns)
    assert {e.column for e in cat.values() if e.group == "r4_rates"} == set(rates.columns)
    assert sorted(ctry.columns) == ["CTRY_GERMANY", "CTRY_JAPAN", "CTRY_UK"]
