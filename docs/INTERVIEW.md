# Interview preparation – the hard questions and honest answers

The questions an experienced quant interviewer is most likely to ask about this project, with an answer grounded in
a file. Read the file behind each answer; say the numbers in your own words; never claim more than the file shows.

## The 60-second pitch
"I built a system that ranks asset classes for the next month and tested it the way a research desk would: every
round of ideas was written down before it touched the data, every trial was counted, and the results were checked by
an independent review. The first model looked good in-sample – IC 0.10 over 45 years – and failed in a held-out
period. Over five rounds exactly one pre-registered test passed: risk parity with a 12-month trend filter beats
passive risk parity. An ablation showed the cross-sectional signals added nothing – the filter did all of it – and
that the edge is not significant since 2008, also with tradable ETFs. The ranking now runs live with a tamper-evident
journal. What I learned is mostly about how easily backtests fool you, and how to stop that."

## Hard questions

**1. "Your best result beats risk parity – but that is your weakest benchmark, and since 2008 you lose to 60/40.
Why should I believe there is anything here?"**
You shouldn't believe there is *alpha*, and the project doesn't claim it. The baseline was fixed in advance because
it isolates the question asked (does the allocator add to the same risk-parity book?), not to win. Against equal
weight and 60/40 the interval includes zero, and since 2008 the allocator's Sharpe is 0.59 vs. 0.72 – that is in the
README and in ADR 060. The defensible statement is narrow: a trend filter on a leveraged risk-parity book helped in
1977–2007, mostly by stepping out of bonds in rising-rate years, and has not been significant since.
*Files:* `output/allocator_v2/WALKFORWARD.md`, ADR 060, `docs/figures/tests.png`.

