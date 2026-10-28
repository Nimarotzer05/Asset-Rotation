# Prognose der Anlageklassen: historische Evaluation 1973–2018

Stand 2026-10-27. Modell `composite` v1, gerankte Klassen ['US_EQ', 'UST10', 'GOLD', 'SILVER'], Cash TBILL; Panel ab 1972-12-31.
Entscheidungen 1973-01-31 bis 2018-11-30 (1 M); Ergebnisfenster enden vor dem Pseudo-Holdout (2019-01-31).
Kennzahlen mit 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025).
Kriterien vorab in ADR 044 (f). Alle Zahlen aus `scripts/forecast_evaluation.py --config forecast`.

**Einordnung (Zweitprüfung 2026-10-26):** Features und Gewichte des Basismodells stammen aus der Forschungsphase (`src/signals.py`, Komposit der multi_asset_rotation) und wurden auf demselben Zeitraum gefunden; diese Evaluation ist deshalb **in-sample bezüglich der Modellwahl** – vorab fixiert sind die Kriterien und die Auswertung, nicht das Modell. Als Robustheitsargument dient die Variante „12-1-Momentum allein“ (keine angepassten Gewichte, ein Standardfeature der Literatur); echte Out-of-Sample-Evidenz liefern nur der unberührte Pseudo-Holdout 2019–2025 (einmalig, am Schluss) und die Live-Bilanz ab November 2026.

Feature-Satz: 5 Features. 3 Entscheidungsmonate am Panelanfang haben keinen Score (kein Feature berechenbar) und sind in keiner Stichprobe; 9 Monate (1973-04 bis 1973-12) sind mit unvollständigem Satz bewertet (1–4 Features, Forschungsformel: Summe der verfügbaren). Sie bleiben in der vorab festgelegten Stichprobe; die Sensitivität ohne sie steht beim 1-Monats-Horizont.

## Horizont 1 Monat (Hauptprognose)

- Rang-IC (Spearman, Mittel je Monat): **+0.0978 [+0.0511, +0.1409] (n = 548)**; Anteil Monate mit IC > 0: 0.535
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **< 0.0005 (0 von 2000 Ziehungen)**, 95. Perzentil des Null-Mittels +0.0394
- Vormonatsrang als Prognose: IC +0.0323 [-0.0080, +0.0693] (n = 551)
- Trefferquote Rang 1 schlägt Rang 4: **0.568** [0.531, 0.599] (Zufall 0.5)
- Top-minus-Bottom-Spread über 1 Monat, annualisiert (×12/1): +0.1095 [+0.0274, +0.1908] (n = 548)
- Sensitivität ohne die 9 Monate mit unvollständigem Feature-Satz: IC +0.0968 [+0.0519, +0.1395] (n = 539)

Je Jahrzehnt (IC):

| decade | months | mean | share_positive |
|---|---|---|---|
| 1973–1979 | 81 | 0.2148 | 0.6420 |
| 1980s | 120 | 0.1050 | 0.5333 |
| 1990s | 120 | 0.0583 | 0.4833 |
| 2000s | 120 | 0.0417 | 0.5083 |
| 2010–2018 | 107 | 0.1084 | 0.5421 |

Je Klasse und Rang, 1 Monat: Trefferquote (relative Rendite > 0) und Monate:

| class | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| GOLD | 0.419 | 0.452 | 0.418 | 0.432 |
| SILVER | 0.558 | 0.427 | 0.438 | 0.440 |
| UST10 | 0.489 | 0.582 | 0.455 | 0.500 |
| US_EQ | 0.610 | 0.520 | 0.505 | 0.480 |

| class | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| GOLD | 86 | 155 | 196 | 111 |
| SILVER | 113 | 82 | 128 | 225 |
| UST10 | 131 | 184 | 123 | 110 |
| US_EQ | 218 | 127 | 101 | 102 |

## Horizont 3 Monate (Nebenauswertung)

- Rang-IC (Spearman, Mittel je Monat): **+0.1158 [+0.0494, +0.1839] (n = 546)**; Anteil Monate mit IC > 0: 0.546
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **< 0.0005 (0 von 2000 Ziehungen)**, 95. Perzentil des Null-Mittels +0.0403 – der Test permutiert jeden Monat unabhängig; bei überlappenden Ergebnisfenstern ist seine Nullverteilung zu eng, massgeblich ist hier das Block-Bootstrap-Intervall
- Vormonatsrang als Prognose: IC +0.0262 [-0.0157, +0.0685] (n = 549)
- Trefferquote Rang 1 schlägt Rang 4: **0.579** [0.531, 0.628] (Zufall 0.5)
- Top-minus-Bottom-Spread über 3 Monate, annualisiert (×12/3): +0.1011 [+0.0259, +0.1805] (n = 546)

