# Prognose der Anlageklassen: historische Evaluation 1981–2018 (Forschungsrunde 2, `forecast_v2`)

Stand 2026-10-27. Modell `mcv` v1, gerankte Klassen ['US_EQ', 'UST10_ME', 'UST2_ME', 'GOLD', 'SILVER'], Cash TBILL; Panel ab 1976-06-30.
Entscheidungen 1981-07-31 bis 2018-11-30 (1 M); Ergebnisfenster enden vor dem Pseudo-Holdout (2019-01-31).
Kennzahlen mit 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025).
Kriterien vorab in ADR 044 (f), übernommen in ADR 052 (d/e). Alle Zahlen aus `scripts/forecast_evaluation.py --config forecast_v2`.

**Einordnung:** Familien, Gewichte (gleich), Klassen und Fenster sind in ADR 052 vor dem ersten Lauf fixiert und nicht auf diesen Daten gewählt; die Ablationen unten werden berichtet und entscheiden nicht. Die Wahl der drei Standardfamilien ist aber im Wissen um die Literatur und um Runde 1 getroffen, und derselbe Zeitraum wurde in Runde 1 bereits ausgewertet – ein zweiter Blick auf dieselben Jahre ist keine unabhängige Stichprobe. Echte Out-of-Sample-Evidenz liefern der einmalige Blick auf 2019–2025 (ADR 052 f) und die Live-Bilanz.

Feature-Satz: 3 Features. 0 Entscheidungsmonate am Panelanfang haben keinen Score (kein Feature berechenbar) und sind in keiner Stichprobe; 0 Monate (–) sind mit unvollständigem Satz bewertet (0–0 Features, Forschungsformel: Summe der verfügbaren). Sie bleiben in der vorab festgelegten Stichprobe; die Sensitivität ohne sie steht beim 1-Monats-Horizont.

## Horizont 1 Monat (Hauptprognose)

- Rang-IC (Spearman, Mittel je Monat): **+0.0559 [-0.0020, +0.1056] (n = 449)**; Anteil Monate mit IC > 0: 0.537
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **0.0070**, 95. Perzentil des Null-Mittels +0.0392
- Vormonatsrang als Prognose: IC +0.0165 [-0.0296, +0.0566] (n = 449)
- Trefferquote Rang 1 schlägt Rang 5: **0.548** [0.499, 0.588] (Zufall 0.5)
- Top-minus-Bottom-Spread über 1 Monat, annualisiert (×12/1): +0.0185 [-0.0538, +0.0840] (n = 449)

Je Jahrzehnt (IC):

| decade | months | mean | share_positive |
|---|---|---|---|
| 1981–1989 | 102 | 0.1225 | 0.6078 |
| 1990s | 120 | 0.0067 | 0.4417 |
| 2000s | 120 | 0.0217 | 0.5500 |
| 2010–2018 | 107 | 0.0860 | 0.5607 |

Je Klasse und Rang, 1 Monat: Trefferquote (relative Rendite > 0) und Monate:

| class | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| GOLD | 0.714 | 0.350 | 0.421 | 0.390 | 0.446 |
| SILVER | 0.378 | 0.581 | 0.386 | 0.440 | 0.455 |
| UST10_ME | 0.527 | 0.535 | 0.519 | 0.522 | 1.000 |
| UST2_ME | 0.550 | 0.503 | 0.510 | 0.396 | 0.353 |
| US_EQ | 0.574 | 0.607 | 0.561 | 0.594 | 0.541 |

| class | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| GOLD | 7 | 20 | 95 | 159 | 168 |
| SILVER | 37 | 31 | 44 | 150 | 187 |
| UST10_ME | 237 | 159 | 27 | 23 | 3 |
| UST2_ME | 100 | 183 | 96 | 53 | 17 |
| US_EQ | 68 | 56 | 187 | 64 | 74 |

## Horizont 3 Monate (Nebenauswertung)

- Rang-IC (Spearman, Mittel je Monat): **+0.0908 [+0.0116, +0.1513] (n = 447)**; Anteil Monate mit IC > 0: 0.544
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **< 0.0005 (0 von 2000 Ziehungen)**, 95. Perzentil des Null-Mittels +0.0387 – der Test permutiert jeden Monat unabhängig; bei überlappenden Ergebnisfenstern ist seine Nullverteilung zu eng, massgeblich ist hier das Block-Bootstrap-Intervall
- Vormonatsrang als Prognose: IC +0.0072 [-0.0360, +0.0450] (n = 447)
- Trefferquote Rang 1 schlägt Rang 5: **0.562** [0.499, 0.609] (Zufall 0.5)
- Top-minus-Bottom-Spread über 3 Monate, annualisiert (×12/3): +0.0437 [-0.0229, +0.0957] (n = 447)

Je Jahrzehnt (IC):

| decade | months | mean | share_positive |
|---|---|---|---|
| 1981–1989 | 102 | 0.1833 | 0.6569 |
| 1990s | 120 | 0.0558 | 0.5167 |
| 2000s | 120 | 0.0267 | 0.4917 |
| 2010–2018 | 105 | 0.1143 | 0.5238 |

