"""P2 (ADR 043): the forecast object and its configuration – contract tests."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from rotationlab.config.models import ForecastConfig, load_bundle
from rotationlab.forecast.types import ClassForecast, Forecast

D = date(2018, 12, 31)


def _classes(status: str = "signal") -> tuple[ClassForecast, ...]:
    ranked = status != "warmup"
    rows = [("US_EQ", 3, -0.002), ("UST10", 1, 0.005), ("GOLD", 2, 0.001), ("SILVER", 4, -0.004)]
    out = [
        ClassForecast(
            asset=a,
            ranked=True,
            trend="up" if r < 3 else "down",
            trend_value=0.01 * (2 - r),
            score=1.0 - r * 0.5,
            rank=r if ranked else None,
            expected=e if ranked else None,
            band=(e - 0.003, e + 0.003) if ranked else None,
            probability=0.5 + 0.02 * (2.5 - r) if ranked else None,
        )
        for a, r, e in rows
    ]
    out.append(ClassForecast(asset="WB_ENERGY", ranked=False, trend="down", trend_value=-0.03))
    out.append(ClassForecast(asset="WB_BASEMETALS", ranked=False, trend=None))
    return tuple(out)


def _fc(**kw) -> Forecast:
    base = {
        "decision_date": D,
        "horizon_months": 1,
        "status": "signal",
        "model_id": "composite",
        "model_version": 1,
        "params": {"feature_weights": {"mom_12_1": 0.3}, "ranked": ["US_EQ", "UST10", "GOLD", "SILVER"]},
        "data_snapshot": "abc123",
        "classes": _classes(kw.get("status", "signal")),
        "calibration_months": 480,
    }
    base.update(kw)
    return Forecast(**base)


def test_round_trip_is_byte_identical() -> None:
    f = _fc(notes=("x",), weights={"UST10": 0.6, "GOLD": 0.4})
    text = f.to_json()
    back = Forecast.from_json(text)
    assert back == f and back.to_json() == text
    assert '"band":[0.002,0.008]' in text  # bands serialise as pairs
    assert text == _fc(notes=("x",), weights={"GOLD": 0.4, "UST10": 0.6}).to_json()  # canonical key order


def test_ranking_and_lookup() -> None:
    f = _fc()
    assert f.ranking() == ["UST10", "GOLD", "US_EQ", "SILVER"]
    assert f.by_asset()["WB_ENERGY"].trend == "down" and f.by_asset()["WB_ENERGY"].rank is None
    assert f.probabilities()["UST10"] == pytest.approx(0.53) and "WB_ENERGY" not in f.probabilities()
    assert _fc(status="warmup").ranking() == []


def test_forecast_is_immutable() -> None:
    f = _fc()
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.status = "warmup"  # type: ignore[misc]
    with pytest.raises(TypeError):
        f.params["x"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        f.params["feature_weights"]["mom_12_1"] = 1.0  # type: ignore[index]
    assert isinstance(f.params["ranked"], tuple)
    stamped = f.stamped("2026-10-31T22:00:00Z")
    assert stamped.created_at == "2026-10-31T22:00:00Z" and f.created_at is None
    assert dataclasses.replace(stamped, created_at=None) == f


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"status": "maybe"}, "status must be one of"),
        ({"horizon_months": 0}, "horizon_months"),
        ({"classes": (*_classes(), ClassForecast("GOLD", True, "up"))}, "appears once"),
        ({"classes": tuple(c for c in _classes() if c.asset != "UST10")}, "ranks every ranked class"),
    ],
)
def test_forecast_validation(change, message) -> None:
    with pytest.raises(ValueError, match=message):
        _fc(**change)


def test_signal_needs_an_expectation_for_every_rank() -> None:
    cls = list(_classes())
    cls[0] = dataclasses.replace(cls[0], expected=None, band=None)
    with pytest.raises(ValueError, match="expectation for every rank"):
        _fc(classes=tuple(cls))
    assert _fc(status="warmup", classes=tuple(cls)).status == "warmup"


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"asset": "X", "ranked": False, "trend": "up", "score": 1.0}, "trend-only"),
        ({"asset": "X", "ranked": True, "trend": "sideways"}, "trend must be"),
        ({"asset": "X", "ranked": True, "trend": None, "rank": 0}, "rank starts at 1"),
        ({"asset": "X", "ranked": True, "trend": None, "expected": 0.01}, "come together"),
        (
            {"asset": "X", "ranked": True, "trend": None, "expected": 0.01, "band": (0.02, 0.03)},
            "does not contain",
        ),
        ({"asset": "X", "ranked": True, "trend": None, "score": float("nan")}, "finite"),
        ({"asset": "X", "ranked": True, "trend": None, "probability": 1.2}, "probability must lie"),
        ({"asset": "X", "ranked": False, "trend": None, "probability": 0.5}, "no probability"),
    ],
)
def test_class_forecast_validation(kw, message) -> None:
    with pytest.raises(ValueError, match=message):
        ClassForecast(**kw)


def test_unknown_schema_version_is_refused() -> None:
    d = _fc().to_dict()
    d["schema_version"] = 99
    with pytest.raises(ValueError, match="schema version"):
        Forecast.from_dict(d)


def test_forecast_config_loads_and_checks(tmp_path, bundle) -> None:
    fc = bundle.forecast
    assert fc is not None
    u = fc.universe["long_history"]
    assert u.ranked == ["US_EQ", "UST10", "GOLD", "SILVER"] and u.trend_only == ["WB_BASEMETALS"]
    assert fc.horizons == [1, 3, 6] and fc.holdout.start == date(2019, 1, 31)
    raw = fc.model_dump()
    with pytest.raises(ValueError, match="disjoint"):
        ForecastConfig(
            **{
                **raw,
                "universe": {"long_history": {**raw["universe"]["long_history"], "trend_only": ["GOLD"]}},
            }
        )
    with pytest.raises(ValueError, match="horizons"):
        ForecastConfig(**{**raw, "horizons": [3, 6]})
    with pytest.raises(ValueError, match="confidence"):
        ForecastConfig(**{**raw, "calibration": {**raw["calibration"], "confidence": 1.2}})
    # an unknown asset is caught by the bundle cross-check
    import shutil

    shutil.copytree("configs", tmp_path / "configs")
    p = tmp_path / "configs" / "forecast.yaml"
    p.write_text(p.read_text().replace("cash: TBILL", "cash: NOPE"))
    with pytest.raises(ValueError, match="unknown assets"):
        load_bundle(tmp_path / "configs")


def test_second_forecast_config_is_loaded_and_tied_to_its_paper_rule(tmp_path, bundle) -> None:
    """Round 2 (ADR 052): every configs/forecast*.yaml is a forecast of its own; the paper rule named in it
    must carry the same weights, clip and feature parameters (ADR 048 b), and `bundle.forecast` stays round 1."""
    import shutil

    assert set(bundle.forecasts) == {"forecast", "forecast_v2"}
    assert bundle.forecast is bundle.forecasts["forecast"]
    v2 = bundle.forecasts["forecast_v2"]
    assert v2.model.id == "mcv" and v2.paper_rule == "forecast_portfolio_v2"
    assert v2.universe["long_history"].ranked == ["US_EQ", "UST10_ME", "UST2_ME", "GOLD", "SILVER"]
    assert set(v2.model.feature_params["carry_yield"]["spec"]) == set(
        v2.universe["long_history"].ranked
    ) | set(v2.universe["live"].ranked)
    assert v2.evaluation.start == date(1981, 7, 31) and [d[0] for d in v2.evaluation.decades] == [
        "1981–1989",
        "1990s",
        "2000s",
        "2010–2018",
    ]
    shutil.copytree("configs", tmp_path / "configs")
    p = tmp_path / "configs" / "strategies" / "forecast_portfolio_v2.yaml"
    p.write_text(
        p.read_text().replace(
            'UST10_ME: { kind: yield, series: "static:fred:DGS10_ME" }', "UST10_ME: { kind: zero }"
        )
    )
    with pytest.raises(ValueError, match=r"feature_params differ from forecast_v2\.yaml"):
        load_bundle(tmp_path / "configs")
