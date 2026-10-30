# Frische Daten: Trendfilter 1886–1926 und Monatswechsel-Effekt (ADR 069)

Stand 2026-10-30. Skript `scripts/fresh_data_check.py`, Regeln `rotationlab/forecast/fresh_data.py`. Daten: US-Aktien Total Return täglich ab 1885 (`static:usmkt:TR`) und der tägliche Cash-Index derselben Datei (`static:usmkt:RF`). Kein Zeitraum vor 1927 wurde im Projekt je ausgewertet; 1988–2025 ist für den Monatswechsel-Effekt neu (nie berechnet), die Aktienreihe selbst aber bekannt. 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Kriterien vor Kosten; Kosten 5 bp je Wechsel berichtet. Laufzeit 3 s.

## 1. Trendfilter auf 41 unberührten Jahren (1886–1926)

| 1886–1926 | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max DD | investiert | Wechsel p.a. |
|---|---|---|---|---|---|---|---|
| Trendfilter 10 M | 488 | +7.4% | 11.1% | +0.446 [+0.166, +0.725] | -29.8% | 65% | 1.70 |
| Trendfilter, nach 5 bp je Wechsel | 488 | +7.3% | 11.1% | +0.438 [+0.157, +0.719] | -30.3% |  |  |
| Buy & Hold | 488 | +7.3% | 14.7% | +0.368 [+0.077, +0.650] | -35.4% | 100% | 0 |

Vorab-Kriterium: Trend − Buy & Hold, gepaarte Sharpe-Differenz **+0.078 [-0.082, +0.240]** → **nicht bestätigt** (Standardfehler ≈ 0.098, kleinste nachweisbare Differenz ≈ 0.24). Deflated Sharpe (Appraisal-Residuum gegen Buy & Hold, N = 87): 0.068.

## 2. Monatswechsel-Effekt: vor der Entdeckung und nach der Veröffentlichung

| Monatswechsel | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max DD | im Markt |
|---|---|---|---|---|---|---|
| Monatswechsel 1885–1926 | 497 | +6.3% | 6.2% | +0.570 [+0.315, +0.866] | -17.1% | 19% |
| Monatswechsel 1885–1926, nach 5 bp je Wechsel | 497 | +5.0% | 6.2% | +0.376 [+0.120, +0.667] | -17.9% |  |
| Buy & Hold 1885–1926 | 497 | +8.0% | 14.8% | +0.406 [+0.106, +0.667] | -35.4% | 100% |
| Monatswechsel 1988–2025 | 455 | +6.7% | 7.4% | +0.524 [+0.234, +0.773] | -17.0% | 19% |
| Monatswechsel 1988–2025, nach 5 bp je Wechsel | 455 | +5.4% | 7.4% | +0.359 [+0.072, +0.601] | -17.8% |  |
| Buy & Hold 1988–2025 | 455 | +11.3% | 14.5% | +0.612 [+0.299, +0.920] | -50.8% | 100% |

| Tage | Tage am Monatswechsel | Ø Überrendite je Tag am Monatswechsel | Ø Überrendite je übriger Tag | t (Welch) | Anteil an der Aktien-Überrendite |
|---|---|---|---|---|---|
| Monatswechsel 1885–1926 | 1988 | +0.074% | +0.012% | +2.66 | 60% |
| Monatswechsel 1988–2025 | 1820 | +0.080% | +0.027% | +1.80 | 41% |

Vorab-Kriterium (Sharpe des Monatswechsels, Intervall > 0): 1885–1926 +0.570 [+0.315, +0.866] → **ja**; 1988–2025 +0.524 [+0.234, +0.773] → **ja**. Lesart: **existiert und hat die Veröffentlichung überlebt**.
