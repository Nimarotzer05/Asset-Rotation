# Runbook (Datenbetrieb ab Phase 1, Backtests ab Phase 2, Monatsprognose ab P6)

## Täglich (automatisch)
`daily.yml` 06:30 UTC Mo–Fr: validate → store verify → ingest → **forecast run** → Commit von `data/store`, `journal`, `reports` nach `data`. Die Portfolio-Schritte (live, scenarios, relationships, report) bleiben aus (ADR 043).

## Datenschicht (Phase 1)

**Erstinstallation** (einmal, lokal oder per `workflow_dispatch`):
```bash
uv sync
export FRED_API_KEY=…                                   # kostenlos: fred.stlouisfed.org/docs/api/api_key.html
export BLS_API_KEY=…                                    # optional, höheres Kontingent der BLS-API
rotationlab validate                                     # 53 Assets · 341 Reihen
rotationlab ingest --full --provider static              # Forschungshistorie, 426 498 Zeilen, ~11 s
rotationlab ingest --full                                # Yahoo, Stooq, FRED/ALFRED, French, CFTC
rotationlab store verify && rotationlab store status
```
Ohne `FRED_API_KEY` werden die ALFRED-Reihen übersprungen (Warnung), nie mit dem Lag-Modell gefüllt.

**Täglich** läuft `rotationlab ingest` inkrementell. Exit 3 heisst: mindestens ein blocking Ergebnis.

| Meldung (`rotationlab store quality`) | Bedeutung | Was tun |
|---|---|---|
| `staleness … sessions behind` (blocking) | Schlusskurs einer handelbaren Anlage veraltet | Provider-Status prüfen; `rotationlab asof --asset SPY --role close --date <heute>` zeigt, ob Stooq überbrückt (Herkunft); keine Entscheidung bis grün |
| `schema … rejected … quarantine` (blocking) | Provider lieferte unmögliche Werte | `data/store/quarantine/` ansehen; die Zeilen sind nicht im Store; nächster Lauf holt erneut |
| `fetch` (warn) | Abruf fehlgeschlagen | nur relevant, wenn daraus Staleness wird |
| `revision … silent revision(s)` (warn) | gespeicherter Preis geändert > 0.5 % | beide Vintages bleiben; bei Häufung Provider prüfen |
| `revision … rescaled uniformly` (ok) | Split/Adjustierung, volle Historie neu geholt | nichts |
| `late_arrival` (warn) | Wert kam > 5 Tage nach seinem Lag | auf Ankunftstag datiert; nichts tun |
| `cross_source` (warn) | Yahoo und Stooq widersprechen sich > 1 % | Kurs des Tages manuell prüfen |
| `outliers` (warn) | Tagesrendite > 8 σ | echtes Ereignis oder Datenfehler? beide bleiben |
| `provider: no FRED_API_KEY` (warn) | Secret fehlt | Secret in GitHub setzen |

**Was war am Tag D bekannt?** `rotationlab asof --date 2008-06-30 --series fred:CPIAUCSL` (mit Vintage je Wert); Makroketten: `rotationlab asof --date … --series macro:CPI` (Herkunft FRED oder BLS).

**Verlauf statt Momentaufnahme:** `rotationlab store health --days 30 --out reports/data_health.md`. Steigen Abruffehler, Verspätungen oder Revisionen eines Providers über Wochen, ist das der Moment, die Ersatzquelle zur primären zu machen (Reihenfolge der Kette in `universe.yaml`/`series.yaml`).

| weitere Meldung | Bedeutung | Was tun |
|---|---|---|
| `revision_cluster` (warn) | ≥ 5 kleine Revisionen in 7 Tagen | Provider prüfen; `store health` zeigt, ob es zunimmt |
| `fetch … need FRED_API_KEY` | ALFRED-Reihe ohne Schlüssel | Secret setzen; die Makroketten liefern bis dahin BLS-Werte |
| `shiller: no source answered` | Shiller-Datei verschoben | neue URL in `configs/system.yaml` → `providers.shiller.urls`; bis dahin liefert der Spiegel |

**Echte Antworten aufzeichnen:** `rotationlab record-fixtures` (wöchentlich im Workflow `network`, Ergebnis im Branch `recorded-fixtures`; nach dem Merge spielt `tests/integration/test_recorded.py` sie in jeder CI ab).

**FRED-MD-Archiv:** `rotationlab fredmd-archive` (oder Workflow `fredmd-archive`) → Branch mergen → `rotationlab ingest --provider static` → `python scripts/revision_study.py`.

