# Phase 1 – Datenschicht: Abnahme

Stand 2026-10-24 (nach der Optimierung). Die Datenschicht beantwortet für jeden Tag D, was damals bekannt
war, und liefert es den oberen Schichten über `MarketView`. Alle Abnahmekriterien aus `ARCHITECTURE.md` §12
sind erfüllt; 183 Tests grün mit echtem pytest, Abdeckung 97 % (`core/` und `data/view.py` 100 %), ruff und
mypy strict ohne Befund (4 Netzwerktests und der Replay-Test echter Antworten laufen in CI). Der Golden-Wert
des Aktien-Exposure-Moduls (Sharpe 0.573, Rendite 9.9 % p.a., Max DD −41.1 %) lässt sich allein aus dem Store
reproduzieren.

## Abnahmekriterien

| Kriterium (§12) | Nachweis |
|---|---|
| `ingest --full` | `rotationlab ingest --full --provider static`: 185 Reihen, 285 655 Zeilen, 7 s, `store verify` ok; zweiter Lauf erkennt unveränderte Rohdaten und überspringt sie (`test_cli.py`) |
| `view.at("2008-06-30").series("CPIAUCSL")` liefert den damaligen Wert | `test_ingest.py::test_acceptance_cpi_as_known_on_2008_06_30`: Erstveröffentlichung vom 15.06.2008, nicht der revidierte Wert; vor dem 15.06. ist Mai unbekannt; Jahresrevision am 20.02. wird genau an diesem Tag sichtbar. Gegen echte Daten: `test_network.py` vergleicht mit FREDs eigener Echtzeitabfrage (`realtime_start = realtime_end = 2008-06-30`) |
| Harness gegen Dummy-Feature | `tests/lookahead/test_view_lookahead.py`: Momentum, Makro-Zustand und CAPE-ähnliches Feature an 21 Stichtagen (8 Krisenmonate) unverändert, wenn alles Unbekannte durch Rauschen ersetzt wird; auch Revisionen nach D (ALFRED) sind Rauschen; ein absichtlich lecken­des Feature wird erkannt |
| Checks mit ±-Fällen | `tests/unit/test_quality.py`: 20 Tests, jeder Check mit bestandenem und verletztem Fall |
| Kalender | 0 Abweichungen gegen 55 Jahre S&P-500-Sitzungen (1971–2025) |

Zusätzlich: Store reproduziert `assets_monthly.csv` (alle 24 Spalten), die Rohspalten von `macro_monthly.csv`
und deren Sichtbarkeit nach den Studien-Lags an 40 Zufallsdaten, die French-Daten der Aktienstudie
(`tests/golden/test_store_parity.py`); inkrementeller ALFRED-Ingest über fünf Termine ergibt an jedem
Stichtag dieselben Werte wie ein einziger voller Ingest; Kompaktierung ändert keine as-of-Antwort.

## Gebaut

| Datei | Inhalt |
|---|---|
| `data/lags.py` | Lags in Tagen oder Monaten, skalar und vektorisiert |
| `data/catalog.py`, `configs/series.yaml` | 341 Reihen aus drei Quellen, Querprüfungen in `validate` |
| `data/store.py` | Append-only-Log, Manifest mit SHA-256, Diff-Regeln (neu, Revision, verspätet), Quarantäne, Logs, Kompaktierung, Verifikation |
| `data/pit.py` | Intervall-Index: as-of in O(log n) |
| `data/view.py` | `StoreView`/`StoreViewFactory`: Serien, Panels, Rollen, Ketten mit Herkunft, Total Return aus vier Quellenarten, Guards |
| `data/quality.py` | Schema, Aktualität, Lücken, Ausreisser, Revision/Split, Quellenabgleich, TR vs. Preis |
| `data/ingest.py` | Orchestrierung, Inkrement-Fenster, Split-Erweiterung, ein Delta je Lauf |
| `data/calendar.py`, `core/clock.py` | NYSE-Kalender; Entscheidung am Kalender-Monatsende, Ausführung nächste Sitzung |
| `data/providers/` | `static` (Port von `build_dataset.py`), `yahoo`, `stooq`, `fred` (ALFRED), `french`, `cftc`, `http` |
| `cli.py` | `ingest`, `store status|verify|compact|quality`, `asof`, `calendar` |

