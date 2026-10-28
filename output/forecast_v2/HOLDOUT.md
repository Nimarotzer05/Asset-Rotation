# Pseudo-Holdout 2019–2025: die eingefrorene Prognose und die eingefrorene Regel, einmal gerechnet (Forschungsrunde 2, `forecast_v2`)

Lauf 2026-10-27T18:48:46+01:00 (erster und einziger Lauf). Modell `mcv` v1, gerankte Klassen ['US_EQ', 'UST10_ME', 'UST2_ME', 'GOLD', 'SILVER'], Cash TBILL; Protokoll und Lesart vorab in ADR 049 (übernommen in ADR 052 f). Daten: Forschungspanel ab 1976-06, Datenstand `frame/3bb31e8d8a73`.

**Einordnung:** „Pseudo“, weil die Periode 2019–2025 bei der Gestaltung bekannt war (Forschungsphase, Allgemeinwissen über Corona-Crash, Zinswende, Goldrally) – nur die Zahlen wurden nie berechnet. Echtes Out-of-sample sind die Live-Prognosen ab November 2026. Mit ≈ 83 Monaten sind die Intervalle breit; die Lesart dafür steht in ADR 049 (d).

## A. Prognose (wie P4)

### Horizont 1 Monat: Entscheidungen 2019-01 bis 2025-11

- Rang-IC (Spearman, Mittel je Monat): **-0.1590 [-0.2338, -0.0530] (n = 83)**; Anteil Monate mit IC > 0: 0.349
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **0.9975**, 95. Perzentil des Null-Mittels +0.0892
- Vormonatsrang als Prognose: IC +0.0735 [-0.0530, +0.1193] (n = 83)
- Trefferquote Rang 1 schlägt Rang 5: **0.337** [0.277, 0.410] (Zufall 0.5)
- Top-minus-Bottom-Spread über 1 Monat, annualisiert (×12/1): -0.2237 [-0.3027, -0.0545] (n = 83)

Je Klasse und Rang, 1 Monat: Trefferquote (relative Rendite > 0) und Monate:

| class | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| GOLD | nan | 0.500 | 0.567 | 0.538 | 0.600 |
| SILVER | 0.667 | 0.600 | 0.312 | 0.560 | 0.552 |
| UST10_ME | 0.319 | 0.371 | 0.000 | nan | nan |
| UST2_ME | 0.345 | 0.296 | 0.500 | 0.571 | 0.333 |
| US_EQ | 0.250 | 0.556 | 0.500 | 0.389 | 0.654 |

| class | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| GOLD | nan | 2 | 30 | 26 | 25 |
| SILVER | 3 | 10 | 16 | 25 | 29 |
| UST10_ME | 47 | 35 | 1 | nan | nan |
| UST2_ME | 29 | 27 | 10 | 14 | 3 |
| US_EQ | 4 | 9 | 26 | 18 | 26 |

### Horizont 3 Monate: Entscheidungen 2019-01 bis 2025-09

- Rang-IC (Spearman, Mittel je Monat): **-0.2222 [-0.3346, -0.0531] (n = 81)**; Anteil Monate mit IC > 0: 0.333
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **1.0000**, 95. Perzentil des Null-Mittels +0.0902 – bei überlappenden Fenstern zu eng, massgeblich ist das Intervall
- Vormonatsrang als Prognose: IC -0.0457 [-0.1605, -0.0160] (n = 81)
- Trefferquote Rang 1 schlägt Rang 5: **0.346** [0.272, 0.469] (Zufall 0.5)
- Top-minus-Bottom-Spread über 3 Monate, annualisiert (×12/3): -0.1338 [-0.2119, -0.0267] (n = 81)

### Horizont 6 Monate: Entscheidungen 2019-01 bis 2025-06

- Rang-IC (Spearman, Mittel je Monat): **-0.3705 [-0.5026, -0.1833] (n = 78)**; Anteil Monate mit IC > 0: 0.231
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **1.0000**, 95. Perzentil des Null-Mittels +0.0949 – bei überlappenden Fenstern zu eng, massgeblich ist das Intervall
- Vormonatsrang als Prognose: IC -0.0641 [-0.1513, +0.0282] (n = 78)
- Trefferquote Rang 1 schlägt Rang 5: **0.256** [0.167, 0.372] (Zufall 0.5)
- Top-minus-Bottom-Spread über 6 Monate, annualisiert (×12/6): -0.1408 [-0.1791, -0.0419] (n = 78)

