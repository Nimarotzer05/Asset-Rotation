# Audit der Aktienstudie: Look-ahead und Zeitlogik

Mechanische Prüfung von `scripts/run_equity.py` am 2026-10-24. 901 Prüfungen bestanden, 0 fehlgeschlagen.

## 1. Trunkierungs- und Mutationstest
Für 28 Daten D (8 historische Stressmonate + 20 zufällige) wurden alle Signale aus Teil A (Exposure) und Teil B (Branchen) einmal aus der Vollstichprobe und einmal aus (a) auf D gekürzten bzw. (b) nach D mit Rauschen überschriebenen Daten berechnet. Alle Werte am Datum D sind identisch: kein Signal verwendet Daten nach D.

## 2. Zeitlogik der Hilfsfunktionen
- PASS run_exposure: Gewicht von t wirkt in t+1, nicht in t
- PASS fwd[1] an t ist die Rendite von t+1
- PASS fwd[3] an t ist das Produkt über t+1..t+3
- PASS IC: Orakel-Signal (kennt t+1) → IC 1.0 (Ausrichtung Signal_t ↔ Rendite_t+1 korrekt)
- PASS IC: Signal aus Monat t hat keinen mechanischen Bezug zur Rendite t+1

## 3. Korrekturen gegenüber der ersten Fassung
| Punkt | Vorher | Nachher | Wirkung |
|---|---|---|---|
| Shiller-Gewinne | Lag 4 Monate | Lag 6 Monate | Gewinne sind quartalsweise linear interpoliert: der Monatswert enthält das Ergebnis des laufenden Quartals, das erst ~7 Wochen nach Quartalsende vorliegt (Vorlauf bis 5 Monate). 6 Monate sind sicher. ECY-Statistik praktisch unverändert (Tabelle unten). |
| CPI in CAPE/ECY | CPI des Monats t | CPI des Monats t−1 | CPI für t erscheint Mitte t+1. Wirkung auf CAPE < 0.3 %. |
| Branchen-Regime-Tabellen (B4) | relative Rendite im selben Monat wie das Regime | Regime am Monatsende t (Makro bis t−1), Rendite in t+1 | Tabelle ist jetzt das, was ein Investor hätte nutzen können. Muster unverändert: Energie +6.0/+4.8 % bei Inflation↑, −8.4 % in IP-Rückgang; langlebiger Konsum +13.0 % und Handel +8.1 % im IP-Rückgang, Defensive ≈ 0. |
| Begründung Composite (A2) | «schlechter, weil Arbeitsmarkt-Baustein falsch zeigt» | Zerlegung: Trend+Kredit Sharpe 0.40, Trend+Arbeitsmarkt 0.44, Trend allein 0.51 | Die alte Begründung war nicht belegt. Beide Makro-Bausteine schaden, Kredit stärker. Mechanismus: ein Baustein, der fast immer «ok» sagt, verwässert den Trend-Ausstieg auf 50 %. |
| Signalbildung | im Analyse-Code verwoben | reine Funktionen `signals_a`, `signals_b` | Trunkierungstest möglich; Vorlage für `rotationlab/features/equity.py`. |

## 4. Sensitivität der Excess CAPE Yield auf den Gewinn-Lag
Zeigt, wie gross der Fehler gewesen wäre: selbst ohne Lag (echter Look-ahead) ändern sich t-Werte und R² nur in der zweiten Stelle, weil ein Quartal in einem 120-Monats-Durchschnitt wenig Gewicht hat. Der Lag ist trotzdem korrekt gesetzt, weil das Live-System dieselbe Funktion nutzt.

| | ECY 1M t | ECY 1M R² | ECY 120M t | ECY 120M R² |
|---|---|---|---|---|
| Gewinn-Lag 0M | 3.79 | 0.015 | 5.24 | 0.443 |
| Gewinn-Lag 4M | 3.87 | 0.016 | 5.19 | 0.442 |
| Gewinn-Lag 6M | 3.88 | 0.016 | 5.17 | 0.441 |
| Gewinn-Lag 9M | 3.89 | 0.016 | 5.14 | 0.441 |

## 5. Golden-Werte nach dem Audit
| Modul | Kennzahl | Wert | Status |
|---|---|---|---|
| us_equity_exposure (Trend/Momentum-Mittel, French-Markt 1927–2026, 5 bp) | Sharpe ex Cash / Rendite / Max-DD | 0.573 / 0.099 / −0.411 | unverändert, freigegeben |
| us_sector_rotation (Top-3 Composite + Markt-Trendfilter, 10 French-Branchen 1928–2026, 10 bp) | Sharpe ex Cash / Rendite / Max-DD | 0.591 / 0.111 / −0.458 | unverändert, freigegeben |

## 6. Restrisiken, die kein Code-Test beseitigt
- **Revisionen:** FRED-MD liefert heutige Endstände. Industrieproduktion wird oft um > 0.5 Punkte revidiert; die Arbeitslosenquote kaum. Betroffen sind nur Kontext-Tabellen (B4) und die ausdrücklich *nicht* genutzten Makro-Signale. Die Module selbst nutzen nur Preise. Phase 1 ersetzt FRED-MD durch ALFRED-Vintages.
- **French-Daten:** CRSP-Korrekturen und SIC-Neuzuordnungen ändern historische Branchenrenditen leicht; keine Vintages verfügbar. Wirkung auf Monatsrenditen klein, auf Goldens innerhalb der Toleranz.
- **Auswahl nach Sicht:** Die Variante «Trend/Momentum-Mittel» wurde unter ~10 Varianten gewählt. Mildernd: alle Trendfenster 6–18 Monate liegen bei Sharpe 0.50–0.56, die Variante ist weder Maximum der Rendite noch des Sharpe; Walk-forward im System testet die Wahl laufend.
- **Proxy-Abweichung:** Goldens auf French-Gesamtmarkt und SIC-Branchen, Live auf SPY und GICS-Sektoren. Phase 2 misst die Abweichung 1999–2026, bevor Live-Toleranzen gesetzt werden.
- **Umsetzung D vs. D+1:** Studie zu D-Schluss, System zu D+1-Schluss; die Golden-Toleranz von ±0.02 Sharpe deckt das nach Erfahrung ab, Phase 2 prüft es.