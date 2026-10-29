"""Round 5 (ADR 063): the macro component of the forecast score – synthetic inputs only.

* ridge_path equals the direct formula on the training sample of every row (running sums are only a speed-up)
* no look-ahead: changing an outcome or a state value after row t leaves m[t] unchanged
* the minimum training length, the carry-forward of a missing state value, a known linear relation
* real_policy_rate = Fed funds − CPI year-on-year rate one month back
* the blended score = (1 − w)·composite + w·z(m) and the config's validation
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rotationlab.config.models import MacroComponentConfig
from rotationlab.features.macro import _real_policy
from rotationlab.forecast.macro import ridge_path, ridge_reference


def _data(n: int = 260, k: int = 3, c: int = 4, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1970-01-31", periods=n, freq="ME")
    x = pd.DataFrame(
        rng.normal(size=(n, k)) * [1.0, 3.0, 0.2] + [0.0, 5.0, -1.0], index=idx, columns=["a", "b", "c"]
    )
    beta = rng.normal(size=(k, c)) * 0.01
    y = pd.DataFrame(x.to_numpy() @ beta + rng.normal(size=(n, c)) * 0.03, index=idx, columns=list("WXYZ"))
    y.iloc[-1] = np.nan  # the last month's outcome is not known yet
    return x, y


def test_ridge_path_equals_the_direct_formula_on_each_training_sample() -> None:
    x, y = _data()
    x.iloc[30, 1] = np.nan  # an incomplete month is no training month
    y.iloc[50, 2] = np.nan
    m = ridge_path(x, y, lam=1.0, min_train=60)
    ok = x.notna().all(axis=1) & y.notna().all(axis=1)
    assert m.iloc[61].isna().all()  # rows 0–60 hold only 59 complete months (30 and 50 are incomplete)
    for t in [62, 63, 100, 180, len(x) - 1]:
        train = ok & (np.arange(len(x)) < t)
        ref = ridge_reference(x[train].to_numpy(), y[train].to_numpy(), x.iloc[t].to_numpy(), 1.0)
        assert np.allclose(m.iloc[t].to_numpy(), ref, atol=1e-12), t


def test_minimum_training_length() -> None:
    x, y = _data()
    m = ridge_path(x, y, lam=1.0, min_train=60)
    assert m.iloc[:60].isna().all().all() and m.iloc[60].notna().all()


def test_no_lookahead_from_later_outcomes_or_states() -> None:
    x, y = _data()
    m = ridge_path(x, y, lam=1.0, min_train=60)
    t = 150
    x2, y2 = x.copy(), y.copy()
    y2.iloc[t:] = 1e6  # outcomes of month t and later (known only after t)
    x2.iloc[t + 1 :] = -1e6  # states after t
    m2 = ridge_path(x2, y2, lam=1.0, min_train=60)
    assert np.array_equal(m.iloc[: t + 1].to_numpy(), m2.iloc[: t + 1].to_numpy(), equal_nan=True)
    assert not np.allclose(m.iloc[t + 1 :].to_numpy(), m2.iloc[t + 1 :].to_numpy())


def test_a_missing_state_is_carried_forward_only_so_far() -> None:
    x, y = _data()
    x.iloc[200:203, 0] = np.nan  # three months without the first variable
    m = ridge_path(x, y, lam=1.0, min_train=60, ffill=2)
    assert m.iloc[200:202].notna().all().all() and m.iloc[202].isna().all()
    assert ridge_path(x, y, lam=1.0, min_train=60).iloc[200].isna().all()


def test_recovers_the_sign_of_a_known_relation() -> None:
    rng = np.random.default_rng(3)
    idx = pd.date_range("1960-01-31", periods=600, freq="ME")
    x = pd.DataFrame({"ff": rng.normal(size=600)}, index=idx)
    y = pd.DataFrame({"BOND": -0.02 * x["ff"] + rng.normal(size=600) * 0.01}, index=idx)
    y["EQ"] = -y["BOND"]
    m = ridge_path(x, y, lam=1.0, min_train=120)
    last = m.iloc[-1]
    assert np.sign(last["BOND"]) == -np.sign(x["ff"].iloc[-1]) and last["EQ"] == pytest.approx(-last["BOND"])


def test_index_mismatch_is_an_error() -> None:
    x, y = _data()
    with pytest.raises(ValueError, match="same index"):
        ridge_path(x, y.iloc[1:], lam=1.0, min_train=60)


def test_real_policy_rate_definition() -> None:
    idx = pd.date_range("2000-01-31", periods=15, freq="ME")
    cpi = pd.Series(100.0 * 1.003 ** np.arange(15), index=idx)
    panel = pd.DataFrame({"fedfunds": np.linspace(1.0, 2.4, 15), "cpi": cpi}, index=idx)
    out = _real_policy(panel)
    yoy_prev = (cpi.iloc[12] / cpi.iloc[0] - 1) * 100  # CPI rate of month 13, read in month 14
    assert out.iloc[13] == pytest.approx(panel["fedfunds"].iloc[13] - yoy_prev)
    assert out.iloc[:13].isna().all()


def test_macro_config_validation() -> None:
    assert MacroComponentConfig(features=["sahm"]).weight == 0.5
    with pytest.raises(ValueError):
        MacroComponentConfig(features=[])
    with pytest.raises(ValueError):
        MacroComponentConfig(features=["sahm", "sahm"])
    with pytest.raises(ValueError):
        MacroComponentConfig(features=["sahm"], weight=0.0)


def test_round5_config_is_the_registered_one(bundle) -> None:
    """ADR 063 (b): the five Fed variables, weight 0.5, λ 1, 120 months, month-end classes, no paper rule."""
    fc = bundle.forecasts["forecast_fed"]
    assert fc.model.macro is not None
    assert fc.model.macro.features == [
        "d_fedfunds_3m",
        "real_policy_rate",
        "d_cpi_yoy_3m",
        "sahm",
        "d_curve_3m",
    ]
    assert (fc.model.macro.weight, fc.model.macro.ridge_lambda, fc.model.macro.min_train_months) == (
        0.5,
        1.0,
        120,
    )
    assert fc.model.feature_weights == bundle.forecast.model.feature_weights
    assert fc.universe["long_history"].ranked == ["US_EQ", "UST10_ME", "GOLD", "SILVER"]
    assert fc.paper_rule is None and bundle.forecast.model.macro is None


def test_blended_score_on_a_toy_view(bundle, monkeypatch) -> None:
    """score_history = 0.5·composite + 0.5·z(m) where the macro fit exists; without `macro` the model is the
    composite alone and its params carry no macro key (earlier journals keep their format)."""
    from datetime import date

    import rotationlab.forecast.model as fm
    from rotationlab.forecast.model import ForecastModel, zscore_rows
    from tests.fixtures.toy import Toy

    rng = np.random.default_rng(5)
    n = 200
    toy = Toy()
    for a in ["US_EQ", "UST10_ME", "GOLD", "SILVER", "TBILL"]:
        toy = toy.monthly(a, list(100 * np.cumprod(1 + rng.normal(0.005, 0.04, n))), start="1990-01-31")
    reg = bundle.forecasts["forecast_fed"]
    assert reg.model.macro is not None
    short = reg.model.macro.model_copy(update={"min_train_months": 60})
    fed = ForecastModel(reg.model_copy(update={"model": reg.model.model_copy(update={"macro": short})}))
    base = ForecastModel(reg.model_copy(update={"model": reg.model.model_copy(update={"macro": None})}))
    idx = pd.date_range("1990-01-31", periods=n, freq="ME")
    x = pd.DataFrame(rng.normal(size=(n, 5)), index=idx, columns=reg.model.macro.features)
    monkeypatch.setattr(
        fm, "state_panel", lambda view, names, fill=0: x.loc[: pd.Timestamp(view.date), list(names)]
    )
    v = toy.factory().at(date(2006, 6, 30))
    s, c = fed.score_history(v), base.score_history(v)
    m = fed.macro_predictions(v, c.index)
    both = s.dropna(how="all").index
    assert len(both) > 50 and s.index.equals(c.index)
    expect = 0.5 * c.loc[both] + 0.5 * zscore_rows(m, 3.0).loc[both]
    assert np.allclose(s.loc[both].to_numpy(), expect.to_numpy(), atol=1e-12)
    assert s.loc[: both[0]].iloc[:-1].isna().all().all()  # no blended score before the macro fit exists
    assert fed.params["macro"]["weight"] == 0.5 and "macro" not in base.params


def test_ridge_coefficients_reproduce_the_path_prediction() -> None:
    from rotationlab.forecast.macro import ridge_coefficients

    x, y = _data()
    t = 200
    beta = ridge_coefficients(x.iloc[:t], y.iloc[:t], 1.0)
    tr = x.iloc[:t].dropna()
    z = (x.iloc[t] - tr.mean()) / tr.std(ddof=1)
    m = ridge_path(x, y, lam=1.0, min_train=60).iloc[t]
    assert np.allclose((z @ beta).to_numpy(), m.to_numpy(), atol=1e-12)


def test_interior_gaps_are_interpolated_only_inside_and_only_short_ones() -> None:
    from rotationlab.forecast.macro import _fill_inside

    idx = pd.date_range("2025-06-30", periods=10, freq="ME")
    p = pd.DataFrame(
        {
            "unrate": [
                4.1,
                4.2,
                4.3,
                np.nan,
                4.5,
                4.4,
                4.3,
                4.3,
                4.4,
                np.nan,
            ],  # one lost month, one not out yet
            "cpi": [1.0, np.nan, np.nan, np.nan, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],  # three months: too long
        },
        index=idx,
    )
    out = _fill_inside(p, 2)
    assert out["unrate"].iloc[3] == pytest.approx(4.4) and np.isnan(out["unrate"].iloc[-1])
    assert out["cpi"].iloc[1:4].isna().all()
    assert out.drop(index=idx[3])["unrate"].equals(p.drop(index=idx[3])["unrate"])


def test_a_lost_release_does_not_blank_the_sahm_indicator() -> None:
    """The October 2025 jobs report never came: with the gap filled, sahm has a value every month after it."""
    from rotationlab.features.macro import _sahm
    from rotationlab.forecast.macro import _fill_inside

    idx = pd.date_range("2024-01-31", periods=30, freq="ME")
    un = pd.Series(4.0 + 0.02 * np.arange(30), index=idx)
    un.iloc[21] = np.nan  # 2025-10
    raw = _sahm(pd.DataFrame({"unrate": un}))
    filled = _sahm(_fill_inside(pd.DataFrame({"unrate": un}), 2))
    assert (
        raw.iloc[22:].isna().all()
    )  # without filling: blank to the end of the sample (14 months in reality)
    assert filled.iloc[16:].notna().all()
