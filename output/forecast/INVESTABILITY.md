# Investierbarkeit (P5): hält die Prognose mit handelbaren Preisen?

Stand 2026-10-27. Live-Daten: `data/raw/p5_live_monthend.csv.gz` (Monatsend-Schnitt des Live-Stores, Branch `data`, Stand 2026-10-26). Alles bis 2018-12.

## A. UST10: Monatsmittel der Rendite (GS10) gegen Monatsend-Rendite (DGS10)

Beide Indizes nutzen dieselbe Par-Bond-Formel (Swinkels 2019); nur die Rendite-Reihe unterscheidet sich.

| Reihe 1973–2018 | ann_return | ann_vol | autocorr_1 |
|---|---|---|---|
| UST10 (GS10-Mittel, Forschung) | 0.0717 | 0.0710 | 0.3054 |
| UST10 (DGS10-Monatsende) | 0.0725 | 0.0820 | 0.1152 |

- Korrelation der Monatsrenditen Mittel vs. Monatsende 1973–2018: **0.722**
- Korrelation mit IEF (7–10 J., 2002–2018): Mittel 0.698, Monatsende **0.989**; mit TLT (20+ J.): Mittel 0.675, Monatsende 0.934
- Volatilität p.a. 2002–2018: IEF 6.421%, TLT 12.907%, UST10 Mittel (2002–18) 6.238%, UST10 Monatsende (2002–18) 7.531%

Prognose mit UST10 aus Monatsend-Renditen statt Monatsmitteln (gleiches Modell, gleiche Stichprobe 1973–2018):

| Variante | IC | IC low | IC high | Trefferquote | Monate |
|---|---|---|---|---|---|
| Forschung (GS10-Mittel) | 0.0978 | 0.0511 | 0.1409 | 0.5675 | 548.0000 |
| Monatsende (DGS10) | 0.0993 | 0.0507 | 0.1423 | 0.5657 | 548.0000 |

- gepaarte IC-Differenz Monatsende − Forschung: **+0.0015** [-0.0150, +0.0153]
- identische Rangfolge in 90.3% der Monate, gleicher Rang 1 in 96.9%

## B. Energie und Basismetalle: 10-Monats-Trend je Preisbasis

**Energie.** Trend = Niveau über seinem 10-Monats-Schnitt. Ziel: für Mittelwerte die Rendite Mittel(t+2)/Mittel(t+1) (Entscheid 5), für Monatsendkurse die Rendite t→t+1. `hit_up` = Anteil positiver Folgerenditen nach Trend „auf“, `hit_down` nach „ab“; `diff_pa` = Differenz der Mittel auf minus ab, p.a., mit 90-%-Block-Bootstrap-Intervall.

| Energie: Basis | months | share_up | hit_up | hit_down | mean_fwd_up_pa | mean_fwd_down_pa | diff_pa | diff_low | diff_high |
|---|---|---|---|---|---|---|---|---|---|
| WB_ENERGY (Mittel) | 697.000 | 0.515 | 0.462 | 0.388 | 0.128 | 0.070 | 0.058 | -0.086 | 0.227 |
| WB_OIL (Mittel) | 697.000 | 0.499 | 0.460 | 0.375 | 0.151 | 0.073 | 0.078 | -0.092 | 0.278 |
| CL=F Monatsende | 211.000 | 0.640 | 0.563 | 0.539 | 0.138 | -0.033 | 0.171 | -0.157 | 0.375 |
| USO Monatsende | 143.000 | 0.469 | 0.507 | 0.474 | 0.055 | -0.199 | 0.254 | -0.128 | 0.573 |
| DBC Monatsende | 145.000 | 0.545 | 0.506 | 0.424 | 0.027 | -0.095 | 0.121 | -0.120 | 0.345 |

Übereinstimmung des Labels mit dem World-Bank-Index: WB_OIL (Mittel) 93.6% (699 Monate ab 1960-10-31); CL=F Monatsende 86.3% (212 Monate ab 2001-05-31); USO Monatsende 77.1% (144 Monate ab 2007-01-31); DBC Monatsende 84.2% (146 Monate ab 2006-11-30)

