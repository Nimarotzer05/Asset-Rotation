<!-- copy of 2026-09.md -->
# Prognose der Anlageklassen – Entscheidung 2026-09-30

Erstellt 2026-10-29 · Modell `composite_fed` v1 · Datenstand `2026-10-29T13:28:54Z/9f3da1d2b4` · gerankt SPY, IEF, GLD, SLV · nur Trend CPER · Cash BIL

## 1 Monat (Hauptprognose) – Status: `signal` (mindestens eine Wahrscheinlichkeit weicht um mehr als die Marge von 50 % ab; beschreibend, kein Verlässlichkeitsmass)

| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend |
|---|---|---|---|---|---|
| 1 | SLV | 49 % | +0.43 | +0.17 % [-0.39, +0.75] | ab ▼ (-15.9 % zum 10M-Schnitt) |
| 2 | SPY | 57 % | +0.23 | +0.03 % [-0.38, +0.39] | auf ▲ (+6.3 % zum 10M-Schnitt) |
| 3 | GLD | 53 % | -0.15 | +0.46 % [+0.15, +0.96] | ab ▼ (-7.7 % zum 10M-Schnitt) |
| 4 | IEF | 41 % | -0.52 | -0.66 % [-1.30, -0.12] | ab ▼ (-4.0 % zum 10M-Schnitt) |

**Nachgeholt (ADR 050):** Diese Prognose wurde mehr als die erlaubte Frist nach dem Entscheidungsdatum geschrieben. Sie ist korrekt aus der Sicht am Entscheidungsdatum berechnet, zählt aber nicht zur Live-Bilanz.

- backfilled: written 2026-10-29, 29 days after the decision date (limit 7); computed from the view at 2026-09-30 like any forecast, but not counted in the live track record

Nur Trend (beschreibend, kein belegter Prognosevorteil – P5):

| Klasse | Trend |
|---|---|
| CPER | auf ▲ (+6.0 % zum 10M-Schnitt) |

Lesart: P(obere Hälfte) = Wahrscheinlichkeit, dass die Klasse über den Horizont zu den besseren zwei der vier gehört (kalibriert auf der Geschichte bis zum Entscheidungsdatum). Rangfolge = Komposit von Runde 1 plus Fed-Kategorie (Zinsentscheide, realer Leitzins, Inflation, Arbeitsmarkt, Zinskurve; ADR 063); in Runde 5 **nicht belegt** – in-sample 1978–2018 schlechter als das Komposit allein (Δ IC −0.058 [−0.108, −0.006], `output/forecast_fed/ROUND5.md`, ADR 064); zweite Liveprognose neben Runde 1; ob sie live hält, zeigt allein die Bilanz unten. „Mittel des Rangs bisher“ = mittlere relative Rendite, die dieser Rang in den bis dahin bekannten Monaten erzielte, mit dem Block-Bootstrap-Intervall dieses Mittels – kein Vorhersageintervall für den kommenden Monat, dessen Streuung um ein Vielfaches grösser ist.

## 3 Monate (Nebenauswertung) – Status `signal`

| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend |
|---|---|---|---|---|---|
| 1 | SLV | 47 % | +0.43 | +0.30 % [-0.94, +1.61] | ab ▼ (-15.9 % zum 10M-Schnitt) |
| 2 | SPY | 62 % | +0.23 | +0.79 % [-0.41, +2.16] | auf ▲ (+6.3 % zum 10M-Schnitt) |
| 3 | GLD | 55 % | -0.15 | +1.32 % [+0.46, +2.50] | ab ▼ (-7.7 % zum 10M-Schnitt) |
| 4 | IEF | 36 % | -0.52 | -2.41 % [-4.15, -1.12] | ab ▼ (-4.0 % zum 10M-Schnitt) |

## 6 Monate (Nebenauswertung) – Status `signal`

| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend |
|---|---|---|---|---|---|
| 1 | SLV | 50 % | +0.43 | +0.62 % [-1.27, +2.54] | ab ▼ (-15.9 % zum 10M-Schnitt) |
| 2 | SPY | 61 % | +0.23 | +1.92 % [+0.14, +4.21] | auf ▲ (+6.3 % zum 10M-Schnitt) |
| 3 | GLD | 61 % | -0.15 | +2.13 % [+0.76, +3.21] | ab ▼ (-7.7 % zum 10M-Schnitt) |
| 4 | IEF | 28 % | -0.52 | -4.67 % [-7.52, -2.29] | ab ▼ (-4.0 % zum 10M-Schnitt) |

## Bilanz bisher (abgerechnete Prognosen)

| Horizont | abgerechnet | Rang-IC (Mittel) | IC > 0 | Rang 1 schlägt letzten | Brier (Modell / 0.5) | Vormonatsrang-IC |
|---|---|---|---|---|---|---|
| 1 M | 0 | – | – | – | – | – |
| 3 M | 0 | – | – | – | – | – |
| 6 M | 0 | – | – | – | – | – |

## Letztes Ergebnis

Noch keine Prognose abgerechnet.

Journal: `journal/forecast/forecasts.jsonl` und `outcomes.jsonl` (append-only, Hash-Kette; `rotationlab forecast verify`; die Kette erkennt Änderungen im Innern der Datei, eine Kürzung am Ende nur gegen den Anker aus dem Actions-Log).