### Wahrscheinlichkeiten (1 Monat, `logistic_tophalf`, Ziel `top_half`), 83 Monate

- Brier Modell 0.2364; Konstante 0.5 0.2500; Klimatologie 0.2361
- Skill gegen 0.5: +0.0136 [+0.0088, +0.0157] (n = 83); **Skill gegen Klimatologie: -0.0003 [-0.0009, +0.0002] (n = 83)** (positiv = Modell besser)
- Grundraten im Holdout: {'US_EQ': 0.482, 'UST10_ME': 0.229, 'UST2_ME': 0.313, 'GOLD': 0.47, 'SILVER': 0.506}

Reliability (Zehn-Prozent-Schritte, wegen der kleinen Stichprobe):

| bin | n | mean_prob | hit_freq |
|---|---|---|---|
| 0.20–0.30 | 30 | 0.288 | 0.367 |
| 0.30–0.40 | 164 | 0.366 | 0.311 |
| 0.40–0.50 | 214 | 0.438 | 0.477 |
| 0.50–0.60 | 7 | 0.506 | 0.286 |

Status (beschreibend) und Trefferquote/IC:

| status | months | hit_rate | mean_ic |
|---|---|---|---|
| signal | 83 | 0.337 | -0.159 |

## B. Paper-Regel (wie P8), 84 Renditemonate 2019-01 bis 2025-12

Regel und Baselines durch dieselbe Engine über die volle Geschichte ab 1976-06-30 (Ausführung `next_tradable`, Kosten 7.5 bp je Seite), Kennzahlen nur über den Holdout. Mittlere Risikoquote der Regel 0.663, Anteil Entscheidungen ganz in Cash 0.167.

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Trefferquote | Umsatz p.a. |
|---|---|---|---|---|---|---|---|
| Regel (Top-2, Trend, Vol-Ziel 10 %) | 84 | 0.0518 | 0.0607 | 0.4219 | -0.0414 | 0.6667 | 2.4454 |
| Equal Weight (5 Klassen) | 84 | 0.1353 | 0.1060 | 1.0121 | -0.1524 | 0.6190 | 0.1804 |
| 60/40 US_EQ/UST10_ME | 84 | 0.1079 | 0.1112 | 0.7437 | -0.2099 | 0.7024 | 0.1171 |
| Buy-and-Hold US_EQ | 84 | 0.1715 | 0.1658 | 0.8839 | -0.2393 | 0.6667 | 0.0000 |

Gepaarte Differenzen Regel − Baseline (90 %, Block 12 auf 84 Monaten – breit):

| Baseline | Δ Rendite p.a. | low | high | Δ Sharpe | Sharpe low | Sharpe high |
|---|---|---|---|---|---|---|
| Equal Weight (5 Klassen) | -0.0806 | -0.1109 | -0.0030 | -0.5903 | -1.2421 | 0.1842 |
| 60/40 US_EQ/UST10_ME | -0.0566 | -0.0970 | 0.0123 | -0.3219 | -1.0180 | 0.3125 |
| Buy-and-Hold US_EQ | -0.1205 | -0.1843 | -0.0258 | -0.4620 | -1.3454 | 0.2396 |

## Lesart nach ADR 049 (d) – vorab festgelegt

- In-sample 1981–2018 (P4): IC +0.0559 [-0.0020, +0.1056]; Holdout 2019–2025: IC **-0.1590** [-0.2338, -0.0530] über 83 Monate; Vormonatsrang-Baseline +0.0735.
- Replikation der Rangfolge: **GESCHEITERT (mittlerer IC ≤ 0)**.
- Wahrscheinlichkeiten: Skill gegen Klimatologie -0.0003 [-0.0009, +0.0002] – nicht von Null zu trennen (in-sample ebenfalls nicht).
- Regel gegen Equal Weight: Sharpe +0.422 gegen +1.012, Δ -0.590 [-1.242, +0.184] – berichtet ohne Pass/Fail (84 Monate).

Nach diesem Lauf wird an Modell und Regel nichts mehr geändert (ADR 049 a / ADR 052 f).

Laufzeit 37 s.
