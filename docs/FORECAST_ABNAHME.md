# Monatsprognose der Anlageklassen: Abnahmeprotokolle (ADR 043)

Jeder Schritt endet mit grünen Tests und diesem Protokoll. Zahlen stammen aus tatsächlichen Läufen; was
offen ist, steht getrennt. Holdout: Alle Läufe dieses Dokuments enden spätestens 2018-12-31.

## P1 Entscheidung (2026-10-25)

ADR 043 und der Bauplan (`ARCHITECTURE.md` §12) vom Auftraggeber freigegeben, mit sechs Methodenentscheiden
(Tabelle in §12). Kein Code geändert.

## P2 Prognoseobjekt (2026-10-25)

**Gebaut:** `rotationlab/forecast/types.py` – `Forecast` (eine Prognose je Entscheidungsdatum und Horizont:
Datum, Horizont, Status, Modell-ID, Version, Parameter, Datenstand, Kalibrierungsmonate, Hinweise, optionale
abgeleitete Gewichte, Zeitstempel beim Schreiben) und `ClassForecast` (je Klasse: gerankt ja/nein, Trend
auf/ab mit Abstand zum 10-Monats-Schnitt, Score, Rang, erwartete relative Überschussrendite mit Band).
Konfiguration `configs/forecast.yaml` mit Schema `ForecastConfig` (unbekannte Schlüssel sind Fehler; Teil
des Config-Hashes; Cross-Check der Assets).

**Eigenschaften, die die Tests erzwingen** (`tests/unit/test_forecast_types.py`, 16 Tests):

- Unveränderlich: Attribute eingefroren, Parameter rekursiv schreibgeschützt.
- Kanonisches JSON: gleiche Prognose = gleiche Bytes (sortierte Schlüssel), Hin- und Rückweg verlustfrei,
  unbekannte Schema-Version wird abgelehnt.
- Status `signal` / `no_clear_signal` verlangt Ränge 1..n für jede gerankte Klasse und eine Erwartung je
  Rang; `warmup` erlaubt fehlende Ränge.
- Klassen nur mit Trend (Energie, Basismetalle) können keinen Score, Rang oder Erwartungswert tragen.
- Band enthält den Erwartungswert; keine NaN-Werte; jede Klasse genau einmal.
- Gewichte sind ein optionales Feld und gehen nirgends ein.

**Datenstand:** `data_snapshot` (Prüfsumme des Stores, aus dem der View gebaut wurde) plus `decision_date`
legen die Daten eindeutig fest: Der View filtert auf `obs_date ≤ D` und `vintage_date ≤ D`.

## P3 Basismodell (2026-10-25)

**Gebaut:** `rotationlab/forecast/model.py` – `ForecastModel`:

- Score = Composite des `multi_asset_rotation`-Moduls (12-1 0.3, 6-1 0.3, 3-1 0.2, Trend 0.2, inverse Vol
  0.1; z-Scores je Monat über US_EQ, UST10, GOLD, SILVER, bei ±3 gekappt). Rang 1 = höchster Score.
- Trend = Abstand zum 10-Monats-Schnitt (`trend_10m`) für alle sechs Klassen; „auf“ bei > 0.
- Erwartung je Rang = Mittelwert der relativen Rendite (Rendite minus Mittel der vier gerankten Klassen),
  die dieser Rang in allen früheren Monaten erzielte, deren Ergebnis am Prognosetag bekannt war; Band =
  zentrales 90-%-Intervall eines Moving-Block-Bootstraps (Blocklänge 12, 2000 Ziehungen, fester Seed,
  gepaarte Ziehungen über die Ränge). Mindestens 60 Ergebnismonate je Rang, sonst Status `warmup`.
- Status nach Entscheid 4: `signal`, wenn das Band von Rang 1 ganz über dem Band des letzten Rangs liegt.
- Horizonte 1, 3, 6 Monate aus denselben Scores; für Monatsmittel-Klassen (Entscheid 5) beginnt die
  Ergebnisrendite einen Monat später (derzeit ohne Wirkung, weil keine gerankte Klasse ein Monatsmittel ist).

**Verifiziert** (`tests/lookahead/test_forecast_model.py`, 8 Tests; Zahlen aus einem Lauf über alle
Monatsenden 1974-06 bis 2018-12, 535 Monate mit vollständigem Querschnitt):

| Prüfung | Ergebnis |
|---|---|
| Score = Code des Moduls auf demselben Querschnitt | maximale Abweichung **0** (bitidentisch), 0 abweichende Rangfolgen |
| Score = Forschungsformel `src/signals.py::composite_score` | maximale Abweichung **0** über 549 Monate |
| Vergangene Scores aus dem Panel an D = Score am damaligen Datum | maximale Abweichung **0**, 0 abweichende Ränge |
| Prognose an D bei verrauschter Zukunft | an 5 Daten (1979, 1987, 1999, 2008, 2018) bytegleich |
| Prognose an D bei entfernter Zukunft | an denselben 5 Daten bytegleich |
| Definitionen (Folgerendite, Verzögerung für Monatsmittel, relative Rendite, Ränge, Kalibrierung, Bootstrap) | auf kleinen bekannten Eingaben |
| Laufzeit | 3 Horizonte für ein Datum ≈ 0.04 s; 552 Monatsenden 1973–2018 in 21 s |

**Befund, der eine Entscheidung braucht: Der Status nach Entscheid 4 ist fast konstant.** Gezählt über alle
Monatsenden 1973–2018:

| Horizont | `warmup` | `no_clear_signal` | `signal` | Wechsel des Status nach dem Warm-up |
|---|---|---|---|---|
| 1 Monat | 63 | 87 | 402 | 13 |
| 3 Monate | 65 | 18 | 469 | 1 |
| 6 Monate | 68 | 20 | 464 | 1 |

Anteil `signal` beim 1-Monats-Horizont je Fünfjahresfenster: 1979–83 0.83, 1984–88 0.93, 1989–93 0.57,
1994–98 0.37, ab 1999 durchgehend 1.00. Grund: Die Erwartung hängt nur am Rang, nicht an den heutigen
Score-Abständen. Ob die Bänder von Rang 1 und Rang 4 überlappen, ist deshalb eine Aussage über die ganze
bisherige Geschichte des Modells („hatte Rang 1 bisher mehr als Rang 4?“), nicht über den heutigen Monat.
Sobald genug Geschichte da ist, steht der Status fest. Das ist nicht, was „kein klares Signal, wenn sich die
Rangabstände nicht vom Rauschen unterscheiden“ meint. Alternativen in der Antwort an den Auftraggeber;
bis zur Entscheidung bleibt Entscheid 4 unverändert umgesetzt.

**Offen:**

- Status (siehe Befund).
- Konfidenzniveau 90 % und Blocklänge 12 sind gesetzte Parameter, nicht aus Daten gewählt; Alternativen
  68 % / 95 % ändern die Bandbreite, nicht die Erwartung.
- Gewichte als abgeleitete Ausgabe sind als Feld vorhanden, aber noch nicht berechnet (Regel offen).
- UST10 ist aus GS10 gebaut, einem Monatsmittel der Tagesrenditen; seine Monatsrendite ist also teilweise
  gemittelt (ADR 042 hat nur die World-Bank-Reihen markiert). Das gehört zu P5 (Investierbarkeit:
  Vergleich mit IEF/TLT ab 2002).

## P4 Evaluation 1973–2018 (2026-10-26)

Vollständiger Bericht: `output/forecast/EVALUATION.md` (aus `scripts/forecast_evaluation.py`, 26 s, mit CSVs).
Kriterien standen vorher fest (ADR 044 f). Entscheidungen 1973-01 bis 2018-11 (1 M), Ergebnisfenster enden vor
2019-01; der Holdout-Guard (`assert_outside_holdout`) ist Teil des Laufs und des Tests.

**Gebaut:** `rotationlab/forecast/evaluation.py` (reine Funktionen: Rang-IC, Trefferquote, Permutationstest,
Brier/Skill/Reliability, Jahrzehnt- und Klassentabellen, abgeleitete Gewichte); Wahrscheinlichkeiten und
Status im Modell (`probability` in `forecast.yaml`, `rank_frequency` primär, `logistic_score` als Variante);
`tests/unit/test_forecast_evaluation.py` (9 Tests auf Eingaben mit bekannter Antwort, inkl. Holdout-Guard).

### Verifizierte Ergebnisse, 1-Monats-Horizont (548 Monate)

| Kennzahl | Wert | Baseline |
|---|---|---|
| Rang-IC, Mittel je Monat | **+0.098 [+0.051, +0.141]** (90-%-Block-Bootstrap) | zufälliger Rang: p < 0.0005, 95. Perzentil des Null-Mittels +0.039; Vormonatsrang +0.032 [−0.008, +0.069] |
| Trefferquote Rang 1 schlägt Rang 4 | **56.8 %** [53.1 %, 59.9 %] | Zufall 50 % |
| Top-minus-Bottom-Spread p.a. | +11.0 % [+2.7 %, +19.1 %] | – |
| IC je Jahrzehnt | 1973–79 +0.21, 1980er +0.11, 1990er +0.06, 2000er +0.04, 2010–18 +0.11 | 4 von 4 vollständigen Jahrzehnten positiv |

**Urteil nach ADR 044 (f): Prognosevorteil belegt – alle drei Kriterien erfüllt.** Die Größenordnung (IC ≈ 0.1)
entspricht dem, was die Literatur für Cross-Asset-Momentum berichtet; „belegt“ heißt systematisch besser als
Raten, nicht „meistens richtig“ (53.5 % der Monate mit IC > 0).

### Nebenauswertungen

| Prüfung | Ergebnis | Entscheid nach ADR 044 |
|---|---|---|
| Horizont 3 M | IC +0.116 [+0.049, +0.184]; Trefferquote 57.9 %; 2000er ≈ 0 | behalten (Kriterium erfüllt) |
| Horizont 6 M | IC +0.191 [+0.099, +0.270]; Trefferquote 63.4 % | behalten (Kriterium erfüllt) |
| 12-1-Momentum allein | IC +0.108; Δ zum Basismodell +0.012 [−0.018, +0.040] | nicht empfehlen (kein belegter Unterschied) |
| Basismodell + Regime-Tilts | IC +0.094; Δ −0.004 [−0.018, +0.010] | nicht empfehlen |
| Abgeleitet Top-2 + Trendfilter (vor Kosten, Studien-Timing) | Rendite 10.6 % p.a., Sharpe 0.38, MDD −43 %; gegen Equal Weight +2.9 % p.a. [−0.05 %, +6.0 %], gegen 60/40 +2.2 % [−2.8 %, +7.5 %], gegen Buy-and-Hold +0.6 % [−5.0 %, +6.5 %] | nur Einordnung; 60/40 hat den besseren Sharpe (0.50) |

Zu 3 und 6 Monaten: Die Fenster überlappen (Block-Bootstrap mit Block 12 trägt dem Rechnung); je Monat ist der
IC höher, aber die Zahl unabhängiger Beobachtungen entsprechend kleiner. Sie bleiben Nebenauswertung.

### Befund 1: Wahrscheinlichkeiten – Ziel gewechselt (ADR 045), Kalibrierung gut, Skill nicht beweisbar

Erster Lauf (Ziel „schlägt den Durchschnitt“, ADR 044): Brier-Skill gegen 0.5 +0.0007 [−0.0013, +0.0028] – nicht
informativ. Diagnose: Das Ziel wird von der **Schiefe** der Klassen dominiert (Gold +0.85, Silber +1.02: sie
schlagen den Durchschnitt nur in 43 % bzw. 46 % der Monate bei mittlerer relativer Rendite ≈ 0; US-Aktien, Schiefe
−0.68, in 54 %). Deshalb (ADR 045 b, nach Sichtung der Daten, so geführt) Ziel gewechselt auf **„landet in der
oberen Hälfte“** (realisierter Rang 1–2 von 4; Grundraten 45–56 %) und Modelle mit Klassen-Konstanten; Kriterium
strenger: Skill gegen die **Klimatologie je Klasse**. Zweiter Lauf, 488 Monate punkt-in-Zeit:

