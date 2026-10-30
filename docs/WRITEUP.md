# Testing asset-class rotation honestly: five pre-registered rounds, one live forecast

*Nima Rotzer · ETH Zürich, BSc Mathematics · October 2026 · code and data: github.com/Nimarotzer05/Asset-Rotation*

## Question
Can a systematic rule tell, at each month-end, which asset classes will do relatively well next month – well enough
to survive held-out data, realistic costs and a correction for every idea tried? The project answers this with a
research process modelled on an institutional desk: rules fixed in writing before each test, every trial counted,
independent review of each result, and a live forecast that cannot be edited after the fact.

## Data and infrastructure
A point-in-time store holds ~540 series (prices, yields, macro data with publication vintages) from FRED, Yahoo,
Stooq, BLS, CFTC, the Kenneth French library and Shiller, so every decision sees only what was known on its date.
One engine runs backtests, walk-forwards and the live forecast; trades execute at the next session, with
per-instrument costs and financing of leverage. About 400 tests, golden tests that pin each published number, and a
look-ahead harness (the future is replaced by noise; no decision may change) guard the code.

## Five rounds
**Round 1 – ranking four classes.** A composite of 3/6/12-month momentum, 10-month trend and low volatility ranks US
equities, Treasuries, gold and silver. In-sample (1973–2018) the rank IC is +0.098 [+0.051, +0.141] over 548 months.
In the held-out period 2019–2025, evaluated once, it is −0.03 – not replicated. A paper portfolio on the ranking
misses its criterion against equal weight (+0.18 Sharpe [−0.01, +0.39]).

**Round 2 – adding carry and value.** IC +0.056 [−0.002, +0.106] in-sample, −0.16 held out. Missed.

**Round 3 – breadth.** A sleeve allocator (10 US industries, 2 Treasuries, gold, silver; momentum inside sleeves,
trend filter, risk parity, 10 % vol target) against the same risk parity without signals: Δ Sharpe −0.002
[−0.19, +0.16]. Not established; the test could not have detected effects below 0.27.

**Round 4 – more breadth, every weakness of round 3 fixed before the data arrived.** Five sleeves, ~45 instruments
(industries, 21 country indices, three Treasury maturities, nine currencies long-short by carry and momentum, gold and
silver). The design was hardened by a synthetic dry run and an independent review before the download; two bugs
that would have biased the result were found then. Result, 1977–2025: Sharpe 0.79 vs. 0.51 for passive risk
parity, Δ +0.285 [+0.14, +0.43] – the first pre-registered criterion met. Both new signals pass a Holm-corrected
Newey-West test as stand-alone rank portfolios.

**What the ablations say.** The same book with the trend filter but no cross-sectional selection reaches the same
Sharpe (Δ −0.001 [−0.07, +0.06], correlation 0.96): the edge is the 12-month trend filter, a known effect
(Moskowitz, Ooi & Pedersen 2012), not the signals. It comes from 1977–2007; since 2008 the difference is +0.08
[−0.18, +0.28] and the allocator trails equal weight and 60/40 (0.59 vs. 0.72). Passive risk parity was the weakest
of four baselines. The deflated Sharpe probability is 0.895 against the 70 trials counted at the time (0.85 with
the 87 of today's register), below the 0.95 bar. No live use.

**Round 5 – the Fed category.** Five Fed decision variables (Fed funds change, real policy rate, inflation change,
Sahm indicator, curve change) mapped to each class by a ridge regression fitted on the expanding past, blended 50/50
with round 1's composite, every score computed pointwise. 1978–2018: rank IC 0.092 → 0.034, Δ −0.058 [−0.108,
−0.006] – worse, not better; in the already-seen 2019–2025 +0.07. Not established. It runs live as a second forecast,
as decided before the test; the published forecast stays round 1.

**A leveraged long-short on the ranking.** Rank 1 long 1.5×, last rank short 1.5×, held while the ranking stands,
with borrow, financing and costs: Sharpe 0.31 [+0.05, +0.52] in 1974–2018 – the Sharpe of equal weight at three times
its volatility, with an −82 % drawdown – and −12 % a year in 2019–2025. Profitable in-sample only. Closed and reopened every
month with a 20 % stop on daily closes it does worse (Sharpe 0.11 [−0.20, +0.32], drawdown −99 %); in dollars and without
any fees, $1500 a side with a $200 stop earns $5,297 in 1974–2018, mostly in 1979, and loses $484 in 2019–2025.

**Fresh data.** A daily US equity series from 1885 gave 41 years no study had touched. There the 10-month trend filter
earned the same return as buy and hold with a quarter less risk (Sharpe difference +0.08 [−0.08, +0.24], not
significant), and the turn-of-the-month effect – equities only around month-end, 19 % of days – had a Sharpe of 0.57
[+0.32, +0.87] before its discovery and 0.52 [+0.23, +0.77] after its publication (1988–2025): the one pre-registered
positive result on untouched data, and a calendar effect, not a forecast.

## Checks on the result
- **Tradable instruments (pre-registered).** The round-4 book rebuilt with ETFs, 2008–2026: filter vs. no filter
  +0.06 [−0.21, +0.20], not significant; the filter lowers volatility by about a quarter and the drawdown by almost
  half. The ETF and index versions
  correlate 0.96 over common months – the research data describe what was investable.
- **Independent rebuild.** A short pandas script, no engine: Sharpe 0.79 vs. 0.80 from the engine, correlation 0.98;
  with the filter switched off it falls to passive risk parity. The rebuild's own first bug (a pandas alignment error
  that silently disabled the filter) is documented in the file.
- **Second review.** A fresh reviewer recomputed every reported number from the stored series (agreement < 1e-14) and
  rebuilt the signal portfolios from raw files bit-exactly; no leak, no post-hoc choice found.

## Live
Since October 2026 the round-1 ranking is written after every month-end into an append-only, hash-chained journal
whose head is anchored outside the repository. With a monthly IC standard deviation of 0.64, even a true IC of 0.098
needs about ten years to reach t = 1.65; the live record demonstrates process, not skill.

## Lessons
A strong in-sample result is a hypothesis. Ablations decide what a result means. Every trial has to be counted,
including the discarded ones. Research data should be checked against tradable instruments, and headline numbers
against an independent implementation. Above all: stop when the data are used up – the fifth round, run because the Fed
variables seemed indispensable, lowered every earlier round's deflated Sharpe and found nothing.

*Built with Claude (Anthropic) as AI coding and research assistant; questions, standards and decisions at each gate
are the author's. Full decision log (German): docs/ADR.md.*
