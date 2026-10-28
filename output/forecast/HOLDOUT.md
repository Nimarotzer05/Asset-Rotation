# Pseudo-Holdout 2019–2025: die eingefrorene Prognose und die eingefrorene Regel, einmal gerechnet

Lauf 2026-10-27T07:39:04+01:00 (erster und einziger Lauf). Modell `composite` v1, gerankte Klassen ['US_EQ', 'UST10', 'GOLD', 'SILVER'], Cash TBILL; Protokoll und Lesart vorab in ADR 049. Daten: Forschungspanel ab 1972-12, Datenstand `frame/3adee71f16fa`.

**Einordnung:** „Pseudo“, weil die Periode 2019–2025 bei der Gestaltung bekannt war (Forschungsphase, Allgemeinwissen über Corona-Crash, Zinswende, Goldrally) – nur die Zahlen wurden nie berechnet. Echtes Out-of-sample sind die Live-Prognosen ab November 2026. Mit ≈ 83 Monaten sind die Intervalle breit; die Lesart dafür steht in ADR 049 (d).

## A. Prognose (wie P4)

### Horizont 1 Monat: Entscheidungen 2019-01 bis 2025-11

- Rang-IC (Spearman, Mittel je Monat): **-0.0313 [-0.1808, +0.0482] (n = 83)**; Anteil Monate mit IC > 0: 0.446
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **0.6905**, 95. Perzentil des Null-Mittels +0.1012
- Vormonatsrang als Prognose: IC +0.0145 [-0.1542, +0.0651] (n = 83)
- Trefferquote Rang 1 schlägt Rang 4: **0.482** [0.373, 0.542] (Zufall 0.5)
- Top-minus-Bottom-Spread über 1 Monat, annualisiert (×12/1): -0.0377 [-0.2602, +0.0271] (n = 83)

Je Klasse und Rang, 1 Monat: Trefferquote (relative Rendite > 0) und Monate:

| class | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| GOLD | 0.517 | 0.516 | 0.650 | 0.667 |
| SILVER | 0.476 | 0.458 | 0.438 | 0.591 |
| UST10 | 0.167 | 0.538 | 0.167 | 0.478 |
| US_EQ | 0.519 | 0.333 | 0.448 | 0.833 |

| class | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| GOLD | 29 | 31 | 20 | 3 |
| SILVER | 21 | 24 | 16 | 22 |
| UST10 | 6 | 13 | 18 | 46 |
| US_EQ | 27 | 15 | 29 | 12 |

### Horizont 3 Monate: Entscheidungen 2019-01 bis 2025-09

- Rang-IC (Spearman, Mittel je Monat): **-0.0272 [-0.2321, +0.1185] (n = 81)**; Anteil Monate mit IC > 0: 0.420
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **0.6925**, 95. Perzentil des Null-Mittels +0.1012 – bei überlappenden Fenstern zu eng, massgeblich ist das Intervall
- Vormonatsrang als Prognose: IC -0.0840 [-0.2000, -0.0716] (n = 81)
- Trefferquote Rang 1 schlägt Rang 4: **0.444** [0.296, 0.568] (Zufall 0.5)
- Top-minus-Bottom-Spread über 3 Monate, annualisiert (×12/3): -0.0741 [-0.2852, +0.0224] (n = 81)

### Horizont 6 Monate: Entscheidungen 2019-01 bis 2025-06

- Rang-IC (Spearman, Mittel je Monat): **+0.0256 [-0.1795, +0.1590] (n = 78)**; Anteil Monate mit IC > 0: 0.526
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **0.3610**, 95. Perzentil des Null-Mittels +0.1104 – bei überlappenden Fenstern zu eng, massgeblich ist das Intervall
- Vormonatsrang als Prognose: IC -0.0897 [-0.1771, +0.0205] (n = 78)
- Trefferquote Rang 1 schlägt Rang 4: **0.538** [0.385, 0.654] (Zufall 0.5)
- Top-minus-Bottom-Spread über 6 Monate, annualisiert (×12/6): -0.0005 [-0.1201, +0.0671] (n = 78)