| Modell | Brier | Skill gegen 0.5 | Skill gegen Klimatologie (Kriterium) |
|---|---|---|---|
| Konstante 0.5 | 0.2500 | – | – |
| Klimatologie je Klasse | 0.2487 | – | – |
| **`logistic_tophalf`** (primär: Score + Konstante je Klasse) | **0.2476** | +0.0024 [−0.0017, +0.0068] | **+0.0011 [−0.0016, +0.0042]** |
| `rank_class` (Klasse × Rang, Beta-Prior) | 0.2486 | +0.0014 | +0.0001 [−0.0014, +0.0019] |
| `rank_frequency` (nur Rang) | 0.2485 | +0.0015 | +0.0002 [−0.0027, +0.0033] |
| `logistic_score` (Score ohne Konstanten) | 0.2479 | +0.0021 | +0.0008 [−0.0027, +0.0046] |

Reliability des primären Modells: vorhergesagt 0.38 → beobachtet 0.41, 0.43 → 0.46, 0.47 → 0.47, 0.52 → 0.51,
0.57 → 0.57, 0.62 → 0.60 (je 200–430 Beobachtungen); nur das dünne Extrem 0.65–0.70 (36 Fälle) ist überzeichnet
(0.47). **Urteil:** Kriterium nicht erfüllt – der Skill gegen die Klimatologie ist positiv, aber das Intervall
enthält die Null. Einordnung: Die Wahrscheinlichkeiten sind gut kalibriert und tragen denselben kleinen Vorteil
wie die Rangfolge; der Brier-Skill eines Vorteils dieser Grösse (Wahrscheinlichkeiten 0.4–0.6) liegt rechnerisch
bei wenigen Tausendsteln und ist mit 488 Monaten nicht von Null zu trennen, während der Rang-IC dieselbe
Information mit t ≈ 3.6 nachweist. Das Produkt gibt die Wahrscheinlichkeit deshalb als kalibrierte Form der
Unsicherheit aus; der **Nachweis des Vorteils bleibt der IC**. Keine weitere Modellsuche (ADR 045).

### Befund 2: Das Modell weiß nicht, wann es verlässlich ist

| Status (primäre Regel, Marge 5 Pp) | Monate | Trefferquote | IC |
|---|---|---|---|
| signal | 288 | 55.6 % | +0.072 |
| no_clear_signal | 200 | 58.0 % | +0.127 |

Mit dem neuen Ziel (ADR 045): „no_clear_signal“ 53 Monate, Trefferquote 64.2 %; „signal“ 435 Monate, 55.6 % –
wieder kein Hinweis, dass der Status Verlässlichkeit anzeigt (53 Monate sind zudem zu wenig). Variante A (Terzil des
heutigen Score-Abstands): 56.6 % / 60.0 % / 53.6 % – nicht monoton. Entscheid (ADR 045 c): Status bleibt
**beschreibend** („alle Wahrscheinlichkeiten innerhalb von 5 Pp um 50 %“) und wird nirgends als Verlässlichkeitsmass
dargestellt.

### Offen

- Die Jahrzehnte 1990–2009 tragen beim 1-M-Horizont wenig (IC +0.06, +0.04); P5 zeigt, dass das Timing von UST10
  (Monatsmittel) daran nicht beteiligt ist.
- Portfolio-Schicht P8: Kriterium (f) ist erfüllt, P8 darf gebaut werden. Die abgeleitete Variante ohne Kosten zeigt
  Rendite über Equal Weight, aber einen schlechteren Sharpe als 60/40 (0.38 gegen 0.50) und einen Drawdown von −43 %.
  Das Vol-Ziel und die Kosten in P8 entscheiden, ob daraus ein brauchbares Portfolio wird; die Erwartung ist nüchtern.

## P5 Investierbarkeit (2026-10-26)

Bericht: `output/forecast/INVESTABILITY.md` (aus `scripts/forecast_investability.py`). Eingabe: Monatsend-Schnitt des
**Live-Stores** (Branch `data`, Yahoo/FRED, Stand 2026-10-26; `scripts/p5_extract_live_monthend.py` →
`data/raw/p5_live_monthend.csv.gz`, 778 Monate, 17 Reihen). Alles bis 2018-12, Holdout unberührt. Trend-Helfer in
`rotationlab/forecast/evaluation.py` (`trend_label`, `trend_table` mit Block-Bootstrap-Intervall), getestet.

### A. UST10: Monatsmittel (GS10) gegen Monatsende (DGS10) – Reihe schlecht, Prognose unverändert

| | Rendite p.a. | Vol p.a. | Autokorrelation (1 M) | Korrelation mit IEF 2002–18 | mit TLT |
|---|---|---|---|---|---|
| UST10 Forschung (GS10-Mittel) | 7.2 % | 7.1 % | **0.31** | **0.70** | 0.68 |
| UST10 Monatsende (DGS10, gleiche Par-Bond-Formel) | 7.3 % | 8.2 % | 0.12 | **0.99** | 0.93 |

Die Forschungsreihe ist als handelbarer Index **untauglich** (Korrelation 0.70 mit IEF, Autokorrelation 0.31 =
Glättungsartefakt gemittelter Reihen); die Monatsend-Variante ist der ETF praktisch (0.99). Für die Prognose spielt
das keine Rolle: mit UST10 aus Monatsend-Renditen IC **+0.099** [+0.051, +0.142] gegen +0.098 (gepaarte Differenz
+0.0015 [−0.015, +0.015]), identische Rangfolge in 90 % der Monate, gleicher Rang 1 in 97 %. **Die Rangfolge
überlebt den Wechsel auf handelbare Treasury-Preise.**

Empfehlung: Langfrist-Evaluation unverändert lassen (Vergleichbarkeit mit den Studien, Ergebnis gleich); im
Live-Universum IEF (ETF, Total Return) verwenden; optional später DGS10-Monatsende als zweite statische Reihe
(Datenschicht-Änderung, ADR nötig).

### B. Energie und Basismetalle: Trend je Preisbasis – Label stabil, Vorteil unbewiesen

Übereinstimmung des 10-Monats-Trendlabels mit dem World-Bank-Index: Energie – CL=F 86 % (212 Monate ab 2001),
USO 77 %, DBC 84 %; Basismetalle – HG=F 85 %, CPER 83 % (77 Monate). Vorwärts-Information des Labels (Mittel auf
minus ab, p.a., 90-%-Block-Bootstrap):

| Basis | Monate | Ziel | auf − ab p.a. |
|---|---|---|---|
| WB_ENERGY (Mittel) | 697 | Mittel(t+2)/Mittel(t+1) (Entscheid 5) | +5.8 % [−8.6 %, +22.7 %] |
| CL=F Monatsende, eigenes Label | 211 | t→t+1 | +17.1 % [−15.7 %, +37.5 %] |
| WB-Label → CL=F-Rendite | 220 | t→t+1 | +2.5 % [−23.3 %, +31.8 %] |
| WB_BASEMETALS (Mittel) | 697 | Mittel(t+2)/Mittel(t+1) | **+11.2 % [+4.1 %, +19.1 %]** |
| HG=F Monatsende, eigenes Label | 211 | t→t+1 | +12.1 % [−12.8 %, +33.7 %] |
| WB-Label → HG=F-Rendite | 220 | t→t+1 | +18.5 % [+0.7 %, +37.5 %] |
| CPER Monatsende | 76 | t→t+1 | +0.7 % [−19.5 %, +30.7 %] |

Energie: Trefferquoten nach „auf“ und „ab“ liegen beide unter 50 % (Schiefe der Energiepreise, 8.9 im
Langfrist-Panel) und nah beieinander; kein Intervall schliesst die Null aus. Basismetalle: auf dem langen
World-Bank-Panel ein belegter Vorteil (+11 % p.a.), auf Kupfer-Futures mit dem World-Bank-Label knapp (+18.5 %,
Intervall gerade über Null), mit dem eigenen Futures-Label nicht. **Urteil:** Der absolute Trend der beiden
Rohstoffklassen ist im Produkt eine **beschreibende** Angabe („über/unter dem 10-Monats-Schnitt“), kein belegter
Prognosevorteil; für Basismetalle gibt es Hinweise, für Energie keine. Der Report muss das so sagen.

### C. Gold, Silber, US-Aktien – Forschungsreihen sind handelbar

Monatsrenditen der Forschungsreihen gegen Futures/ETFs: Gold (LBMA-Monatsende) vs GC=F 0.98, vs GLD 0.98; Silber vs
SI=F 0.96, vs SLV 0.96; US_EQ (French) vs SPY Total Return 0.98 (311 Monate). Vol-Verhältnisse 0.97–1.02. Keine
Einschränkung.

### Entscheid für P6 (Live-Universum)

Gerankt SPY, IEF, GLD, SLV; nur Trend DBC (Energie-Proxy, Übereinstimmung 84 %) und CPER (Basismetall-Proxy,
83 %); Cash BIL. Kalibrierung und Wahrscheinlichkeiten aus der eigenen Historie des Live-Universums (ETF-Daten ab
2006, Yahoo-Historie im Live-Store seit dem ersten daily-Lauf).

### Offen

- Energie-Trend ohne Nachweis: beibehalten als Beschreibung oder streichen (Entscheid des Auftraggebers).
- DGS10-Monatsende als statische Reihe für künftige Langfrist-Läufe (Datenschicht).

## P6 Live-Lauf, Journal, Report (2026-10-26)

**Gebaut:** `rotationlab/forecast/journal.py` (append-only JSON-lines mit Hash-Kette; Prognosen und Abrechnungen;
idempotente Schreibvorgänge), `live.py` (Lauf: Entscheidungsdatum = letztes Monatsende vor dem Lauftag;
Datenvollständigkeits-Guard; Abrechnung; Bilanz), `report.py` (Monatsreport), CLI `rotationlab forecast run|verify`,
Schritt in `daily.yml` nach dem Ingest. Dabei ein Fehler in `complete_months` behoben: Die Funktion verwarf an einem
Nicht-Monatsende immer die letzte Zeile, auch wenn diese ein abgeschlossener Monat war (Monatsreihen); jetzt fällt nur
die Zeile des laufenden Teilmonats (Label = Lauftag). Auf die Evaluation (Views an Monatsenden) hatte das keinen
Einfluss; auf Abrechnungen von Monatsreihen schon.

**Verifiziert** (`tests/unit/test_forecast_journal.py` 7 Tests, `tests/integration/test_forecast_live.py` 5 Tests,
`tests/lookahead/test_forecast_model.py` +1):

| Prüfung | Ergebnis |
|---|---|
| Journal: gleiche Prognose zweimal | zweiter Schreibvorgang ist ein No-op; Zeitstempel beim Schreiben; Rückweg bytegleich mit der Prognose |
| Hash-Kette | jede Zeile verweist auf die vorige; Bearbeiten, Löschen, Vertauschen im Innern und Anhängen einer gefälschten Zeile werden erkannt (`verify` → Exit 3). **Nicht** erkannt (Zweitprüfung unten): eine am Ende gekürzte Datei und eine komplette Neuberechnung – dafür der Anker ausserhalb der Datei |
| Lauf auf dem Forschungspanel (2010) | Lauf am 3. 2. 2010 schreibt 3 Prognosen (1/3/6 M) für 2010-01-31; zweiter Lauf am selben Tag schreibt nichts; am 2. 4. ist die Januar-Prognose abgerechnet; relative Renditen = Forschungspanel; die Prognose im Journal ist bytegleich mit dem Modell an diesem Datum |
| Guard | Store bei 2010-01-20 abgeschnitten: keine Prognose, Grund im Report („not complete“) |
| Abrechnung auf bekannten Zahlen (Toy) | realisierte Ränge, obere Hälfte, Rang-IC, Rang 1 schlägt letzten, Brier, Vormonatsrang-IC, Trend-Treffer exakt |
| CLI | `ingest --provider static` → `forecast run --date 2009-02-02 --universe long_history` → Journal und Report; `verify` 0, nach Manipulation 3 |

**Probelauf auf dem echten Live-Store** (Branch `data`, Stand 2026-10-26, hier lokal geklont; Universum SPY, IEF, GLD,
SLV / DBC, CPER / BIL), Lauftage 3. 8., 1. 9., 1. 10. und zweimal 26. 10. 2026:

| Lauftag | Entscheidung | geschrieben | abgerechnet |
|---|---|---|---|
| 2026-08-03 | 2026-07-31 | 3 | 0 |
| 2026-09-01 | 2026-08-31 | 3 | 1 (Juli: IC −0.80, Rang 1 schlug den letzten nicht, Brier 0.272) |
| 2026-10-01 | 2026-09-30 | 3 | 1 (August: IC +1.00, Rang 1 schlug den letzten, Brier 0.235) |
| 2026-10-26 (zweimal) | 2026-09-30 | 0 | 0 |

