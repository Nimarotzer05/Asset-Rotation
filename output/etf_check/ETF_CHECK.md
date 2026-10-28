# Umsetzbarkeits-Check mit ETFs (ADR 061): Risikoparität + Trendfilter

Stand 2026-10-28. Daten: Live-Store, Branch `data@1c110a48e72c` (Yahoo-Schlusskurse mit Dividenden und Splits). Fenster nach ADR 058 (e): 2008-06-30 … 2026-09-30 (220 Monate); erste Entscheidung mit allen Long-Sleeves 2008-05-31. Ausführung `next_tradable`, Kosten je ETF aus `configs/universe.yaml`, Finanzierung zum Cash-ETF BIL +30 bp. Ein vorregistrierter Lauf (ADR 061), im Versuchsregister vor dem Lauf eingetragen. Alle Zahlen aus `scripts/etf_check.py`.

**Einordnung:** Das Fenster überlappt die Teilperiode 2008–2025 von Runde 4, in der der Vorteil zu B1 auf Indizes +0.08 [−0.18, +0.28] betrug (ADR 060). Der Check prüft die Umsetzbarkeit, keine neue Hypothese, und ist keine unabhängige Evidenz für den Filter.

## Kennzahlen

| Lauf | Monate | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Calmar | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|---|---|
| R Risikoparität + Trendfilter (ETF) | 220 | 0.0476 | 0.0642 | 0.5584 | -0.0928 | 0.5127 | 2.0087 | 0.0016 |
| B1 Risikoparität ohne Filter (ETF) | 220 | 0.0540 | 0.0889 | 0.4940 | -0.1672 | 0.3231 | 0.7675 | 0.0008 |
| B2 Equal Weight (14 ETFs) | 220 | 0.0912 | 0.1242 | 0.6640 | -0.3252 | 0.2805 | 0.1890 | 0.0002 |
| B3 60/40 SPY/IEF | 220 | 0.0849 | 0.0971 | 0.7569 | -0.2457 | 0.3454 | 0.1242 | 0.0001 |
| B4 Buy-and-Hold SPY | 220 | 0.1171 | 0.1566 | 0.7067 | -0.4181 | 0.2801 | 0.0000 | 0.0000 |

## Gepaarte Sharpe-Differenzen R − Baseline (90-%-Block-Bootstrap)

| Baseline | Δ Sharpe | low | high |
|---|---|---|---|
| B1 Risikoparität ohne Filter (ETF) | 0.0644 | -0.2149 | 0.1990 |
| B2 Equal Weight (14 ETFs) | -0.1055 | -0.5501 | 0.0493 |
| B3 60/40 SPY/IEF | -0.1985 | -0.7116 | 0.0132 |
| B4 Buy-and-Hold SPY | -0.1483 | -0.6618 | 0.0810 |

## Index-Studie gegen ETF-Umsetzung (gleiche Monate)

- Korrelation der monatlichen Überschussrenditen ETF-Version gegen Index-Version „ohne Querschnitt“ (Runde 4): **0.96** über 210 Monate.
- Sharpe ex Cash über diese Monate: ETF +0.577, Index +0.657.

## Urteil nach ADR 061 (d) – vorab festgelegt

1. Sharpe ex Cash von R (+0.558) über B1 (+0.494): **ja**
2. Intervall der gepaarten Differenz über null: **nein** (+0.064 [-0.215, +0.199])
→ Trendfilter mit ETFs umsetzbar belegt: **NEIN** – Standardfehler 0.126, MDE (80 % Power) 0.31

Laufzeit 187 s.