Je Jahrzehnt (IC):

| decade | months | mean | share_positive |
|---|---|---|---|
| 1973–1979 | 81 | 0.2123 | 0.5926 |
| 1980s | 120 | 0.1683 | 0.5667 |
| 1990s | 120 | 0.1733 | 0.5833 |
| 2000s | 120 | -0.0067 | 0.4750 |
| 2010–2018 | 105 | 0.0552 | 0.5238 |

## Horizont 6 Monate (Nebenauswertung)

- Rang-IC (Spearman, Mittel je Monat): **+0.1908 [+0.0987, +0.2704] (n = 543)**; Anteil Monate mit IC > 0: 0.593
- Zufälliger Rang (Permutation, 2000 Ziehungen): p = **< 0.0005 (0 von 2000 Ziehungen)**, 95. Perzentil des Null-Mittels +0.0398 – der Test permutiert jeden Monat unabhängig; bei überlappenden Ergebnisfenstern ist seine Nullverteilung zu eng, massgeblich ist hier das Block-Bootstrap-Intervall
- Vormonatsrang als Prognose: IC +0.0370 [-0.0125, +0.0832] (n = 546)
- Trefferquote Rang 1 schlägt Rang 4: **0.634** [0.567, 0.692] (Zufall 0.5)
- Top-minus-Bottom-Spread über 6 Monate, annualisiert (×12/6): +0.1186 [+0.0382, +0.2004] (n = 543)

Je Jahrzehnt (IC):

| decade | months | mean | share_positive |
|---|---|---|---|
| 1973–1979 | 81 | 0.2914 | 0.6667 |
| 1980s | 120 | 0.1883 | 0.5417 |
| 1990s | 120 | 0.2683 | 0.6750 |
| 2000s | 120 | 0.0650 | 0.5167 |
| 2010–2018 | 102 | 0.1706 | 0.5882 |

## Wahrscheinlichkeiten (1 Monat, Hauptausgabe) – Ziel `top_half`

Ziel „landet in der oberen Hälfte (Rang 1–2 von 4)“ (ADR 045 b). Grundraten je Klasse 1973–2018: {'US_EQ': 0.561, 'UST10': 0.528, 'GOLD': 0.45, 'SILVER': 0.461}.
Primäres Modell `logistic_tophalf`; alle Modelle punkt-in-Zeit über 488 Monatsenden; Prior 60 Monate; Status-Marge 0.05 (beschreibend).
Baselines: Konstante 0.5 Brier 0.2500; Klimatologie (expandierende Häufigkeit je Klasse) Brier 0.2487. Skill = Brier(Baseline) − Brier(Modell), positiv = Modell besser; Kriterium ADR 045: Skill gegen Klimatologie mit Intervall ohne Null.

| Modell | Brier | Skill vs 0.5 | low | high | Skill vs Klimatologie | low  | high  |
|---|---|---|---|---|---|---|---|
| logistic_tophalf | 0.24761 | 0.00239 | -0.00165 | 0.00678 | 0.00113 | -0.00163 | 0.00422 |
| rank_class | 0.24860 | 0.00140 | -0.00115 | 0.00394 | 0.00014 | -0.00142 | 0.00192 |
| rank_frequency | 0.24853 | 0.00147 | -0.00106 | 0.00407 | 0.00021 | -0.00267 | 0.00331 |
| logistic_score | 0.24790 | 0.00210 | -0.00129 | 0.00573 | 0.00084 | -0.00270 | 0.00461 |

Reliability des primären Modells (vorhergesagt vs. beobachtet):

| bin | n | mean_prob | hit_freq |
|---|---|---|---|
| 0.30–0.35 | 23 | 0.336 | 0.435 |
| 0.35–0.40 | 201 | 0.381 | 0.413 |
| 0.40–0.45 | 371 | 0.426 | 0.461 |
| 0.45–0.50 | 432 | 0.475 | 0.468 |
| 0.50–0.55 | 338 | 0.524 | 0.512 |
| 0.55–0.60 | 318 | 0.574 | 0.569 |
| 0.60–0.65 | 233 | 0.622 | 0.597 |
| 0.65–0.70 | 36 | 0.659 | 0.472 |

Brier je Jahrzehnt (primäres Modell, Klimatologie, 0.5):

| decade | Modell | Klimatologie | 0.5 | Monate |
|---|---|---|---|---|
| 1973–1979 | 0.2305 | 0.2426 | 0.2500 | 21 |
| 1980s | 0.2457 | 0.2494 | 0.2500 | 120 |
| 1990s | 0.2423 | 0.2405 | 0.2500 | 120 |
| 2000s | 0.2579 | 0.2598 | 0.2500 | 120 |
| 2010–2018 | 0.2476 | 0.2460 | 0.2500 | 107 |