Kette intakt (9 Prognosen, 2 Abrechnungen); ein Lauf dauert ≈ 0.1 s nach ≈ 7 s Laden des Stores. Prognose vom
30. 9. 2026 (1 M): SPY 56 %, GLD 51 %, IEF 47 %, SLV 45 % (obere Hälfte); Status `signal`, beschreibend. Diese
Probeläufe sind **nicht** das Live-Journal: das beginnt mit dem ersten Actions-Lauf und zählt erst ab dann als
Out-of-sample (Entscheid 6). Zwei Monate sind keine Bilanz.

**Offen:** erster Actions-Lauf nach dem Upload (`daily.yml` ruft `forecast run` täglich auf; `PHASE` auf 2 gesetzt,
die Portfolio-Schritte bleiben aus).

## Zweitprüfung P2–P6 (2026-10-26, frischer Prüfer ohne Vorgeschichte; ADR 046)

Der Prüfer hat Prognoseobjekt, Modell, Evaluation, Investierbarkeit, Journal und Live-Lauf gegen die Arbeitsregeln
und die vorab fixierten Kriterien gelesen. **Bestätigt** (keine Befunde): kein Look-ahead in Scores, Trend, Outcomes
und Kalibrierung; Block-Bootstrap-Intervalle paarweise und deterministisch; Spearman, Brier-Vorzeichen, Logit-Fit,
Kriterien wie geschrieben, Idempotenz des Laufs. **Befunde** und was daraus wurde:

| Nr | Schwere | Befund | Änderung | Prüfung |
|---|---|---|---|---|
| 1 | hoch | „Manipulationssicher“ war überzeichnet: die Kette erkennt keine Kürzung am Ende (`verify` bleibt grün, wenn die letzten Zeilen fehlen), eine komplette Neuberechnung ist möglich (kein Geheimnis), kein Anker ausserhalb der Datei, `run` prüfte erst **nach** dem Anhängen | Kettenprüfung vor jedem Anhängen (`JournalError`, Exit 3, Store unberührt); `head()` beider Ketten; jeder Lauf druckt `journal head: …` (Actions-Log, Job-Zusammenfassung, Telegram bei neuen Zeilen); `forecast verify --anchor "<Zeile>"`; Grenzen in RUNBOOK, Report-Fusszeile und Modul-Docstring | Test `test_tail_truncation_needs_an_anchor`: ohne Anker grün, mit Anker „tail was cut off“; umgeschriebene Kette mit anderem Kopf: „anchored hash“; `test_a_broken_chain_is_never_extended`. CLI auf dem Live-Probejournal: Kürzung auf 6 Zeilen → ohne Anker Exit 0, mit Anker Exit 3 |
| 2 | mittel | `settle` prüfte `d1a` gegen den **Vereinigungsindex** aller Klassen: ein fehlendes Monatsmittel wurde NaN, der Trend-Treffer stillschweigend weggelassen und die Prognose galt für immer als abgerechnet; der Guard prüfte die Mittelwert-Klassen nur bis Horizontende statt einen Monat weiter | `class_windows(f)`: Fenster je Klasse aus den Parametern **der Prognose** (`averaged`); Vollständigkeits-Guard und NaN-Prüfung je Klasse am Fensterrand; ohne jedes Niveau keine Abrechnung | `test_settlement_waits_for_every_class`: Mittelwert-Klasse hält die Abrechnung bis t+2; Klasse mit Lücke im März trotz April-Wert → Warten statt Verlust. Forschungspanel-Lauf unverändert (Januar 2010 am 2. 4. abgerechnet, beide Trend-Treffer da) |
| 3 | mittel | `EVALUATION.md`: Top-minus-Bottom-Spread für 3/6 M mit ×12 statt ×12/h annualisiert (+0.3033/+0.7114); „p = 0.0000“; Permutationstest setzt unabhängige Monate voraus | ×12/h; p als „< 0.0005 (0 von 2000 Ziehungen)“; Hinweis bei 3/6 M, dass das Block-Bootstrap-Intervall massgeblich ist | neu gerechnet: Spread 1 M +0.1095 [+0.0274, +0.1908] (unverändert), **3 M +0.1011 [+0.0259, +0.1805], 6 M +0.1186 [+0.0382, +0.2004]**; alle übrigen Zahlen bytegleich |
| 4 | mittel | Verspätete Daten (Ankunft > Lag + 5 Tage → Vintage = Ankunftstag) sind in der Sicht an D für immer unsichtbar: die Monatsprognose würde nie geschrieben; Cash (BIL) blockierte den Guard, obwohl ungelesen | Sicht mit getrenntem Wissensdatum `factory.at(D, knowledge=Lauftag)` (Beobachtungen ≤ D, Vintages ≤ Lauftag; Default unverändert); `run` nutzt sie nur, wenn die Sicht an D unvollständig ist, und vermerkt es (`notes`, Output); Cash raus aus dem Guard | Oracle-Test (Hypothesis) `as_of(d, knowledge)` ≡ `as_of_pandas`; `test_late_data_forecast_is_written_once_the_store_knows`: US_EQ-Kurse von Januar 2010 auf Vintage 10. 2. gesetzt → Lauf am 3. 2. schreibt nichts (Grund genannt), Lauf am 12. 2. schreibt 3 Prognosen mit Notiz, bytegleich mit der pünktlichen Prognose (ausser Notiz und Snapshot-Id); die Sicht enthält keine Beobachtung nach D |
| 5 | mittel (Wortlaut) | „Prognosevorteil belegt“ ist **in-sample bezüglich der Modellwahl** (Features und Gewichte aus der Forschung auf demselben Zeitraum); 9 Monate 1973 mit unvollständigem Feature-Satz (Forschungsformel summiert die vorhandenen) | README, EVALUATION und dieses Protokoll sagen es; 12-1-Variante (keine angepassten Gewichte, IC +0.108) als Robustheitsargument; Zählung und Sensitivität im Skript | 3 Monate ohne Score (nie in der Stichprobe), 9 Monate 1973-04…12 mit 1–4 Features; **Sensitivität ohne sie: IC +0.0968 [+0.0519, +0.1395] (n = 539)** – Urteil unverändert |
| 6 | niedrig | `settle` nahm Ziel und Mittelwert-Klassen aus der **heutigen** Konfiguration, nicht aus der Prognose; `Outcome` ohne Ziel | beides aus `f.params`; `Outcome.target` | Toy-Test: Prognose mit `target: beats_mean` wird gegen „schlägt den Durchschnitt“ abgerechnet; Feld im Journal |
| 7 | niedrig | Report: „[90 %]“ ist das Intervall des historischen Rangmittels, kein Vorhersageintervall; fester Satz „Rang-IC ≈ 0.10 seit 1973“ im Live-Report; `types.py`-Docstring beschrieb das alte Ziel | Spaltenkopf „Mittel des Rangs bisher [90-%-KI des Mittels]“ und Lesart; Verweis auf EVALUATION statt Zahl; Docstring | Report-Test grün; Sichtprüfung `2026-09.md` |
| 8 | niedrig | ADR 044 (c) „alles je Jahrzehnt und je Klasse“ war für Brier nicht gerechnet; Testname `test_tampering_is_detected` überzeichnete; Regime-Tilt-Variante nutzt finale FRED-MD-Daten | Brier je Jahrzehnt und je Klasse (primäres Modell, Klimatologie, 0.5) im Skript; Tests umbenannt nach dem, was sie zeigen; Hinweis in ADR 046 (finale Daten helfen dem Tilt eher – konservativ für den Vergleich) | Brier je Jahrzehnt: Modell unter der Klimatologie 1973–79 (0.2305/0.2426), 1980er (0.2457/0.2494), 2000er (0.2579/0.2598), darüber 1990er (0.2423/0.2405) und 2010–18 (0.2476/0.2460) – passt zum Befund „Skill nicht von Null zu trennen“ |

**Probelauf auf dem Live-Store nach den Änderungen** (gleicher Klon, Stand 2026-10-26): identische Prognosen und
Abrechnungen wie oben (Juli IC −0.80, August IC +1.00; 30. 9. 2026: SPY 56 %, GLD 51 %, IEF 47 %, SLV 45 %), jetzt mit
`target` in jeder Abrechnung und dem Kettenkopf im Output; ein Lauf ≈ 0.1 s.

**Verifiziert nach der Einarbeitung:** ruff und mypy strict ohne Befund; Testsuite 326 bestanden, 1 übersprungen, 0 Fehler (`-m "not network and not sweep"`, wie CI; vorher 320 + 1 – sechs neue Tests). Die Evaluation ist mit
dem korrigierten Skript neu erzeugt (`output/forecast/EVALUATION.md`, 81 s).

**Offen (Entscheid des Auftraggebers):** Der Anker lebt im Actions-Log (Aufbewahrung 90 Tage), in der
Job-Zusammenfassung, in Telegram und in der Git-Historie des Branches `data`; wer eine stärkere Garantie will, kopiert
die `journal head`-Zeile gelegentlich an einen eigenen Ort. Ein kryptografischer Schutz (Signatur) wurde bewusst nicht
gebaut (ADR 046).

## Entscheide des Auftraggebers und Optimierung des Vorschritts (2026-10-27)

**Entscheide (ADR 047):** Energie-Trend gestrichen (`forecast.yaml` trend_only: WB_BASEMETALS / CPER); DGS10-Monatsende
als zweite Treasury-Reihe: `static:fred:DGS10_ME` und die Par-Bond-Konstruktion `static:UST10_ME` (Asset `UST10_ME`) aus
dem P5-Extrakt, der laufende Monat des Extrakts verworfen, Extraktskript korrigiert. Kontrolle: Monatsrenditen
`UST10_ME` gegen `UST10` 1973–2018 Korrelation 0.72, Vol 8.2 % / 7.1 %, Autokorrelation 0.12 / 0.31 – wie in P5.

**Optimierung:** Das Journal liest jede Datei je Zustand einmal (Cache über den Inhaltsdigest, nie über mtime; jeder
Aufruf prüft die Bytes neu, eine Fremdänderung ist sofort sichtbar) und parst die Prognosen einmal je Dateistand; die
Registry nimmt Mapping-Parameter in den Feature-Memo-Schlüssel (`_hashable`), nötig für `sleeve_vol_12m`; das
Monatspanel `tr_panel` wird je Sicht und Asset-Tupel einmal gebaut (Memo der Sicht, Kopie an die Aufrufer) – ein
Engine-Lauf über 553 Monate sinkt von 13.1 auf 10.7 s bei bitgleichen Ergebnissen (Goldens, Harness, Sweep grün).
Ein Live-Lauf bleibt ≈ 0.1 s nach dem Laden des Stores (≈ 6 s).

## P8 Portfolio-Schicht (2026-10-27)

**Vorab fixiert (ADR 048, vor dem ersten Lauf):** Regel Top-2 gleichgewichtet, Trendfilter, Vol-Ziel 10 % aus der
12-Monats-Stichproben-Vol des Risikoteils (Floor 5 %), kein Hebel; `next_tradable`; 7.5 bp je Seite inkl. Cash-Bein;
Treasury-Leg `UST10_ME`; Stichprobe 1974-01 bis 2018-12; Baselines Equal Weight, 60/40, Buy-and-Hold durch dieselbe
Engine; Kriterium: Sharpe über Equal Weight **und** 90-%-Intervall der gepaarten Sharpe-Differenz ohne Null;
Sensitivitäten Hebel 1.5 und Forschungsreihe `UST10`.

**Gebaut:** Modul `rotationlab/strategies/forecast_portfolio.py` (Rolle `paper`, neuer Wert von `Role`), Baseline-Modul
`fixed_weights.py`, Feature `sleeve_vol_12m` (Panel-Formel), `configs/strategies/{forecast_portfolio,fixed_weights}.yaml`
mit Golden-Lauf, `scripts/forecast_portfolio.py` → `output/forecast/PORTFOLIO.md` + CSVs, gepaarter Block-Bootstrap der
Sharpe-Differenz (`evaluation.block_rows`, `paired_sharpe_diff`; Blockzeilen reproduzieren `BlockBootstrap.interval`
exakt). Live: `Forecast.weights` (nur 1 M) aus der Regel auf dem Prognose-Universum; `Outcome.portfolio_return`,
`ew_return`, `cash_return`; Report-Spalte und Paper-Bilanz.

