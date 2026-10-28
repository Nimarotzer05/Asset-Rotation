# Testing asset-class rotation honestly: four pre-registered rounds, one live forecast

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
per-instrument costs and financing of leverage. 368 tests, golden tests that pin each published number, and a
look-ahead harness (the future is replaced by noise; no decision may change) guard the code.

## Four rounds
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
of four baselines. The deflated Sharpe probability against all 71 trials is 0.895, below the 0.95 bar. No live use.

## Checks on the result
- **Tradable instruments (pre-registered).** The round-4 book rebuilt with ETFs, 2008–2026: filter vs. no filter
  +0.06 [−0.21, +0.20], not significant; the filter halves volatility and drawdown. The ETF and index versions
  correlate 0.96 over common months – the research data describe what was investable.
- **Independent rebuild.** 120 lines of pandas, no engine: Sharpe 0.79 vs. 0.80 from the engine, correlation 0.98;
  with the filter switched off it falls to passive risk parity. The rebuild's own first bug (a pandas alignment error
  that silently disabled the filter) is documented in the file.
- **Second review.** A fresh reviewer recomputed every reported number from the stored series (agreement < 1e-14) and
  rebuilt the signal portfolios from raw files bit-exactly; no leak, no post-hoc choice found.

## Live
Since October 2026 the round-1 ranking is written after every month-end into an append-only, hash-chained journal
whose head is anchored outside the repository. With a monthly IC standard deviation of 0.64, even a true IC of 0.10
needs about ten years to reach t = 1.65; the live record demonstrates process, not skill.

## Lessons
A strong in-sample result is a hypothesis. Ablations decide what a result means. Every trial has to be counted,
including the discarded ones. Research data should be checked against tradable instruments, and headline numbers
against an independent implementation. Above all: stop when the data are used up – a fifth round on the same history
would lower the evidential value of the first four.

*Built with Claude (Anthropic) as AI coding and research assistant; questions, standards and decisions at each gate
are the author's. Full decision log (German): docs/ADR.md.*
