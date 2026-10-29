# Forschungsrunde 5: Fed-Kategorie in der Monatsprognose

Stand 2026-10-29. Vorregistrierung ADR 063 (b); Konfiguration `configs/forecast_fed.yaml`; Skript `scripts/round5_fed.py`. Gerankt: ['US_EQ', 'UST10_ME', 'GOLD', 'SILVER']; Ergebnisse = relative Monatsrenditen auf Monatsendpreisen.
Jeder Score punktweise aus der Sicht am Entscheidungstag (575 Sichten); 90-%-Moving-Block-Bootstrap (Block 12, 2000 Ziehungen, Seed 20261025). Laufzeit 105 s.

**Basis** = Komposit von Runde 1 auf denselben Klassen (Monatsend-Treasury `UST10_ME` statt `UST10`, ADR 063 b). **Basis + Fed** = 0.5 · Komposit + 0.5 · z(Ridge-Vorhersage aus Zinsentscheiden, realem Leitzins, Inflation, Arbeitsmarkt, Zinskurve). **Nur Fed** = die Fed-Komponente allein (Ablation, berichtet, entscheidet nicht).

## Rang-IC (1 Monat)

| Zeitraum | Monate | IC Basis | IC Basis + Fed | IC nur Fed | Δ IC (Fed − Basis) |
|---|---|---|---|---|---|
| In-sample 1978-01 … 2018-11 | 491 | +0.0921 [+0.0395, +0.1381] | +0.0342 [-0.0135, +0.0807] | -0.0045 [-0.0582, +0.0526] | -0.0578 [-0.1075, -0.0061] |
| Gesehen 2019-01 … 2025-11 | 83 | -0.0289 [-0.1614, +0.0410] | +0.0410 [-0.0554, +0.1205] | +0.0651 [-0.0024, +0.1639] | +0.0699 [-0.0000, +0.1855] |
| Gesamt 1978-01 … 2025-11 | 575 | +0.0730 [+0.0209, +0.1137] | +0.0348 [-0.0136, +0.0758] | +0.0063 [-0.0470, +0.0567] | -0.0383 [-0.0856, +0.0080] |

## Vorab-Kriterien (ADR 063 b)

1. In-sample: Δ IC -0.0578 [-0.1075, -0.0061] → Intervall über null: **nein** (Standardfehler ≈ 0.0308, kleinste nachweisbare Differenz bei 80 % Power ≈ 0.0767).
2. Gesehener Zeitraum 2019–2025: Δ IC +0.0699 [-0.0000, +0.1855] → über null: **ja**.

Lesart: **nicht belegt** (Kriterium 1 nicht erfüllt).

Rang 1 stimmt in 47% der Monate zwischen Basis und Basis + Fed überein.

## Δ IC je Jahrzehnt (in-sample)

| decade | months | mean | share_positive |
|---|---|---|---|
| 1978–1989 | 144 | -0.0458 | 0.3264 |
| 1990s | 120 | -0.0617 | 0.3250 |
| 2000s | 120 | 0.0083 | 0.4250 |
| 2010–2018 | 107 | -0.1439 | 0.3645 |

## Steigungen der Fed-Komponente (letzter Fit vor dem Holdout und am Ende)

Standardisierte Ridge-Steigungen (λ = 1) in Prozentpunkten relativer Monatsrendite je Standardabweichung der Variable; positiv = die Klasse schneidet relativ besser ab, wenn die Variable hoch ist. Beschreibend, kein Test.

| Fit / Variable (Steigung in %-Punkten relativer Monatsrendite je SD) | US_EQ | UST10_ME | GOLD | SILVER |
|---|---|---|---|---|
| 2018-11: Zinsentscheide (Δ Fed Funds 3 M) | -0.026 | +0.124 | +0.042 | -0.140 |
| 2018-11: Realer Leitzins (Fed Funds − Inflation) | +0.110 | +0.188 | -0.102 | -0.196 |
| 2018-11: Inflation (Δ CPI-Jahresrate 3 M) | -0.135 | +0.004 | +0.146 | -0.015 |
| 2018-11: Arbeitsmarkt (Sahm-Indikator) | +0.084 | +0.041 | -0.091 | -0.034 |
| 2018-11: Zinskurve (Δ GS10 − T-Bill 3 M) | +0.050 | +0.087 | +0.023 | -0.159 |
| 2025-11: Zinsentscheide (Δ Fed Funds 3 M) | -0.025 | +0.117 | +0.037 | -0.129 |
| 2025-11: Realer Leitzins (Fed Funds − Inflation) | +0.076 | +0.165 | -0.090 | -0.152 |
| 2025-11: Inflation (Δ CPI-Jahresrate 3 M) | -0.113 | +0.052 | +0.146 | -0.085 |
| 2025-11: Arbeitsmarkt (Sahm-Indikator) | +0.090 | -0.061 | -0.134 | +0.105 |
| 2025-11: Zinskurve (Δ GS10 − T-Bill 3 M) | +0.033 | +0.081 | +0.025 | -0.139 |
