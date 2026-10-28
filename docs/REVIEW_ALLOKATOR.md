# Prüfung aus Sicht eines professionellen Allokators (2026-10-27)

Auftrag des Auftraggebers (19:33): das Projekt so prüfen und weiterbauen, wie es ein Allokator mit institutioneller
Praxis täte – Breite erhöhen, Schwachstellen beseitigen, die dort niemand einbauen würde. Dieses Dokument ist die
Prüfung (Teil A), die daraus folgenden Änderungen ohne Forschungsentscheid (Teil B) und der Entwurf der
Forschungsrunde 3 (Teil C, fixiert erst mit ADR 054 nach Freigabe, vor der ersten Zahl).

Massstab: Grinold/Kahn (Fundamental Law: IR ≈ IC · √Breite · TC), Asness/Moskowitz/Pedersen (2013), Moskowitz/Ooi/
Pedersen (2012), Koijen et al. (2018), Harvey/Liu/Zhu (2016) und Bailey/López de Prado (2014) zur Mehrfachprüfung,
Moskowitz/Grinblatt (1999) zu Industrie-Momentum.

## A. Befund: was hält, was ein Profi nie so bauen würde

### Was hält (nicht anfassen)

| Element | Warum es professionellem Standard entspricht |
|---|---|
| Point-in-time-Store mit Vintages, Look-ahead-Harness, Mid-Month-Audit | Das ist der Teil, an dem die meisten Backtests scheitern; hier ist er erzwungen und getestet. |
| Vorab-Fixierung je Runde (ADR 044/048/049/052), Kriterien vor der ersten Zahl, Negativergebnisse dokumentiert | Entspricht dem Forschungsprotokoll jeder ernsthaften Quant-Gruppe. Zwei ehrlich berichtete Negativrunden sind mehr wert als eine geschönte Kurve. |
| Block-Bootstrap, Permutationstest, gepaarte Differenzen, Reliability-Diagramme | Richtige Werkzeuge für autokorrelierte Monatsdaten mit kleinem n. |
| Dieselbe Engine für Regel und Baselines, `next_tradable`, Kosten je Seite, append-only Journal mit externem Anker | Vergleichbarkeit und Nachprüfbarkeit – ohne das ist jede Zahl wertlos. |
| Gleichgewichtete z-Scores von Standardfamilien (Runde 2) statt gefitteter Gewichte | So kombinieren AQR/Man/Two Sigma Signale im Querschnitt: Ränge/z-Scores, Gleichgewicht, keine Regression auf 450 Punkten. |

### Schwachstellen, nach Gewicht geordnet

