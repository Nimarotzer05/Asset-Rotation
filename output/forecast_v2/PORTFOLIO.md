# Prognose-Portfolio (P8): die vorab fixierte Regel gegen Baselines, 1981–2018 (Forschungsrunde 2, `forecast_portfolio_v2`)

Stand 2026-10-27. Regel und Baselines durch dieselbe Engine (`rotationlab.engine`), Ausführung `next_tradable`, Kosten 7.5 bp je Seite inkl. Cash-Bein, Daten ab 1976-06-30; wirksame Entscheidungen 1981-07 bis 2018-11 (der Entscheid vom 2018-12-31 wird am nächsten Handelstag gehandelt und nie bewertet); Kennzahlen über die 449 Renditemonate 1981-08 bis 2018-12 (für alle Läufe identisch). Pseudo-Holdout ab 2019-01-31 unberührt.
Timing: `next_tradable` handelt tägliche Reihen (US_EQ, SILVER) am Handelstag nach der Entscheidung; UST10_ME, UST2_ME, GOLD, TBILL sind im Langfrist-Panel Monatsreihen, ihr nächster Preis ist der Monatsendwert selbst – diese Beine werden also zum Entscheidungspreis gehandelt, für Regel und Baselines gleich (kein Blick in die Zukunft, aber auch kein Folgetagspreis).
Intervalle: 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025), gepaart über dieselben Blockziehungen. Regel, Konventionen und Kriterium vorab in ADR 048, Runde 2 in ADR 052. Alle Zahlen aus `scripts/forecast_portfolio.py --config forecast_v2`.

**Einordnung:** Rangfolge (drei Familien, gleiche Gewichte) und Regel (Top-2 von 5, Trendfilter, Vol-Ziel, kein Hebel) sind in ADR 052 vor diesem Lauf fixiert und nicht auf den Daten gewählt; die Rangfolge der Regel ist dieselbe, die die Prognose `forecast_v2` veröffentlicht (gleiche Reihen, gleiche Formel). Der erste Entscheid der Stichprobe (1981-07) ist mit 3 von 3 Features bewertet; ohne ihn: Sharpe Regel 0.610, Equal Weight 0.332.

## Kennzahlen

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Trefferquote | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|---|
| Regel (Top-2, Trend, Vol-Ziel 10 %) | 449 | 0.0763 | 0.0603 | 0.6047 | -0.0909 | 0.8392 | 0.7038 | 2.1772 | 0.0033 |
| Equal Weight (5 Klassen) | 449 | 0.0680 | 0.0920 | 0.3303 | -0.2200 | 0.3090 | 0.5813 | 0.1695 | 0.0003 |
| 60/40 US_EQ/UST10_ME | 449 | 0.1019 | 0.0954 | 0.6560 | -0.2894 | 0.3522 | 0.6615 | 0.1030 | 0.0002 |
| Buy-and-Hold US_EQ | 449 | 0.1092 | 0.1476 | 0.5111 | -0.5078 | 0.2150 | 0.6370 | 0.0000 | 0.0000 |
| Regel, Hebel bis 1.5 | 449 | 0.0874 | 0.0749 | 0.6363 | -0.1070 | 0.8164 | 0.6771 | 3.2212 | 0.0048 |

## Gepaarte Differenzen Regel − Baseline

| Baseline | Δ Rendite p.a. | low | high | Δ Sharpe | low  | high  |
|---|---|---|---|---|---|---|
| Equal Weight (5 Klassen) | 0.0054 | -0.0234 | 0.0269 | 0.2745 | -0.0844 | 0.5558 |
| 60/40 US_EQ/UST10_ME | -0.0264 | -0.0540 | -0.0047 | -0.0512 | -0.4145 | 0.1977 |
| Buy-and-Hold US_EQ | -0.0395 | -0.0866 | -0.0039 | 0.0936 | -0.3323 | 0.3898 |

Δ Rendite p.a. = Mittel der Monatsdifferenz × 12; Δ Sharpe = Sharpe ex Cash der Regel minus Baseline, Intervall aus denselben Blockziehungen für beide Reihen (Perzentil-Intervall, nicht bias-korrigiert; der Bootstrap-Mittelwert liegt bei der Sharpe-Differenz leicht über dem Punktwert, die Basic-Variante läge entsprechend tiefer – das Urteil hängt davon nicht ab).

## Was die Regel tut

- Entscheidungen 1981-07 bis 2018-11: mittlere Risikoquote: 0.814
- Anteil Entscheidungen ganz in Cash: 0.031
- Anteil Entscheidungen mit Vol-Skalierung < 1 (von denen mit Risikoteil): 0.145
- mittlere Skalierung (dito): 0.961
- Median Sleeve-Vol (dito): 0.047

## Je Jahrzehnt

| decade | Regel: Rendite p.a. | Regel: Sharpe | EW: Rendite p.a. | EW: Sharpe | 60/40: Rendite p.a. | 60/40: Sharpe | Monate |
|---|---|---|---|---|---|---|---|
| 1981–1989 | 0.132 | 0.670 | 0.087 | 0.066 | 0.171 | 0.703 | 101 |
| 1990s | 0.072 | 0.396 | 0.063 | 0.209 | 0.140 | 0.940 | 120 |
| 2000s | 0.071 | 0.685 | 0.082 | 0.589 | 0.024 | 0.014 | 120 |
| 2010–2018 | 0.037 | 0.687 | 0.042 | 0.422 | 0.087 | 1.239 | 108 |

## Sensitivitäten (vorab benannt, nicht urteilsrelevant)

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Trefferquote | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|---|
| Regel, Hebel bis 1.5 | 449 | 0.0874 | 0.0749 | 0.6363 | -0.1070 | 0.8164 | 0.6771 | 3.2212 | 0.0048 |

## Urteil nach ADR 048 (e) – Kriterium vorab festgelegt

1. Sharpe ex Cash der Regel (+0.605) über Equal Weight (+0.330): **ja**
2. Gepaarte Sharpe-Differenz zu Equal Weight positiv und Intervall ohne Null: **nein** (+0.274 [-0.084, +0.556]; Intervall mit Null)
→ Portfolio-Vorteil gegen Equal Weight belegt: **NEIN**

60/40 und Buy-and-Hold stehen zur Einordnung (anderes Universum, anderes Risiko) und entscheiden nicht.

Deflated Sharpe (Bailey/López de Prado 2014; ADR 056) der Residualrendite gegen Equal Weight (Überschuss abzüglich Beta × EW-Überschuss: was die Regel über die Baseline hinaus bringt, ohne ein anderes Risikoniveau als Können zu zählen): +0.518 p.a.; Hürde aus N = 58 Versuchen und der Varianz derselben Statistik über das Register `docs/TRIALS.yaml` +0.360; Wahrscheinlichkeit, dass die wahre Grösse darüber liegt: **0.841** (≥ 0.95 wäre ein Beleg, der die Mehrfachprüfung überlebt). Beschreibend, nicht Teil des vorab fixierten Kriteriums.

Laufzeit 37 s.
