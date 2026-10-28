# Sleeve-Allokator (Forschungsrunde 3, ADR 054): Walk-forward 1979-01 bis 2026-01

Stand 2026-10-27. Allokator, Baselines und Varianten durch dieselbe Engine (`rotationlab.engine`), Ausführung `next_tradable`, Kosten je Instrument (ADR 054 d, Annahmen: Industrien 5 bp, Treasuries 2 bp, Gold 5 bp, Silber 10 bp je Seite), Panel ab 1976-06-30; wirksame Entscheidungen 1978-12 bis 2025-12; Kennzahlen über die 565 Renditemonate 1979-01 bis 2026-01 (für alle Läufe identisch). Intervalle: 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025), gepaart. Design, Kriterien und Varianten vorab in ADR 054. Alle Zahlen aus `scripts/allocator_walkforward.py`.

**Korrigierte Fassung (Zweitprüfung, ADR 056).** Die erste Fassung entschied in zwei-Instrument-Sleeves Gleichstände (Momentum und Carry widersprechen sich, beide Scores exakt 0) nach Rundungsrauschen von ±1e-15 statt nach der Konfigurationsreihenfolge, die ADR 054 (b) vorschreibt; behoben (Scores auf 1e-12 gerundet), alle Läufe neu gerechnet. ADR 054 setzte den Hebel auf das ganze Buch (brutto ≤ 1.5, kein Sleeve über 1.0) – der Auftraggeber hatte Hebel für das Anleihe-Sleeve freigegeben; diese Abweichung des Designs wird hier nicht nachträglich korrigiert (das wäre ein neuer Versuch), sondern in Runde 4 umgesetzt. Abschnitte mit „Diagnose“ sind nach dem Lauf gerechnet und entscheiden nichts.

Timing: `next_tradable` handelt nur GOLD_D und SILVER am Folgetag; 13 Beine (FF_NODUR, FF_DURBL, FF_MANUF, FF_ENRGY, FF_HITEC, FF_TELCM, FF_SHOPS, FF_HLTH, FF_UTILS, FF_OTHER, UST2_ME, UST10_ME, TBILL) sind Monatsreihen und werden zum Kurs des Entscheidungstags gehandelt – derselbe Stand, der den Trendfilter speist (akademische Konvention, nicht umsetzbar; Runde 4 rechnet mit Tagesreihen).

**Einordnung:** Null freie Parameter; jede Grösse am Entscheidungstag nur aus Daten bis dahin. Out-of-sample bezüglich der Daten, in-sample bezüglich des Designs (Literaturwahl, in Kenntnis der Runden 1 und 2 und der Periode 2019–2025). Kein Holdout-Blick mehr (Versuchsregister `docs/TRIALS.yaml`); echter Out-of-sample bleibt die Live-Bilanz. B1 ist das passive Gegenstück des Allokators (gleiche Sleeves, Budgets, inverse Vol, Vol-Ziel, Hebelgrenze, aber alle Instrumente immer gehalten): die Differenz zu B1 ist das, was die Signale leisten.

## Kennzahlen

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Trefferquote | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|---|
| Allokator (ADR 054) | 565 | 0.1066 | 0.0948 | 0.6830 | -0.1472 | 0.7239 | 0.6673 | 3.5602 | 0.0022 |
| B1 Risikoparität ohne Signale | 565 | 0.0874 | 0.0654 | 0.6849 | -0.1297 | 0.6739 | 0.6407 | 0.2714 | 0.0002 |
| B2 Equal Weight (14 Instrumente) | 565 | 0.1167 | 0.1157 | 0.6547 | -0.3446 | 0.3388 | 0.6531 | 0.1837 | 0.0002 |
| B3 60/40 US_EQ/UST10_ME | 565 | 0.1029 | 0.0985 | 0.6239 | -0.2892 | 0.3557 | 0.6637 | 0.1057 | 0.0001 |
| B4 Buy-and-Hold US_EQ | 565 | 0.1222 | 0.1501 | 0.5686 | -0.5078 | 0.2406 | 0.6460 | 0.0000 | 0.0000 |

## Gepaarte Differenzen Allokator − Baseline

