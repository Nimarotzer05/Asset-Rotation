# Long-Short mit monatlichem Neuaufbau und 20-%-Stop (ADR 065)

Stand 2026-10-29. Skript `scripts/long_short_stop.py`, Buchhaltung `rotationlab/forecast/long_short.py::run_long_short_stop`. Regel: an jedem Monatsende beide Beine schliessen und neu eröffnen (volle Kosten auf Verkauf und Kauf, auch bei gleicher Klasse) – Rang 1 der Prognose von Runde 1 long 1.5 × Eigenkapital, letzter Rang short 1.5 ×. Stop: Schlusskurs 20 % gegen ein Bein (long −20 %, short +20 % ab Einstieg) → **beide** Beine zu diesem Schlusskurs raus, Rest des Monats Cash. Geprüft auf Tagesschlusskursen (Gold/Silber: LBMA-Fixing); ein Sprung über den Stop wird zum schlechteren Kurs ausgeführt, Intraday-Kurse sind nicht modelliert.
Reibung wie ADR 063 (a): 7.5 bp je gehandelter Einheit, Finanzierung T-Bill + 30 bp auf den fremdfinanzierten Teil, Leihgebühr p.a. Aktien/Treasury 0.30 %, Gold 0.50 %, Silber 1.50 %, Short-Erlöse zum T-Bill-Satz; Finanzierung und Leihe anteilig zur Haltedauer. 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Laufzeit 8 s.

**Einordnung, offen gesagt:** Die Stop-Regel wurde nach dem Blick auf die Drawdowns von ADR 064 formuliert (März 1980: −60 % in einem Monat) – sie ist eine Reaktion auf gesehene Zahlen und deshalb schwache Evidenz, auch wenn ihre Parameter (20 %, beide Beine raus) vor diesem Lauf fixiert wurden. 2019–2025 ist gesehen.

## 1974–2018 (in-sample)

| 1974–2018 (in-sample) | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | t (NW, Überrendite) | Max DD | schlechtester Monat | Monate mit Stop | Reibung p.a. |
|---|---|---|---|---|---|---|---|---|---|
| LS 1.5× monatlich neu, Stop 20 % (Regel) | 540 | -2.1% | 49.2% | +0.109 [-0.195, +0.323] | +0.67 | -99.2% | -68.0% | 19 | 6.8% |
| LS 1.5× monatlich neu, ohne Stop | 540 | -1.7% | 49.1% | +0.173 [-0.104, +0.368] | +1.12 | -99.1% | -94.6% | 0 | 6.8% |
| LS 1.5× monatlich neu, Stop 20 %, ohne Wochenend-Fixing (ADR 066) | 540 | 0.5% | 48.1% | +0.145 [-0.146, +0.353] | +0.89 | -97.7% | -40.9% | 18 | 6.8% |
| Referenz ADR 064: Halten je Bein | 540 | 9.3% | 43.0% | +0.313 [+0.051, +0.518] | +2.06 | -82.5% | -60.4% | – | – |
| Referenz ADR 064: monatlich neu gewichtet | 540 | 2.4% | 49.1% | +0.254 [-0.021, +0.451] | +1.65 | -96.8% | -94.3% | – | – |
| Equal Weight (4 Klassen) | 540 | 8.1% | 13.4% | +0.301 [+0.028, +0.546] | +1.83 | -38.3% | -23.1% | – | – |

## 2019–2025 (gesehen)

| 2019–2025 (gesehen) | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | t (NW, Überrendite) | Max DD | schlechtester Monat | Monate mit Stop | Reibung p.a. |
|---|---|---|---|---|---|---|---|---|---|
| LS 1.5× monatlich neu, Stop 20 % (Regel) | 84 | -15.2% | 38.0% | -0.324 [-1.469, -0.053] | -0.65 | -86.9% | -22.8% | 0 | 6.5% |
| LS 1.5× monatlich neu, ohne Stop | 84 | -15.2% | 38.0% | -0.324 [-1.469, -0.053] | -0.65 | -86.9% | -22.8% | 0 | 6.5% |
| LS 1.5× monatlich neu, Stop 20 %, ohne Wochenend-Fixing (ADR 066) | 84 | -15.2% | 38.0% | -0.324 [-1.469, -0.053] | -0.65 | -86.9% | -22.8% | 0 | 6.5% |
| Referenz ADR 064: Halten je Bein | 84 | -12.1% | 37.4% | -0.237 [-1.338, +0.118] | -0.47 | -84.0% | -26.4% | – | – |
| Referenz ADR 064: monatlich neu gewichtet | 84 | -12.0% | 38.1% | -0.228 [-1.350, +0.061] | -0.46 | -84.0% | -22.6% | – | – |
| Equal Weight (4 Klassen) | 84 | 16.3% | 13.2% | +1.022 [+0.220, +1.325] | +2.60 | -17.6% | -6.8% | – | – |