| # | Schwachstelle | Warum ein Profi das nicht baut | Behebung | Status |
|---|---|---|---|---|
| 1 | **Breite 4–5 Entscheidungen pro Monat** (ein Querschnitt über Anlageklassen). | IR ≈ IC·√Breite: bei IC ≈ 0.05 und Breite 5 ist die erwartbare IR ≈ 0.1 – unmessbar in 450 Monaten. Beide Negativrunden sind vor allem ein Breitenproblem. Institutionelle Allokatoren ranken **innerhalb** von Klassen (Sektoren, Länder, Laufzeiten, Rohstoffe, Währungen: 30–60 Instrumente) und steuern die Klassen selbst mit **Zeitreihen**-Signalen (absoluter Trend/Carry je Instrument), nicht mit einem Rang über fünf Äpfel und Birnen. | Runde 3: Sleeve-Architektur (Teil C). Verfügbare echte Monatsendpreise jetzt: 10 French-Industrien (CRSP, TR, ab 1926), zwei Treasury-Laufzeiten, Gold/Silber (LBMA-Fixings) = 14; nach einem Daten-Zyklus (Actions holt, Extrakt friert ein): Treasuries 5 J./30 J., 7 Währungen (FRED DEX, ab 1971), Länderindizes (Yahoo, Preisindizes) → 25–35. | offen, Teil C |
| 2 | **Querschnitt über Anlageklassen mit Carry/Value, die nur innerhalb einer Klasse vergleichbar sind.** Runde 2 verglich die Rendite der Zehnjährigen mit der Dividendenrendite und mit „0“ für Gold – und setzte damit 47 von 83 Holdout-Monaten die Anleihe auf Rang 1, in die Zinswende hinein. | Carry und Value werden je Anlageklasse definiert und **innerhalb** der Klasse standardisiert (Koijen et al. 2018 rechnen Carry je Klasse getrennt). Über Klassen hinweg braucht es Zeitreihen-Signale oder Risikoparität, keinen Rang. | Runde 3: je Sleeve eigener Querschnitt; Klassen-Allokation durch Zeitreihen-Trend und inverse Volatilität. | offen, Teil C |
| 3 | **Volatilität aus 12 Monatsrenditen** für das Vol-Ziel; **binärer Trendfilter**; **Top-N gleichgewichtet**. | 12 Punkte haben einen Standardfehler von ≈ 20 % der Vol; die Regel springt zwischen 0 und 1. Profis skalieren stetig: Zielgewicht ∝ Signal × 1/σ mit σ aus täglichen Renditen (EWMA, Halbwertszeit 30–60 Tage) und Rebalancing-Bändern gegen Umsatz. | Tägliche Reihen für alle Sleeves (French-Industrien täglich, DGS-Renditen täglich, LBMA täglich); Feature `vol_ewma_d` (täglich, Halbwertszeit fix vorab); stetige Gewichte in der Runde-3-Regel; Bänder vorab. | Teil B (Datenbasis), Teil C (Regel) |
| 4 | **Kein Risikomodell**: UST2_ME und UST10_ME (ρ ≈ 0.8) zählten als zwei unabhängige Klassen; Top-2 konnte beide halten. | Mindestens inverse Volatilität je Instrument und Risikoparität über Sleeves; bei korrelierten Instrumenten innerhalb eines Sleeves Equal-Risk-Contribution. Eine volle Kovarianz-Optimierung auf 10–30 Instrumenten ist **nicht** nötig (Schätzfehler); Risikoparität genügt. | Runde 3: inverse Vol innerhalb des Sleeves, Risikoparität über Sleeves, Gesamt-Vol-Ziel; Kovarianz nur zur Diagnose. | offen, Teil C |
| 5 | **Holdout 2019–2025 zweimal angeschaut** (Runde 1, Runde 2). Keine Buchführung der Versuche. | Jeder Blick auf dieselbe Periode senkt ihren Beweiswert; Harvey/Liu/Zhu verlangen t > 3 nach Mehrfachprüfung, Bailey/LdP den „Deflated Sharpe“ mit der Zahl der Versuche. Profis führen ein Versuchsregister. | **Versuchsregister** in diesem Dokument (unten); Runde 3 ohne Holdout-Blick: **Walk-forward** ab 1990 mit vorab fixiertem Design und **null** freien Parametern – jeder Monat ist dann out-of-sample bezüglich der Daten, nur das Design ist in-sample bezüglich der Literatur. Berichtet wird der Deflated Sharpe mit der Versuchszahl des Registers. | Teil B (Register), Teil C |
| 6 | **Monatsmittel-Reihen im Forschungspanel** (UST10 aus GS10, World-Bank-Rohstoffe), in Runde 1 sogar live gerankt. | Niemand rankt ein handelbares Instrument auf einem Monatsmittel – autokorrelierte Renditen erzeugen Scheinmomentum. ADR 052 hat das für Runde 2 beseitigt; Runde 1 ist eingefroren (ADR 049) und bleibt als dokumentiertes Negativergebnis live. | Runde 3: nur echte Preise. World-Bank-Reihen bleiben Diagnose. | erledigt für neue Runden |
| 7 | **Kosten uniform 7.5 bp je Seite**, nicht je Instrument. | Spreads reichen von 0.5 bp (SPY) bis 5–10 bp (SLV, DBC, EEM); bei 2× Umsatz p.a. ist das ein Unterschied von 10–30 bp p.a. – nicht urteilsrelevant, aber ein Profi rechnet es je Instrument (`universe.yaml` kann das: `cost_bps` je Asset, `default_bps: null`). | Runde 3: `default_bps: null`, Kostensätze je Asset vorab aus typischen Spreads fixiert und im ADR begründet. | Teil C |
| 8 | **Vol-Ziel mit Untergrenze 5 % und ohne Hebel**: eine anleihelastige Top-2 erreicht 6 % Vol, das Ziel 10 % ist Dekoration; Vergleiche gegen EW mit 9 % Vol sind renditeseitig unfair (Sharpe-seitig fair). | Profis vergleichen risikoangepasst: entweder Hebel bis zum Ziel (Duration ist hebelbar) oder Baseline auf gleiche Vol skaliert. | Runde 3: Baselines **vol-skaliert** auf das Ziel; Hebelgrenze vorab (1.5 für Anleihen-Sleeve); Sharpe bleibt das Kriterium. | Teil C |
| 9 | **Live-Prognose trägt kein Konfidenzmass auf Portfolioebene** (nur je Klasse). | Ein Allokator sieht erwartete Vol, Risikobeitrag je Sleeve, Umsatz der Entscheidung. | Runde-3-Report: Risikobeiträge, erwartete Vol, Umsatz je Entscheidung. | Teil C |
| 10 | **Zwei Live-Journale wären ohne Nutzen** (abgelehnt 19:30). | Richtig entschieden: ein verworfenes Modell live mitzuführen misst nichts. | – | erledigt |