**Befund beim Bau (vor dem Urteil behoben):** Der erste Lauf zeigte für Equal Weight und 60/40 die Cash-Kennzahlen
(Vol 1 %, Umsatz 0) und für die Regel eine Sharpe von 0.36 mit mittlerer Risikoquote 0.48. Ursache: `UST10_ME` trug
den Lag `1D` der täglichen FRED-Reihe; an einem Monatsende war ihr Monatsendwert in der Sicht an D unsichtbar, der
Trend NaN, die Klasse ging stets an Cash, und die Baselines blieben im Warm-up. Nach der Hausregel des statischen
Providers (Marktpreise `0D`, ADR 022) sind Monatsendrendite und Index jetzt `0D`; Store lokal neu aufgebaut
(428 051 Zeilen, `UST10_ME` 776 Zeilen, Vintage = Beobachtung). Die Regel selbst war davon nicht betroffen – ohne
die Korrektur wäre das Urteil auf einem Portfolio ohne Anleihen gefallen.

**Verifizierte Ergebnisse** (`output/forecast/PORTFOLIO.md`, 540 Monate 1974-01 bis 2018-12, 55 s):

| Lauf | Rendite p.a. | Vol p.a. | Sharpe ex Cash | Max Drawdown | Umsatz p.a. | Kosten p.a. |
|---|---|---|---|---|---|---|
| Regel (Top-2, Trend, Vol-Ziel 10 %) | 9.19 % | 9.58 % | **0.487** | **−15.9 %** | 2.34 | 0.35 % |
| Equal Weight (4 Klassen) | 8.14 % | 13.38 % | 0.305 | −38.7 % | 0.20 | 0.03 % |
| 60/40 US_EQ/UST10_ME | 9.60 % | 9.84 % | 0.512 | −28.9 % | 0.10 | 0.02 % |
| Buy-and-Hold US_EQ | 10.59 % | 15.08 % | 0.438 | −50.8 % | 0 | 0 |
| Sensitivität: Hebel bis 1.5 | 9.81 % | 10.57 % | 0.505 | −16.7 % | 3.16 | 0.47 % |
| Sensitivität: Forschungsreihe UST10 | 9.20 % | 9.45 % | 0.493 | −17.3 % | 2.23 | 0.33 % |

Gepaarte Differenzen Regel − Baseline (90 %): Equal Weight Δ Rendite +0.54 Pp [−1.69, +3.15] p.a.,
**Δ Sharpe +0.181 [−0.011, +0.395]**; 60/40 Δ Rendite −0.41 Pp [−3.52, +1.89], Δ Sharpe −0.026 [−0.345, +0.193];
Buy-and-Hold Δ Rendite −1.98 Pp [−6.28, +1.14], Δ Sharpe +0.049 [−0.289, +0.273]. Was die Regel tut: mittlere Risikoquote 0.70, 2.6 % der Monate ganz in Cash, in
48 % der Monate skaliert das Vol-Ziel (mittlere Skalierung 0.82), Median der Sleeve-Vol 9.8 %. Je Jahrzehnt liegt die
Sharpe der Regel 1970er–1990er über Equal Weight, 2000er darunter (0.43 gegen 0.56), 2010–18 darüber (0.52 gegen 0.42).

**Urteil nach ADR 048 (e): nicht belegt.** Kriterium 1 erfüllt (0.487 > 0.305), Kriterium 2 nicht – das Intervall
der Sharpe-Differenz enthält die Null knapp. Ehrlich gelesen: die Regel bleibt in jeder Sensitivität bei Sharpe ≈ 0.5
und ist gegen 60/40 nicht besser; ihr kleinerer Drawdown (−16 % gegen −29 % bis −51 %) ist zu einem grossen Teil
das Vol-Ziel (9.6 % Vol gegen 10–15 % der Baselines) und war kein Kriterium. Die Gewichte laufen im Live-Journal als
Paper-Spur mit, im Report als „historisch nicht belegt“ bezeichnet.

**Tests** (`tests/unit/test_forecast_portfolio.py` 8, `tests/lookahead/test_forecast_model.py` +1 „Top-2 der Regel =
Rang 1–2 der Prognose“ an fünf Stichtagen, `tests/golden/test_module_goldens.py` +1 Golden 0.487, Harness-Listen
um Modul und Feature erweitert, Engine-Trunkierungstest und wöchentlicher Sweep um `forecast_portfolio` erweitert,
Live-Tests mit Paper-Rendite): 337 bestanden, 1 übersprungen, 0 Fehler (lokal, `-m "not network and not sweep"` inkl. Goldens); Sweep `forecast_portfolio` (15 Schnitte bis 2018) separat grün; ruff und mypy strict ohne Befund; P4- und P5-Berichte nach dem Store-Neuaufbau bytegleich neu erzeugt.

### Zweitprüfung P8 (2026-10-27, frischer Prüfer)

Kein schwerer Befund: kein Look-ahead in Regel, Baselines, Vol-Ziel und Statistik; das Urteil folgt ADR 048 (e)
wörtlich. Befunde und was daraus wurde:

| Nr | Schwere | Befund | Änderung | Prüfung |
|---|---|---|---|---|
| 1 | mittel | `paper_rule` nahm Feature-Gewichte und Clip aus der Strategie-YAML, nicht aus dem Prognosemodell: bei einer Variante (`--variant mom_12_1`) hätten die Journal-Gewichte der veröffentlichten Rangfolge widersprochen, stillschweigend und append-only | Regel scort mit `model.weights`/`model.clip`; `paper_weights` prüft, dass der Risikoteil in den veröffentlichten Top-2 liegt, sonst Abbruch statt Journal; Cross-Check in `load_bundle`: `forecast_portfolio.yaml` und `forecast.yaml` dürfen nicht auseinanderlaufen (Drift wird beim Laden abgewiesen) | `test_paper_weights_follow_the_published_ranking_also_for_a_variant`; manuelle Negativprobe des Cross-Checks |
| 2 | mittel | ADR 047 (b) nannte Lag `1D`, der Code trägt `0D`; die Änderung nach dem ersten P8-Lauf stand nur im Protokoll | Status-Spalte von ADR 047 ergänzt (Änderung, Grund, Zeitpunkt vor dem Urteil); Prüfer stimmt `0D` zu | – |
| 3 | mittel | „handelbares Timing“ gilt nur halb: GOLD, UST10_ME, TBILL sind Monatsreihen, ihr nächster Preis ist der Monatsendwert; nur US_EQ und SILVER handeln am Folgetag | Satz in PORTFOLIO.md und hier; GOLD bleibt die Forschungsreihe (eine tägliche LBMA-Reihe würde die eingefrorene Prognosedatenbasis ändern) | – |
| 4 | mittel | Die Urteilsstatistik (`block_rows`, `paired_sharpe_diff`) war ungetestet; kein Regressionstest für die Sichtbarkeit des Monatsendwerts; `_load_live_me` ungetestet | Tests: Blockzeilen reproduzieren `BlockBootstrap.interval` (n = 24, 100, 547), Sharpe-Differenz identischer Reihen = 0 mit Intervall [0, 0], Vorzeichen bei Verschiebung, Punktwert = Formel; Store-Test: Monatsendwert und Index an drei Monatsenden sichtbar, Index = Par-Bond-Formel auf den Monatsendrenditen (> 700 Monate), laufender Monat nicht im Store; Provider wirft, wenn mehr als eine Zeile nach dem Extraktstand läge | 13 + 1 Tests grün |
| 5 | mittel | `settle`: fehlte das Cash-Niveau am Fensterende, wurde die Abrechnung trotzdem geschrieben – die Paper-Rendite des Monats wäre für immer verloren | Eine Prognose mit Gewichten wartet auf das Cash-Niveau wie auf jede Klasse; ohne Gewichte bleibt Cash optional (EW-Rendite braucht kein Cash) | `test_settlement_with_weights_waits_for_the_cash_level` |
| 6 | niedrig | Bewertete Rangfolge (UST10_ME) ≠ veröffentlichte (UST10) | PORTFOLIO.md zählt: Top-2 verschieden in **21 von 540** Entscheidungsmonaten; die Sensitivität „Forschungsreihe“ ist die Regel auf der veröffentlichten Rangfolge | im Skript berechnet |
| 7 | niedrig | Erster Entscheid der Stichprobe (1973-12) mit 4 von 5 Features (12-1 braucht 14 Stände) | PORTFOLIO.md nennt es; ohne Januar 1974: Sharpe 0.476 gegen 0.293 – Urteil unverändert | im Skript berechnet |
| 8 | niedrig | „Entscheidungen bis 2018-12-31“ ungenau | „wirksame Entscheidungen 1973-12 bis 2018-11; der Entscheid vom 2018-12-31 wird am nächsten Handelstag gehandelt und nie bewertet“ (Prüfer: die Ausführungssicht liest Kurse vom 2019-01-02, nichts ≥ 2019-01-31; akzeptabel) | – |
| 9 | niedrig | Perzentil-Intervall nicht bias-korrigiert (Bootstrap-Mittel 0.193 vs Punkt 0.181; Basic-Intervall ≈ [−0.03, +0.37]) | Fussnote in PORTFOLIO.md; Urteil identisch | – |
| 10 | niedrig | Tie-Bruch `top_n` (instabiler Sort) ≠ `ranks_of` (method first) | Modul nutzt `top_picks` mit Rang-Methode „first“ wie die Prognose | Golden 0.487 unverändert |
| 11 | niedrig | Expositionsstatistik mit zwei Nennern | eine Menge: die Entscheidungen 1973-12 bis 2018-11, deren Rendite in der Stichprobe liegt | Risikoquote 0.70, 2.6 % ganz Cash, 48 % skaliert |
| 12 | niedrig | Extrakt: Vollständigkeit über alle Reihen hinweg beurteilt (DGS10 kommt einen Tag später); Konstante `LIVE_ME_EXTRACTED` von Hand | Vollständigkeit = Minimum der letzten Beobachtung über die genutzten Reihen; Provider wirft bei mehr als einer verworfenen Zeile | – |
| 13 | niedrig | Unit-Tests leiteten Erwartungen aus der Implementation ab; Trendfilter- und Floor-Tests zeigten nicht, was sie behaupten; Buy-and-Hold auf dem `next_tradable`-Pfad ungetestet | Composite von Hand aus Monatsständen (unabhängig von der Registry); konstruierter Fall, in dem ein Top-2-Pick unter seinem 10-Monats-Schnitt liegt und an Cash geht; Floor- und Hebelkappe getrennt; Buy-and-Hold unter beiden Ausführungspfaden ohne Umsatz nach dem ersten Trade | 10 Unit-Tests grün |
| 14 | niedrig | Urteilszeile 2 missverständlich bei negativem Intervall; Dict-Schlüssel mit Leerzeichen | Text „Differenz positiv und Intervall ohne Null“ mit expliziter Angabe „Intervall mit/ohne Null“; explizite Variablen | – |
| 15 | niedrig | „halbiert den Drawdown“ vergleicht 9.6 % Vol mit 10–15 % Vol | Einschränkung im Urteilstext oben (Drawdown war kein Kriterium) | – |

Bestätigt vom Prüfer: Composite = Prognose-Composite (z-Score ddof 1, normierte Gewichte, fill 0); Sleeve-Vol =
√(w'Σw) mit Stichproben-Kovarianz, annualisiert; Engine-Timing (Mark vor Trade, Kosten im Folgemonat, Equity endet
2018-12-31); Baselines mit identischen Kosten, Timing, Stichprobe und Cash-Reihe; Buy-and-Hold ohne Umsatz nach dem
ersten Trade; Statistik reproduziert (+0.1815 [−0.0110, +0.3946] aus `portfolio_monthly.csv`); `_Chain`-Cache ohne
Staleness-Pfad; `_hashable` korrekt; Rolle `paper` ausserhalb der Budgets; Live-Arithmetik der Paper-Rendite.

**Verifiziert nach der Einarbeitung:** ruff und mypy strict ohne Befund; Testsuite 344 bestanden, 1 übersprungen, 0 Fehler (lokal inkl. Goldens; +7 Tests gegenüber dem P8-Bau); PORTFOLIO.md neu erzeugt (Kennzahlen bitgleich, Golden 0.487 unverändert); Live-Probelauf auf dem Live-Store unverändert (≈ 0.08 s je Lauf).