## 1974–2025 (gesamt)

| 1974–2025 (gesamt) | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | t (NW, Überrendite) | Max DD | schlechtester Monat | Monate mit Stop | Reibung p.a. |
|---|---|---|---|---|---|---|---|---|---|
| LS 1.5× monatlich neu, Stop 20 % (Regel) | 624 | -4.0% | 47.9% | +0.063 [-0.262, +0.235] | +0.40 | -99.9% | -68.0% | 19 | 6.8% |
| LS 1.5× monatlich neu, ohne Stop | 624 | -3.7% | 47.7% | +0.119 [-0.194, +0.278] | +0.80 | -99.8% | -94.6% | 0 | 6.8% |
| LS 1.5× monatlich neu, Stop 20 %, ohne Wochenend-Fixing (ADR 066) | 624 | -1.8% | 46.9% | +0.094 [-0.231, +0.267] | +0.60 | -99.6% | -40.9% | 18 | 6.8% |
| Referenz ADR 064: Halten je Bein | 624 | 6.2% | 42.3% | +0.247 [-0.053, +0.412] | +1.64 | -93.7% | -60.4% | – | – |
| Referenz ADR 064: monatlich neu gewichtet | 624 | 0.3% | 47.8% | +0.201 [-0.103, +0.362] | +1.34 | -99.0% | -94.3% | – | – |
| Equal Weight (4 Klassen) | 624 | 9.1% | 13.3% | +0.395 [+0.111, +0.577] | +2.57 | -38.3% | -23.1% | – | – |

## Stops (Regel, 1974–2025)

| ausgelöst durch | Stops | Ø Rendite Long-Bein bis Ausstieg | Ø Rendite Short-Bein bis Ausstieg | Ø gehaltener Monatsanteil |
|---|---|---|---|---|
| long | 9 | -0.248 | -0.011 | +0.518 |
| short | 10 | +0.036 | +0.230 | +0.584 |

Ausgelöst durch Klasse: SILVER 16, GOLD 2, US_EQ 1.

Schlechteste Monate der Regel:

| Monat | long | short | stopped | stop_leg | r_long | r_short | ret |
|---|---|---|---|---|---|---|---|
| 1983-02-28 00:00:00 | SILVER | GOLD | True | long | -0.454 | -0.002 | -0.680 |
| 1987-10-31 00:00:00 | US_EQ | UST10_ME | True | long | -0.300 | -0.027 | -0.409 |
| 2013-08-31 00:00:00 | US_EQ | SILVER | True | short | -0.032 | +0.218 | -0.381 |
| 1999-09-30 00:00:00 | US_EQ | GOLD | True | short | -0.037 | +0.205 | -0.364 |
| 1981-09-30 00:00:00 | US_EQ | SILVER | True | short | -0.015 | +0.228 | -0.361 |

## Vorab-Kriterium (ADR 065)

- 1974–2018: Sharpe ex Cash +0.109 [-0.195, +0.323] → Intervall über null: **nein**
- 2019–2025: Sharpe ex Cash -0.324 → über null: **nein**
- Stop gegen ohne Stop (gepaart, 1974–2018): Δ Sharpe -0.063 [-0.188, +0.032]
- Datenkorrektur (ADR 066, nach dem ersten Lauf gefunden; entfernt: 1983-02-05): Regel 1974–2018 Sharpe +0.145 [-0.146, +0.353], 2019–2025 -0.324; gegen ohne Stop Δ -0.027 [-0.112, +0.044]
- Ruin: Regel nein; ohne Stop nein
- Deflationierte Sharpe der Regel (Appraisal-Residuum gegen Equal Weight, 1974–2018, N = 82): 0.002

Lesart: **nicht belegt** (Intervall 1974–2018 schliesst null ein).