### Versuchsregister (für Deflated-Sharpe-Haircuts; wird mit jeder Runde fortgeschrieben)

| Runde | Modelle/Varianten mit berechneter Kennzahl auf 1973/1981–2018 | Blicke auf 2019–2025 |
|---|---|---|
| Forschungsphase (vor ADR 043) | `src/signals.py`-Komposit, Walk-forward-Gitter der `multi_asset_rotation` (Top-N × Trendfilter, ≈ 8 Punkte), Sektor-/Edelmetall-Studien | 0 (Periode im Panel, aber nicht als Holdout geführt) |
| Runde 1 (ADR 044–048) | Basismodell, 12-1-Variante, Regime-Tilts, 4 Wahrscheinlichkeitsmodelle, 2 Regel-Sensitivitäten | 1 (ADR 049) |
| Runde 2 (ADR 052/053) | Basismodell, 6 Ablationen, 4 Wahrscheinlichkeitsmodelle, 1 Regel-Sensitivität | 1 (ADR 052 g) |
| Runde 3 (ADR 054/055) | Allokator, 8 vorab benannte Varianten (Walk-forward, 2019–2025 enthalten) | 0 (kein Holdout mehr) |
| **Summe** | ≈ 38 Varianten auf überlappenden Daten | **2** – die Periode ist als Holdout verbraucht |

Folge: Runde 3 bekommt keinen Holdout-Blick mehr; ihr Walk-forward-Ergebnis wird mit N ≈ 30 Versuchen deflationiert
berichtet (Bailey/López de Prado 2014, `evaluation.deflated_sharpe`), und jede weitere Variante wird vor dem Lauf hier
eingetragen.

## B. Änderungen ohne Forschungsentscheid

Gebaut und getestet (Abnahme in `docs/FORECAST_ABNAHME.md`, „Allokator-Prüfung“):

1. **Versuchsregister** (oben) und `rotationlab.forecast.evaluation.deflated_sharpe(excess, n_trials, trials_var)`
   nach Bailey/López de Prado (2014): erwartetes Maximum der Sharpe von N Versuchen ohne Können und die
   Wahrscheinlichkeit, dass die wahre Sharpe darüber liegt (Schiefe und Kurtosis der Reihe berücksichtigt).
   `scripts/forecast_portfolio.py` berichtet sie für beide Runden (N = 30, Varianz aus den fünf gelaufenen Regeln,
   `scripts/_forecast_common.py`), beschreibend, nicht als Kriterium. Auf der Überschussrendite über Cash liegt die
   Wahrscheinlichkeit bei 0.989 (Runde 1) und 0.998 (Runde 2) – das ist die Prämie des Haltens von Aktien und Anleihen,
   kein Können. Auf der **aktiven Rendite Regel − Equal Weight** (dem, was die Auswahl leistet): Sharpe +0.06 p.a. in
   beiden Runden, Hürde +0.15, Wahrscheinlichkeit **0.27 / 0.30** – keine der beiden Auswahlen überlebt die
   Mehrfachprüfung (≥ 0.95 wäre nötig). Die Varianz der Versuche stammt aus fünf ähnlichen Regeln und ist eher zu
   klein, die Hürde also eher zu tief.