**Alte Historie nachladen:** Lieferte ein Provider bei der Erstladung nur einen Teil der Historie, datiert der Store später nachgelieferte alte Werte auf den Ankunftstag (sie wären im Backtest unsichtbar). Richtiger Weg: `rotationlab ingest --full --series <id>` auf einer *leeren* Reihe (Store ohne diese Reihe neu aufbauen oder vor dem ersten Lauf vollständige Historie sicherstellen). Nach einem Split-Lauf tragen alle neuen Zeilen des Symbols den Lauftag (ADR 034).

**Pflege:** `rotationlab store verify` vor jedem Lauf (Prüfsummen); quartalsweise `rotationlab ingest --full` (holt alle Historien neu, Unterschiede werden Revisionen mit heutigem Datum, nichts geht verloren) und danach `rotationlab store compact` (fasst die Deltas zu einer Basisdatei zusammen; as-of-Antworten bleiben identisch, getestet).

**Neue Reihe:** Eintrag in `configs/series.yaml` (oder Rolle in `universe.yaml`) → `rotationlab validate` → `rotationlab ingest --series <id>`; die Erstladung datiert Historie nach dem Lag-Modell.

## Module und Backtests (Phase 2)

```bash
rotationlab golden                                   # die fünf Module gegen die Forschung (≈ 60 s); Exit 1 bei Abweichung
rotationlab golden --walkforward                     # + Walk-forward Multi-Asset (≈ 96 s)
rotationlab golden --execution next_close            # dieselben Läufe mit Produktions-Timing (ADR 011)
rotationlab backtest --strategy multi_asset_rotation                         # Forschungsuniversum, Produktions-Timing, Kosten aus universe.yaml
rotationlab backtest --strategy multi_asset_rotation --costs research --execution same_close   # wie die Studie
rotationlab backtest --strategy us_sector_rotation --universe live --start 2004-01-31          # ETFs (braucht Live-Daten)
rotationlab walkforward --strategy multi_asset_rotation --costs research
```

Jeder Lauf schreibt `output/runs/<run_id>/` (`record.json` mit Git-SHA, Config-Hash, Datenstand und Kennzahlen;
`decisions.csv`, `weights.csv`, `proposals.jsonl`). Golden rot nach einer Änderung: `rotationlab golden --strategy <id>`
zeigt die Abweichung je Kennzahl; die Gewichts-Tests in `tests/golden/test_module_goldens.py` zeigen, ob die Logik
oder nur die Kosten/Timing abweichen. Gold/Silber-Hedge-Varianten: `python scripts/precious_hedge_study.py`.

## Monatsprognose (ADR 043, P6)

```bash
rotationlab forecast run                             # heute: Prognose am letzten Monatsende, fällige Prognosen abrechnen, Report
rotationlab forecast run --date 2026-11-01           # ein bestimmter Lauftag (Entscheidung = Monatsende davor)
rotationlab forecast run --universe long_history --provider static --journal /tmp/j --reports /tmp/r   # Probelauf auf dem Forschungspanel
rotationlab forecast run --config forecast_v2 --universe long_history --provider static --journal /tmp/j2 --reports /tmp/r2   # Runde 2 (ADR 052/053): nur von Hand, nicht im Workflow; Standard-Journalpfade wären journal/forecast_v2, reports/forecast_v2
rotationlab forecast verify                          # Hash-Ketten des Journals prüfen (Exit 3 bei Bruch)
rotationlab forecast verify --anchor "journal head: forecasts.jsonl seq 41 hash 3f9a…"   # zusätzlich gegen einen früheren Kopf (erkennt Kürzung)
```