**Offen:** erster Actions-Lauf; Gesamtpaket.

## Pseudo-Holdout 2019–2025 (2026-10-27, 07:39 – einmaliger Lauf nach Freigabe)

**Vorab (ADR 049):** Modell, Regel, Konfiguration und Code eingefroren zum Stand P8 mit Zweitprüfung; Stichprobe
Entscheidungen 2019-01 bis 2025-11 (1 M), Ergebnisse bis 2025-12; Kennzahlen wie P4 und P8; Lesart: gelungen /
schwach / gescheitert nach dem mittleren 1-M-IC gegen das In-sample-Intervall [+0.051, +0.141]. Skript
`scripts/forecast_holdout.py` (verweigert einen zweiten Lauf ohne `--again`), Bericht `output/forecast/HOLDOUT.md`.

**Ergebnis – Replikation gescheitert.**

| Kennzahl | In-sample 1973–2018 (P4/P8) | Pseudo-Holdout 2019–2025 |
|---|---|---|
| Rang-IC 1 M (90 %) | +0.098 [+0.051, +0.141], 548 Monate | **−0.031 [−0.181, +0.048]**, 83 Monate; IC > 0 in 45 % der Monate; Permutations-p 0.69 |
| Rang 1 schlägt Rang 4 | 56.8 % | **48.2 %** [37.3, 54.2] |
| Vormonatsrang-Baseline (IC) | +0.009 | +0.015 |
| 3 M / 6 M (IC) | +0.116 / +0.191 | −0.027 [−0.232, +0.119] / +0.026 [−0.180, +0.159] |
| Brier-Skill gegen Klimatologie | +0.0011 [−0.0016, +0.0042] | **−0.0030 [−0.0068, −0.0013]** (Modell schlechter als die Grundrate) |
| Regel: Sharpe / Drawdown | 0.487 / −15.9 % | 0.613 / −14.7 % |
| Equal Weight: Sharpe / Drawdown | 0.305 / −38.7 % | **1.028** / −17.5 % (16.3 % p.a.) |
| 60/40, Buy-and-Hold: Sharpe | 0.512, 0.438 | 0.744, 0.884 |
| Δ Sharpe Regel − Equal Weight (90 %) | +0.181 [−0.011, +0.395] | **−0.416 [−0.846, −0.154]** |

Was das heisst, ohne Beschönigung: Die Rangfolge hatte 2019–2025 keinen messbaren Vorteil; das Holdout-Intervall
schliesst sogar das In-sample-Niveau (+0.098) aus. Die kalibrierten Wahrscheinlichkeiten waren in dieser Periode
schlechter als die blosse Grundrate je Klasse. Die Paper-Regel verdiente positiv (8.1 % p.a., Sharpe 0.61) und blieb
in ihrem Drawdown, lag aber klar hinter Equal Weight, weil in einer Periode, in der alle vier Klassen stark stiegen,
jede Kasse- und Vol-Bremse kostete. Zwei Lesarten sind mit den Daten vereinbar und werden beide genannt: (1) der
In-sample-Vorteil war zum Teil Anpassung an die Periode, in der er gefunden wurde (ADR 046 e: in-sample bezüglich
der Modellwahl); (2) 83 Monate mit zwei Regimebrüchen (2020, 2022) sind zu kurz, um einen kleinen Vorteil zu
sehen – das Intervall ist ±0.11 breit. Unterscheiden kann das nur die Live-Bilanz ab November 2026; sie ist jetzt
der einzige ehrliche Test, und sie beginnt ohne Vorschuss.

**Nicht geändert (ADR 049 a):** Modell, Regel, Konfiguration. Geändert wurde nur der Wortlaut: README,
Live-Report und Architektur sagen, dass das Holdout nicht repliziert hat.

**Offen:** erster Actions-Lauf; Gesamtpaket.

## Nachgeholte Prognosen (2026-10-27, ADR 050)

**Anlass:** Der erste Actions-Lauf nach dem Upload schreibt den Entscheid vom 30.9.2026 erst Ende Oktober – korrekt
aus der Sicht am 30.9. berechnet (simuliert auf dem Store von Branch `data`), aber als Out-of-sample-Punkt nicht
glaubwürdig, weil das Ergebnisfenster beim Schreiben grösstenteils vorbei ist.

**Gebaut:** `forecast.yaml backfill_after_days: 7`; `live.backfill_note`, `is_backfill`; `run` versieht verspätet
geschriebene Prognosen mit der Notiz `backfilled: written …, N days after the decision date`; die Bilanz im Report
lässt ihre Abrechnungen weg und nennt die Zahl; der Monatsreport und „Letztes Ergebnis“ kennzeichnen sie. `run` ist
dafür in Lauf und Report-Schreiben (`_write_report`) geteilt.

**Verifiziert:** `test_backfilled_forecasts_are_kept_but_not_counted` (Grenze 7/8 Tage; Lauf 26 Tage nach D markiert,
pünktliche Folgemonate nicht; Abrechnung im Journal, nicht in der Bilanz; Kette intakt); Live-Suite, Journal- und
Vertragstests grün. Paket-Prüfung auf einer frischen Kopie von GitHub `main` + Paket − 4 Altlasten: ruff, mypy, validate, 321 + 25 Tests grün; Tageslauf auf dem Store von Branch `data`: der Entscheid vom 30.9. wird als „nachgeholt (27 Tage)“ geschrieben.

## Optimierungen nach dem Paket (2026-10-27, ADR 051)

- **Anker-Branch:** neuer Workflow-Schritt in `daily.yml` nach dem Commit auf `data`: liest die `journal head`-Zeile des
  Laufs, legt beim ersten Mal den Orphan-Branch `anchors` an (nur `journal-anchors.txt`), hängt die Zeile mit
  UTC-Zeitstempel an, wenn sich der Kopf geändert hat, und pusht. Lokal gegen ein Fake-Remote geprüft: erster Lauf
  erzeugt den Branch mit genau einer Datei, unveränderter Kopf schreibt nichts, geänderter Kopf eine zweite Zeile.
  RUNBOOK zeigt die Prüfung von Hand.
- **`GOLD_D`** (tägliche LBMA-Reihe) als Asset für künftige Runden; nicht in Prognose, Regel oder Baselines.
- **README** benennt den Forschungscode als Referenz der Golden-Tests.
- Nicht gemacht, weil Entscheid des Auftraggebers: neue Forschungsrunde (breiteres Universum, andere Signalfamilien) –
  müsste wieder vorab fixiert werden und würde nur live bewertet.


## Forschungsrunde 2 (2026-10-27, ADR 052/053): drei Standardfamilien auf fünf Klassen – nicht übernommen

**Vorab (ADR 052, geschrieben vor der ersten Zahl; Entscheide des Auftraggebers 16:51/17:10):** Universum US_EQ,
UST10_ME, **UST2_ME** (neu), GOLD, SILVER, Cash TBILL – nur Klassen mit echten Monatsendpreisen; Familien Momentum
(12-1), Carry (laufende Ertragsrendite), Value (−5-Jahres-Rendite), je ein Querschnitts-z-Score, **gleichgewichtet**;
Stichprobe Entscheidungen 1981-07 bis 2018-11 (Panel ab 1976-06); Kriterien wie ADR 044 (f) und ADR 048 (e);
Ablationen berichtet, nicht entscheidend; ein einziger Blick auf 2019–2025 danach (ADR 049 d).

**Gebaut:** zweite Treasury-Reihe `static:fred:DGS2_ME` (+ `DGS3MO_ME` als Datenreihe), Konstruktion `static:UST2_ME`,
Assets `UST2_ME` und `SHY` (Live-Bein); Features `value_rev_60m` und `carry_yield` (Arten `equity_dy`, `dividend_dy`,
`yield`, `zero`, je Klasse über `feature_params.carry_yield.spec`); `configs/forecast_v2.yaml` als zweite
Prognosekonfiguration (`Bundle.forecasts`, `rotationlab forecast run/verify --config forecast_v2`, Journal und Reports
unter `journal/forecast_v2`, `reports/forecast_v2`); Modul `forecast_portfolio_v2` (dieselbe Regel, eigene Id, eigener
Golden); die drei Forschungsskripte nehmen `--config` und schreiben nach `output/<config>/`; Runde 1 mit dem
Standardwert reproduziert ihre Dateien Zahl für Zahl (Diff nur in der Aufrufzeile).

**Ergebnis in-sample 1981–2018 (`output/forecast_v2/EVALUATION.md`, 449 Entscheidungsmonate):**

| Kennzahl | Runde 2 (`mcv` v1) | zum Vergleich Runde 1 (1973–2018) |
|---|---|---|
| Rang-IC 1 M (90 %) | **+0.056 [−0.002, +0.106]**; p = 0.007; IC > 0 in 4 von 4 Jahrzehnten | +0.098 [+0.051, +0.141] |
| Rang 1 schlägt Rang 5 (bzw. 4) | 54.8 % [49.9, 58.8] | 56.8 % |
| Vormonatsrang-Baseline (IC) | +0.017 | +0.009 |
| 3 M / 6 M (IC) | +0.091 [+0.012, +0.151] / +0.130 [+0.017, +0.214] | +0.116 / +0.191 |
| Brier-Skill gegen Klimatologie | −0.0005 [−0.0031, +0.0014] | +0.0011 [−0.0016, +0.0042] |
| Ablationen (IC, berichtet) | Momentum +0.100 [+0.051, +0.144]; Carry +0.084 [+0.027, +0.132]; **Value −0.097 [−0.154, −0.046]**; Momentum+Carry +0.105 (Δ zum Basismodell +0.049 [+0.017, +0.081]); Momentum+Value −0.012; Carry+Value −0.016 | 12-1 allein +0.082 |
| Paper-Regel (ADR 048 e) | Sharpe **0.605** (7.6 % p.a., Vol 6.0 %, Drawdown −9.1 %) gegen Equal Weight 0.330 (−22.0 %), 60/40 0.656, Buy-and-Hold 0.511; Δ Sharpe zu EW **+0.274 [−0.084, +0.556]** | 0.487 gegen 0.305; +0.181 [−0.011, +0.395] |

Urteil nach ADR 044 (f): Kriterium 1 **nicht erfüllt** (Intervall schliesst die Null knapp ein), 2 und 3 erfüllt →
**NEIN**. Urteil nach ADR 048 (e): Sharpe über EW ja, Intervall der Differenz mit Null → **NEIN**.

**Pseudo-Holdout 2019–2025 (`output/forecast_v2/HOLDOUT.md`, ein Lauf 18:48, 83 Monate) – Replikation gescheitert, deutlich:**
Rang-IC 1 M **−0.159 [−0.234, −0.053]**, IC > 0 in 35 % der Monate, Permutations-p 0.998; Rang 1 schlägt Rang 5 in
**33.7 %** [27.7, 41.0]; 3 M −0.222, 6 M −0.371 (beide Intervalle ohne Null, negativ); Vormonatsrang +0.074;
Brier-Skill gegen Klimatologie −0.0003 [−0.0009, +0.0002]. Regel: Sharpe 0.422 (5.2 % p.a., Drawdown −4.1 %) gegen
Equal Weight **1.012** (13.5 % p.a.); Δ Sharpe −0.590 [−1.242, +0.184]. Das Modell setzte `UST10_ME` in 47 von 83
Monaten auf Rang 1 (Trefferquote dort 32 %): Carry (hohe Rendite der Zehnjährigen) und Value (negative Fünfjahresrendite
der Anleihen) zeigten beide in die Zinswende 2022 hinein.

**Lesart, ohne Beschönigung:** Die drei Standardfamilien gleichgewichtet haben auf fünf Klassen in-sample einen
kleineren Vorteil als Runde 1 und verfehlen das vorab fixierte Kriterium knapp; im Holdout kehrt sich die Rangfolge um.
Die Ablationen zeigen, dass Value als Fünfjahres-Umkehr auf Anlageklassen in dieser Stichprobe schadet und
Momentum + Carry in-sample besser wäre – **das ist eine Beobachtung nach dem Lauf und wird nicht benutzt** (ADR 052 e):
ein auf den Ablationen gewähltes Modell wäre genau die Auswahl auf den Daten, die Runde 1 geschwächt hat, und sein
Holdout wurde bewusst nicht gerechnet. Fünf Klassen sind wenig Breite; mit ≈ 450 Monaten lassen sich IC-Niveaus um
+0.05 nicht von Null trennen, und 83 Holdout-Monate mit zwei Regimebrüchen entscheiden ein knappes In-sample-Ergebnis
nicht – nur verwerfen können sie es, und das tun sie hier.