Geplant, weil sie Teil des Designs von Runde 3 sind und mit ADR 054 fixiert werden (nicht vorher gebaut, damit keine
Zahl vor der Fixierung entsteht):

2. **Tägliche Reihen für die Volatilität**: Tagesextrakt der DGS-Renditen aus dem Live-Store (ab 1962/1976),
   Par-Bond-Tagesindizes, French-Industrien täglich (Download im Actions-Lauf), LBMA täglich (vorhanden).
3. **Kosten je Instrument** (`cost_bps` je Asset, `default_bps: null`), Sätze vorab aus typischen Spreads, im ADR
   begründet; Runde 1 und 2 bleiben eingefroren.

## C. Forschungsrunde 3 – Sleeve-Allokator (fixiert als ADR 054 nach Freigabe 19:50; Ergebnis ADR 055)

**Stand nach dem Lauf und der Zweitprüfung (2026-10-27):** gebaut und gerechnet wie unten beschrieben (Stufe 1, SPDR-
Zuordnung). Die Zweitprüfung (ADR 056) fand einen Gleichstand-Fehler (korrigiert: Sharpe 0.683 gegen B1 0.685, Δ −0.002
[−0.19, +0.16]), eine Abweichung vom Kundenentscheid (Hebel aufs ganze Buch statt aufs Anleihe-Sleeve), einen falsch
definierten Deflated Sharpe (korrekt 0.221) und mehrere ungedeckte Aussagen. Kriterium nicht erfüllt, nicht live.
Details `docs/FORECAST_ABNAHME.md`, `output/allocator/WALKFORWARD.md`; Register `docs/TRIALS.yaml` (N = 58).

### Entwurf (Stand vor dem Lauf)

**Ziel:** eine monatliche Allokation über drei Sleeves mit echten Preisen, Breite ≥ 14 (Stufe 1) bzw. ≥ 25 (Stufe 2),
null freie Parameter, Walk-forward-Bewertung ohne Holdout-Blick.

**Sleeves (Stufe 1, Daten vorhanden):**

| Sleeve | Instrumente | Querschnitts-Signal (innerhalb) | Zeitreihen-Signal (Sleeve-Gewicht) |
|---|---|---|---|
| US-Aktien nach Industrie | 10 French-Industrien (Live: 11 SPDR-Sektoren, Zuordnung vorab) | 12-1-Momentum (Moskowitz/Grinblatt 1999); Top-5 von 10, inverse Vol | Trend des Marktes (12-1 > 0, Vol-skaliert) |
| US-Treasuries | 2 J., 10 J. (Stufe 2: 5 J., 30 J.) | Carry = Rendite − 3-M-Satz, inverse Duration-Vol | Trend je Laufzeit |
| Edelmetalle | Gold, Silber (LBMA täglich; Stufe 2: Platin über PPLT nur live) | 12-1-Momentum | Trend je Metall |

**Stufe 2 (nach einem Daten-Zyklus):** Währungen (FRED DEX: JPY, GBP, CHF, CAD, AUD, SEK, NOK gegen USD, ab 1971; Carry aus
OECD-3-M-Sätzen), Länder-Aktienindizes (Yahoo: ^N225, ^FTSE, ^GDAXI, ^HSI, ^GSPTSE – Preisindizes, nur Momentum/Trend),
Treasuries 5 J./30 J. Der Zyklus: Reihen in `series.yaml` → Upload → Actions-Lauf holt sie → Extrakt friert sie ein →
Forschung. Ohne diesen Zyklus bleibt Stufe 1.

**Kombination:** Zielgewicht je Instrument = (Querschnitts-Rang-Gewicht innerhalb des Sleeves) × (Sleeve-Gewicht aus
Risikoparität über Sleeves, skaliert mit dem Zeitreihen-Trend des Sleeves ∈ {0, 1}) × (Gesamt-Vol-Ziel 10 % /
erwartete Vol, Hebel ≤ 1.5, sonst Cash). Vol aus täglichen Renditen, EWMA-Halbwertszeit 60 Tage (fix). Rebalancing-Band:
Gewichtsänderung < 2 Pp wird nicht gehandelt (fix). Alle Zahlen vorab; keine ist auf den Daten gewählt.

