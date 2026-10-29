# Long-Short-Regel auf der Monatsprognose (ADR 063 a)

Stand 2026-10-29. Skript `scripts/long_short_check.py`, Buchhaltung `rotationlab/forecast/long_short.py`. Regel: Rang 1 long mit 1.5 × Eigenkapital, letzter Rang short mit 1.5 × Eigenkapital, Entscheid am Monatsende, Halten für einen Monat; ein Bein, dessen Klasse sich nicht ändert, wird nicht gehandelt (es driftet). Handel zum Schlusskurs des Entscheidungstags (Monatsdaten).
Reibung (Annahmen für eine ETF-Umsetzung, vorab fixiert): 7.5 bp je gehandelter Einheit, Finanzierung T-Bill + 30 bp auf den fremdfinanzierten Teil des Long-Beins, Leihgebühr p.a. Aktien 0.30 %, Treasury 0.30 %, Gold 0.50 %, Silber 1.50 %; Short-Erlöse verzinst zum T-Bill-Satz.
90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Laufzeit 6 s.

**Vorwissen, offen gesagt:** Der unverschuldete Top-minus-Bottom-Spread von Runde 1 ist bekannt (`output/forecast/EVALUATION.md`: +11 % p.a. [+2.7 %, +19 %] 1973–2018; `HOLDOUT.md`: −3.8 % p.a. 2019–2025). Neu sind hier Hebel, Halteregel, Reibung, Monatsend-Treasury, Drawdown und Ruinrisiko.

## 1974–2018 (in-sample)

| 1974–2018 (in-sample) | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | t (NW, Überrendite) | Max DD | schlechtester Monat | Monate mit Handel | Umschlag p.a. | Reibung p.a. | max. Bein |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LS 1.5× Runde 1 (Regel) | 540 | 9.3% | 43.0% | +0.313 [+0.051, +0.518] | +2.06 | -82.5% | -60.4% | 39.6% | 1614.3% | 2.4% | 3.04 |
| LS 1.0× Runde 1 | 540 | 9.3% | 31.1% | +0.293 [+0.036, +0.491] | +1.95 | -67.6% | -57.1% | 39.6% | 1069.9% | 1.5% | 1.78 |
| LS 1.5× Runde 1, monatlich neu gewichtet | 540 | 2.4% | 49.1% | +0.254 [-0.021, +0.451] | +1.65 | -96.8% | -94.3% | 100.0% | 1973.2% | 2.9% | 1.50 |
| LS 1.5× Runde 1, ohne Reibung | 540 | 12.0% | 42.8% | +0.369 [+0.109, +0.574] | +2.44 | -77.3% | -60.2% | 39.6% | 1607.1% | 0.0% | 2.98 |
| LS 1.5× Runde 5 (Fed-Modell) | 491 | 0.2% | 45.4% | +0.137 [-0.115, +0.387] | +0.90 | -92.5% | -65.4% | 46.0% | 2031.0% | 2.6% | 3.94 |
| Equal Weight (4 Klassen) | 540 | 8.1% | 13.4% | +0.301 [+0.028, +0.546] | +1.83 | -38.3% | -23.1% | – | – | – | – |

## 2019–2025 (gesehen)

| 2019–2025 (gesehen) | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | t (NW, Überrendite) | Max DD | schlechtester Monat | Monate mit Handel | Umschlag p.a. | Reibung p.a. | max. Bein |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LS 1.5× Runde 1 (Regel) | 84 | -12.1% | 37.4% | -0.237 [-1.338, +0.118] | -0.47 | -84.0% | -26.4% | 53.6% | 2240.2% | 2.8% | 2.74 |
| LS 1.0× Runde 1 | 84 | -5.6% | 25.5% | -0.208 [-1.345, +0.121] | -0.40 | -68.2% | -17.2% | 53.6% | 1465.7% | 1.8% | 1.59 |
| LS 1.5× Runde 1, monatlich neu gewichtet | 84 | -12.0% | 38.1% | -0.228 [-1.350, +0.061] | -0.46 | -84.0% | -22.6% | 100.0% | 2372.4% | 2.9% | 1.50 |
| LS 1.5× Runde 1, ohne Reibung | 84 | -9.3% | 37.2% | -0.160 [-1.233, +0.188] | -0.32 | -81.5% | -25.8% | 53.6% | 2227.7% | 0.0% | 2.70 |
| LS 1.5× Runde 5 (Fed-Modell) | 84 | -9.3% | 40.0% | -0.093 [-0.513, +0.377] | -0.32 | -73.8% | -46.3% | 38.1% | 1848.7% | 2.5% | 4.52 |
| Equal Weight (4 Klassen) | 84 | 16.3% | 13.2% | +1.022 [+0.220, +1.325] | +2.60 | -17.6% | -6.8% | – | – | – | – |

## 1974–2025 (gesamt)

| 1974–2025 (gesamt) | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | t (NW, Überrendite) | Max DD | schlechtester Monat | Monate mit Handel | Umschlag p.a. | Reibung p.a. | max. Bein |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LS 1.5× Runde 1 (Regel) | 624 | 6.2% | 42.3% | +0.247 [-0.053, +0.412] | +1.64 | -93.7% | -60.4% | 41.5% | 1698.6% | 2.5% | 3.04 |
| LS 1.0× Runde 1 | 624 | 7.2% | 30.4% | +0.236 [-0.060, +0.396] | +1.59 | -78.3% | -57.1% | 41.5% | 1123.1% | 1.6% | 1.78 |
| LS 1.5× Runde 1, monatlich neu gewichtet | 624 | 0.3% | 47.8% | +0.201 [-0.103, +0.362] | +1.34 | -99.0% | -94.3% | 100.0% | 2026.9% | 2.9% | 1.50 |
| LS 1.5× Runde 1, ohne Reibung | 624 | 8.8% | 42.1% | +0.305 [+0.011, +0.470] | +2.05 | -88.6% | -60.2% | 41.5% | 1690.7% | 0.0% | 2.98 |
| LS 1.5× Runde 5 (Fed-Modell) | 575 | -1.3% | 44.6% | +0.107 [-0.140, +0.328] | +0.77 | -97.8% | -65.4% | 44.9% | 2004.3% | 2.6% | 4.52 |
| Equal Weight (4 Klassen) | 624 | 9.1% | 13.3% | +0.395 [+0.111, +0.577] | +2.57 | -38.3% | -23.1% | – | – | – | – |

## Vorab-Kriterium (ADR 063 a)

- 1974–2018: Sharpe ex Cash +0.313 [+0.051, +0.518] → Intervall über null: **ja**
- 2019–2025: Sharpe ex Cash -0.237 → über null: **nein**
- Ruin (Eigenkapital ≤ 0 in einem Monat): LS 1.5× Runde 1 (Regel): nein; LS 1.0× Runde 1: nein; LS 1.5× Runde 1, monatlich neu gewichtet: nein; LS 1.5× Runde 1, ohne Reibung: nein; LS 1.5× Runde 5 (Fed-Modell): nein
- Drift der Beine (Hauptregel, 1974–2018): Beingrösse bis 3.04, Netto-Exposure long − short zwischen -1.08 und +1.21, |netto| > 0.5 in 16% der Monate – die Regel ist kein sauberer 1.5/1.5-Spread; monatlich zurückgesetzt schliesst das Intervall null ein (Tabelle oben)
- Deflationierte Sharpe der Hauptregel (Appraisal-Residuum gegen Equal Weight, 1974–2018, N = 79): 0.075

Lesart: **nur in-sample profitabel** (2019–2025 nicht).
