# output/ – reports and the data behind every number

Every figure in `README.md`, `docs/WRITEUP.md` and the ADRs comes from a file here. Each folder names the script that
writes it; rerunning the script reproduces the files (the research rounds also have golden tests that pin their headline
numbers).

| folder | what | written by | status |
|---|---|---|---|
| `forecast/` | Round 1: monthly forecast of 4 asset classes – in-sample evaluation 1973–2018, pseudo-holdout 2019–2025, paper portfolio, investability | `scripts/forecast_evaluation.py`, `forecast_holdout.py`, `forecast_portfolio.py`, `forecast_investability.py` | live since 2026-10 (branch `data`) |
| `forecast_v2/` | Round 2: momentum + carry + value, 5 classes | the same scripts with `--config forecast_v2` | criterion missed, not live |
| `allocator/` | Round 3: sleeve allocator (industries, Treasuries, metals) | `scripts/allocator_walkforward.py` | signals not established |
| `allocator_v2/` | Round 4: five sleeves, ≈ 45 instruments, pre-registered; `DATA.md` = data gates | `scripts/allocator_v2_walkforward.py`, `scripts/r4_data_check.py` | criterion met; advantage = trend filter, not since 2008 |
| `etf_check/` | Round 4's ablation rebuilt with ETFs (2008–2026), pre-registered | `scripts/etf_check.py` | criterion not met; tracks the index study (ρ 0.96) |
| `execution/` | timing of execution (decision close vs. next session) | `scripts/execution_timing_study.py` | reference |
| `precious/` | gold/silver hedge variants | `scripts/precious_hedge_study.py` | reference |
| `revisions/` | real-time vs. revised macro data (FRED-MD vintages) | `scripts/revision_study.py` | reference |
| `long/`, `equity/`, `commodities/`, `gold_silver/` | the first exploratory studies (Oct 2026) that the package was ported from | legacy scripts on branch `archive/legacy-research` (`run.py`, `scripts/run_*.py`) | historical; the package reproduces their formulas (tests/fixtures/legacy_reference) |