| Baseline | Δ Rendite p.a. | low | high | Δ Sharpe | low  | high  |
|---|---|---|---|---|---|---|
| B1 Risikoparität ohne Signale | 0.0199 | 0.0020 | 0.0357 | -0.0019 | -0.1883 | 0.1641 |
| B2 Equal Weight (14 Instrumente) | -0.0115 | -0.0352 | 0.0095 | 0.0283 | -0.1916 | 0.2148 |
| B3 60/40 US_EQ/UST10_ME | 0.0030 | -0.0232 | 0.0230 | 0.0591 | -0.1892 | 0.2235 |
| B4 Buy-and-Hold US_EQ | -0.0211 | -0.0568 | 0.0088 | 0.1144 | -0.1599 | 0.3194 |

Δ Rendite vergleicht Läufe mit verschiedenem Risiko (Vol Allokator 9.4%, B1 6.5%) und ist kein Beleg: bei gleicher Volatilität (B1 auf 9.4% skaliert) beträgt der Unterschied der Überschussrendite **-0.02% p.a.** Massgeblich ist die Sharpe-Differenz.

## Was das Buch tut

- Entscheidungen 1978-12 bis 2025-12: mittlere Bruttoquote: 0.974
- Anteil Entscheidungen mit Hebel (brutto > 1): 0.467
- Anteil Entscheidungen ganz in Cash: 0.000
- mittlere Skalierung (Vol-Ziel / Portfolio-Vol, gekappt): 1.365
- mittleres Gewicht Sleeve EQ: 0.365
- mittleres Gewicht Sleeve FI: 0.468
- mittleres Gewicht Sleeve PM: 0.143
- Anteil Monate Sleeve EQ in Cash: 0.051
- Anteil Monate Sleeve FI in Cash: 0.340
- Anteil Monate Sleeve PM in Cash: 0.439

## Querschnitt je Sleeve (Score am Monatsende gegen die Rendite des Folgemonats innerhalb des Sleeves)

| Sleeve | Instrumente | Kennzahl | Wert | low | high | Monate |
|---|---|---|---|---|---|---|
| EQ | 10 | Rang-IC (Spearman) | 0.0483 | 0.0238 | 0.0773 | 565 |
| FI | 2 | Trefferquote (höherer Score schlägt den anderen; Zufall 0.5) | 0.5130 | 0.4830 | 0.5491 | 499 |
| PM | 2 | Trefferquote (höherer Score schlägt den anderen; Zufall 0.5) | 0.5204 | 0.4903 | 0.5522 | 565 |

Diagnose Industrie-Momentum (EQ) je Periode und vor/nach der Stichprobe der Originalstudie (Moskowitz/Grinblatt 1999, bis 1995): bis 1995 IC +0.0729 [+0.0311, +0.1172] (205 Monate), ab 1996 IC +0.0342 [+0.0080, +0.0736] (360 Monate).

| Periode | Wert | low | high | Monate |
|---|---|---|---|---|
| 1979–1989 | 0.0569 | -0.0047 | 0.1102 | 132 |
| 1990s | 0.0947 | 0.0369 | 0.1467 | 120 |
| 2000s | 0.0442 | -0.0239 | 0.1157 | 120 |
| 2010s | 0.0292 | -0.0301 | 0.0691 | 120 |
| 2020–2026 | -0.0000 | -0.0555 | 0.0481 | 72 |

## Je Periode

| Periode | Allokator: Rendite p.a. | Allokator: Sharpe | B1: Rendite p.a. | B1: Sharpe | B2: Rendite p.a. | B2: Sharpe | Monate |
|---|---|---|---|---|---|---|---|
| 1979–1989 | 0.182 | 0.700 | 0.140 | 0.527 | 0.163 | 0.536 | 132 |
| 1990s | 0.116 | 0.788 | 0.080 | 0.524 | 0.129 | 0.823 | 120 |
| 2000s | 0.062 | 0.403 | 0.077 | 0.843 | 0.053 | 0.270 | 120 |
| 2010s | 0.075 | 0.946 | 0.051 | 1.065 | 0.102 | 0.981 | 120 |
| 2020–2026 | 0.088 | 0.680 | 0.086 | 0.801 | 0.148 | 0.853 | 73 |

