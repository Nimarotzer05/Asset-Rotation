# Interview preparation – the hard questions and honest answers

The questions an experienced quant interviewer is most likely to ask about this project, with an answer grounded in
a file. Read the file behind each answer; say the numbers in your own words; never claim more than the file shows.

## The 60-second pitch
"I built a system that ranks asset classes for the next month and tested it the way a research desk would: every
round of ideas was written down before it touched the data, every trial was counted, and the results were checked by
an independent review. The first model looked good in-sample – IC 0.10 over 45 years – and failed in a held-out
period. Over four rounds exactly one pre-registered test passed: risk parity with a 12-month trend filter beats
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
N = 71, every variant ever computed on this history, including ones whose results I saw and discarded. The tested
statistic is the Sharpe of the allocator's return net of its beta to the baseline, so extra risk doesn't count as
skill. Given how much the 71 trials vary, 0.895 is the probability that the observed Sharpe beats the best of 71
unskilled tries. It's a probability, not a p-value, and it's below the 0.95 I set as the bar – so round 4 does not
survive the multiple-testing correction. *File:* `docs/METHODS.md` §8, `docs/TRIALS.yaml`.

**3. "Which parts did you write yourself?"**
Be precise and honest: "I used Claude as a coding and research assistant – it wrote most of the code and drafts. I set
the question and the standard, decided at each gate (what to test, which baseline, go/no-go for live, how to handle a
missing data series), reviewed the results, and I can explain every number. To check that I understand the core
result, there is a 120-line pandas rebuild of it that I can walk you through." Then do it:
`examples/trend_filter_from_scratch.py`. *Only say this once you can actually walk through that file line by line.*

**4. "Isn't this overfit? Four rounds on the same 50 years."**
Yes, that is the main risk, and it is handled, not avoided: each round was fixed before its run (git timestamps), all
71 trials are counted, the deflated Sharpe uses all of them, and no failed round was re-tested with tweaked
parameters. What the register cannot count are the *design* choices between rounds, made knowing earlier results –
the garden of forking paths. That is why I stopped: a fifth round on this history would lower the evidential value of
everything before it.

**5. "Why a moving-block bootstrap, and why block length 12?"**
Monthly returns are autocorrelated and two strategies on the same months are correlated. Resampling single months
would understate the error; resampling the same 12-month blocks for both strategies keeps both properties. 12 months
covers the autocorrelation of 12-month signals; with block 24 the round-4 interval is [+0.14, +0.43], unchanged.

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
Three layers: the store only shows data known at the decision date (vintages and publication lags); a harness
replaces everything after D with noise and asserts that the decision at D does not change, for every feature and
strategy; and execution is at the next session after the decision. The independent pandas rebuild, with its own
simple timing, gets the same Sharpe within 0.02.

**9. "Can the live forecast prove anything?"**
Not soon. The monthly IC has a standard deviation of 0.64; even a true IC of 0.10 needs about 10 years for t = 1.65
and about 22 years for 80 % power. The live journal shows an honest, tamper-evident process – forecasts written
before outcomes, hash-chained, anchored outside the repo – not evidence of skill.

**10. "What would you do differently?"**
Start with the held-out period and the trial register on day one, not after the first exciting result. Test on
tradable instruments from the start. Spend the budget on one clean hypothesis with enough power rather than on
breadth – the MDE of 0.22–0.31 Sharpe means small real effects were invisible to every test here.

## Likely follow-ups to prepare
- Fundamental law of active management: IC × √breadth – why 4 classes give little breadth (round 4 widened it to ~45).
- Why risk parity leverages bonds, and what that did in 1977–81 (the passive baseline held leveraged bonds through rising rates; the filter stepped out).
- What a Holm correction does with two tests (`docs/METHODS.md` §7).
- Why execution at the next session matters (+0.012 Sharpe difference here – small, but measured).