Brier je Klasse:

| Klasse | Modell | Klimatologie | 0.5 |
|---|---|---|---|
| US_EQ | 0.2456 | 0.2469 | 0.2500 |
| UST10 | 0.2481 | 0.2503 | 0.2500 |
| GOLD | 0.2488 | 0.2484 | 0.2500 |
| SILVER | 0.2480 | 0.2494 | 0.2500 |

Zum Vergleich das alte Ziel „schlägt den Durchschnitt“ (ADR 044): Klimatologie Brier 0.2489, Grundraten {'US_EQ': 0.544, 'UST10': 0.515, 'GOLD': 0.434, 'SILVER': 0.461}.

Status (beschreibend, ADR 045 c) und Trefferquote (Rang 1 schlägt Rang 4) bzw. IC:

| status | months | hit_rate | mean_ic |
|---|---|---|---|
| no_clear_signal | 53 | 0.642 | 0.151 |
| signal | 435 | 0.556 | 0.088 |
| warmup | 60 | 0.583 | 0.123 |

Variante A (Terzil des heutigen Score-Abstands Rang 1 – Rang 4, Terzile aus der Vergangenheit):

| tercile | months | hit_rate | mean_ic |
|---|---|---|---|
| low | 159 | 0.566 | 0.072 |
| mid | 150 | 0.600 | 0.123 |
| high | 179 | 0.536 | 0.092 |

## Varianten (1 Monat, gepaarte Differenz des IC zum Basismodell)

| Variante | IC | IC low | IC high | Δ zum Basismodell | Δ low | Δ high |
|---|---|---|---|---|---|---|
| 12-1-Momentum allein | 0.1083 | 0.0564 | 0.1551 | 0.0115 | -0.0175 | 0.0404 |
| Basismodell + Regime-Tilts | 0.0938 | 0.0456 | 0.1376 | -0.0040 | -0.0175 | 0.0099 |

Regime-Labels bekannt in 551 von 551 Monaten (unbekannt = kein Tilt).

## Abgeleitete Gewichte gegen Portfolio-Baselines (vor Kosten, Umsetzung zum Entscheidungsschluss)

Nur zur Einordnung – die Portfolio-Schicht mit Kosten, ehrlichem Timing und Vol-Ziel ist Schritt P8 und wird nur gebaut, wenn die Kriterien erfüllt sind.

|  | months | ann_return | ann_vol | sharpe_ex_cash | max_drawdown |
|---|---|---|---|---|---|
| Abgeleitet: Top-2 + Trendfilter | 547.0000 | 0.1058 | 0.1858 | 0.3831 | -0.4270 |
| Equal Weight (4 Klassen) | 547.0000 | 0.0831 | 0.1344 | 0.3125 | -0.3838 |
| 60/40 US_EQ/UST10 | 547.0000 | 0.0949 | 0.0976 | 0.5000 | -0.2880 |
| Buy-and-Hold US_EQ | 547.0000 | 0.1050 | 0.1506 | 0.4295 | -0.5078 |

Gepaarte Differenz der Monatsrendite (annualisiert), abgeleitet minus Baseline:

- Equal Weight: +0.0289 [-0.0005, +0.0602] (n = 547)
- 60/40: +0.0222 [-0.0277, +0.0749] (n = 547)
- Buy-and-Hold: +0.0062 [-0.0504, +0.0646] (n = 547)

## Urteil nach ADR 044 (f) – Kriterien vorab festgelegt

1. IC-Intervall (1 M) schliesst die Null aus: **ja** (+0.0511 … +0.1409)
2. Permutations-p < 0.05: **ja** (p = < 0.0005 (0 von 2000 Ziehungen))
3. IC positiv in ≥ 3 der 4 vollständigen Jahrzehnte: **ja** (4 von 4)
→ Prognosevorteil nach den vorab fixierten Kriterien: **JA** (in-sample bezüglich der Modellwahl, siehe Einordnung oben)

- Wahrscheinlichkeiten informativ (ADR 045: Brier-Skill gegen die Klimatologie > 0, Intervall ohne Null): primäres Modell `logistic_tophalf` **nein**; alle Modelle: logistic_tophalf nein, rank_class nein, rank_frequency nein, logistic_score nein
- Horizont 3 M behalten (IC-Intervall ohne Null und IC über Vormonatsrang): **ja**
- Horizont 6 M behalten (IC-Intervall ohne Null und IC über Vormonatsrang): **ja**
- 12-1-Momentum allein empfehlen (Δ-Intervall ohne Null): **nein**
- Basismodell + Regime-Tilts empfehlen (Δ-Intervall ohne Null): **nein**
- Status brauchbar (Trefferquote in „signal“ > in „no_clear_signal“): **nein**

Laufzeit 75 s.