**Bewertung:** Walk-forward 1990-01 bis 2026-09 (alles davor dient nur zur Initialisierung der Vol- und
Carry-Schätzer): jeder Monat wird mit Informationen bis zum Monatsende entschieden, keine Grösse wird je rückwirkend
gewählt. Kriterien (vorab): (1) Sharpe ex Cash über der vol-skalierten Equal-Weight-Baseline aller Instrumente mit
90-%-Intervall der gepaarten Differenz ohne Null; (2) Deflated Sharpe > 0 bei N = 30 + Zahl der in dieser Runde
gelaufenen Varianten; (3) jeder Sleeve einzeln mit IC-Intervall ohne Null über seine Instrumente (Breite 10 / 2 / 2 –
für die kleinen Sleeves nur berichtet). Kein Blick auf eine Holdout-Periode: 2019–2025 ist Teil des Walk-forward und
zählt nicht mehr als Beweis. Echter Out-of-sample bleibt die Live-Bilanz.

**Was bewusst nicht gebaut wird:** Kovarianz-Optimierer (Schätzfehler > Nutzen bei 14–30 Instrumenten),
Machine-Learning-Signale (Breite zu klein für Lernverfahren), Fundamental-Value mit Publikationslag (Vergleichbarkeit),
Short-Positionen (Paper-Allokator long-only; Cash ist die Short-Seite).

**Offene Entscheide des Auftraggebers (keine Annahme umgesetzt):**

1. Stufe 1 sofort (14 Instrumente, alles im Repo) und Stufe 2 nach dem Daten-Zyklus – oder auf Stufe 2 warten?
2. Hebel bis 1.5 auf Sleeve-Ebene (Anleihen) zulassen oder long-only ohne Hebel (dann Vol-Ziel als Obergrenze)?
3. Live-Universum für die Industrien: 11 SPDR-Sektoren auf 10 French-Industrien abgebildet (Zuordnung im ADR) –
   akzeptiert?

## D. Forschungsrunde 4 – Stufe 2 mit behobenen Schwachstellen (ADR 057)

Vorab fixiert, bevor die Daten im Projekt sind. Jede Zeile der Befundtabelle aus Teil A und jeder Befund der Zweitprüfung
(ADR 056) ist eine Designregel: Breite ≈ 45 Instrumente in fünf Sleeves; Querschnitt nur ab sechs Instrumenten (US-
Industrien, Länder, Währungen), FI und Metalle nur Zeitreihe; Rang-Gewichte statt binärer Auswahl; Währungen dollar-
neutral; Volatilität aus Tagesrenditen, Korrelation aus Monatsrenditen; Vol-Ziel auf dem ungefilterten Buch, der
Trendfilter senkt das Risiko; Hebel nur im Anleihe-Sleeve (Kundenentscheid), Systemgrenze brutto 2.0; kein Band;
Folgetag-Ausführung mit Tagesreihen; Kosten konservativ plus 30 bp Finanzierungsaufschlag; Teststärke (MDE) und
Sekundärtests je Signal (Rang-Portfolios, Newey-West, Holm 10 %); Deflated Sharpe auf der Residualrendite mit dem ganzen
Register; Teilperioden und das Jahr mit dem grössten Beitrag vorab als Robustheitsbericht. Bewusst nicht gebaut:
Kovarianz-Optimierer, FX-Value ohne CPI-Vintages, Rohstoff-Futures ohne Total-Return-Historie, Unternehmens- und
internationale Staatsanleihen, Länder-Value. Stand: gebaut und getestet; die Daten kommen über den Workflow
`research-data` (Upload, ein manueller Lauf), dann Einfrieren und Lauf.

## E. Zweitprüfung des Designs von Runde 4 vor dem Download (2026-10-28, ADR 058)

Ein frischer Prüfer ohne Vorgeschichte hat ADR 057 gegen Code und Konstruktionen geprüft, parallel lief ein Trockenlauf
der ganzen Kette auf synthetischen Daten. Ergebnis: zwei Blocker, vier gewichtige und sieben kleinere Befunde – alle
nachgerechnet, alle vor dem ersten Blick auf die Daten entschieden (ADR 058).