## Varianten (ADR 054 f: vorab benannt, berichtet, entscheiden nicht)

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Trefferquote | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|---|
| ohne Zeitreihenfilter | 565 | 0.0940 | 0.0867 | 0.6029 | -0.1747 | 0.5380 | 0.6425 | 2.4889 | 0.0017 |
| nur Zeitreihe + Risikoparität | 565 | 0.0954 | 0.0741 | 0.7152 | -0.1470 | 0.6491 | 0.6690 | 2.6306 | 0.0015 |
| Hebelgrenze 1.0 | 565 | 0.0896 | 0.0739 | 0.6432 | -0.1472 | 0.6087 | 0.6920 | 2.5765 | 0.0016 |
| Halbwertszeit 6 | 565 | 0.1069 | 0.0934 | 0.6941 | -0.1403 | 0.7618 | 0.6726 | 3.6247 | 0.0023 |
| Kosten ×2 | 565 | 0.1041 | 0.0947 | 0.6594 | -0.1476 | 0.7053 | 0.6655 | 3.5602 | 0.0045 |
| nur Sleeve EQ | 565 | 0.1013 | 0.0982 | 0.6112 | -0.2004 | 0.5056 | 0.6832 | 1.9667 | 0.0016 |
| nur Sleeve FI | 565 | 0.0642 | 0.0608 | 0.3751 | -0.1129 | 0.5683 | 0.7522 | 2.0975 | 0.0005 |
| nur Sleeve PM | 565 | 0.0814 | 0.0938 | 0.4392 | -0.1459 | 0.5579 | 0.7345 | 1.3596 | 0.0011 |

## Diagnosen der Zweitprüfung (nach dem Lauf gerechnet, entscheiden nichts)

- Ohne die Jahre 1979–80 (Silber-Episode): Δ Sharpe zu B1 -0.092 [-0.257, +0.064]; ab 2000: -0.226 [-0.445, +0.050]; ohne das Jahr mit dem grössten Beitrag (1979): -0.055 [-0.234, +0.095].
- Trendfilter: Allokator gegen „ohne Zeitreihenfilter“ +0.080 [-0.087, +0.211]; „nur Zeitreihe + Risikoparität“ gegen B1 +0.030 [-0.157, +0.175]. Querschnitt: Allokator gegen „nur Zeitreihe + Risikoparität“ -0.032 [-0.134, +0.085]; Auswahl ohne Filter gegen B1 -0.082 [-0.199, +0.052]. Keine dieser Komponenten ist von Null zu trennen.
- Band: beide ohne Band – Allokator Sharpe 0.675, B1 0.631 (B1 mit Band 0.685); Δ +0.044 [-0.138, +0.212]. Das 2-Pp-Band friert die kleinen Industriegewichte von B1 über Jahre ein; die Engine handelt die Drift trotzdem zurück.
- Kosten ×2 für beide: Allokator 0.659, B1 0.682. Finanzierung des Hebels zum Cash-Index +50 bp: Allokator 0.677, B1 0.656.
- Vol-Ziel: realisierte/vorhergesagte Vol (Standardabweichung der standardisierten Folgemonatsrendite, 1 = treffend) Allokator 1.13, B1 1.14; mittlere vorhergesagte Vol 7.8% bzw. 5.8%; Anteil Entscheidungen, in denen eine Kappe das Vol-Ziel verhindert: 65% bzw. 88%.
- Teststärke: Standardfehler der Sharpe-Differenz ≈ 0.107; kleinster mit 80 % Power erkennbarer Effekt ≈ 0.27 Sharpe. Ein realistischer Beitrag des Industrie-Momentums (≈ 0.05) war mit diesem Test nicht zu erkennen: „nicht belegt“ heisst hier fehlende Evidenz, nicht Evidenz für kein Effekt.

## Urteil nach ADR 054 (e) – Kriterien vorab festgelegt

1. Sharpe ex Cash des Allokators (+0.683) über B1 Risikoparität ohne Signale (+0.685): **nein**
2. Gepaarte Sharpe-Differenz zu B1 positiv und Intervall ohne Null: **nein** (-0.002 [-0.188, +0.164])
→ Vorteil der Signale belegt: **NEIN**

Deflated Sharpe (Bailey/López de Prado 2014) der Residualrendite gegen B1 (Überschuss abzüglich Beta × B1-Überschuss, Appraisal Ratio – belohnt kein höheres Risiko; ADR 056): +0.251 p.a.; Hürde aus N = 58 Versuchen und der Varianz derselben Statistik über das Register (`docs/TRIALS.yaml`) +0.360; Wahrscheinlichkeit **0.221** (≥ 0.95 überlebt die Mehrfachprüfung) – berichtet, nicht entscheidend. (Die erste Fassung nannte 0.933: falsche Varianz – absolute statt aktiver Sharpe-Werte – und eine Aktivrendite, die Hebel als Können zählte.)

B2–B4 stehen zur Einordnung (anderes Universum, anderes Risiko) und entscheiden nicht. Finanzierung von Hebel zum Cash-Index ohne Aufschlag ist eine benannte Annahme (ADR 054 c).

Laufzeit 475 s.
