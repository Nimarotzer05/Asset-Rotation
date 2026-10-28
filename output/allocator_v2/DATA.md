# Datenprüfung Runde 4 (ADR 058 g)

| Prüfung | bestanden | Befund |
|---|---|---|
| G1 Pflichtquellen | ja | fehlend: keine; optional nicht verfügbar: ['fred/DEXGEUS'] |
| G2 Industrien täglich = Monatsdatei | ja | NoDur 0.99995/0.017 Pp (1201 M); Durbl 1.00000/0.014 Pp (1201 M); Manuf 0.99999/0.014 Pp (1201 M); Enrgy 0.99998/0.018 Pp (1201 M); HiTec 1.00000/0.013 Pp (1201 M); Telcm 0.99977/0.019 Pp (1201 M); Shops 0.99999/0.014 Pp (1201 M); Hlth 0.99994/0.017 Pp (1201 M); Utils 0.99986/0.017 Pp (1201 M); Other 0.99998/0.017 Pp (1201 M) |
| G3 Par-Bonds täglich ~ Monatsende | ja | UST10_D~UST10_ME 0.9999 (775 M); UST2_D~UST2_ME 0.9995 (602 M) |
| G4 Notierung und Euro-Verkettung | ja | Korrelation mit dem Dollar-Index: JPY -0.66, GBP -0.72, CHF -0.80, CAD -0.55, AUD -0.54, NZD -0.57, SEK -0.80, NOK -0.82, EUR -0.90; keine DEM-Reihe, EUR ab 1999-01-04 (ADR 059) |
| G5 Länderrenditen in USD | ja | Median +0.52 über 9 Heimatländer: JAPAN +0.46, UK +0.50, SWITZERLAND +0.51, CANADA +0.69, AUSTRALIA +0.72, NEWZEALAND +0.69, SWEDEN +0.47, NORWAY +0.53, GERMANY +0.52 |
| G6 Breite (Notfallregeln h) | ja | Währungen mit Index: max 9, ≥ 6 ab 1991-01-02; Länder in der Datei: 21, max gleichzeitig 21, ≥ 6 ab 1974-12-31 |

## Abdeckung

| Reihe | erster Wert | letzter Wert | Werte |
|---|---|---|---|
| FX_JPY | 1991-01-02 | 2026-10-23 | 8987 |
| FX_GBP | 1991-01-02 | 2026-04-30 | 8866 |
| FX_CHF | 1991-01-02 | 2026-10-23 | 8987 |
| FX_CAD | 1991-01-02 | 2026-10-23 | 8987 |
| FX_AUD | 1991-01-02 | 2026-10-23 | 8987 |
| FX_NZD | 1991-01-02 | 2026-10-23 | 8987 |
| FX_SEK | 1991-01-02 | 2026-10-23 | 8987 |
| FX_NOK | 1991-01-02 | 2026-10-23 | 8987 |
| FX_EUR | 1999-01-04 | 2026-04-30 | 6853 |
| UST2_D | 1976-06-01 | 2026-10-26 | 12597 |
| UST5_D | 1962-01-02 | 2026-10-26 | 16189 |
| UST10_D | 1962-01-02 | 2026-10-26 | 16189 |
| IND_NODUR | 1926-07-01 | 2026-09-30 | 26338 |
| IND_DURBL | 1926-07-01 | 2026-09-30 | 26338 |
| IND_MANUF | 1926-07-01 | 2026-09-30 | 26338 |
| IND_ENRGY | 1926-07-01 | 2026-09-30 | 26338 |
| IND_HITEC | 1926-07-01 | 2026-09-30 | 26338 |
| IND_TELCM | 1926-07-01 | 2026-09-30 | 26338 |
| IND_SHOPS | 1926-07-01 | 2026-09-30 | 26338 |
| IND_HLTH | 1926-07-01 | 2026-09-30 | 26338 |
| IND_UTILS | 1926-07-01 | 2026-09-30 | 26338 |
| IND_OTHER | 1926-07-01 | 2026-09-30 | 26338 |
| CTRY_UK | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_AUSTRIA | 1986-12-31 | 2025-12-31 | 469 |
| CTRY_AUSTRALIA | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_BELGIUM | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_CANADA | 1976-12-31 | 2025-12-31 | 589 |
| CTRY_DENMARK | 1988-12-31 | 2025-12-31 | 445 |
| CTRY_FINLAND | 1987-12-31 | 2025-12-31 | 457 |
| CTRY_FRANCE | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_GERMANY | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_HONGKONG | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_IRELAND | 1990-12-31 | 2025-12-31 | 421 |
| CTRY_ITALY | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_JAPAN | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_MALAYSIA | 1993-12-31 | 2001-10-31 | 95 |
| CTRY_NETHERLANDS | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_NEWZEALAND | 1987-12-31 | 2025-12-31 | 457 |
| CTRY_NORWAY | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_SINGAPORE | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_SPAIN | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_SWEDEN | 1974-12-31 | 2025-12-31 | 613 |
| CTRY_SWITZERLAND | 1974-12-31 | 2025-12-31 | 613 |