| Nr | Befund | Gewicht | Entscheid |
|---|---|---|---|
| 1 | Kappen nach dem Trendfilter: freigewordener Platz wurde mit Anleihen aufgefüllt | Blocker (Codefehler gegen 057 c) | Kappen-Faktoren auf dem ungefilterten Buch, Filter danach |
| 2 | FX-Carry mit Monatslag hatte im Entscheidungsmonat nie einen Wert → FX-Sleeve nie aktiv (auch im Trockenlauf gefunden) | Blocker | `max_age_months` 3; Carry = Niveau des eigenen 3-M-Zinses |
| 3 | Overlay senkte k, Allokator hielt mechanisch mehr Anleihen als B1 | gewichtig | Vol-Ziel auf dem Long-Buch, Overlay mit demselben k, aber ausserhalb |
| 4 | Budget eines inaktiven Sleeves wanderte zu den anderen | gewichtig | Budget² bleibt als unkorrelierter Cash-Platz in σ_book |
| 5 | Fensterende stand von Hand in der Konfiguration | gewichtig | Ende nach Regel über die Datengruppen, vom Skript gerechnet und geprüft |
| 6 | Heimische Zinsen vor der Liberalisierung für Dollar-Anleger nicht erreichbar | gewichtig (Design) | Währungen erst ab 1991, einheitlich und konservativ |
| 7 | Par-Bond-Verzinsung täglich aufgezinst (+y²/4 p.a.); T-Bill-Diskont- statt Investitionsrendite | klein | (1 + c/2)^(2Δt) − 1; Cash `TBILL_IY` |
| 8 | Holm mit NaN-p-Wert hängt von der Reihenfolge ab | klein | Familie nur aus testbaren Hypothesen, NaN = Fehler |
| 9 | Varianz des Deflated Sharpe ohne die eigene Runde | klein | die 12 Läufe der Runde gehen in die Varianz ein |
| 10 | Metalle am Fixing des Entscheidungstags, wenn London am Ausführungstag zu ist | klein | benannte Einschränkung, begrenzt durch eine Variante |
| 11 | Gleichstand anders herum als in Runde 3 | klein | das frühere Instrument gewinnt, wie in Runde 3 |
| 12 | Lücken überbrückt; Rang-Test entfernte Austritte rückwirkend | klein | Index endet an der Lücke; Austritt verdient 0, nie neu gerankt |
| 13 | EQ_US prüft dasselbe Signal wie Runde 3 erneut; Kosten konstant | Lesart | EQ_US als Replikation, Holm nur über EQ_INTL und FX; Kosten-×2-Variante |

Was der Prüfer als korrekt bestätigt hat: Notierungsrichtungen aller zehn H.10-Reihen, DEM→EUR-Faktor und Datum, Lag des
Monatszinses, Zinsabgrenzung mit dem Vortageswert, Preisanteil des Par-Bonds gegen exakte Bewertung, Rang- und
Langbein-Gewichte, Verfügbarkeit unabhängig von den Schaltern, Risikoparität und Buch-Vol-Formel, Ausrichtung Score →
Folgemonat (ein Orakel-Score ergibt t = 63), Newey-West, Holm, Deflated Sharpe (gegen scipy), gepaarter Block-Bootstrap,
MDE, Finanzierungsaufschlag, `next_tradable`, B1–B4 und die elf Varianten.


## F. Zweitprüfung des Ergebnisses von Runde 4 (2026-10-28, ADR 060)

Frischer Prüfer ohne Vorgeschichte, rein lesend, eigene Nachrechnungen aus `output/allocator_v2/*.csv` und `data/raw/`.
**Kein Blocker, kein Datenleck, keine Abweichung des Codes von ADR 057/058/059 in der Sache, keine nach dem Datenblick
gewählte Grösse** (ausser Länder-Parser, Länderliste und Fenster – alle drei nach Regel, wie angekündigt). Jede Kennzahl
des Berichts reproduziert (Abweichung < 1e-14); die drei Rang-Portfolios aus den Rohdateien unabhängig nachgebaut
(maximale Abweichung 1e-16) – die Scores nutzen nur Daten bis D und den mit 1M Lag publizierten Zins. Bootstrap-Robustheit:
Seeds 1–5 und Block 24 geben [+0.13, +0.43]. Datenplausibilität: Cash 4.5 % p.a., UST 2/5/10 J. 5.1/5.6/6.2 % bei Vol
2.9/5.6/8.4 %, Par-Bond flach 5 % → 5.08 % p.a.

