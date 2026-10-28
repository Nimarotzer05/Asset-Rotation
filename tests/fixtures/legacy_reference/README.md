# Frozen outputs of the legacy research code

The package `rotationlab` was ported from a first research codebase (`src/`, `config.py`, `run.py`, `scripts/run_*.py`).
That code was moved to the branch `archive/legacy-research` on 2026-10-28. Before the move it was run once more on the
same static panel the tests use, and its outputs were stored here, so the parity tests still prove that the package
reproduces the research to 1e-9:

| file | legacy function | test |
|---|---|---|
| `multi_asset_rotation_weights.csv.gz` | `src/signals.py` `composite_score` + `build_weights(top_n=3, trend_filter=True)` | `tests/golden/test_module_goldens.py` |
| `commodity_trend_weights.csv.gz` | `src/commodity_model.py` `tilted_weights(lam=0)` | `tests/golden/test_module_goldens.py` |
| `forecast_composite_2018-12-31.csv.gz` | `src/signals.py` `composite_score` on the forecast features at 2018-12-31 | `tests/lookahead/test_forecast_model.py` |
| `metrics_summary_seed0.json` | `src/metrics.py` `summary` on `numpy.random.default_rng(0)` draws | `tests/unit/test_engine.py` |