### Wahrscheinlichkeiten (1 Monat, `logistic_tophalf`, Ziel `top_half`), 83 Monate

- Brier Modell 0.2569; Konstante 0.5 0.2500; Klimatologie 0.2540
- Skill gegen 0.5: -0.0069 [-0.0124, -0.0035] (n = 83); **Skill gegen Klimatologie: -0.0030 [-0.0068, -0.0013] (n = 83)** (positiv = Modell besser)
- Grundraten im Holdout: {'US_EQ': 0.506, 'UST10': 0.434, 'GOLD': 0.566, 'SILVER': 0.494}

Reliability (Zehn-Prozent-Schritte, wegen der kleinen Stichprobe):

| bin | n | mean_prob | hit_freq |
|---|---|---|---|
| 0.40–0.50 | 192 | 0.468 | 0.526 |
| 0.50–0.60 | 129 | 0.538 | 0.473 |
| 0.60–0.70 | 11 | 0.607 | 0.364 |

Status (beschreibend) und Trefferquote/IC:

| status | months | hit_rate | mean_ic |
|---|---|---|---|
| no_clear_signal | 26 | 0.462 | -0.000 |
| signal | 57 | 0.491 | -0.046 |

## B. Paper-Regel (wie P8), 84 Renditemonate 2019-01 bis 2025-12

Regel und Baselines durch dieselbe Engine über die volle Geschichte ab 1972-12-31 (Ausführung `next_tradable`, Kosten 7.5 bp je Seite), Kennzahlen nur über den Holdout. Mittlere Risikoquote der Regel 0.627, Anteil Entscheidungen ganz in Cash 0.071.

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Trefferquote | Umsatz p.a. |
|---|---|---|---|---|---|---|---|
| Regel (Top-2, Trend, Vol-Ziel 10 %) | 84 | 0.0814 | 0.0925 | 0.6129 | -0.1467 | 0.6310 | 2.9896 |
| Equal Weight (4 Klassen) | 84 | 0.1632 | 0.1309 | 1.0284 | -0.1754 | 0.6190 | 0.1923 |
| 60/40 US_EQ/UST10_ME | 84 | 0.1079 | 0.1112 | 0.7437 | -0.2099 | 0.7024 | 0.1171 |
| Buy-and-Hold US_EQ | 84 | 0.1715 | 0.1658 | 0.8839 | -0.2393 | 0.6667 | 0.0000 |

Gepaarte Differenzen Regel − Baseline (90 %, Block 12 auf 84 Monaten – breit):

| Baseline | Δ Rendite p.a. | low | high | Δ Sharpe | Sharpe low | Sharpe high |
|---|---|---|---|---|---|---|
| Equal Weight (4 Klassen) | -0.0777 | -0.1167 | -0.0333 | -0.4155 | -0.8464 | -0.1537 |
| 60/40 US_EQ/UST10_ME | -0.0264 | -0.0917 | 0.0085 | -0.1308 | -0.8318 | 0.1818 |
| Buy-and-Hold US_EQ | -0.0903 | -0.1786 | -0.0365 | -0.2710 | -1.0427 | 0.0304 |

## Lesart nach ADR 049 (d) – vorab festgelegt

- In-sample 1973–2018 (P4): IC +0.0978 [+0.0511, +0.1409]; Holdout 2019–2025: IC **-0.0313** [-0.1808, +0.0482] über 83 Monate; Vormonatsrang-Baseline +0.0145.
- Replikation der Rangfolge: **GESCHEITERT (mittlerer IC ≤ 0)**.
- Wahrscheinlichkeiten: Skill gegen Klimatologie -0.0030 [-0.0068, -0.0013] – Intervall ohne Null (in-sample ebenfalls nicht).
- Regel gegen Equal Weight: Sharpe +0.613 gegen +1.028, Δ -0.416 [-0.846, -0.154] – berichtet ohne Pass/Fail (84 Monate).

Nach diesem Lauf wird an Modell und Regel nichts mehr geändert (ADR 049 a).

Laufzeit 38 s.