Was der Lauf tut: Entscheidungsdatum D = letztes Kalender-Monatsende **vor** dem Lauftag (die Schlusskurse von D
müssen im Store sein). Sind die Preise der gerankten und der Trendklassen bis zur letzten Sitzung ≤ D in der Sicht an D
nicht vollständig, prüft er, ob sie in der Sicht des Lauftags (Beobachtungen ≤ D, Vintages ≤ Lauftag) vollständig sind –
der Fall **verspäteter Daten**: ein Kurs, der den Store mehr als fünf Tage nach seiner Sitzung erreicht, trägt das
Ankunftsdatum als Vintage und wäre in der Sicht an D für immer unsichtbar. Dann schreibt er die Prognose aus dieser
Sicht und vermerkt es in der Prognose (`notes`: „late data …“) und im Lauf-Output; `created_at` zeigt die Verspätung.
Fehlen die Preise auch dort (der Ingest ist noch nicht durch), schreibt er **keine** Prognose und sagt warum; der
nächste Tageslauf versucht es wieder. Cash (BIL) wird nicht gelesen und blockiert nicht. Sonst hängt er die Prognosen
(1, 3, 6 Monate) an `journal/forecast/forecasts.jsonl` an, rechnet alle Prognosen ab, deren Fenster geschlossen und
deren Daten für **jede** Klasse der Prognose vollständig sind (`outcomes.jsonl`; Trendklassen zu Monatsmitteln einen
Monat länger, Entscheid 5; ein fehlendes Niveau am Fensterrand lässt die Abrechnung warten statt die Klasse zu
verlieren), und schreibt `reports/forecast/<YYYY-MM>.md` und `latest.md`. Jeder Schritt ist idempotent: ein zweiter
Lauf am selben Tag ändert nichts. Vor dem ersten Anhängen prüft der Lauf die Ketten; eine gebrochene Kette wird nie
verlängert (Exit 3, Store unberührt).

Das Journal ist append-only mit Hash-Kette (jede Zeile trägt `seq`, `prev_hash`, `hash`). Eine geänderte, gelöschte,
vertauschte oder von Hand angehängte Zeile lässt `forecast verify` (und jeden `forecast run`) mit Exit 3 scheitern.
**Was die Kette nicht leistet (Zweitprüfung 2026-10-26):** eine am Ende gekürzte Datei ist eine kürzere, in sich
stimmige Kette, und wer die Datei hat, kann sie komplett neu hashen – es gibt kein Geheimnis und keine Signatur. Darum
druckt jeder Lauf den **Kopf** beider Ketten (`journal head: forecasts.jsonl seq N hash …`) ins Actions-Log und in die
Job-Zusammenfassung und schickt ihn per Telegram, sobald eine Zeile dazukam; zusammen mit der Git-Historie des Branches
`data` (jeder Tageslauf ist ein Commit) ist das der Anker ausserhalb der Datei. `forecast verify --anchor "<Zeile>"`
prüft, dass die Datei den verankerten Kopf noch enthält. Seit ADR 051 schreibt jeder Lauf, dessen Kopf sich geändert hat, die Zeile zusätzlich auf den Branch `anchors` (`journal-anchors.txt`, eine Zeile je Änderung) – unabhängig von der Log-Aufbewahrung. Prüfung von Hand:

```bash
git fetch origin anchors data && git show origin/anchors:journal-anchors.txt | tail -1   # letzter Anker
git show origin/data:journal/forecast/forecasts.jsonl > /tmp/f.jsonl   # … und gegen das Journal verifizieren
``` Eine Prognose wird nie überschrieben – auch nicht, wenn sich
Daten später als revidiert erweisen; der Datenstand steht in jeder Zeile (`data_snapshot`).

Live-Universum (`configs/forecast.yaml`): gerankt SPY, IEF, GLD, SLV; nur Trend CPER (Energie gestrichen, ADR 047);
Cash BIL. Im Forschungsuniversum (Probeläufe) werden Prognosen einen Monat später abgerechnet, weil das World-Bank-
Mittel der Trendklasse das Fenster t+1 → t+2 braucht (Entscheid 5).

**Nachgeholte Prognosen (ADR 050):** Wird eine Prognose mehr als 7 Tage nach ihrem Entscheidungsdatum geschrieben (z. B. der erste Lauf nach dem Upload für den Entscheid vom 30.9.), trägt sie die Notiz `backfilled`, steht im Journal und wird abgerechnet, zählt aber nicht zur Bilanz; der Report kennzeichnet sie. Die Live-Bilanz beginnt damit mit dem ersten rechtzeitig geschriebenen Entscheid (voraussichtlich 31.10.2026).

Die 1-Monats-Prognose trägt zusätzlich die Gewichte der vorab fixierten Paper-Regel (ADR 048: Top-2 gleichgewichtet,
Trendfilter, Vol-Ziel 10 %, kein Hebel) als abgeleitete Ausgabe; der Report zeigt sie in der Spalte „Gewicht
(Paper-Regel)“ und rechnet sie Monatsende zu Monatsende vor Kosten gegen Equal Weight ab („Paper-Regel …“ in der
Bilanz). Historisch (1974–2018, mit Kosten und ehrlichem Timing) hat die Regel das vorab fixierte Kriterium gegen
Equal Weight **nicht** erfüllt (`output/forecast/PORTFOLIO.md`); die Spur ist Beobachtung, keine Empfehlung.

