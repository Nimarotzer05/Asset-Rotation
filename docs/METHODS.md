# Methods – what each tool does, why it is here, where it lives

One section per method, in plain language, with the formula and the file that implements it. Written so the
author can explain every number in the README without opening the code.

## 1. Point-in-time data
**What.** Every observation is stored with the date it became known (`vintage_date`), not only the date it refers
to. Unemployment for September is published in early October; a decision on 30 September must not see it.
**Convention.** Returns that are computable from public prices on their date – the Kenneth French industry and
country portfolios, monthly average yields – carry no lag even though the files appear weeks later: an investor
holding the same stocks would know them at the close. It is a stated assumption (configs/series.yaml); the ETF check
uses real closing prices and tracks the index result (ρ 0.96).
**How.** A *view* at date D returns only rows with `obs_date ≤ D` and `vintage_date ≤ D`; publication lags per
series (`0D` for market prices, `1M` for monthly macro data) set the vintage when a source has no history of revisions.
**Where.** `rotationlab/data/store.py`, `data/view.py`, `data/lags.py`. **Test.** `tests/lookahead/`: the future
after D is replaced by noise; every decision at D must stay identical.

## 2. Momentum, trend and the composite score (round 1)
**12-1 momentum** = price 1 month ago / price 13 months ago − 1 (skips the last month, which tends to reverse).
**Trend** = price / 10-month average − 1. Each feature is z-scored across the classes at D, clipped at ±3, and
combined with fixed weights (3-1M 0.2, 6-1M 0.3, 12-1M 0.3, trend 0.2, inverse vol 0.1). The highest score ranks 1.
**Where.** `rotationlab/forecast/model.py`, `configs/forecast.yaml`.

## 3. Rank IC – how good is a ranking?
**What.** Each month, the Spearman correlation between the predicted ranks and the realised next-month returns of
the classes. +1 = perfect order, 0 = no information. With 4 classes one month says little; the *mean over many
months* is the statistic. Round 1: +0.098 over 548 months (1973–2018), −0.03 over 83 held-out months.
**Why it is hard to prove live.** The monthly IC has a standard deviation of 0.64. To show a true IC with
t = 1.645 needs n = (1.645 × 0.642 / 0.098)² ≈ 116 months (≈ 10 years) at the in-sample IC of 0.098; with 80 % power
(1.645 + 0.842 instead of 1.645) ≈ 265 months (≈ 22 years).
**Where.** `rotationlab/forecast/evaluation.py`.

## 4. Volatility, risk parity, volatility target (rounds 3–4)
**Volatility** is an exponentially weighted standard deviation (recent days count more; centre of mass 60 sessions
for daily data, half-life 12 months for monthly data), floored at 2 %.
**Risk parity**: each sleeve gets weight a_s = budget_s / σ_s, so a calm sleeve (bonds) gets more capital than a
volatile one (silver) and each contributes risk in proportion to its budget.
**Volatility target**: the whole book is scaled by k = 10 % / σ_book, with σ_book = √(a′DRDa) from the sleeve
volatilities D and their correlation R (slow, half-life 24 months). If bonds are calm, k > 1 – that is the leverage,
capped at 1.5× gross (equities and metals at most 1.0).
**Where.** `rotationlab/strategies/sleeve_allocator_v2.py` (its docstring is the full specification).

## 5. The trend filter – the one thing that worked
**Rule.** If an instrument's return over the last 12 months is below cash over the same 12 months, its share is held
in T-bills instead (nothing is re-scaled). **Why it helps.** It steps out of assets in sustained decline – bonds in
1979–81, 2013 and 2022 – and so cuts drawdowns. **Why it is not new.** Time-series momentum is documented
(Moskowitz, Ooi & Pedersen 2012); here it is confirmed 1977–2007 and not significant since 2008.
**Rebuild.** `examples/trend_filter_from_scratch.py` implements the whole book in a short pandas script.

## 6. Paired block bootstrap – is a Sharpe difference real?
**Problem.** Two strategies on the same months are correlated, and monthly returns are autocorrelated, so a
textbook standard error is wrong. **Method.** Resample *blocks* of 12 consecutive months (keeps autocorrelation),
the *same* blocks for both strategies (keeps their pairing), recompute the Sharpe difference 2000 times; the middle
90 % of those values is the interval. If it excludes zero, the difference is called established.
**Minimum detectable effect (MDE).** With standard error SE, an effect smaller than (1.65 + 0.84) × SE would be
missed 20 % of the time or more. Round 4: SE 0.088, MDE 0.22; ETF check: SE 0.126, MDE 0.31.
**Where.** `rotationlab/forecast/evaluation.py` (`paired_sharpe_diff`), `forecast/model.py` (`BlockBootstrap`).

## 7. Newey-West t-test and Holm correction – testing a signal directly
A long-short *rank portfolio* (weight ∝ (N+1)/2 − rank, dollar-neutral) earns the next month's return of the signal
alone. Its mean is tested with a Newey-West standard error (12 lags; corrects for autocorrelation). Two new signals
were tested in round 4, so the p-values are adjusted with Holm's method (multiply the smallest p by 2, the next by
1) to keep the overall error rate at 10 %.

## 8. Deflated Sharpe – how many tries did it take?
**Idea.** If you try N variants, the best one looks good by luck. The deflated Sharpe (Bailey & López de Prado 2014)
asks: what is the probability that the observed Sharpe exceeds the maximum expected from N unskilled tries, given
how much the tries vary? It is a probability (≥ 0.95 = survives), not a p-value. **Here.** N = every variant ever
run on this history (`docs/TRIALS.yaml`; 70 when round 4 ran, 71 after the ETF check); the statistic is the Sharpe of the return net of the baseline
(beta-adjusted residual), so a strategy cannot win by simply taking more risk. Round 4: 0.895 at N = 70, 0.90 with
today's register.

## 9. Pre-registration and the trial register
Before a round touches its data, its rules, criterion, baselines and variants are written into the decision log and
merged (a timestamp in git). Results are reported as they come; a failed criterion is not re-tested with new
parameters on the same data. Unforeseen events follow emergency rules written in advance (ADR 057 h → ADR 059).

## 10. Execution realism
Decisions at the month-end close; trades at the next session (`next_tradable`); costs per instrument (3–20 bp per
trade side); negative cash (leverage) costs T-bills + 30 bp p.a.; the ETF check uses buyable funds with dividends.

## 11. Hash-chained journal
Each forecast record stores the SHA-256 hash of the previous one; changing any past record breaks every later hash.
The latest hash is written to a separate branch (`anchors`) each day, so even truncating the end is detectable.
**Where.** `rotationlab/forecast/journal.py`; `rotationlab forecast verify` checks the chain.
