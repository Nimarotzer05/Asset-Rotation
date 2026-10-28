# Prognose-Portfolio (P8): die vorab fixierte Regel gegen Baselines, 1974–2018

Stand 2026-10-27. Regel und Baselines durch dieselbe Engine (`rotationlab.engine`), Ausführung `next_tradable`, Kosten 7.5 bp je Seite inkl. Cash-Bein, Daten ab 1972-12-31; wirksame Entscheidungen 1973-12 bis 2018-11 (der Entscheid vom 2018-12-31 wird am nächsten Handelstag gehandelt und nie bewertet); Kennzahlen über die 540 Renditemonate 1974-01 bis 2018-12 (für alle Läufe identisch). Pseudo-Holdout ab 2019-01-31 unberührt.
Timing: `next_tradable` handelt tägliche Reihen (US_EQ, SILVER) am Handelstag nach der Entscheidung; UST10_ME, GOLD, TBILL sind im Langfrist-Panel Monatsreihen, ihr nächster Preis ist der Monatsendwert selbst – diese Beine werden also zum Entscheidungspreis gehandelt, für Regel und Baselines gleich (kein Blick in die Zukunft, aber auch kein Folgetagspreis).
Intervalle: 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025), gepaart über dieselben Blockziehungen. Regel, Konventionen und Kriterium vorab in ADR 048. Alle Zahlen aus `scripts/forecast_portfolio.py --config forecast`.

**Einordnung:** Die Rangfolge hinter der Regel ist in-sample bezüglich der Modellwahl (ADR 046 e); die Regel selbst (Top-2, Trendfilter, Vol-Ziel, kein Hebel) wurde vor diesem Lauf festgelegt und nicht auf den Daten gewählt. Bewertet wird die Rangfolge auf dem handelbaren Treasury-Index `UST10_ME` (ADR 048 c); die veröffentlichte Prognose rankt die Forschungsreihe `UST10` – die Top-2 unterscheiden sich in 21 von 540 Entscheidungsmonaten; die Sensitivität „Forschungsreihe UST10“ unten ist die Regel auf der veröffentlichten Rangfolge. Der erste Entscheid der Stichprobe (1973-12) ist mit 4 von 5 Features bewertet (12-1-Momentum braucht 14 Monatsstände); ohne den Januar 1974: Sharpe Regel 0.476, Equal Weight 0.293.

## Kennzahlen

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Trefferquote | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|---|
| Regel (Top-2, Trend, Vol-Ziel 10 %) | 540 | 0.0919 | 0.0958 | 0.4868 | -0.1586 | 0.5791 | 0.6204 | 2.3443 | 0.0035 |
| Equal Weight (4 Klassen) | 540 | 0.0814 | 0.1338 | 0.3053 | -0.3867 | 0.2105 | 0.5704 | 0.1984 | 0.0003 |
| 60/40 US_EQ/UST10_ME | 540 | 0.0960 | 0.0984 | 0.5124 | -0.2894 | 0.3317 | 0.6389 | 0.1031 | 0.0002 |
| Buy-and-Hold US_EQ | 540 | 0.1059 | 0.1508 | 0.4377 | -0.5078 | 0.2085 | 0.6204 | 0.0000 | 0.0000 |
| Regel, Hebel bis 1.5 | 540 | 0.0981 | 0.1057 | 0.5045 | -0.1671 | 0.5873 | 0.6185 | 3.1598 | 0.0047 |
| Regel mit Forschungsreihe UST10 | 540 | 0.0920 | 0.0945 | 0.4932 | -0.1733 | 0.5311 | 0.6204 | 2.2278 | 0.0033 |

## Gepaarte Differenzen Regel − Baseline