**2. "Walk me through the deflated Sharpe. What is N, and what does 0.895 mean?"**
N counts every variant ever computed on this history, including ones whose results I saw and discarded: 70 when
round 4 ran, 79 today (after the ETF check, round 5 and the long-short study). The tested
statistic is the Sharpe of the allocator's return net of its beta to the baseline, so extra risk doesn't count as
skill. Given how much the trials vary, 0.895 is the probability that the observed Sharpe beats the best of 70 unskilled
tries (0.87 with today's 79). It's a probability, not a p-value, and it's below the 0.95 I set as the bar – so round 4 does not
survive the multiple-testing correction. *File:* `docs/METHODS.md` §8, `docs/TRIALS.yaml`.

**3. "Which parts did you write yourself?"**
Be precise and honest: "I used Claude as a coding and research assistant – it wrote most of the code and drafts. I set
the question and the standard, decided at each gate (what to test, which baseline, go/no-go for live, how to handle a
missing data series), reviewed the results, and I can explain every number. To check that I understand the core
result, there is a 120-line pandas rebuild of it that I can walk you through." Then do it:
`examples/trend_filter_from_scratch.py`. *Only say this once you can actually walk through that file line by line.*

**4. "Isn't this overfit? Five rounds on the same 50 years."**
Yes, that is the main risk, and it is handled, not avoided: each round was fixed before its run (git timestamps), all
79 trials are counted, the deflated Sharpe uses all of them, and no failed round was re-tested with tweaked
parameters. What the register cannot count are the *design* choices between rounds, made knowing earlier results –
the garden of forking paths. I ran a fifth round anyway, because the Fed variables were a category I considered
indispensable and had not tested properly; its cost is visible – every earlier round's deflated Sharpe went down
(round 4: 0.90 → 0.87) – and it came out negative, which is itself a check that the process does not just confirm.

**5. "Why a moving-block bootstrap, and why block length 12?"**
Monthly returns are autocorrelated and two strategies on the same months are correlated. Resampling single months
would understate the error; resampling the same 12-month blocks for both strategies keeps both properties. 12 months
covers the autocorrelation of 12-month signals; with block 24 the round-4 interval is [+0.13, +0.43], practically
unchanged.

**6. "Your research data are indices, not tradable instruments."**
Checked, pre-registered: the round-4 book rebuilt with ETFs (sector SPDRs, EFA, SHY/IEF, GLD/SLV) correlates 0.96
with the index version over the 210 common months; Sharpe 0.58 vs. 0.66. The ETF test itself (2008–2026) does not
show a significant filter edge (+0.06 [−0.21, +0.20]) – consistent with the index result for the same period.
*File:* `output/etf_check/ETF_CHECK.md`, ADR 061/062.

**7. "Your old README said walk-forward Sharpe 0.77, Max-DD −11 %. What happened to that?"**
That was the first exploratory study: parameters chosen each year on past data, but the feature set, universe and
grid were chosen after seeing the same history, nothing was pre-registered and trials weren't counted. It is the
reason for the later process. The strict tests that followed did not confirm it. The study is kept on branch
`archive/legacy-research` for transparency.

**8. "How do you know there is no look-ahead?"**
Three layers, and one stated convention: the store only shows data known at the decision date (vintages and
publication lags) – except that research returns computable from public prices on their date (the French industry
and country portfolios) are treated as known at the close, although French publishes them weeks later; a harness
replaces everything after D with noise and asserts that the decision at D does not change, for every feature and
strategy; and execution is at the next session after the decision. The independent pandas rebuild, with its own
simple timing, gets the same Sharpe within 0.02. The convention matters least where it is checked: the ETF version,
on real closes, tracks the index version at ρ = 0.96.

**9. "Can the live forecast prove anything?"**
Not soon. The monthly IC has a standard deviation of 0.64; even a true IC of 0.098 needs about 10 years for t = 1.65
and about 22 years for 80 % power. The live journal shows an honest, tamper-evident process – forecasts written
before outcomes, hash-chained, anchored outside the repo – not evidence of skill.

**10. "What would you do differently?"**
Start with the held-out period and the trial register on day one, not after the first exciting result. Test on
tradable instruments from the start. Spend the budget on one clean hypothesis with enough power rather than on
breadth – the MDE of 0.22–0.31 Sharpe means small real effects were invisible to every test here.

**11. "Why does the model that failed the holdout run live?"**
Because it was frozen before the holdout ran (ADR 049: "after the run, model and rule are not changed"). Swapping in a
model chosen after seeing the holdout would be selecting on the holdout – the one thing the holdout exists to
prevent. The live record is the only genuinely out-of-sample test left for that frozen model; it is published with
the holdout failure stated next to it, including that its probabilities did worse than the base rate there.

**12. "Where does your long history come from?"**
Partly from public GitHub mirrors of official sources (FRED-MD vintages, LBMA fixings, Shiller, World Bank, the
French library), listed with links in `data/DATA_SOURCES.md`, because the research machine could not reach the
originals; round 4's data were downloaded from FRED and the French library directly by a GitHub workflow, stored
byte-for-byte with SHA-256 checksums, and checked by six gates before use (`output/allocator_v2/DATA.md`). The live
store reads the primary sources daily. A mirror can carry errors; the gates (e.g. daily vs. monthly French files
agree to 0.9998) and the ETF cross-check are how I would detect them.

**13. "Leverage financed at T-bills + 30 bp in 1977–89 – realistic?"**
Optimistic for that period; it is an assumption, stated as such. The sensitivity is small: each extra 100 bp of
financing costs about 0.017 Sharpe (`docs/REVIEW_ALLOKATOR.md` F4), and the passive baseline is leveraged as well,
so the comparison is not driven by it.

**14. "You ignore the Fed. Rates, inflation, unemployment drive everything."**
Tested, pre-registered (ADR 063/064). Five Fed variables – 3-month change of Fed funds, real policy rate, change of
the inflation rate, Sahm indicator, change of the curve – are the same for every class, so a ridge regression per class
learns, on the expanding past only, how each variable moved that class's next-month relative return; its prediction is
blended 50/50 with the momentum composite. Result 1978–2018: rank IC falls from 0.092 to 0.034, paired difference
−0.058 [−0.108, −0.006]; the Fed part alone has IC −0.005. Some slopes read like a textbook, others flip sign between fits; none of
it forecasts the next month. Caveat: the macro history is the revised FRED-MD release with a one-month lag, not the
first-print data – which could only have helped the Fed model. Monthly-average macro data and month-end prices were kept apart on purpose (an averaged Treasury
series would have handed the Fed variables a spurious edge). *File:* `output/forecast_fed/ROUND5.md`.

**15. "So just lever it up and go long-short."**
Pre-registered too: rank 1 long 1.5×, last rank short 1.5×, held while the ranking stands, with borrow fees,
financing and costs. 1974–2018: Sharpe 0.31 [+0.05, +0.52] – the same Sharpe as equal weight at three times the
volatility, a −82 % drawdown and a −60 % month (March 1980, silver held long). 2019–2025: −12 % a year. At 1.0× the
annual return is the same 9.3 %: volatility drag eats the leverage. *File:* `output/long_short/LONG_SHORT.md`.

## Likely follow-ups to prepare
- Volatility drag: geometric ≈ arithmetic return − σ²/2 – why 1.5× and 1.0× end at the same 9.3 % (σ 43 % vs. 31 %).
- Ridge regression: why a fixed λ and standardised variables, and why the intercept is left out.
- Fundamental law of active management: IC × √breadth – why 4 classes give little breadth (round 4 widened it to ~45).
- Why risk parity leverages bonds, and what that did in 1977–81 (the passive baseline held leveraged bonds through rising rates; the filter stepped out).
- What a Holm correction does with two tests (`docs/METHODS.md` §7).
- Why execution at the next session matters (+0.012 Sharpe difference here – small, but measured).