| Energie: Label → handelbare Rendite | months | share_up | hit_up | hit_down | mean_fwd_up_pa | mean_fwd_down_pa | diff_pa | diff_low | diff_high |
|---|---|---|---|---|---|---|---|---|---|
| WB-Label → Rendite CL=F Monatsende | 220.000 | 0.618 | 0.551 | 0.548 | 0.077 | 0.052 | 0.025 | -0.233 | 0.318 |
| eigenes Label → Rendite CL=F Monatsende | 211.000 | 0.640 | 0.563 | 0.539 | 0.138 | -0.033 | 0.171 | -0.157 | 0.375 |
| WB-Label → Rendite USO Monatsende | 152.000 | 0.586 | 0.483 | 0.460 | -0.022 | -0.218 | 0.196 | -0.171 | 0.600 |
| eigenes Label → Rendite USO Monatsende | 143.000 | 0.469 | 0.507 | 0.474 | 0.055 | -0.199 | 0.254 | -0.128 | 0.573 |
| WB-Label → Rendite DBC Monatsende | 154.000 | 0.578 | 0.461 | 0.492 | 0.007 | -0.053 | 0.059 | -0.137 | 0.322 |
| eigenes Label → Rendite DBC Monatsende | 145.000 | 0.545 | 0.506 | 0.424 | 0.027 | -0.095 | 0.121 | -0.120 | 0.345 |

**Basismetalle.** Trend = Niveau über seinem 10-Monats-Schnitt. Ziel: für Mittelwerte die Rendite Mittel(t+2)/Mittel(t+1) (Entscheid 5), für Monatsendkurse die Rendite t→t+1. `hit_up` = Anteil positiver Folgerenditen nach Trend „auf“, `hit_down` nach „ab“; `diff_pa` = Differenz der Mittel auf minus ab, p.a., mit 90-%-Block-Bootstrap-Intervall.

| Basismetalle: Basis | months | share_up | hit_up | hit_down | mean_fwd_up_pa | mean_fwd_down_pa | diff_pa | diff_low | diff_high |
|---|---|---|---|---|---|---|---|---|---|
| WB_BASEMETALS (Mittel) | 697.000 | 0.528 | 0.587 | 0.462 | 0.097 | -0.014 | 0.112 | 0.041 | 0.191 |
| WB_COPPER (Mittel) | 697.000 | 0.515 | 0.540 | 0.524 | 0.093 | 0.037 | 0.056 | -0.052 | 0.175 |
| HG=F Monatsende | 211.000 | 0.573 | 0.554 | 0.556 | 0.160 | 0.039 | 0.121 | -0.128 | 0.337 |
| CPER Monatsende | 76.000 | 0.355 | 0.296 | 0.551 | -0.041 | -0.048 | 0.007 | -0.195 | 0.307 |

Übereinstimmung des Labels mit dem World-Bank-Index: WB_COPPER (Mittel) 86.7% (699 Monate ab 1960-10-31); HG=F Monatsende 84.9% (212 Monate ab 2001-05-31); CPER Monatsende 83.1% (77 Monate ab 2012-08-31)

| Basismetalle: Label → handelbare Rendite | months | share_up | hit_up | hit_down | mean_fwd_up_pa | mean_fwd_down_pa | diff_pa | diff_low | diff_high |
|---|---|---|---|---|---|---|---|---|---|
| WB-Label → Rendite HG=F Monatsende | 220.000 | 0.591 | 0.569 | 0.522 | 0.171 | -0.014 | 0.185 | 0.007 | 0.375 |
| eigenes Label → Rendite HG=F Monatsende | 211.000 | 0.573 | 0.554 | 0.556 | 0.160 | 0.039 | 0.121 | -0.128 | 0.337 |
| WB-Label → Rendite CPER Monatsende | 85.000 | 0.447 | 0.447 | 0.447 | 0.024 | -0.100 | 0.124 | -0.010 | 0.333 |
| eigenes Label → Rendite CPER Monatsende | 76.000 | 0.355 | 0.296 | 0.551 | -0.041 | -0.048 | 0.007 | -0.195 | 0.307 |

## C. Plausibilität: Gold, Silber, US-Aktien

| Paar | Monate | ab | Korrelation | Vol-Verhältnis |
|---|---|---|---|---|
| GOLD (Forschung) vs GC=F | 220 | 2000-09-30 | 0.980 | 0.995 |
| GOLD (Forschung) vs GLD | 169 | 2004-12-31 | 0.975 | 0.980 |
| SILVER (Forschung) vs SI=F | 220 | 2000-09-30 | 0.957 | 1.018 |
| SILVER (Forschung) vs SLV | 152 | 2006-05-31 | 0.957 | 1.000 |
| US_EQ (French Markt) vs SPY TR | 311 | 1993-02-28 | 0.984 | 0.968 |

