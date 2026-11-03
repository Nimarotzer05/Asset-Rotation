<!-- copy of 2026-10.md -->
# Prognose der Anlageklassen – Entscheidung 2026-10-31

Erstellt 2026-11-03 · Modell `composite` v1 · Datenstand `2026-11-03T14:30:52Z/3b208b26b7` · gerankt SPY, IEF, GLD, SLV · nur Trend CPER · Cash BIL

## 1 Monat (Hauptprognose) – Status: `signal` (mindestens eine Wahrscheinlichkeit weicht um mehr als die Marge von 50 % ab; beschreibend, kein Verlässlichkeitsmass)

| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend | Gewicht (Paper-Regel) |
|---|---|---|---|---|---|---|
| 1 | SPY | 57 % | +0.71 | +0.08 % [-0.40, +0.66] | auf ▲ (+4.2 % zum 10M-Schnitt) | 50 % |
| 2 | GLD | 51 % | -0.17 | +0.13 % [-0.27, +0.45] | ab ▼ (-12.9 % zum 10M-Schnitt) | 0 % |
| 3 | SLV | 45 % | -0.19 | -0.05 % [-0.42, +0.38] | ab ▼ (-29.1 % zum 10M-Schnitt) | 0 % |
| 4 | IEF | 47 % | -0.35 | -0.16 % [-0.49, +0.14] | ab ▼ (-0.9 % zum 10M-Schnitt) | 0 % |
| – | Cash | | | | | 50 % |

Nur Trend (beschreibend, kein belegter Prognosevorteil – P5):

| Klasse | Trend |
|---|---|
| CPER | auf ▲ (+2.8 % zum 10M-Schnitt) |

Lesart: P(obere Hälfte) = Wahrscheinlichkeit, dass die Klasse über den Horizont zu den besseren zwei der vier gehört (kalibriert auf der Geschichte bis zum Entscheidungsdatum). Die Rangfolge ist der im Backtest geprüfte Teil (`output/forecast/EVALUATION.md`, in-sample 1973–2018); im Pseudo-Holdout 2019–2025 hat sie sich **nicht** repliziert (`output/forecast/HOLDOUT.md`); ob sie live hält, zeigt allein die Bilanz unten. „Mittel des Rangs bisher“ = mittlere relative Rendite, die dieser Rang in den bis dahin bekannten Monaten erzielte, mit dem Block-Bootstrap-Intervall dieses Mittels – kein Vorhersageintervall für den kommenden Monat, dessen Streuung um ein Vielfaches grösser ist.

## 3 Monate (Nebenauswertung) – Status `signal`

| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend |
|---|---|---|---|---|---|
| 1 | SPY | 57 % | +0.71 | +0.58 % [-0.72, +2.15] | auf ▲ (+4.2 % zum 10M-Schnitt) |
| 2 | GLD | 52 % | -0.17 | -0.33 % [-1.02, +0.35] | ab ▼ (-12.9 % zum 10M-Schnitt) |
| 3 | SLV | 48 % | -0.19 | -0.64 % [-1.62, +0.18] | ab ▼ (-29.1 % zum 10M-Schnitt) |
| 4 | IEF | 42 % | -0.35 | +0.39 % [-0.79, +1.60] | ab ▼ (-0.9 % zum 10M-Schnitt) |

## 6 Monate (Nebenauswertung) – Status `signal`

| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend |
|---|---|---|---|---|---|
| 1 | SPY | 60 % | +0.71 | +0.44 % [-1.85, +2.94] | auf ▲ (+4.2 % zum 10M-Schnitt) |
| 2 | GLD | 54 % | -0.17 | +0.52 % [-0.86, +2.27] | ab ▼ (-12.9 % zum 10M-Schnitt) |
| 3 | SLV | 46 % | -0.19 | -0.21 % [-1.89, +1.45] | ab ▼ (-29.1 % zum 10M-Schnitt) |
| 4 | IEF | 39 % | -0.35 | -0.76 % [-2.91, +1.10] | ab ▼ (-0.9 % zum 10M-Schnitt) |

## Bilanz bisher (abgerechnete Prognosen)

| Horizont | abgerechnet | Rang-IC (Mittel) | IC > 0 | Rang 1 schlägt letzten | Brier (Modell / 0.5) | Vormonatsrang-IC |
|---|---|---|---|---|---|---|
| 1 M | 0 | – | – | – | – | – |
| 3 M | 0 | – | – | – | – | – |
| 6 M | 0 | – | – | – | – | – |

Nicht in der Bilanz (nachgeholt, ADR 050 – mehr als die erlaubte Frist nach dem Entscheidungsdatum geschrieben): 1 M: 1

## Letztes Ergebnis

Prognose vom 2026-09-30 (1 M), abgerechnet per 2026-10-31 – nachgeholt, nicht in der Bilanz:

| Klasse | prognostizierter Rang | P(obere Hälfte) | realisierte relative Rendite | realisierter Rang | obere Hälfte |
|---|---|---|---|---|---|
| IEF | 2 | 47 % | +8.74 % | 1 | ja |
| SPY | 1 | 56 % | +4.74 % | 2 | ja |
| GLD | 3 | 51 % | -0.94 % | 3 | nein |
| SLV | 4 | 45 % | -12.54 % | 4 | nein |

Rang-IC +0.80; Rang 1 schlug den letzten; Brier 0.2334 (0.5: 0.2500); Vormonatsrang-IC +0.80; Trend: CPER falsch; Paper-Regel -0.28 % gegen Equal Weight -5.64 %.

Journal: `journal/forecast/forecasts.jsonl` und `outcomes.jsonl` (append-only, Hash-Kette; `rotationlab forecast verify`; die Kette erkennt Änderungen im Innern der Datei, eine Kürzung am Ende nur gegen den Anker aus dem Actions-Log).