## Forschungsdaten Runde 4 (einmalig, ADR 057/058)

1. Actions → `research-data` → Run workflow. Der Lauf lädt die Rohdateien (FRED H.10, Treasury-Renditen, OECD-Zinsen,
   French-Industrien täglich, French-Länder) und legt sie mit `MANIFEST.json` auf den Branch `research-data`; die
   Job-Zusammenfassung zeigt je Datei den Status und am Ende den Commit des Branches. Er schlägt fehl, wenn eine
   Pflichtquelle fehlt (die übrigen Dateien liegen trotzdem auf dem Branch).
2. Einfrieren (in der Forschungsumgebung): `git fetch origin research-data`; eingefroren wird der **früheste** Commit,
   dessen Manifest alle Pflichtquellen hat (ADR 058 – nie ein späterer, weil seine Daten anders aussehen). Erst
   `python scripts/freeze_research_data.py --src <Checkout> --commit <SHA> --describe` (zeigt den Aufbau der
   Länderdatei), dann den Länder-Parser nach der Regel im Modulkopf schreiben (alle Länder der Datei, `Mkt` der
   umfassenderen Gruppe, keine US-Spalte), dann ohne `--describe` einfrieren – prüft jede Datei gegen das Manifest
   und schreibt nach `data/raw/` samt `r4_PROVENANCE.json`.
3. Länder eintragen, nicht wählen: `R4_COUNTRIES` in `rotationlab/data/providers/static.py` = die Länder der Datei in
   ihrer Reihenfolge (`python -c "import sys; sys.path.insert(0,'scripts'); import r4_register as r; print(r.countries())"`);
   damit erst entstehen die Round-4-Reihen im Katalog.
4. `python scripts/r4_data_check.py` – die Datenprüfung (G1–G6, Schwellen vor dem Download); ein „NEIN“ stoppt Runde 4.
5. `python scripts/r4_register.py --sample 1900-01-31,1900-01-31 --write`, `rotationlab ingest --full --provider static`,
   `python scripts/allocator_v2_walkforward.py` – bricht nach dem ersten Lauf mit dem Fenster nach Regel ab; dann
   `python scripts/r4_register.py --sample <Beginn>,<Ende> --write` und das Skript erneut (Laufzeit gut eine Stunde).
   Danach `python scripts/r4_register.py --sample <Beginn>,<Ende>` (prüft: Registrierung = Vorlage), Golden pinnen,
   Versuchsregister von „planned“ auf „stored“, `tests/test_contracts.py` um die Paper-Rolle `sleeve_allocator_v2`
   ergänzen, Zweitprüfung.

## Wenn Telegram meldet …
| Meldung | Bedeutung | Was tun |
|---|---|---|
| `quality blocking` | Pflichtreihe fehlt/veraltet oder Schema verletzt | Report lesen; Provider prüfen; bei Yahoo-Ausfall `--provider stooq`; keine Trades bis grün |
| `RISK HALT` | Daten-Kill-Switch | Positionen halten; Ursache wie oben |
| `stop fired` | Modul-Stop (z. B. Ratio −15 %) | Zielgewichte im Report sind bereits angepasst; umsetzen |
| `targets changed` | Entscheidungstag | Report §5: Ziel vs. Ist; zu Schlusskurs D+1 umsetzen; Journal übernimmt Referenzkurs automatisch |
| `signal health red` | 36M-IC ≤ 0 | keine automatische Reaktion; Entscheidung dokumentieren (ADR), ggf. neue Version |
| `drift` | Live-Sharpe unter Backtest-Band | Umsetzungsdifferenz prüfen (Report §8), Kosten, dann Modelle |
| `daily run FAILED` (Heartbeat) | Workflow abgebrochen | Actions-Log; Lauf manuell über `workflow_dispatch` wiederholen |

## Manuell
- Neuaufbau: `rotationlab ingest --full` (quartalsweise, Vergleich mit inkrementellem Stand im Report).
- Backtest/Golden lokal: `rotationlab golden --walkforward`, `rotationlab backtest --strategy <id>`.
- Konfiguration ändern: PR mit `version`-Erhöhung, Golden-Update, ADR-Zeile; Merge nur bei grüner CI.
- Journal ist append-only; Korrektur = neuer Eintrag mit `supersedes`.