| Baseline | Δ Rendite p.a. | low | high | Δ Sharpe | low  | high  |
|---|---|---|---|---|---|---|
| Equal Weight (4 Klassen) | 0.0054 | -0.0169 | 0.0315 | 0.1815 | -0.0110 | 0.3946 |
| 60/40 US_EQ/UST10_ME | -0.0041 | -0.0352 | 0.0189 | -0.0256 | -0.3452 | 0.1926 |
| Buy-and-Hold US_EQ | -0.0198 | -0.0628 | 0.0114 | 0.0490 | -0.2894 | 0.2727 |

Δ Rendite p.a. = Mittel der Monatsdifferenz × 12; Δ Sharpe = Sharpe ex Cash der Regel minus Baseline, Intervall aus denselben Blockziehungen für beide Reihen (Perzentil-Intervall, nicht bias-korrigiert; der Bootstrap-Mittelwert liegt bei der Sharpe-Differenz leicht über dem Punktwert, die Basic-Variante läge entsprechend tiefer – das Urteil hängt davon nicht ab).

## Was die Regel tut

- Entscheidungen 1973-12 bis 2018-11: mittlere Risikoquote: 0.701
- Anteil Entscheidungen ganz in Cash: 0.026
- Anteil Entscheidungen mit Vol-Skalierung < 1 (von denen mit Risikoteil): 0.481
- mittlere Skalierung (dito): 0.817
- Median Sleeve-Vol (dito): 0.098

## Je Jahrzehnt

| decade | Regel: Rendite p.a. | Regel: Sharpe | EW: Rendite p.a. | EW: Sharpe | 60/40: Rendite p.a. | 60/40: Sharpe | Monate |
|---|---|---|---|---|---|---|---|
| 1973–1979 | 0.202 | 1.026 | 0.225 | 0.864 | 0.059 | -0.038 | 72 |
| 1980s | 0.123 | 0.365 | 0.041 | -0.213 | 0.159 | 0.563 | 120 |
| 1990s | 0.066 | 0.222 | 0.062 | 0.176 | 0.140 | 0.940 | 120 |
| 2000s | 0.068 | 0.425 | 0.090 | 0.560 | 0.024 | 0.014 | 120 |
| 2010–2018 | 0.045 | 0.524 | 0.050 | 0.421 | 0.087 | 1.239 | 108 |

## Sensitivitäten (vorab benannt, nicht urteilsrelevant)

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Trefferquote | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|---|
| Regel, Hebel bis 1.5 | 540 | 0.0981 | 0.1057 | 0.5045 | -0.1671 | 0.5873 | 0.6185 | 3.1598 | 0.0047 |
| Regel mit Forschungsreihe UST10 | 540 | 0.0920 | 0.0945 | 0.4932 | -0.1733 | 0.5311 | 0.6204 | 2.2278 | 0.0033 |

## Urteil nach ADR 048 (e) – Kriterium vorab festgelegt

1. Sharpe ex Cash der Regel (+0.487) über Equal Weight (+0.305): **ja**
2. Gepaarte Sharpe-Differenz zu Equal Weight positiv und Intervall ohne Null: **nein** (+0.181 [-0.011, +0.395]; Intervall mit Null)
→ Portfolio-Vorteil gegen Equal Weight belegt: **NEIN**

60/40 und Buy-and-Hold stehen zur Einordnung (anderes Universum, anderes Risiko) und entscheiden nicht.

Deflated Sharpe (Bailey/López de Prado 2014; ADR 056) der Residualrendite gegen Equal Weight (Überschuss abzüglich Beta × EW-Überschuss: was die Regel über die Baseline hinaus bringt, ohne ein anderes Risikoniveau als Können zu zählen): +0.381 p.a.; Hürde aus N = 58 Versuchen und der Varianz derselben Statistik über das Register `docs/TRIALS.yaml` +0.360; Wahrscheinlichkeit, dass die wahre Grösse darüber liegt: **0.558** (≥ 0.95 wäre ein Beleg, der die Mehrfachprüfung überlebt). Beschreibend, nicht Teil des vorab fixierten Kriteriums.

Laufzeit 51 s.