**Offene Fragen (nicht entschieden, nicht ausprobiert):** (1) Carry für Anleihen als Renditeniveau statt Laufzeitprämie
plus Roll-down (Koijen et al.) – im Querschnitt kürzt sich der Geldmarktsatz, der Roll-down fehlt; (2) Value als
Fünfjahres-Umkehr ist eine von mehreren Definitionen (Realzins, CAPE wären die anderen, mit Publikationslag);
(3) ob eine Zeitreihen-Variante (absoluter Trend je Klasse statt Querschnittsrang) die Breite ersetzen kann. Jede
davon wäre eine Runde 3 mit eigener Vorab-Fixierung; keine davon ist durch diese Zahlen belegt.

**Nicht geändert nach dem Holdout (ADR 052 g):** Modell, Regel, Konfiguration von `forecast_v2`; Golden
`forecast_portfolio_v2` gepinnt (0.605 / 7.6 % / −9.1 %, Regressionspin, kein Erfolg). Runde 1 (`forecast`) bleibt
die veröffentlichte Prognose und der Live-Track.

**Verifiziert:** `test_value_reversal_and_carry_yield_formulas` (Toy: Umkehr, implizite Dividendenrendite,
ETF-Dividendenrendite, Rendite/100, Null, Panel = punktweise), Look-ahead-Harness und Mid-Month-Audit mit Carry-Spec auf
allen vier Arten, `test_forecast_portfolio_v2_golden`, `test_second_forecast_config_is_loaded_and_tied_to_its_paper_rule`
(Drift-Check Regel ↔ Prognose), CLI-Lauf mit `--config forecast_v2` (Journal, Report, Top-2-Gewichte der Regel,
`verify --config`); Runde-1-Skripte reproduzieren `output/forecast/` (EVALUATION, PORTFOLIO, alle CSVs) unverändert.

## Allokator-Prüfung (2026-10-27, Auftrag 19:33; `docs/REVIEW_ALLOKATOR.md`)

**Gebaut:** `evaluation.deflated_sharpe` (Bailey/López de Prado 2014; Inverse der Normalverteilung ohne scipy),
Versuchsregister (≈ 30 Varianten, 2 Holdout-Blicke) in `REVIEW_ALLOKATOR.md`, Zeile „Deflated Sharpe“ in beiden
`PORTFOLIO.md` (Überschuss über Cash und aktive Rendite gegen Equal Weight).

**Verifiziert:** `test_deflated_sharpe_follows_bailey_lopez_de_prado` (N = 1 → Hürde 0 und PSR = probabilistische
Sharpe; N = 30 hebt die Hürde nach der Formel √V·[(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))] und senkt die Wahrscheinlichkeit;
V = 0 hebt sie nicht; Φ⁻¹(0.975) = 1.95996). Beide Portfolio-Berichte neu gerechnet: alle Zahlen unverändert
(Runde 1 Diff gegen den eingefrorenen Bericht: nur Aufrufzeile, Reihenfolge der Monatsbeine im Timing-Satz, neue
Deflated-Sharpe-Zeile). Volle lokale Suite 350 Tests grün (ohne `network`/`sweep`), ruff und mypy ohne Befund.

**Ergebnis der Zeile:** Runde 1 aktive Sharpe +0.055 p.a., PSR 0.273; Runde 2 +0.061, PSR 0.302 – keine Auswahl
überlebt die Mehrfachprüfung. Das ist konsistent mit beiden Holdouts.

**Offen (Entscheide des Auftraggebers zu Runde 3, Teil C der Prüfung):** Stufe 1 sofort oder Stufe 2 nach dem
Daten-Zyklus; Hebel auf Sleeve-Ebene; Zuordnung der SPDR-Sektoren auf die French-Industrien. Nichts davon ist umgesetzt;
ADR 054 wird erst nach der Freigabe geschrieben, vor der ersten Zahl.

## Forschungsrunde 3 – Sleeve-Allokator (2026-10-27, ADR 054/055): Signale nicht belegt

> **Erste Fassung – durch die Zweitprüfung korrigiert (ADR 056).** Zahlen und mehrere Aussagen dieses Abschnitts sind
> falsch: Gleichstände in den Zwei-Instrument-Sleeves entschied Rundungsrauschen (korrekt: Sharpe 0.683, nicht 0.704);
> die „+2.2 % p.a.“ waren Hebel; „Trendfilter trägt“, „Querschnitt trägt nichts“ und „Industrie-Momentum belegt“ sind so
> nicht gedeckt; der Deflated Sharpe (0.933) war falsch definiert. Der Text bleibt als Prüfspur stehen; gültig ist der
> Abschnitt „Zweitprüfung von Runde 3“ weiter unten.

**Vorab (ADR 054, vor der ersten Zahl; Entscheide des Auftraggebers 19:33/19:50):** drei Sleeves mit echten Preisen
(10 French-Industrien, UST2_ME/UST10_ME, GOLD_D/SILVER; 14 Instrumente), Querschnitt innerhalb des Sleeves (12-1-
Momentum, in FI zusätzlich Carry; ⌈n/2⌉ ausgewählt), Zeitreihenfilter (12-Monats-Überschussrendite > 0), inverse
EWMA-Vol (Halbwertszeit 12, ≥ 24, Untergrenze 2 %), Risikoparität mit festen Budgets 1/3, Vol-Ziel 10 %, Hebel ≤ 1.5,
kein Sleeve > 1.0, Band 2 Pp, Kosten je Instrument (Annahmen), Walk-forward ohne Holdout-Blick, Kriterien gegen die
signalfreie Risikoparität B1, acht vorab benannte Varianten.

**Gebaut:** Features `vol_ewma`, `basket_vol_ewma` (pandas `ewm(halflife, adjust=True).std()`, annualisiert,
Untergrenze); Modul `sleeve_allocator` (Rolle `paper`; Auswahl, Filter, Korb, Risikoparität, Skalierung, Kappen,
Band im Zustand `extra["targets"]`); `configs/strategies/sleeve_allocator.yaml` (live SPDR/SHY/IEF/GLD/SLV/BIL,
Forschung French/UST/LBMA/TBILL, `golden_run.costs.per_asset`); `scripts/allocator_walkforward.py` (Allokator, B1–B4,
acht Varianten, gepaarte Differenzen, Buch-Kennzahlen, Querschnitt je Sleeve, Perioden, Deflated Sharpe).

**Ergebnis (`output/allocator/WALKFORWARD.md`, 565 Renditemonate 1979-01 bis 2026-01):**

| Lauf | Rendite p.a. | Vol | Sharpe ex Cash | Drawdown | Umsatz p.a. |
|---|---|---|---|---|---|
| Allokator (ADR 054) | 10.9 % | 9.5 % | **0.704** | −14.7 % | 3.6× |
| B1 Risikoparität ohne Signale | 8.7 % | 6.5 % | 0.685 | −13.0 % | 0.3× |
| B2 Equal Weight 14 | 11.7 % | 11.6 % | 0.655 | −34.5 % | 0.2× |
| B3 60/40, B4 Buy-and-Hold US_EQ | 10.3 %, 12.2 % | 9.9 %, 15.0 % | 0.624, 0.569 | −28.9 %, −50.8 % | – |

Gepaarte Differenz zu B1: Rendite **+2.2 % p.a. [+0.4, +3.8]** (ohne Null), Sharpe **+0.020 [−0.170, +0.187]** (mit
Null). Urteil ADR 054 (e): Kriterium 1 ja, Kriterium 2 **nein** → **NEIN**. Deflated Sharpe der aktiven Rendite 0.933
(N = 38; < 0.95). Querschnitt: Industrie-Momentum IC +0.048 [+0.025, +0.077] (571 Monate) – belegt; FI/PM
Trefferquoten 0.513 / 0.524, nicht von 0.5 zu trennen. Varianten: ohne Zeitreihenfilter 0.592; nur Zeitreihe +
Risikoparität 0.715; Hebelgrenze 1.0 0.665; Halbwertszeit 6 0.713; Kosten ×2 0.681; nur EQ 0.611, nur FI 0.387,
nur PM 0.439. Buch: mittlere Bruttoquote 0.97, Hebel in 44 % der Entscheidungen, nie ganz in Cash; Sleeve-Gewichte im
Mittel EQ 0.37, FI 0.46, PM 0.15; FI in 35 %, PM in 44 % der Monate in Cash.

**Lesart, ohne Beschönigung:** Die Breite hat das Bild geschärft, nicht gedreht. Der Trendfilter trägt (ohne ihn
Sharpe 0.59), die Risikoparität trägt (B1 allein 0.685) – beides bekannte Prämien, kein Können der Auswahl. Der
Querschnitt – die Frage, *welches* Instrument – liefert in den Industrien einen kleinen, belegten Rang-Vorteil
(IC +0.05), der in Rendite ankommt (+2.2 % p.a. gegen B1), aber mit mehr Risiko erkauft wird: die Sharpe ist nicht
höher als ohne jede Auswahl. In Treasuries und Metallen mit je zwei Instrumenten gibt es nichts zu messen. Nach drei
vorregistrierten Runden ist das die stabile Antwort des Projekts: *Auswahl zwischen Anlageklassen oder innerhalb
kleiner Sleeves ist auf Monatsfrequenz nicht als Sharpe-Vorteil belegbar; Industrie-Momentum ist der einzige
messbare Querschnittseffekt.*

**Offen, nicht entschieden:** Stufe 2 (Währungen, Länderindizes, weitere Laufzeiten; Daten-Zyklus über Actions) als
einziger verbleibender Hebel (Breite); tägliche Renditen für die EWMA-Vol (Stufe 2); die Variante „nur Zeitreihe +
Risikoparität“ ist eine Beobachtung nach dem Lauf, kein Modell.

**Nicht geändert nach dem Lauf (ADR 054/055):** Modul, Config, Kriterien. Golden `sleeve_allocator` gepinnt (0.705 /
10.9 % / −14.7 %, 565 Monate; Bruttoquote nie über 1.5 geprüft). Kein Live-Lauf (ADR 054 g).

**Verifiziert:** `tests/unit/test_sleeve_allocator.py` (7 Tests: Auswahl ⌈n/2⌉ und Gleichstand, inverse Vol, Konfigurations-
fehler, Regel Schritt für Schritt auf einem Toy – Filter, Korb = Feature `vol_ewma`, gleiches Risiko je Sleeve,
Bruttoquote ≤ 1.5, Zustand –, Band und Kappen, Sleeve ohne investierbares Instrument lässt sein Budget in Cash,
Warm-up, EWMA = pandas und Untergrenze); Look-ahead-Harness und Mid-Month-Audit mit dem Modul und den beiden
Features; `test_sleeve_allocator_golden`; Vertragstest (Paper-Rollen). Laufzeit des Skripts 6 min (14 Engine-Läufe).

**Paket (2026-10-27 spät):** `upload-final.zip` = 142 Dateien gegenüber GitHub `main` (34a464b) − 4 Altlasten; auf
dieser Kopie ruff format/check, mypy, validate, 331 Tests und 27 Golden-Tests grün; Tageslauf-Simulation auf dem Store
von Branch `data` (store verify → forecast run, Entscheid 30.9. „nachgeholt“, Journal `journal/forecast/`) ok.

## Zweitprüfung von Runde 3 (2026-10-27, frischer Prüfer ohne Vorgeschichte; ADR 056)

**Auftrag (21:07):** Schwachstellen des Allokators beheben, Prüferblick auf die letzte Untersuchung, Stufe 2. Ein
unabhängiger Prüfer bekam Code, Konfiguration, ADR 054 und die Kundenentscheide, nicht meine Schlüsse; dazu meine eigene
Prüfung. Alle Befunde des Prüfers sind nachgerechnet; die korrigierten Zahlen stammen aus dem Neulauf
(`scripts/allocator_walkforward.py`, `output/allocator/WALKFORWARD.md`).

