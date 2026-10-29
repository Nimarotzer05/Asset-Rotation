# Long-Short in Dollar: $1000 je Bein mit 1.5× Hebel, Stop bei $200 (ADR 067)

Stand 2026-10-29. Skript `scripts/long_short_dollar.py`, Buchhaltung `rotationlab/forecast/long_short.py::run_dollar_long_short`. Jeden Monat $1500 long auf Rang 1 und $1500 short auf den letzten Rang der Prognose von Runde 1 ($1000 Kapital je Bein, Hebel 1.5), Einstieg zum Schlusskurs am Monatsende. Hat ein Bein an einem Tagesschluss $200 verloren (13.3 % Kursbewegung), werden beide Beine zu diesem Kurs geschlossen bis Monatsende. Danach wieder $1000 je Bein – kein Zinseszins. **Ohne Gebühren, Leihe, Finanzierung und Zinsen** (Vorgabe). Tagesdaten Montag–Freitag (ADR 066). Sharpe = monatlicher P&L auf $2000, 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Laufzeit 7 s.

**Einordnung:** vierte Fassung der Long-Short-Idee auf derselben Geschichte (ADR 063–066), formuliert nach dem Blick auf deren Ergebnisse; 2019–2025 ist gesehen. Ohne Kosten sind die Zahlen eine Obergrenze.

## 1974–2018 (in-sample)

| 1974–2018 (in-sample) | Monate | P&L gesamt $ | P&L je Jahr $ | % p.a. auf $2000 | Vol p.a. | Sharpe | t (NW) | Gewinnmonate | bester Monat $ | schlechtester Monat $ | grösster Rückgang $ | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LS $1500/$1500, Stop $200 (Regel) | 540 | 5297 | 118 | +5.9% | 23.8% | +0.247 [-0.021, +0.470] | +1.52 | 55% | 1025 | -409 | -2141 | 51 |
| LS $1500/$1500, ohne Stop | 540 | 6880 | 153 | +7.6% | 24.5% | +0.312 [+0.046, +0.509] | +2.03 | 56% | 1025 | -952 | -1778 | 0 |
| Equal Weight $2000 (Überrendite) | 540 | 3654 | 81 | +4.1% | 13.4% | +0.303 [+0.030, +0.548] | +1.85 | 52% | 460 | -484 | -1449 | – |

## 2019–2025 (gesehen)

| 2019–2025 (gesehen) | Monate | P&L gesamt $ | P&L je Jahr $ | % p.a. auf $2000 | Vol p.a. | Sharpe | t (NW) | Gewinnmonate | bester Monat $ | schlechtester Monat $ | grösster Rückgang $ | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LS $1500/$1500, Stop $200 (Regel) | 84 | -484 | -69 | -3.5% | 19.2% | -0.180 [-1.272, +0.090] | -0.37 | 49% | 517 | -214 | -1619 | 5 |
| LS $1500/$1500, ohne Stop | 84 | -403 | -58 | -2.9% | 19.0% | -0.152 [-1.250, +0.140] | -0.31 | 49% | 517 | -221 | -1542 | 0 |
| Equal Weight $2000 (Überrendite) | 84 | 1878 | 268 | +13.4% | 13.1% | +1.024 [+0.222, +1.327] | +2.60 | 58% | 265 | -139 | -385 | – |

## 1974–2025 (gesamt)

| 1974–2025 (gesamt) | Monate | P&L gesamt $ | P&L je Jahr $ | % p.a. auf $2000 | Vol p.a. | Sharpe | t (NW) | Gewinnmonate | bester Monat $ | schlechtester Monat $ | grösster Rückgang $ | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LS $1500/$1500, Stop $200 (Regel) | 624 | 4814 | 93 | +4.6% | 23.3% | +0.199 [-0.102, +0.386] | +1.27 | 54% | 1025 | -409 | -2141 | 56 |
| LS $1500/$1500, ohne Stop | 624 | 6477 | 125 | +6.2% | 23.8% | +0.261 [-0.033, +0.422] | +1.75 | 55% | 1025 | -952 | -1872 | 0 |
| Equal Weight $2000 (Überrendite) | 624 | 5532 | 106 | +5.3% | 13.4% | +0.398 [+0.114, +0.579] | +2.58 | 53% | 460 | -484 | -1449 | – |

## P&L je Jahrzehnt ($)

| Jahrzehnt | P&L Regel $ | P&L ohne Stop $ | Stops |
|---|---|---|---|
| 1970er | +3,742 | +4,441 | 7 |
| 1980er | +355 | +491 | 19 |
| 1990er | +387 | +790 | 8 |
| 2000er | -196 | +137 | 8 |
| 2010er | +594 | +606 | 9 |
| 2020er | -69 | +12 | 5 |

Stops 1974–2025: 56 (Long-Bein 23, Short-Bein 33); Ø Verlust des auslösenden Beins $-231, Ø P&L des Monats $-201.

Schlechteste Monate der Regel ($):

| Monat | long | short | stopped | pnl_long | pnl_short | pnl |
|---|---|---|---|---|---|---|
| 1987-10-31 00:00:00 | US_EQ | UST10_ME | True | -450 | +41 | -409 |
| 1990-08-31 00:00:00 | US_EQ | GOLD | True | -203 | -162 | -365 |
| 1981-09-30 00:00:00 | US_EQ | SILVER | True | -30 | -290 | -320 |
| 2009-01-31 00:00:00 | UST10_ME | SILVER | True | -77 | -239 | -316 |
| 1984-02-29 00:00:00 | US_EQ | SILVER | True | -79 | -235 | -314 |

## Vorab-Kriterium (ADR 067)

- 1974–2018: Sharpe +0.247 [-0.021, +0.470] → Intervall über null: **nein**
- 2019–2025: Sharpe -0.180 → über null: **nein**

Lesart: **nicht belegt** (Intervall 1974–2018 schliesst null ein). Jahr für Jahr: `output/long_short_dollar/by_year.csv`.