Leistung: Store laden und indexieren 0.7 s; 612 Monatsenden × 6 Assets + 1 Makroreihe in 4.9 s.

## Abweichungen von der Architektur (alle mit ADR)

- Store als gzip-CSV-Log statt Parquet + DuckDB (ADR 020). DuckDB bleibt als optionales Analysewerkzeug.
- Lags pro Reihe in `configs/series.yaml`, Monatseinheit für Monatsstatistiken (ADR 021).
- Entscheidungsdatum = Kalender-Monatsende statt letzter Handelstag (ADR 021).
- Vintage-Prinzip korrigiert zwei Entwurfsfehler: French-Renditen `0D` statt +35 Tage, Shiller-Gewinne `6M` statt +120 Tage (ADR 022).
- Eigener NYSE-Kalender statt `exchange_calendars`; `yfinance` und `requests` entfallen (ADR 023, 027).
- Neu: Serienketten mit Herkunft (ADR 024), Quarantäne (ADR 025), Datierung verspäteter Werte auf ihre Ankunft, Split-Erweiterung (ADR 026).

## Datenbefunde

- VIX-Spiegel: 4 fehlende Sitzungen, 34 Werte an NYSE-Feiertagen (CBOE-Feiertagsberechnung seit 2022).
- S&P-Total-Return-Rekonstruktion: 110 Tage vor 1990 mit TR-Rendite unter der Preisrendite (max. −0.26 %).
- Shiller-Spiegel füllt fehlende Monate mit 0 (Gewinne/Dividenden ab 2023-07, CPI/Zins ab 2023-10) → als fehlend behandelt.
- Die Golden-Kennzahl 0.099 des Aktien-Exposure-Moduls ist die Jahresrendite, nicht die Volatilität (12.1 %); im Projektstatus war sie falsch beschriftet.

## Grenzen

Die Bauumgebung erreicht weder Yahoo, Stooq, FRED, French noch CFTC. Die Provider sind gegen nachgebaute
Antworten im dokumentierten Format getestet (`tests/fixtures/fakes.py`); die echten Formate prüft
`pytest -m network` beim ersten Lauf in GitHub Actions (wöchentlich, `network.yml`). Unsicher sind vor allem:
CFTC-Feldnamen der Socrata-API, Stooqs Adjustierungsbasis, ob FRED Echtzeitperioden bei inkrementellen
Abfragen auf den Start kappt (die Regel „nur Perioden, die danach beginnen“ ist für beide Fälle korrekt).

## Optimierung (zweiter Durchgang, 24.10.2026)

| Bereich | Ergebnis |
|---|---|
| Prüfwerkzeuge | pytest, Hypothesis, coverage, mypy 1.15 aus GitHub-Quellen, ruff als Release-Binary (PyPI gesperrt); Warnungen sind in Tests Fehler. ruff und mypy strict ohne Befund; Abdeckung 92 % → 97 % |
| Eigenschaftstests | 7 Hypothesis-Eigenschaften (Intervall-Index = Referenzabfrage, Idempotenz, unveränderliche Vergangenheit, Kompaktierung, Periodenlabels, Lags, Ketten), je 500 Beispiele einmal geprüft. Hypothesis fand selbst die einzige Ausnahme: die Erstladung einer Reihe gilt als Historie (ADR 026) |
| Echtzeit-Makrodaten | drei echte FRED-MD-Vintages (2019-09, 2021-04, 2026-10) als `static:fredmd_rt:*`; Revisionsstudie `output/revisions/REPORT.md`: am Rand stimmen die Studien-Regime nur zu 83–88 % (gesamt 98–99 %), Jahresrate der Industrieproduktion um 0.9–1.1 Pkt revidiert; Download des ganzen Archivs vorbereitet |
| Zweite Quellen | BLS für CPI, Kern-CPI, Arbeitslosenquote, Beschäftigung; Shiller live für Gewinne/CAPE; virtuelle Makroketten `macro:*` mit Herkunft |
| Beobachtung | Check auf Revisionshäufung; `store health` (Verlauf je Provider und Check) |
| Echte Antworten | `record-fixtures` zeichnet auf, `test_recorded.py` spielt ab; wöchentlicher Workflow |
| Leistung | Präfix-Caches, bitidentisch zum Referenzpfad: 612 Monatsenden in 2.1 s statt 4.9 s |
| Betrieb | Logs erweitern ihr Schema ohne Bruch; `daily.yml` mit Phasenschalter und robustem Zustands-Commit |

