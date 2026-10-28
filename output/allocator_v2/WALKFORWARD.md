# Sleeve-Allokator v2 (Forschungsrunde 4, ADR 057/058): Walk-forward 1977-01 bis 2025-11

Stand 2026-10-28. Allokator, Baselines und Varianten durch dieselbe Engine, Ausführung `next_tradable` (Tagesreihen am Folgetag, Länder zum Entscheidungskurs), Kosten je Instrument und Finanzierung des Hebels zum Cash-Index `TBILL_IY` +30 bp (ADR 057 d, 058; Annahmen). Fenster nach ADR 058 (e): Renditemonate 1977-01 bis 2025-11 (587 Monate); erste Entscheidung mit allen Long-Sleeves 1976-12; Datenende je Gruppe: EQ_US 2026-09, EQ_INTL 2025-12, FI 2026-09, PM 2026-01, FX 2026-09, US-Markt (B3/B4) 2025-11, Cash 2026-08. Währungs-Overlay in 394 von 587 Monaten (handelbar ab 1991, ADR 058 f). Intervalle: 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025), gepaart. Alle Zahlen aus `scripts/allocator_v2_walkforward.py`.

**Einordnung:** null freie Parameter, jede Grösse am Entscheidungstag nur aus Daten bis dahin; Design, Kriterien, Varianten und Notfallregeln vor dem Download der Daten fixiert (ADR 057, 058). Out-of-sample bezüglich der Daten, in-sample bezüglich der Literaturwahl und der Erfahrung aus drei Runden auf überlappender Historie – deshalb der Deflated Sharpe mit dem ganzen Versuchsregister.

## Kennzahlen

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|
| Allokator v2 (ADR 057/058) | 587 | 0.1083 | 0.0796 | 0.7911 | -0.1309 | 0.8280 | 3.1634 | 0.0040 |
| B1 passive Risikoparität | 587 | 0.0907 | 0.0939 | 0.5065 | -0.2091 | 0.4336 | 0.7053 | 0.0011 |
| B2 Equal Weight (15 Long-Instrumente) | 587 | 0.1096 | 0.1078 | 0.6140 | -0.3154 | 0.3473 | 0.1820 | 0.0003 |
| B3 60/40 US-Markt/10-J. | 587 | 0.0987 | 0.0985 | 0.5629 | -0.2885 | 0.3422 | 0.1090 | 0.0001 |
| B4 Buy-and-Hold US-Markt | 587 | 0.1171 | 0.1497 | 0.5243 | -0.5078 | 0.2305 | 0.0000 | 0.0000 |

B2–B4 ex post auf die Vol des Allokators skaliert (nur Darstellung):

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|
| B2 Equal Weight (15 Long-Instrumente) (Vol 7.9%) | 587 | 0.0931 | 0.0790 | 0.6140 | -0.2345 | 0.3969 | 0.1820 | 0.0003 |
| B3 60/40 US-Markt/10-J. (Vol 7.9%) | 587 | 0.0887 | 0.0792 | 0.5629 | -0.2338 | 0.3795 | 0.1090 | 0.0001 |
| B4 Buy-and-Hold US-Markt (Vol 7.9%) | 587 | 0.0854 | 0.0792 | 0.5243 | -0.2969 | 0.2876 | 0.0000 | 0.0000 |

Mittlere Gewichte über das Fenster: „vor Filter“ ist die konstruierte Mischung nach den Kappen (bei Allokator und B1 gleich gebaut; ein Rest kommt aus konzentrierteren Körben der Auswahl, ADR 058 d), „gehalten“ nach dem Trendfilter:

|  | physisch | Zinsen | Overlay brutto |
|---|---|---|---|
| Allokator v2 (ADR 057/058) vor Filter | 0.7312 | 0.7373 | 0.3356 |
| Allokator v2 (ADR 057/058) gehalten | 0.4890 | 0.4398 | 0.3356 |
| B1 passive Risikoparität vor Filter | 0.7550 | 0.7131 | 0.0000 |
| B1 passive Risikoparität gehalten | 0.7550 | 0.7131 | 0.0000 |

## Gepaarte Differenzen Allokator − Baseline

| Baseline | Δ Sharpe | low | high | Δ Rendite bei gleicher Vol p.a. | low  | high  |
|---|---|---|---|---|---|---|
| B1 passive Risikoparität | 0.2846 | 0.1404 | 0.4299 | 0.0225 | 0.0120 | 0.0329 |
| B2 Equal Weight (15 Long-Instrumente) | 0.1771 | -0.0157 | 0.3447 | 0.0140 | -0.0022 | 0.0285 |
| B3 60/40 US-Markt/10-J. | 0.2282 | -0.0129 | 0.4217 | 0.0180 | -0.0021 | 0.0353 |
| B4 Buy-and-Hold US-Markt | 0.2667 | 0.0067 | 0.4731 | 0.0211 | -0.0003 | 0.0401 |

## Sekundär: die Signale je Querschnitts-Sleeve

Dollar-neutrales Rang-Portfolio ∝ (N+1)/2 − Rang (Σ|w| = 1, vor Kosten), Score am Monatsende, Rendite des Folgemonats; einseitiger t-Test mit Newey-West-Standardfehler (12 Lags). Holm auf 10 % über die neuen Signale (EQ_INTL, FX); EQ_US wiederholt das Industrie-Signal von Runde 3 auf überlappenden Monaten und ist eine Replikation ohne eigene Beweiskraft (ADR 058).