## Horizont 6 Monate (Nebenauswertung)

- Rang-IC (Spearman, Mittel je Monat): **+0.1297 [+0.0173, +0.2144] (n = 444)**; Anteil Monate mit IC > 0: 0.572
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **< 0.0005 (0 von 2000 Ziehungen)**, 95. Perzentil des Null-Mittels +0.0405 – der Test permutiert jeden Monat unabhängig; bei überlappenden Ergebnisfenstern ist seine Nullverteilung zu eng, massgeblich ist hier das Block-Bootstrap-Intervall
- Vormonatsrang als Prognose: IC +0.0322 [-0.0185, +0.0793] (n = 444)
- Trefferquote Rang 1 schlägt Rang 5: **0.581** [0.500, 0.642] (Zufall 0.5)
- Top-minus-Bottom-Spread über 6 Monate, annualisiert (×12/6): +0.0495 [-0.0137, +0.0968] (n = 444)

Je Jahrzehnt (IC):

| decade | months | mean | share_positive |
|---|---|---|---|
| 1981–1989 | 102 | 0.2098 | 0.6373 |
| 1990s | 120 | 0.1050 | 0.5833 |
| 2000s | 120 | 0.0233 | 0.4833 |
| 2010–2018 | 102 | 0.2039 | 0.5980 |

## Wahrscheinlichkeiten (1 Monat, Hauptausgabe) – Ziel `top_half`

Ziel „landet in der oberen Hälfte (Rang 1–2 von 5)“ (ADR 045 b). Grundraten je Klasse 1981–2018: {'US_EQ': 0.488, 'UST10_ME': 0.421, 'UST2_ME': 0.298, 'GOLD': 0.383, 'SILVER': 0.41}.
Primäres Modell `logistic_tophalf`; alle Modelle punkt-in-Zeit über 438 Monatsenden; Prior 60 Monate; Status-Marge 0.05 (beschreibend).
Baselines: Konstante 0.5 Brier 0.2500; Klimatologie (expandierende Häufigkeit je Klasse) Brier 0.2373. Skill = Brier(Baseline) − Brier(Modell), positiv = Modell besser; Kriterium ADR 045: Skill gegen Klimatologie mit Intervall ohne Null.

| Modell | Brier | Skill vs 0.5 | low | high | Skill vs Klimatologie | low  | high  |
|---|---|---|---|---|---|---|---|
| logistic_tophalf | 0.24024 | 0.00976 | 0.00767 | 0.01286 | -0.00053 | -0.00307 | 0.00144 |
| rank_class | 0.24124 | 0.00876 | 0.00727 | 0.01022 | -0.00360 | -0.00557 | -0.00170 |
| rank_frequency | 0.24160 | 0.00840 | 0.00782 | 0.00899 | -0.00418 | -0.00704 | -0.00133 |
| logistic_score | 0.24106 | 0.00894 | 0.00877 | 0.01000 | -0.00312 | -0.00576 | -0.00039 |

Reliability des primären Modells (vorhergesagt vs. beobachtet):

| bin | n | mean_prob | hit_freq |
|---|---|---|---|
| 0.15–0.20 | 1 | 0.171 | 1.000 |
| 0.20–0.25 | 2 | 0.230 | 0.500 |
| 0.25–0.30 | 203 | 0.284 | 0.325 |
| 0.30–0.35 | 285 | 0.323 | 0.330 |
| 0.35–0.40 | 510 | 0.380 | 0.425 |
| 0.40–0.45 | 701 | 0.418 | 0.398 |
| 0.45–0.50 | 376 | 0.476 | 0.492 |
| 0.50–0.55 | 81 | 0.515 | 0.259 |
| 0.55–0.60 | 29 | 0.573 | 0.414 |
| 0.60–0.65 | 2 | 0.609 | 0.000 |

Brier je Jahrzehnt (primäres Modell, Klimatologie, 0.5):

| decade | Modell | Klimatologie | 0.5 | Monate |
|---|---|---|---|---|
| 1981–1989 | 0.2517 | 0.2377 | 0.2500 | 91 |
| 1990s | 0.2355 | 0.2335 | 0.2500 | 120 |
| 2000s | 0.2418 | 0.2435 | 0.2500 | 120 |
| 2010–2018 | 0.2341 | 0.2346 | 0.2500 | 107 |

Brier je Klasse:

| Klasse | Modell | Klimatologie | 0.5 |
|---|---|---|---|
| US_EQ | 0.2550 | 0.2518 | 0.2500 |
| UST10_ME | 0.2480 | 0.2441 | 0.2500 |
| UST2_ME | 0.2078 | 0.2057 | 0.2500 |
| GOLD | 0.2443 | 0.2397 | 0.2500 |
| SILVER | 0.2461 | 0.2453 | 0.2500 |

Zum Vergleich das alte Ziel „schlägt den Durchschnitt“ (ADR 044): Klimatologie Brier 0.2504, Grundraten {'US_EQ': 0.57, 'UST10_ME': 0.532, 'UST2_ME': 0.497, 'GOLD': 0.421, 'SILVER': 0.445}.