| # | Befund (Schwere) | nachgerechnet | Folge |
|---|---|---|---|
| 1 | Gleichstände in FI/PM nach Rundungsrauschen statt Konfigurationsreihenfolge (ADR 054 b); 115 von 181 Monaten (Blocker) | ja: 0.683 statt 0.705 | behoben, alle Läufe neu, Golden neu |
| 2 | Hebel aufs ganze Buch statt aufs Anleihe-Sleeve (Kundenentscheid); B1 nie auf gleichem Risiko; B2–B4 nicht vol-skaliert (Blocker) | ja: Vol 9.4 % gegen 6.5 %; bei gleicher Vol −0.02 % p.a. | Aussage korrigiert; Runde 4: Hebel nur Anleihen |
| 3 | Die Hälfte des Vorsprungs aus Silber 1979–80 (schwer) | ja: ohne 1979–80 Δ −0.092, ab 2000 Δ −0.226 | im Bericht; Runde 4: Teilperioden vorab |
| 4 | Deflated Sharpe: falsche Varianz, Hebel als Können (schwer) | ja: 0.221 statt 0.933 | Residualrendite + Register `docs/TRIALS.yaml` |
| 5 | Kriterium 1 hing an Kostenannahmen; Finanzierung ohne Aufschlag (schwer) | ja: Kosten ×2 beidseitig 0.659/0.682; +50 bp 0.677/0.656 | `CostSpec.borrow_bps`; Runde 4 konservative Kosten + 30 bp |
| 6 | Test zu schwach für den einen gefundenen Effekt (schwer) | ja: SE 0.107, MDE 0.27 | Runde 4: MDE vorab, Sekundärtests je Signal |
| 7 | Ungedeckte Aussagen (Trendfilter, Querschnitt, IC „belegt“) (schwer) | ja | im Bericht korrigiert |
| 8 | Band friert B1 ein, Drift wird trotzdem gehandelt, Abgewählte bleiben (schwer) | ja: B1 ohne Band 0.631 | Runde 4: kein Band, Ausstieg handelt immer |
| 9 | Vol-Ziel nur nominal; Monats-EWMA zu träge (leicht) | ja: realisiert/vorhergesagt 1.13 | Runde 4: Tages-Vol, Korrelation monatlich |
| 10 | Skalierung füllt Cash-Budgets wieder auf (leicht) | – | Runde 4: Vol-Ziel auf dem ungefilterten Buch |
| 11 | Zwei-Instrument-Sleeves können nicht ranken; FI-Carry = Laufzeitwette (leicht) | ja | Runde 4: FI, PM nur Zeitreihe |
| 12 | 13 von 15 Beinen zum Kurs des Entscheidungstags gehandelt (leicht, vermutet) | Timing dokumentiert | Runde 4: Tagesreihen, Folgetag |

**Korrigiertes Ergebnis Runde 3 (565 Renditemonate 1979-01 bis 2026-01):** Allokator Sharpe **0.683** (10.7 % p.a., Vol
9.4 %, Drawdown −14.7 %) gegen B1 **0.685**; Δ Sharpe **−0.002 [−0.188, +0.164]** → Kriterium 1 und 2 nein → **NEIN**.
Industrie-Momentum IC +0.048 [+0.024, +0.077] (565 Monate, nur Fenster): bis 1995 +0.073, ab 1996 +0.034 [+0.008,
+0.074], je Jahrzehnt seit 2000 nicht von Null zu trennen (+0.044, +0.029, −0.000). FI/PM-Trefferquoten 0.513/0.520.
Komponenten (gepaart, alle nicht von Null zu trennen): Trendfilter +0.080 [−0.087, +0.211]; Zeitreihe + Risikoparität
gegen B1 +0.030 [−0.157, +0.175]; Querschnitt −0.032 [−0.134, +0.085]. Deflated Sharpe 0.221 (Runde 1 0.558, Runde 2
0.841 – keine Runde überlebt die Mehrfachprüfung).

**Lesart, korrigiert:** Runde 3 hat keinen Vorteil der Signale gezeigt – aber auch keinen Nachteil, und der Test hätte
einen realistischen Beitrag nicht erkennen können. Die einzige robuste Beobachtung ist das Industrie-Momentum im
Querschnitt, und auch das schwächt sich nach der Veröffentlichung der Originalstudie deutlich ab (wie bei vielen
publizierten Anomalien). Was in der ersten Fassung wie ein Renditevorsprung aussah, war Hebel.

**Verifiziert:** `test_helpers_select_the_top_half_and_normalise_inverse_vol` (Gleichstand nach Konfigurationsreihenfolge, auch bei ±1e-16-Resten);
`test_sleeve_allocator_golden` neu gepinnt (0.6830); `test_cost_model_rates_cash_leg_and_borrow` und `test_book_pays_the_financing_spread_on_leverage`
(Aufschlag nur auf negativen Cash, Standard 0); `test_appraisal_residual_removes_leverage_but_keeps_alpha`; Runde-1/2-
Berichte neu gerechnet – alle Zahlen gleich, nur die Deflated-Sharpe-Zeile neu.

## Runde 4 vorab fixiert (2026-10-27, ADR 057): Stufe 2 und behobene Schwachstellen – Daten ausstehend

**Warum ein eigener Daten-Zyklus:** Die Arbeitsumgebung erreicht FRED und die French-Bibliothek nicht (Proxy verweigert
die Verbindung). Der Workflow `research-data` lädt die Rohdateien einmal in GitHub Actions auf den Branch
`research-data`; `scripts/freeze_research_data.py` friert einen festgelegten Commit prüfsummenkontrolliert ein. ADR 057
ist geschrieben, bevor diese Daten im Projekt sind.

**Gebaut:** `scripts/fetch_research_data.py` + `.github/workflows/research-data.yml` (Rohbytes, Manifest mit SHA-256,
Schlüssel geschwärzt, Pflicht-/Wahlquellen, eigener Branch, berührt den Tageslauf nicht); `scripts/freeze_research_data.py`
(Manifest-Prüfung, kompakte deterministische Dateien, Provenienz; Länderdatei: Parser nach erstem Blick, `--describe`);
`read_french_section` liest auch Tagesblöcke; Features `vol_ewma_d` (EWMA täglicher Renditen, Schwerpunkt 60, veraltet →
leer), `basket_vol_ewma_d`, `book_vol_hybrid` (Sleeve-Vols × EWMA-Korrelation der Monatsrenditen); Modul
`sleeve_allocator_v2` (Modi long_xs/long_ts/long_short_xs, Rang-Gewichte, Verfügbarkeit unabhängig von den Schaltern,
Risikoparität, Vol-Ziel auf ungefiltertem Buch, Filter → Cash, Gruppen-Kappen mit Systemgrenze brutto 2.0, kein Band,
Ausstieg handelt immer, Prüfung auf Tagespreise); Statistik `newey_west_t`, `one_sided_p`, `holm`, `sharpe_ci`,
`long_short_rank_returns`; Versuchsregister mit geplanten 12 Läufen; Auswertungsskript `scripts/allocator_v2_walkforward.py`
(läuft, sobald die Daten eingefroren sind).

**Verifiziert:** `tests/unit/test_research_data.py` (6: Rohbytes byte-gleich, Manifest, Schlüssel geschwärzt, fehlende
Pflichtquelle, mehrseitige FRED-Antwort abgelehnt, Einfrieren deterministisch, ein geändertes Byte stoppt, Tagesblock
der French-Datei); Git-Logik des Workflows gegen ein Fake-Remote (erster Lauf legt den Orphan-Branch nur mit den Daten an,
zweiter hängt an, `main` unberührt); `tests/unit/test_sleeve_allocator_v2.py` (9: Rang-Hilfen, Konfigurationsfehler,
Regel Schritt für Schritt, Filter lässt Anteil in Cash ohne Umskalierung, Baseline sieht dieselben Instrumente, Kappen,
Band, Ausstieg handelt, Gleichstand ohne Rauschen, Tagesprüfung, Warm-up, kein Blick in die Zukunft bei verrauschter
Zukunft); neue Features gegen Handrechnung (Tageskorb-Vol, Hybrid-Buch-Vol) und im Look-ahead-Harness; Statistik-Tests
(Newey-West gegen iid und überlappende Mittel, Holm schrittweise, Sharpe-Intervall, Rang-Portfolio von Hand).

**Offen (Reihenfolge):** Upload; Actions → `research-data`; Commit einfrieren; Parser der Länderdatei nach erstem Blick;
statische Reihen und Konstruktionen (Industrien täglich, Länder, Währungs-Einlagenindizes mit verzögertem Zins,
Par-Bonds täglich); Assets und `configs/strategies/sleeve_allocator_v2.yaml`; Lauf nach ADR 057; Golden; Zweitprüfung.

**Paket (2026-10-27, 22 Uhr):** `upload-final.zip` = 152 Dateien gegenüber GitHub `main` (34a464b) − 4 Altlasten (ersetzt
das Paket von 21 Uhr, das nicht hochgeladen wurde); auf dieser Kopie ruff format/check, mypy, validate, 349 Tests und 27
Golden-Tests grün; Tageslauf-Simulation auf dem Store von Branch `data` (store verify → forecast run → forecast verify,
Entscheid 30.9. „nachgeholt“, Kette intakt) ok. Die Altlast-Formatierung der Forschungsskripte (`ruff format scripts`)
wurde lokal rückgängig gemacht; sie war nie im Paket.

## Runde 4 vor dem Download gehärtet (2026-10-28, ADR 058): Trockenlauf und Zweitprüfung des Designs

**Auftrag (27.10., 23:08):** alles auf dem Niveau eines professionellen Allokators; Frage, ob das Ausrollen auf GitHub erst
am Schluss geht. **Vorgehen:** Solange die Daten nicht im Projekt sind, lässt sich jeder Fehler noch ohne Datenblick
beheben. Deshalb zwei unabhängige Prüfungen vor dem Download: ein frischer Prüfer ohne Vorgeschichte (ADR 057 gegen Code,
Konstruktionen, Statistik) und ein Trockenlauf der ganzen Kette auf synthetischen Daten im exakten Quellformat (echter
Download-Code mit Test-HTTP → Einfrieren → Konstruktion → Store → Registrierung → Walk-forward → Bericht).

**Befunde und Entscheide:** Tabelle in `docs/REVIEW_ALLOKATOR.md` Teil E, Begründungen und Alternativen in ADR 058. Zwei
Fehler hätten das Ergebnis verfälscht: der FX-Carry wäre wegen des Publikationslags nie verfügbar gewesen (der FX-Sleeve
wäre stillschweigend ausgefallen; vom Trockenlauf und vom Prüfer unabhängig gefunden), und die Kappen wirkten nach dem
Trendfilter, sodass Anleihen in frei gewordenen Platz nachrückten (Spielwelt: 2-J.-Gewicht 0.60 → 1.19, nach der Korrektur
0.51 mit und ohne Filter). Die gewichtigste Designschwäche: Das Währungs-Overlay ging in das Vol-Ziel ein, hing aber an
seiner Kappe; dadurch hielt der Allokator mechanisch mehr Anleihen als B1 (Spielwelt Zinsen 0.85 statt 0.71) – der
Hauptvergleich hätte eine Mischungsdifferenz gemessen. Nach der Korrektur: k gleich (0.264/0.264), Zinsen 0.73 gegen 0.71
(Rest aus konzentrierteren Körben, im Bericht ausgewiesen).

**Verifiziert (Tests, alle grün):** 17 neue Tests, zusammen 366 Tests und 27 Golden-Tests auf GitHub `main` + Paket (CI-Simulation: ruff format, ruff check, mypy, validate) – `test_r4_pipeline.py` (Datenprüfung besteht auf konsistenten Daten und stoppt bei vertauschter Notierung, Lokalwährungs-Ländern und falschem Industrie-Abschnitt; die Registrierungsvorlage ist die Regel von ADR 057/058; Fensterende über Datengruppen samt Austritt; Investitionsrendite der T-Bills; die Round-4-Reihen ruhen im Katalog, bis die Länder eingetragen sind, und die Lader bauen sie aus den eingefrorenen Dateien), `test_constructs_r4.py` (veralteter Zins beendet den Index, Lücke beendet den Index, Basis 100, Par-Bond exakt (1 + y/2)^(2t), Zusammenbau und Währungsbeginn 1991), `test_features.py` (Carry eines publizierten Monatszinses mit und ohne Altersgrenze), `test_sleeve_allocator_v2.py` (Kappen vor dem Filter auch bei bindender Anleihe-Kappe; Overlay ändert weder k noch das Long-Buch; Overlay allein; ruhendes Budget bleibt in Cash; Gleichstand wie Runde 3), `test_forecast_evaluation.py` (Holm lehnt NaN ab; Rang-Portfolio ohne Blick auf den Folgemonat; Gleichstand). Die Vektorisierung der Buch-Vol ist auf 40 Zufallsbüchern gleich bis 3e-16. Tageslauf-Simulation auf dem Store von Branch `data` (dddc9f8): validate (63 Assets, 488 Reihen), store verify, forecast run (Entscheid 30.9. „nachgeholt“), forecast verify, zweiter Lauf idempotent.

