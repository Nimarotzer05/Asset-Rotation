"""rotationlab: cross-asset rotation system.

One engine for backtest, walk-forward and live; point-in-time data; pure features;
pluggable strategy modules; the monthly forecast with its hash-chained journal; research rounds.

Architecture: docs/ARCHITECTURE.md. Decisions: docs/ADR.md. Docstrings that cite `src/…`, `config.py` or
`scripts/run_*.py` refer to the first research code, kept on branch `archive/legacy-research` (ADR 062); the
package reproduces it to 1e-9 (tests/fixtures/legacy_reference).
"""

__version__ = "0.1.0"
