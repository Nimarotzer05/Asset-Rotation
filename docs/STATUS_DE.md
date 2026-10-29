# rotationlab – ausführlicher Stand (Deutsch)

Die englische Kurzfassung ist `README.md`; diese Seite ist der ausführliche Stand mit allen Verweisen auf ADRs
und Abnahmeprotokolle. Der erste Forschungscode (`src/`, `config.py`, `run.py`, `scripts/run_*.py`) liegt seit
28.10.2026 auf Branch `archive/legacy-research` (ADR 062).

An jedem Monatsende sagt `rotationlab`, welche von vier Anlageklassen – US-Aktien, US-Treasuries (10 J.), Gold,
Silber – im nächsten Monat relativ attraktiv sind: eine **Rangfolge** mit einer **Wahrscheinlichkeit** je
Klasse, in der oberen Hälfte zu landen (in-sample kalibriert, im Pseudo-Holdout schlechter als die Grundrate), und dem historischen Mittel je Rang; Basismetalle nur mit ihrem Trend (auf/ab;
der Energie-Trend wurde mangels Nachweis gestrichen, ADR 047). Einen Monat später wird jede Prognose gegen das Ergebnis
und gegen einfache Baselines abgerechnet – in einem append-only Journal mit Hash-Kette, dessen Kopf ausserhalb des
Repos verankert wird. Paper-Betrieb, kein Kapital (ADR 043–048).

**Was die Evaluation in-sample zeigt (1973–2018, Kriterien vorab fixiert; der Pseudo-Holdout 2019–2025 wurde danach einmalig gerechnet und ist gescheitert, siehe unten):** Rang-IC +0.098
[+0.051, +0.141], Rang 1 schlägt Rang 4 in 56.8 % der Monate, positiv in allen vier Jahrzehnten, Permutations-p < 0.0005
– ein kleiner, systematischer Vorteil, nicht „meistens richtig“ (`output/forecast/EVALUATION.md`). **In-sample
bezüglich der Modellwahl:** Features und Gewichte stammen aus der Forschungsphase auf demselben Zeitraum; vorab fixiert
sind Kriterien und Auswertung. Das reine 12-1-Momentum ohne angepasste Gewichte erreicht IC +0.108 (Robustheit). Echte
Out-of-Sample-Evidenz lieferte der Pseudo-Holdout (gescheitert, unten); offen ist allein die Live-Bilanz ab November 2026.
Die Rangfolge überlebt handelbare Preise (ETFs, Monatsend-Renditen: IC +0.099; `output/forecast/INVESTABILITY.md`). Die
Wahrscheinlichkeiten sind in-sample kalibriert, ihr Brier-Skill gegen die Grundrate je Klasse ist mit 488 Monaten nicht von Null
zu trennen; der Basismetall-Trend ist beschreibend, kein belegter Vorteil. Abnahmeprotokolle: `docs/FORECAST_ABNAHME.md`.

**Pseudo-Holdout 2019–2025 (einmalig gerechnet, Lesart vorab, ADR 049): Replikation gescheitert.** Rang-IC
**−0.03** [−0.18, +0.05] über 83 Monate, Rang 1 schlägt Rang 4 in 48 %, Wahrscheinlichkeiten schlechter als die
Grundrate; die Portfolio-Regel 8.1 % p.a. (Sharpe 0.61) gegen Equal Weight 16.3 % (Sharpe 1.03). Der In-sample-Vorteil
hat sich auf dieser Periode nicht gezeigt – ob er Anpassung war oder in 83 Monaten nur nicht sichtbar, entscheidet
allein die Live-Bilanz ab November 2026, die ohne Vorschuss beginnt (`output/forecast/HOLDOUT.md`). Modell und Regel
wurden danach nicht angefasst.

**Portfolio-Schicht (P8, Regel und Kriterium vorab fixiert, ADR 048):** Top-2 der Rangfolge gleichgewichtet, Trendfilter,
Vol-Ziel 10 % ohne Hebel, handelbares Timing und 15 bp Kosten, 1974–2018 durch dieselbe Engine wie die Baselines:
Sharpe 0.49 bei 9.2 % p.a., Vol 9.6 %, Max Drawdown −16 % – gegen Equal Weight 0.31 (Drawdown −39 %), 60/40 0.51 (−29 %),
Buy-and-Hold 0.44 (−51 %). Die gepaarte Sharpe-Differenz zu Equal Weight (+0.18 [−0.01, +0.39]) schliesst die Null
knapp nicht aus: **nach dem vorab fixierten Kriterium nicht belegt**; die Gewichte laufen als Paper-Spur im Journal mit
(`output/forecast/PORTFOLIO.md`).

