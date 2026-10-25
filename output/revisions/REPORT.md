# Revisionen: Was Echtzeitdaten an den Makrosignalen ändern

Stichprobe aus 3 echten FRED-MD-Vintages (2019-09, 2021-04, 2026-10), jede mit der neuesten (2026-10) verglichen. Quelle und Datierung: `data/raw/fredmd_vintages/vintages.yaml`. Erzeugt mit `scripts/revision_study.py`.

## 1. Wie viel wird revidiert?

Anteil der Monatswerte, die sich bis heute geändert haben, und mittlere Änderung der Jahresrate (bei der Arbeitslosenquote: des Niveaus). „Rand“ = die letzten 24 Monate der alten Vintage – die Werte, auf denen eine Entscheidung damals beruhte.

**Vintage 2019-09**

| Reihe | revidiert | Ø |Δ| gesamt | Ø |Δ| letzte 24 M | max |Δ| Rand | Einheit |
|---|---|---|---|---|---|
| Industrieproduktion | 100% | 0.12 | 1.14 | 1.89 | Pkt Jahresrate |
| Beschäftigung (NFP) | 48% | 0.01 | 0.15 | 0.36 | Pkt Jahresrate |
| CPI | 8% | 0.00 | 0.03 | 0.09 | Pkt Jahresrate |
| Kern-CPI | 8% | 0.00 | 0.04 | 0.10 | Pkt Jahresrate |
| PCE-Deflator | 100% | 0.02 | 0.06 | 0.13 | Pkt Jahresrate |
| Realeinkommen | 100% | 0.13 | 0.40 | 0.93 | Pkt Jahresrate |
| Einzelhandel | 100% | 0.08 | 0.37 | 0.70 | Pkt Jahresrate |
| Baubeginne | 8% | 0.06 | 0.81 | 2.32 | Pkt Jahresrate |
| Arbeitslosenquote | 2% | 0.00 | 0.04 | 0.10 | Pkt |

**Vintage 2021-04**

| Reihe | revidiert | Ø |Δ| gesamt | Ø |Δ| letzte 24 M | max |Δ| Rand | Einheit |
|---|---|---|---|---|---|
| Industrieproduktion | 100% | 0.13 | 0.89 | 1.78 | Pkt Jahresrate |
| Beschäftigung (NFP) | 48% | 0.01 | 0.08 | 0.26 | Pkt Jahresrate |
| CPI | 7% | 0.00 | 0.03 | 0.13 | Pkt Jahresrate |
| Kern-CPI | 7% | 0.00 | 0.04 | 0.14 | Pkt Jahresrate |
| PCE-Deflator | 100% | 0.03 | 0.10 | 0.32 | Pkt Jahresrate |
| Realeinkommen | 100% | 0.16 | 1.17 | 2.55 | Pkt Jahresrate |
| Einzelhandel | 100% | 0.08 | 0.39 | 2.17 | Pkt Jahresrate |
| Baubeginne | 8% | 0.09 | 1.21 | 3.70 | Pkt Jahresrate |
| Arbeitslosenquote | 1% | 0.00 | 0.03 | 0.10 | Pkt |

Die Industrieproduktion wurde zwischendurch umbasiert (Niveau heute im Median 0.972× des Werts von 2019-09): Niveaus über Vintages hinweg sind nicht vergleichbar, Jahresraten schon. Features rechnen deshalb immer innerhalb eines Datenstands (MarketView), nie über Vintages gemischt.

## 2. Hätten die Studien-Regime damals anders ausgesehen?

Regime wie in `src/features.py::macro_regime` (Richtung der 3M-geglätteten Jahresraten von Industrieproduktion und CPI), einmal mit den damaligen, einmal mit den heutigen Daten.

| Vintage | Zeitraum | Monate | Wachstum gleich | Inflation gleich | Quadrant gleich |
|---|---|---|---|---|---|
| 2019-09 | gesamt | 711 | 99% | 100% | 99% |
| 2019-09 | letzte 24 M | 24 | 88% | 96% | 83% |
| 2021-04 | gesamt | 730 | 99% | 100% | 98% |
| 2021-04 | letzte 24 M | 24 | 96% | 92% | 88% |

Was ein Live-System am Rand der Vintage gesehen hätte:

| Vintage | letzter Monat | Regime damals | Regime heute | Sahm damals | Sahm heute |
|---|---|---|---|---|---|
| 2019-09 | 2019-08 | Wachstum fallend, Inflation fallend | Wachstum fallend, Inflation fallend | 0.07 | 0.00 |
| 2021-04 | 2021-03 | Wachstum steigend, Inflation steigend | Wachstum steigend, Inflation steigend | 0.00 | 0.00 |

## 3. Folgerung

Die Studien rechnen mit heutigen, revidierten Daten und einem Monat Verzögerung (Lag-Modell). Über die ganze Historie stimmen die Regime meist überein; am Rand – dort, wo eine Live-Entscheidung fällt – weichen sie häufiger ab. Deshalb trennt der Store `static:fredmd:*` (Forschungsparität) und `static:fredmd_rt:*` (Echtzeit) und holt live echte ALFRED-Vintages. Mit dem vollständigen Archiv (monatlich seit 1999) lässt sich jede Studie einmal mit Echtzeitdaten wiederholen; die Differenz der Kennzahlen ist der Preis der Revisionen.