| Nr | Schwere | Befund | Umgang |
|---|---|---|---|
| F1 | gewichtig | Das JA ist ein Trendfilter-Ergebnis: Allokator − „ohne Querschnitt“ −0.001 [−0.069, +0.060] bei Korrelation 0.96 – ein *präziser* Nullbefund, kein schwacher Test; „ohne Querschnitt“ − B1 +0.286 [+0.139, +0.442]. Die Variante ohne Querschnitt hat weniger Vol (6.8 %), Drawdown (−10 %), Umsatz und Kosten. | Deutung so in ADR 060, Abnahme, README; beide Differenzen jetzt im Bericht (Abschnitt „Nach der Zweitprüfung ergänzt“, nicht vorregistriert). |
| F2 | gewichtig | EQ_INTL und FX seit 2008 flach (−0.1 % / +0.0 % p.a., t ≈ 0); Evidenz aus der Literaturperiode; Holm 10 % einseitig ist eine milde Hürde. | Rang-Portfolios je Teilperiode im Bericht ergänzt; Deutung in ADR 060. |
| F3 | gewichtig | Teilperiode 2008–Ende +0.08 [−0.18, +0.28] und Deflated Sharpe 0.895 < 0.95 gehören ins Urteil. | In ADR 060 und Abnahme als Grund gegen Live genannt. |
| F4 | gewichtig | Regimekonzentration: Filtervorteil aus Zinswende-Jahren (1980/81, 2013, 2022) und der Hochzinsphase bis 1989; Long-Buch > 1.0 in 47 % der Monate; Finanzierung −0.017 Sharpe je +100 bp. | Berichtet hier; Hebelannahme (T-Bill + 30 bp) ist für 1977–89 eher optimistisch. |
| F5 | klein | SE und MDE wurden nur bei NEIN gedruckt (ADR 057 f verlangt sie immer): SE 0.088, MDE 0.22. | Skript gibt sie jetzt immer aus. |
| F6 | klein | ADR 057 (c) „Rang − (N+1)/2“ zweideutig; Code und Docstring (die Spezifikation) eindeutig: Rang 1 = höchster Score, Offset (N+1)/2 − Rang. | Klargestellt in ADR 060. |
| F7 | klein | Zeitangabe in ADR 059 ohne Zone. | „17:10 MEZ (16:10 UTC)“ nachgetragen; Lauf 1 16:04 UTC, Lauf 2 16:34 UTC. |
| F8 | klein | `register()` schlüsselte nach Namen, Runde 3 und 4 teilen Namen – im genutzten Pfad folgenlos. | Schlüssel jetzt `round/name`; DSR unverändert (26 Reihen, p 0.895). |
| F9 | klein | Fensterende 2025-11 durch die Darstellungs-Baselines B3/B4 (US-Markt) gesetzt. | So in ADR 058 (e) vorgesehen; keine Änderung. |
| F10 | klein | Länderindizes mit Lag 0D, gehandelt zum Entscheidungskurs; French publiziert Wochen später. | Als Einschränkung benannt (ein Länder-ETF-Schlusskurs wäre am Monatsende verfügbar). |
| F11 | klein | Einlagenindex verzinst mit dem zuletzt *publizierten* Monatszins (um einen Monat verschobener Carry). | Gewollte Konvention (ADR 057 a), vernachlässigbar. |
| F12 | klein | Bootstrap-Intervalle schliessen den Punktschätzer ein; hier ohne Wirkung. | – |
| F13 | klein | DSR-Varianz von Designunterschieden der Runden dominiert; ohne die eigenen 12 Läufe wäre p 0.968. | Konservative Fassung ist vorregistriert (ADR 058). |

**Urteil des Prüfers (gekürzt):** Protokoll eingehalten, ehrlich gerechnet. Die richtige Schlussfolgerung lautet
„Risikoparität mit 12-Monats-Trendfilter, Hebel bis 1.5“ – nicht „Allokator mit fünf Sleeves und drei Signalen“; ein Drittel
des Ergebnisses stammt aus einer Hochzinsphase, die sich seit 2008 nicht wiederholt hat.