## Zinsen je Währung: Verkettung und Spanne des Einlagenindex

- JPY: JP: 3M ab 2002-04-30, Tagesgeld ab 1985-07-31, Sprung beim Wechsel +0.10 Pp; Index 1991-01-02 … 2026-10-23
- GBP: GB: 3M ab 1957-01-31, Tagesgeld ab 1978-01-31; Index 1991-01-02 … 2026-04-30
- CHF: CH: 3M ab 1999-07-31, Tagesgeld ab 1972-01-31, Sprung beim Wechsel +0.18 Pp; Index 1991-01-02 … 2026-10-23
- CAD: CA: 3M ab 1956-01-31, Tagesgeld ab 1975-01-31; Index 1991-01-02 … 2026-10-23
- AUD: AU: 3M ab 1968-01-31, Tagesgeld ab 1990-08-31; Index 1991-01-02 … 2026-10-23
- NZD: NZ: 3M ab 1973-12-31, Tagesgeld ab 1985-01-31; Index 1991-01-02 … 2026-10-23
- SEK: SE: 3M ab 1982-01-31, Tagesgeld ab 1955-01-31, Sprung beim Wechsel +0.71 Pp; Index 1991-01-02 … 2026-10-23
- NOK: NO: 3M ab 1979-01-31, Tagesgeld ab 1982-01-31; Index 1991-01-02 … 2026-10-23
- EUR: DE: 3M ab 1960-01-31, Tagesgeld ab 1960-01-31, Sprung beim Wechsel +0.52 Pp; EZ: 3M ab 1994-01-31, Tagesgeld ab 1994-01-31, Sprung beim Wechsel +0.07 Pp; Index 1999-01-04 … 2026-04-30

## Länder: interne Lücken (beenden den Index, ADR 058 c)

keine

## Tagesbewegungen über 10 σ (EWMA, Schwerpunkt 60) – zur Sichtprüfung, bleiben drin

FX_GBP 2016-06-24 -7.8%; FX_CHF 2015-01-15 +13.9%; UST2_D 1979-10-09 -1.2%; UST5_D 1965-12-06 -0.7%; UST5_D 1979-10-09 -2.0%; IND_NODUR 1950-06-26 -3.8%; IND_NODUR 1955-09-26 -5.1%; IND_NODUR 1987-10-19 -17.0%; IND_DURBL 1987-10-19 -18.0%; IND_MANUF 1955-09-26 -7.9%; IND_MANUF 1987-10-19 -20.1%; IND_ENRGY 1939-09-05 +17.3%; IND_ENRGY 1955-09-26 -6.9%; IND_ENRGY 1987-10-19 -19.9%; IND_ENRGY 2020-03-09 -19.7%; IND_HITEC 1955-09-26 -6.6%; IND_HITEC 1987-10-19 -20.0%; IND_TELCM 1927-03-16 +4.1%; IND_TELCM 1928-05-17 +5.4%; IND_TELCM 1940-05-13 -3.9%; IND_TELCM 1940-05-14 -6.4%; IND_TELCM 1950-06-26 -3.8%; IND_SHOPS 1987-10-19 -16.6%; IND_HLTH 1955-09-26 -6.4%; IND_HLTH 1987-10-19 -17.9%; IND_UTILS 1950-06-26 -4.0%; IND_UTILS 1955-09-26 -4.2%; IND_UTILS 1962-05-28 -8.2%; IND_UTILS 1987-10-19 -12.9%; IND_OTHER 1955-09-26 -6.8%; IND_OTHER 1987-10-19 -15.2%; IND_OTHER 1989-10-13 -5.4%