**Forschungsrunde 2 (ADR 052/053, vorab fixiert, Ergebnis negativ):** drei Standardfamilien – 12-1-Momentum, Carry
(laufende Ertragsrendite), Value (Fünfjahres-Umkehr) – gleichgewichtet über fünf Klassen mit echten Monatsendpreisen
(US_EQ, UST10_ME, neu UST2_ME, GOLD, SILVER), 1981–2018: Rang-IC +0.056 [−0.002, +0.106] – Kriterium knapp verfehlt;
Value allein schadet (−0.10); Pseudo-Holdout 2019–2025 IC **−0.16** [−0.23, −0.05], Regel Sharpe 0.42 gegen Equal
Weight 1.01: Replikation deutlich gescheitert (`output/forecast_v2/`). Das Modell bleibt als reproduzierbares
Negativergebnis im Repo (`configs/forecast_v2.yaml`, `forecast_portfolio_v2`, `--config forecast_v2` in Skripten und
CLI) und läuft nicht live. Die veröffentlichte Prognose bleibt Runde 1.

**Forschungsrunde 3 (ADR 054–056, Sleeve-Allokator, vorab fixiert, Walk-forward ohne Holdout-Blick):** Breite statt
Parameter – 10 US-Industrien (French), 2 Treasury-Laufzeiten, Gold/Silber in drei Sleeves; Querschnitt innerhalb des
Sleeves, Zeitreihenfilter, inverse EWMA-Vol, Risikoparität, Vol-Ziel 10 %. Nach der Zweitprüfung (ein Gleichstand-Fehler
behoben, ADR 056) 1979–2026: Sharpe 0.683 gegen die signalfreie Risikoparität 0.685, Δ −0.002 [−0.19, +0.16] →
**Signale nicht belegt**; der scheinbare Renditevorsprung der ersten Fassung war Hebel. Industrie-Momentum (IC +0.05) ist
die einzige robuste Querschnittsbeobachtung und schwächt sich nach der Originalstudie deutlich ab. Der Test hätte
Effekte unter 0.27 Sharpe nicht erkannt (`output/allocator/WALKFORWARD.md`). Deflated Sharpe gegen das Versuchsregister
(`docs/TRIALS.yaml`, N = 58): Runde 1 0.56, Runde 2 0.84, Runde 3 0.22 – keine Runde überlebt die Mehrfachprüfung.