Status (beschreibend, ADR 045 c) und Trefferquote (Rang 1 schlägt Rang 5) bzw. IC:

| status | months | hit_rate | mean_ic |
|---|---|---|---|
| signal | 438 | 0.543 | 0.047 |
| warmup | 11 | 0.727 | 0.418 |

Variante A (Terzil des heutigen Score-Abstands Rang 1 – Rang 5, Terzile aus der Vergangenheit):

| tercile | months | hit_rate | mean_ic |
|---|---|---|---|
| low | 125 | 0.528 | 0.017 |
| mid | 134 | 0.493 | -0.022 |
| high | 130 | 0.577 | 0.092 |

## Varianten (1 Monat, gepaarte Differenz des IC zum Basismodell) – Ablationen, berichtet, entscheiden nicht (ADR 052 e)

| Variante | IC | IC low | IC high | Δ zum Basismodell | Δ low | Δ high |
|---|---|---|---|---|---|---|
| momentum | 0.0996 | 0.0510 | 0.1439 | 0.0437 | -0.0024 | 0.0964 |
| carry | 0.0841 | 0.0267 | 0.1321 | 0.0282 | -0.0121 | 0.0683 |
| value | -0.0973 | -0.1544 | -0.0461 | -0.1532 | -0.2254 | -0.0826 |
| momentum_carry | 0.1051 | 0.0486 | 0.1497 | 0.0492 | 0.0171 | 0.0811 |
| momentum_value | -0.0120 | -0.0512 | 0.0307 | -0.0679 | -0.1073 | -0.0189 |
| carry_value | -0.0163 | -0.0664 | 0.0272 | -0.0722 | -0.1176 | -0.0274 |


## Abgeleitete Gewichte gegen Portfolio-Baselines (vor Kosten, Umsetzung zum Entscheidungsschluss)

Nur zur Einordnung – die Portfolio-Schicht mit Kosten, ehrlichem Timing und Vol-Ziel ist Schritt P8 und wird nur gebaut, wenn die Kriterien erfüllt sind.

|  | months | ann_return | ann_vol | sharpe_ex_cash | max_drawdown |
|---|---|---|---|---|---|
| Abgeleitet: Top-2 + Trendfilter | 448.0000 | 0.0816 | 0.0698 | 0.5984 | -0.1388 |
| Equal Weight (5 Klassen) | 448.0000 | 0.0676 | 0.0921 | 0.3262 | -0.2215 |
| 60/40 US_EQ/UST10_ME | 448.0000 | 0.1034 | 0.0952 | 0.6706 | -0.2921 |
| Buy-and-Hold US_EQ | 448.0000 | 0.1122 | 0.1469 | 0.5311 | -0.5078 |

Gepaarte Differenz der Monatsrendite (annualisiert), abgeleitet minus Baseline:

- Equal Weight: +0.0113 [-0.0188, +0.0338] (n = 448)
- 60/40: -0.0222 [-0.0500, +0.0022] (n = 448)
- Buy-and-Hold: -0.0366 [-0.0814, +0.0015] (n = 448)

## Urteil nach ADR 044 (f) – Kriterien vorab festgelegt

1. IC-Intervall (1 M) schliesst die Null aus: **nein** (-0.0020 … +0.1056)
2. Permutations-p < 0.05: **ja** (p = 0.0070)
3. IC positiv in ≥ 3 der 4 vollständigen Jahrzehnte: **ja** (4 von 4)
→ Prognosevorteil nach den vorab fixierten Kriterien: **NEIN** (Modell vorab fixiert, siehe Einordnung oben)

- Wahrscheinlichkeiten informativ (ADR 045: Brier-Skill gegen die Klimatologie > 0, Intervall ohne Null): primäres Modell `logistic_tophalf` **nein**; alle Modelle: logistic_tophalf nein, rank_class nein, rank_frequency nein, logistic_score nein
- Horizont 3 M behalten (IC-Intervall ohne Null und IC über Vormonatsrang): **ja**
- Horizont 6 M behalten (IC-Intervall ohne Null und IC über Vormonatsrang): **ja**
- momentum besser als das Basismodell (Δ-Intervall ohne Null): **nein** – berichtet, entscheidet nicht
- carry besser als das Basismodell (Δ-Intervall ohne Null): **nein** – berichtet, entscheidet nicht
- value besser als das Basismodell (Δ-Intervall ohne Null): **nein** – berichtet, entscheidet nicht
- momentum_carry besser als das Basismodell (Δ-Intervall ohne Null): **ja** – berichtet, entscheidet nicht
- momentum_value besser als das Basismodell (Δ-Intervall ohne Null): **nein** – berichtet, entscheidet nicht
- carry_value besser als das Basismodell (Δ-Intervall ohne Null): **nein** – berichtet, entscheidet nicht
- Status brauchbar (Trefferquote in „signal“ > in „no_clear_signal“): **nicht messbar (nur ein Status)**

Laufzeit 54 s.