**Trockenlauf (synthetisch, zählt nicht im Versuchsregister):** Beide Welten liefen durch die ganze Kette (Fenster nach Regel 1977-01 bis 2025-11, 587 Monate; Währungs-Overlay ab 1993, 394 Monate). **Signalwelt** (eingebaute Persistenz): alle drei Signale gefunden – Rang-Portfolio EQ_US t = 21.2, EQ_INTL t = 23.9, FX t = 8.1 (Holm: beide neuen Signale belegt); Δ Sharpe zu B1 +1.79 [+1.60, +2.05]. **Nullwelt** (keine Persistenz): die Querschnittsignale korrekt nicht belegt (t = 0.83 / −0.35 / 0.41, IC um null). Der Allokator lag trotzdem +0.26 [+0.10, +0.44] über B1 – geprüft statt hingenommen: Der Vorteil stammt fast ganz aus 1977–1989 (Sharpe +0.32 gegen B1 −0.28), als der *echte* Cash-Satz (8.8 % p.a.) über der festen Drift der *synthetischen* Anlagen lag; der Trendfilter sass dann in Cash (Filtergewinn +9.5 % p.a. bei Cash über 8 %, −1.2 % sonst). 2008–2025 liegt der Allokator wie erwartet knapp unter B1 (1.21 gegen 1.26). Also ein Artefakt der Testwelt (synthetische Renditen ohne Zinsbezug gegen echten Cash), kein Leck – das bestätigen auch die Querschnittstests und der Look-ahead-Test des Moduls. Die Lehre für die echte Auswertung ist ernst: Der Filter verdient, wenn Cash hoch gegenüber den Anlagerenditen ist (1979–1985); genau dafür sind die Teilperioden und der Ausweis ohne das stärkste Jahr vorab festgelegt. Ein erster Trockenlauf mit dem alten Code hatte den Carry-Fehler (a) bestätigt; die Datenprüfung stoppt auf den synthetischen Daten wie verlangt (G2–G5 verfehlt, weil die Vergleichsreihen echt sind). Der Berichtsteil lief zusätzlich auf einem kurzen Fenster (2008–2025) durch und fand zwei Schwächen, die den echten Lauf erst am Ende getroffen hätten: eine Teilperiode ohne Monate brach die Bootstrap-Rechnung ab, und Monate mit ganz in Cash liegendem Buch machten die Vol-Kalibrierung unbestimmt (Division durch null) – beide behoben; ausserdem zeigt der Bericht die Mischung jetzt vor und nach dem Filter (kurzes Nullfenster: Allokator vor Filter physisch 0.87 / Zinsen 0.63, B1 0.90 / 0.60; Urteil dort NEIN, Δ −0.06, wie in einer Welt ohne Signal und ohne Zinsartefakt zu erwarten).

**Erledigt am 28.10.:** Upload über Pull Request #3 (Zugriff über die Claude-GitHub-App), `daily` schreibt die erste
Live-Prognose (Entscheid 30.9. „nachgeholt“, Anker auf `anchors`), `research-data` liefert die Rohdaten – Fortsetzung unten.

## Runde 4 gerechnet (2026-10-28, ADR 059/060): Hauptkriterium erfüllt, Mehrwert ist der Trendfilter

**Daten.** Der erste `research-data`-Lauf (16:04 UTC) holte 34 von 35 Dateien; die Pflichtreihe DEXGEUS (D-Mark täglich,
1971–2001) antwortete mit HTTP 400 – FRED führt sie nicht mehr. Notfallregel ADR 057 (h): kein Lauf, neuer ADR. **ADR 059**
(Entscheid von Nima um 17:10 MEZ, vor jedem Datenblick): DEXGEUS optional, der Euro tritt ohne Verkettung am ersten Euro-Kurs
(1999-01-04) ein – Eintritt nach Datenverfügbarkeit wie bei jedem Instrument; der FX-Sleeve läuft ab 1991 mit acht Währungen.
Zweiter Lauf (16:34 UTC, PR #4 vorher gemerged): Branch `research-data@5e175d2`, Werte Byte für Byte gleich wie im ersten
Lauf (nur FRED-Zeitstempel anders), eingefroren nach `data/raw/` mit `r4_PROVENANCE.json`. Länderdatei: 21 Länder
(`<Country>.Dat`, erster Block „Value-Weight Dollar Returns, All 4 Data Items Not Reqd“, Spalte `Mkt`), 1975-01 bis
2025-12, kein US; Malaysia nur 1994–2001 (Austritt nach Daten, wie vorgesehen). Parser mit Test. Abgleich mit den Jahrestabellen derselben Datei (957 Länder-Jahre mit 12 Monaten): aus den Monaten
aufgezinst gegen die Jahreszahl Korrelation 0.9992, mediane Abweichung 0.03 Pp (seit 2008 0.007 Pp), 90 % unter 0.63 Pp,
Maximum 19.9 Pp (Singapur 1993), 5 Jahre mit anderem Vorzeichen (alle nahe null) – French bildet die Jahresportfolios mit
Jahresgewichten, die Monatsrenditen mit Monatsgewichten; keine exakte Abstimmung zu erwarten. Den Dollar-Bezug prüft G5. Datenprüfung G1–G6 bestanden (`output/allocator_v2/DATA.md`): Industrien täglich = Monatsdatei (Korrelation
≥ 0.9998, Abweichung ≤ 0.02 Pp), Par-Bonds täglich ~ Monatsende (0.9999/0.9995), Notierungen richtig (Korrelation mit dem
Dollar-Index −0.54 bis −0.90), Länder in USD (Median +0.52), Breite (neun Währungen ab 1991, 21 Länder).

**Registrierung.** `R4_COUNTRIES` = die 21 Länder in Dateireihenfolge; Platzhalter-Registrierung, Ingest (106 Assets, 540
Reihen), erster Lauf bricht mit dem Fenster nach Regel ab: **1977-01 bis 2025-11** (587 Monate; Beginn: erste Entscheidung
mit allen Long-Sleeves 1976-12; Ende: US-Markt-Reihe für B3/B4 endet 2025-12-19). Registrierung mit dem Fenster = Vorlage.
Der Walk-forward lief 31 Minuten. Nach dem Lauf wurde nichts geändert (ADR 057 j); die Golden-Werte wurden gepinnt.

**Verifiziert (`output/allocator_v2/WALKFORWARD.md`):**
- Allokator: 10.8 % p.a., Vol 8.0 %, Sharpe ex Cash **0.791**, Max Drawdown −13.1 %, Umsatz 3.2 p.a., Kosten 0.40 % p.a.
  B1 passive Risikoparität: 9.1 %, Vol 9.4 %, Sharpe **0.506**, Drawdown −20.9 %.
- Gepaarte Sharpe-Differenz zu B1 **+0.285 [+0.140, +0.430]** (90-%-Block-Bootstrap) → beide Primärkriterien **ja**.
  Gegen B2/B3/B4 (ex post auf gleiche Vol): +0.18 [−0.02, +0.34], +0.23 [−0.01, +0.42], +0.27 [+0.01, +0.47].
- Sekundär (Rang-Portfolios, Newey-West 12 Lags, Holm 10 % über die neuen Signale): EQ_INTL 2.3 % p.a., t = 2.26, p Holm
  0.024 **belegt**; FX 1.1 % p.a. (394 Monate), t = 1.74, p Holm 0.041 **belegt**; EQ_US t = 2.28 (Replikation Runde 3).
- Berichtet: Teilperioden Δ Sharpe +0.41 [+0.11, +0.72] (1977–89), +0.38 [+0.17, +0.60] (1990–2007), **+0.08 [−0.18,
  +0.28] (2008–2025)**; ohne 2013 +0.26 [+0.11, +0.40]. Vol-Kalibrierung 1.26 / 1.01 / 0.95. Kappen bindend: Zinsen 91 %
  (B1 gleich), Overlay 67 %, physisch 13 %. Deflated Sharpe (N = 70): +0.65 p.a. gegen Hürde +0.46, Wahrscheinlichkeit **0.895** (< 0.95; kein p-Wert).
- Varianten: ohne Zeitreihenfilter 0.552; **ohne Querschnitt (B1 + Filter) 0.792**; ohne FX 0.788; Kosten ×2 0.735;
  Entscheidungskurs 0.803; Vol monatlich 0.778; einzelne Sleeves 0.58 / 0.55 / 0.42 / 0.22 / 0.48.
- Reproduktion: `rotationlab golden --strategy sleeve_allocator_v2` 0.7911 / 0.1083 / −0.1309 exakt;
  `test_sleeve_allocator_v2_golden` (587 Monate, Long-Buch ≤ 1.5, Overlay ≤ 0.5). Register: 12 Läufe gespeichert,
  N = 70 unverändert; DSR aus den gespeicherten Reihen nachgerechnet (Hürde +0.460, Wahrscheinlichkeit 0.895 identisch; ohne den
  Schutz gegen Doppelzählung wäre sie 0.925 gewesen). Tests: 367 Haupttests, 28 Golden, ruff, mypy grün.

**Deutung (ADR 060).** Das vorab festgelegte Kriterium ist erfüllt; es misst den Allokator gegen die passive
Risikoparität. Die vorab benannte Ablation sagt, woher der Vorteil kommt: Risikoparität + Trendfilter ohne jede
Querschnittsauswahl erreicht denselben Sharpe (0.792 gegen 0.791). Die Querschnittssignale sind als Rang-Portfolios je für
sich messbar (2.3 % bzw. 1.1 % p.a. vor Kosten), tragen aber im Buch nach Vol-Ziel, Kappen und Kosten nichts Messbares bei.
Der Filtervorteil stammt aus 1977–2007 und ist seit 2008 nicht belegt – genau das Muster, das der Trockenlauf (Nullwelt)
als Risiko benannt hatte (Filter verdient, wenn Cash hoch gegenüber den Anlagerenditen ist). Deflated Sharpe unter der
Hürde. B1 ist allerdings die schwächste der vier Baselines (Sharpe 0.506 gegen Buy-and-Hold 0.524, 60/40 0.563, Equal Weight 0.614); gegen B2–B4 enthält das Intervall die Null oder streift sie, und seit 2008 liegt der Allokator (0.594) unter Equal Weight (0.719) und 60/40 (0.720) – Punktschätzer, nachgerechnet in der Projekt-Rückschau vom 28.10. Entscheid: kein Live-Betrieb von v2; die Live-Prognose von Runde 1 bleibt der einzige Live-Track. Ein Trendfilter auf
Risikoparität ist ein bekanntes Ergebnis der Literatur, kein neues dieses Projekts.

**Zweitprüfung (frischer Prüfer, `docs/REVIEW_ALLOKATOR.md` Teil F):** kein Blocker, kein Leck, alle Zahlen bis 1e-14 reproduziert, Rang-Portfolios aus Rohdaten bit-genau nachgebaut. Gewichtig: das JA ist ein Trendfilter-Ergebnis (Allokator − „ohne Querschnitt“ −0.001 [−0.069, +0.060], präziser Nullbefund), die neuen Signale sind seit 2008 flach, Regimekonzentration auf Zinswende-Jahre. Umgesetzt: SE/MDE immer im Bericht (0.088 / 0.22), Abschnitt „Nach der Zweitprüfung ergänzt“ mit beiden Differenzen und den Rang-Portfolios je Teilperiode (nicht vorregistriert, ändert kein Urteil), Register nach `round/name`, Zeitzone in ADR 059, Wortlaut ADR 057 (c) in ADR 060 klargestellt. Der Walk-forward wurde dafür ein zweites Mal gerechnet; alle Ergebnisdateien sind Byte für Byte gleich, im Bericht kamen nur die neuen Zeilen dazu.