**Forschungsrunde 4 (ADR 057, vorab fixiert, bevor die Daten im Projekt sind):** Stufe 2 der Breite – fünf Sleeves,
≈ 45 Instrumente: US-Industrien (täglich), Länderaktien (French International), Treasuries 2/5/10 J. (täglich),
neun G10-Währungen dollar-neutral nach Carry und Momentum, Gold/Silber; jede Schwachstelle der Zweitprüfung als Designregel
(Hebel nur Anleihen, Tages-Vol mit langsamer Korrelation, Folgetag-Ausführung, kein Band, konservative Kosten mit
Finanzierungsaufschlag, Teststärke und Sekundärtests je Signal mit Holm-Korrektur). Die Daten holt der Workflow
`research-data` (die Forschungsumgebung erreicht FRED/French nicht); Ergebnis folgt nach dem Einfrieren. **Vor dem
Download gehärtet (ADR 058):** Trockenlauf der ganzen Kette auf zwei synthetischen Welten und frische Zweitprüfung des
Designs – zwei Fehler behoben (FX-Carry mit Monatslag wäre nie verfügbar gewesen; Kappen wirkten nach dem Trendfilter),
Vol-Ziel auf dem Long-Buch mit dem Währungs-Overlay ausserhalb (sonst mass der Vergleich mit B1 eine mechanische
Anleihe-Übergewichtung), Fenster an beiden Enden nach Regel, Währungen erst ab 1991 (Kapitalverkehrskontrollen), Cash
mit Investitionsrendite, Datenprüfung mit Schwellen vor dem Download, Registrierung aus einer Vorlage. **Gerechnet am 28.10. (ADR 059/060):** FRED liefert die D-Mark-Reihe nicht mehr, der Euro tritt ohne Verkettung 1999 ein (Notfallregel, vor dem Datenblick entschieden); Datenprüfung G1–G6 bestanden; Fenster nach Regel 1977-01 bis 2025-11 (587 Monate). Ergebnis (`output/allocator_v2/WALKFORWARD.md`): Allokator Sharpe 0.79 gegen passive Risikoparität 0.51, Δ +0.285 [+0.14, +0.43] → **Primärkriterium erfüllt**; Länder-Momentum und Währungs-Carry/Momentum als Rang-Portfolios je belegt (Holm 10 %). Nüchterne Deutung, die im Bericht steht: Die Variante „Risikoparität + Trendfilter ohne Querschnitt“ erreicht denselben Sharpe (0.792) – der Mehrwert ist der Zeitreihen-Trendfilter, nicht die Auswahl innerhalb der Sleeves; seit 2008 Δ +0.08 [−0.18, +0.28], Deflated-Sharpe-Wahrscheinlichkeit 0.895 (unter 0.95). B1 ist allerdings die schwächste der vier Baselines (Sharpe 0.506 gegen Buy-and-Hold 0.524, 60/40 0.563, Equal Weight 0.614); gegen B2–B4 enthält das Intervall die Null oder streift sie, und seit 2008 liegt der Allokator (0.594) unter Equal Weight (0.719) und 60/40 (0.720) – Punktschätzer, nachgerechnet in der Projekt-Rückschau vom 28.10. Deshalb kein Live-Betrieb von v2 (ADR 060); die Live-Prognose von Runde 1 bleibt der einzige Live-Track. **ETF-Check (ADR 061/062, vorregistriert):** dieselbe Ablation mit handelbaren ETFs 2008–2026: Filter gegen Risikoparität ohne Filter +0.064 [−0.215, +0.199] → nicht belegt; Vol um gut ein Viertel, Drawdown um fast die Hälfte tiefer; Korrelation mit der Index-Studie 0.96 (`output/etf_check/ETF_CHECK.md`).

**Fed-Kategorie und Long-Short-Regel (ADR 063/064, 29.10., vorregistriert):** Auftrag Nima: Zinsentscheide,
Arbeitslosigkeit und Inflation gehören in die Prognose, und „Rang 1 long 1.5×, letzter Rang short 1.5×“ soll auf
Profitabilität geprüft werden. **Runde 5:** fünf Fed-Variablen (Δ Fed Funds 3 M, realer Leitzins, Δ CPI-Jahresrate,
Sahm-Indikator, Δ Zinskurve), je Klasse per Ridge-Regression auf der expandierenden Vergangenheit abgebildet, 50/50 mit
dem Komposit von Runde 1, jeder Score punktweise: 1978–2018 Rang-IC 0.092 → 0.034, Δ −0.058 [−0.108, −0.006] →
**nicht belegt, in-sample schlechter**; 2019–2025 (gesehen) +0.070 (`output/forecast_fed/ROUND5.md`). `forecast_fed`
läuft trotzdem wie vorab entschieden als zweite Liveprognose mit eigenem Journal und Anker; veröffentlicht bleibt
Runde 1 (Entscheid Nima 29.10.: nicht ersetzen). **Long-Short:** 1974–2018 9.3 % p.a., Sharpe +0.313
[+0.051, +0.518], aber Vol 43 %, Max-Drawdown −82.5 %, schlechtester Monat −60 % (März 1980); 2019–2025 −12.1 % p.a. →
**nur in-sample profitabel**, nicht investierbar (`output/long_short/LONG_SHORT.md`). **Long-Short monatlich neu mit
20-%-Stop (ADR 065/066):** 1974–2018 −2.1 % p.a., Sharpe +0.109 [−0.195, +0.323], Drawdown −99 % → **nicht belegt**; der
Stop hilft nicht (Δ −0.06), Reibung 6.8 % p.a. Dabei gefunden: eine Samstags-Notierung im LBMA-Silber (1983-02-05),
offen berichtet; ohne sie +0.145 [−0.146, +0.353], Lesart unverändert (`output/long_short_stop/STOP.md`). Offen: Einfluss
dieser Zeile auf Runde 4 (tägliche Silber-Volatilität). **Long-Short in Dollar ohne Gebühren (ADR 067/068):**
$1500 long / $1500 short je Monat, Stop bei $200 Verlust eines Beins: 1974–2018 +$5,297 (Sharpe +0.247 [−0.021, +0.470]),
davon 1979 allein +$2,867; 2019–2025 −$484 → **nicht belegt**; ohne Stop mehr Gewinn (+$6,880), also schadet der Stop
auch ohne Kosten (`output/long_short_dollar/DOLLAR.md`). Register N = 84; Runde 4 jetzt Deflated Sharpe 0.83.