## Fable-Review der Vintage-Logik – durchgeführt 24.10.2026

Ergebnis in `AUDIT_phase1_vintage.md`: 11 Punkte geprüft, 4 Korrekturen (Rückfüllung nur vor Archivbeginn, Split-Lauf datiert
auch neue Zeilen auf heute, Kettenanker am gemeinsamen Handelstag, HWI/HWIURATIO `2M`), 3 dokumentierte Restrisiken,
restliche Punkte bestätigt (ADR 034). Danach 183 Tests grün, Store neu aufgebaut, Goldens unverändert.

## Prüfliste des Reviews

1. **ALFRED inkrementell** (`fred.py::alfred_frame`, `ingest.py::_since`): Clip = letzter Abruf − 7 Tage, nur Perioden mit Start > Clip. Geht eine echte Vintage verloren, wenn ein Lauf ausfällt oder FRED eine Veröffentlichung rückdatiert?
2. **Rückfüllung vor Archivbeginn**: ältester archivierter Wert am Lag-Datum. Wie gross ist der Unterschied zum echten Erstwert (Benchmark-Revisionen), und reicht der Hinweis als Restrisiko?
3. **Klemmen** von Veröffentlichungen innerhalb der eigenen Periode auf das Periodenende (Michigan): Verliert ein Monatsend-Entscheid dadurch Information, oder gewinnt er welche?
4. **Verspätete Ankunft** (`store.py::diff`): Toleranz 5 Tage nach Lag; Erstladung behält Lag-Vintages. Reicht das für lange Wochenenden, CFTC-Shutdowns, einen ausgefallenen Cron?
5. **Lag-Tabelle FRED-MD** (`static.py`): Gruppen `0D`/`1M`/`2M`/`6M` – vollständig und konservativ genug?
6. **Vintage-Prinzip** `0D` für Marktpreis-Derivate (French, World-Bank-Mittel, Monatsmittel von Zinsen): konsistent mit „Live ist ein Backtest, dessen Uhr auf heute steht“, wenn live andere Quellen (ETFs) die Information liefern?
7. **Splits**: Erweiterung auf volle Historie bei Split im Fenster und bei gleichförmiger Reskalierung; Dividendenbasis nach Split.
8. **Monatslabels** `min(Monatsende, D)` und Teilmonate in der täglichen Risikoschleife (Phase 3).
9. **Revisionen** `max(Lauftag, Lag)` und Überschreiben desselben Schlüssels vor seiner Sichtbarkeit.
10. **Ketten**: Verhältnis-Spleiss am Übergang mit Wert „letzter ≤ Übergang“, wenn das exakte Datum fehlt; Makroketten füllen keine Lücken im Inneren der primären Reihe.
11. **Echtzeit-FRED-MD**: Vintage-Datum = Monatsende + 7 Tage für Archivdateien; Datierung der drei vorhandenen Dateien in `vintages.yaml` (2019-09 aus dem Inhalt erschlossen).