| Sleeve | Rolle | Monate | Rang-L/S p.a. | t (Newey-West) | p einseitig | Rang-IC | IC low | IC high | p Holm | belegt |
|---|---|---|---|---|---|---|---|---|---|---|
| EQ_US | Replikation Runde 3 | 587 | 0.0195 | 2.2764 | 0.0114 | 0.0506 | 0.0244 | 0.0770 | nan | – |
| EQ_INTL | neu (Holm) | 587 | 0.0233 | 2.2595 | 0.0119 | 0.0408 | 0.0151 | 0.0617 | 0.0239 | ja |
| FX | neu (Holm) | 394 | 0.0106 | 1.7373 | 0.0412 | 0.0741 | 0.0370 | 0.1054 | 0.0412 | ja |

## Varianten (ADR 057 g: vorab benannt, berichtet, entscheiden nicht)

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|
| ohne Zeitreihenfilter | 587 | 0.0976 | 0.0986 | 0.5516 | -0.2327 | 0.4197 | 2.0955 | 0.0037 |
| ohne Querschnitt | 587 | 0.0993 | 0.0682 | 0.7920 | -0.1008 | 0.9854 | 1.9789 | 0.0021 |
| ohne FX-Sleeve | 587 | 0.1053 | 0.0761 | 0.7881 | -0.1183 | 0.8902 | 2.5664 | 0.0037 |
| Kosten und Finanzierung ×2 | 587 | 0.1034 | 0.0796 | 0.7348 | -0.1331 | 0.7770 | 3.1635 | 0.0081 |
| Ausführung zum Entscheidungskurs | 587 | 0.1093 | 0.0794 | 0.8033 | -0.1236 | 0.8839 | 3.1612 | 0.0040 |
| Vol überall monatlich | 587 | 0.1095 | 0.0827 | 0.7775 | -0.1531 | 0.7155 | 2.9848 | 0.0038 |
| nur Sleeve EQ_US | 587 | 0.1004 | 0.0976 | 0.5837 | -0.1812 | 0.5542 | 2.2592 | 0.0035 |
| nur Sleeve EQ_INTL | 587 | 0.0973 | 0.0989 | 0.5523 | -0.2478 | 0.3927 | 1.8397 | 0.0057 |
| nur Sleeve FI | 587 | 0.0625 | 0.0443 | 0.4174 | -0.0543 | 1.1506 | 1.8363 | 0.0006 |
| nur Sleeve FX | 587 | 0.0478 | 0.0174 | 0.2169 | -0.0440 | 1.0876 | 0.6118 | 0.0004 |
| nur Sleeve PM | 587 | 0.0814 | 0.0791 | 0.4810 | -0.2072 | 0.3931 | 1.0684 | 0.0013 |

## Berichtet, nicht entscheidend

- Teilperioden Δ Sharpe zu B1: Start–1989 +0.412 [+0.106, +0.724] (156 Monate); 1990–2007 +0.381 [+0.166, +0.603] (216 Monate); 2008–Ende +0.080 [-0.175, +0.277] (215 Monate); ohne das Kalenderjahr mit der grössten Summe der monatlichen Überschussrendite-Differenz (2013): +0.257 [+0.108, +0.399] (575 Monate).
- Vol-Kalibrierung (Standardabweichung der standardisierten Folgemonatsrendite, 1 = treffend): Start–1989 1.26; 1990–2007 1.01; 2008–Ende 0.95 (0 Monate mit fast leerem Buch – vorhergesagte Vol unter 0.5 % – ausgenommen); Anteil Entscheidungen mit gebundener Kappe – physisch 13%, Zinsen 91%, Overlay 67% (B1: Zinsen 91%).
- Verzögerungskosten der Ausführung (Sharpe am Entscheidungskurs minus Folgetag): +0.012.
- FX-Sleeve allein (ab seinem ersten Monat, 394 Monate): Sharpe +0.265 [-0.036, +0.550].
- Deflated Sharpe (Residualrendite gegen B1, N = 70 inkl. dieser Runde, Varianz aus dem Register und den 12 Läufen dieser Runde): +0.649 p.a., Hürde +0.460, Wahrscheinlichkeit **0.895** (≥ 0.95 überlebt die Mehrfachprüfung).

## Urteil nach ADR 057 (f) – Kriterien vorab festgelegt

1. Sharpe ex Cash des Allokators (+0.791) über B1 (+0.506): **ja**
2. Gepaarte Sharpe-Differenz zu B1 positiv und Intervall ohne Null: **ja** (+0.285 [+0.140, +0.430])
→ Vorteil des Allokators belegt: **JA** – Standardfehler 0.088, MDE (80 % Power) 0.22

## Nach der Zweitprüfung ergänzt (nicht vorregistriert, ändert kein Urteil)

Woher der Vorteil kommt und wie die Signale über die Zeit tragen (`docs/REVIEW_ALLOKATOR.md` Teil F):

- Δ Sharpe Allokator v2 (ADR 057/058) − ohne Querschnitt: -0.001 [-0.069, +0.060]
- Δ Sharpe ohne Querschnitt − B1 passive Risikoparität: +0.285 [+0.139, +0.442]
- Rang-Portfolio EQ_US je Teilperiode: Start–1989 +2.0% p.a. (t +1.60, 157 M); 1990–2007 +2.4% p.a. (t +1.73, 216 M); 2008–Ende +1.5% p.a. (t +0.89, 214 M)
- Rang-Portfolio EQ_INTL je Teilperiode: Start–1989 +5.1% p.a. (t +2.24, 157 M); 1990–2007 +2.7% p.a. (t +1.44, 216 M); 2008–Ende -0.1% p.a. (t -0.08, 214 M)
- Rang-Portfolio FX je Teilperiode: 1990–2007 +2.3% p.a. (t +2.43, 180 M); 2008–Ende +0.0% p.a. (t +0.04, 214 M)

Laufzeit 1890 s.