```bash
python -m rotationlab.cli forecast run                    # Prognose am letzten Monatsende, fällige abrechnen, Report (täglich in Actions)
python -m rotationlab.cli forecast verify                 # Hash-Ketten des Journals prüfen (mit --anchor gegen den Kopf aus dem Actions-Log)
python scripts/forecast_evaluation.py                     # historische Evaluation 1973–2018 (≈ 1 min); --config forecast_v2 für Runde 2
python scripts/forecast_investability.py                  # Rangfolge mit handelbaren Preisen
python scripts/forecast_portfolio.py                      # Portfolio-Regel gegen Baselines 1974–2018 (≈ 1 min); --config forecast_v2
python scripts/forecast_holdout.py                        # Pseudo-Holdout 2019–2025 – je Modell einmal gelaufen; Wiederholung nur mit --again
python scripts/allocator_walkforward.py                   # Runde 3: Sleeve-Allokator, Walk-forward 1979–2026, mit Diagnosen der Zweitprüfung (≈ 8 min)
python scripts/fetch_research_data.py --out research_data # Runde 4: Rohdaten laden (läuft im Workflow research-data)
python scripts/freeze_research_data.py --src <Checkout> --commit <SHA>   # Runde 4: eingefrorene, geprüfte Daten nach data/raw
python scripts/r4_data_check.py                            # Runde 4: Datenprüfung G1–G6 (ein NEIN stoppt die Runde)
python scripts/r4_register.py --sample <Beginn>,<Ende> --write   # Runde 4: Universum und Konfiguration aus der Vorlage
python scripts/allocator_v2_walkforward.py                 # Runde 4: Walk-forward nach ADR 057/058 (≈ 1 h; prüft zuerst das Fenster)
python scripts/round5_fed.py                               # Runde 5: Fed-Kategorie, punktweise (≈ 2 min)
python scripts/long_short_check.py                         # Long-Short 1.5/1.5 mit offener Buchhaltung (≈ 5 s)
python scripts/long_short_stop.py                          # Long-Short monatlich neu mit 20-%-Stop auf Tagesschlusskursen
python scripts/long_short_dollar.py                        # Long-Short in Dollar, Stop $200, ohne Gebühren
python -m rotationlab.cli forecast run --config forecast_fed   # zweite Liveprognose (täglich in Actions)
```

Darunter liegt das unveränderte Fundament: Point-in-time-Store mit Vintages, acht Provider, `MarketView`; 42
registrierte Features; fünf Strategie-Module und Walk-forward mit Goldens (eingefroren: `us_equity_exposure`,
`us_sector_rotation`, `precious_metals`; die nie gebauten Phasen 3/4 – Szenarien, Beziehungen, Live-Portfolio – wurden mit ADR 062 entfernt); eine Engine mit vier
Ausführungsmodi (`docs/PHASE2_ABNAHME.md`, ADR 042). Look-ahead-Audits in zwei Durchgängen
(`docs/AUDIT_phase1_vintage.md`, `docs/AUDIT_phase2_lookahead.md`); ruff und mypy strict ohne Befund. Architektur
`docs/ARCHITECTURE.md` (§12 Bauplan), Entscheidungen `docs/ADR.md`, Betrieb `docs/RUNBOOK.md`.

```bash
python -m rotationlab.cli validate                                   # Konfiguration und Katalog prüfen
python -m rotationlab.cli ingest --full --provider static            # Forschungshistorie in den Store
python -m rotationlab.cli asof --date 2008-06-30 --series static:fredmd:CPIAUCSL   # was war damals bekannt?
python -m rotationlab.cli golden --walkforward                       # alle Module gegen die Forschung
python -m rotationlab.cli backtest --strategy multi_asset_rotation --execution next_tradable   # ehrliches Timing
```
