# Review der Vintage-Logik (Phase 1 Datenschicht)

Reviewer: Claude Fable 5.1, unabhängig vom Autor der Schicht (Opus). Datum 24.10.2026.
Grundlage: die 11-Punkte-Prüfliste in `PHASE1_ABNAHME.md`, der Code in `rotationlab/data/` und eigene
Gegenexperimente (nicht die bestehenden Tests). Jeder Punkt: Befund, Beleg, Entscheid.

**Ergebnis in einem Satz:** Die Grundkonstruktion (Intervall-Index, Diff-Regeln, Lag-Einheit `nM`, Erstladung = Historie,
Verspätung = Ankunftsdatum) ist korrekt. Vier Befunde waren Fehler oder Lücken und sind behoben (ADR 034); drei sind
dokumentierte Restrisiken; der Rest ist bestätigt. Alle 183 Tests grün, ruff und mypy strict ohne Befund, Store neu
aufgebaut (`verify` OK), Golden-Werte unverändert.

## Befunde

| # | Punkt | Befund | Schwere | Entscheid |
|---|---|---|---|---|
| 1 | ALFRED inkrementell | korrekt | – | bestätigt |
| 2 | Rückfüllung vor Archivbeginn | **Fehler**: feuerte auch bei verspäteten Veröffentlichungen im Archiv (Shutdown) → Look-ahead | hoch (selten) | behoben |
| 3 | Klemmen auf Periodenende | korrekt, kein Informationsverlust am Monatsende | – | bestätigt |
| 4 | Verspätete Ankunft | korrekt und konservativ | – | bestätigt |
| 5 | Lag-Tabelle FRED-MD | **Lücke**: HWI, HWIURATIO mit `1M` zu kurz (JOLTS) | mittel | behoben (`2M`) |
| 6 | Vintage-Prinzip `0D` | konsistent; Dollar-Konstrukt der Forschung bleibt bewusst `0D` | niedrig | Restrisiko dokumentiert |
| 7 | Splits | **Fehler**: Sicht am Split-Tag mischte alte und neue Basis (−50 % Scheinrendite) | hoch | behoben |
| 8 | Monatslabels | korrekt; Teilmonate brauchen in Phase 3 eine Regel in den Features | – | Hinweis an Phase 2/3 |
| 9 | Revisionen `max(Lauftag, Lag)` | korrekt; Überschreiben vor Sichtbarkeit ist beabsichtigt | – | bestätigt |
| 10 | Ketten | **Ungenauigkeit**: Spleiss ohne exaktes Datum erzwang eine Nullrendite | niedrig | behoben |
| 11 | Echtzeit-FRED-MD | Datierung konservativ und konsistent; Label der Datei 2026-10 ist kosmetisch | niedrig | dokumentiert |

## 1. ALFRED inkrementell – bestätigt

Clip = letzter erfolgreicher Abruf − 7 Tage; nur Echtzeitperioden mit `realtime_start > Clip` werden übernommen, weil
die API ältere Perioden auf den angefragten Start kappt und so Vintages fälschen würde (`fred.py::alfred_frame`).

*Ausgefallener Lauf:* `last_fetch` wird nur nach einem erfolgreichen Abruf gesetzt (`ingest.py`, `state[...]` erst nach
dem Diff). Fällt ein Lauf aus, bleibt der Clip beim letzten Erfolg; der nächste Lauf holt alles seither. Kein Verlust,
beliebig lange Ausfälle.

*Veröffentlichung genau am Clip-Datum:* `realtime_start == Clip` wird verworfen. Das ist unschädlich, weil Clip =
letzter Abruf − 7 Tage, und der letzte Abruf (Clip′ < Clip) diese Vintage schon gesehen hat; der allererste Abruf ist
ein Vollabruf ab 1776.

*Rückdatierung durch FRED:* `realtime_start` ist das Datum, an dem FREDs Datenbank sich geändert hat; nach hinten
datierte Vintages gibt es nicht. Korrekturen des Archivs (seltene „archive fixes“) kommen nur über `--full` herein und
erscheinen als `revised` mit Protokoll. Restrisiko akzeptiert.

## 2. Rückfüllung vor Archivbeginn – Fehler, behoben

Regel vorher: Jede Beobachtung, deren erste archivierte Vintage mehr als 31 Tage nach dem Lag-Datum liegt, bekam eine
zusätzliche Zeile am Lag-Datum mit dem ältesten archivierten Wert. Gedacht für die Jahrzehnte vor Archivbeginn.

**Gegenexperiment** (`alfred_frame`, Lag `1M`): Archivbeginn 2000-01-15; September 2025 erst am 2025-12-02
veröffentlicht (Muster des Shutdowns Okt–Nov 2025: Beschäftigung September erschien am 20.11., Baubeginne später).
Ergebnis vorher:

```
2025-09-30   2025-10-31   4.0   ← Rückfüllung: Wert gilt als bekannt am 31.10., war es aber nicht
2025-09-30   2025-12-02   4.0
```

Ein Monatsend-Entscheid am 31.10.2025 hätte eine Zahl benutzt, die erst fünf Wochen später erschien. Genau die Art
Look-ahead, die der Store ausschliessen soll – und ausgerechnet in den Monaten, in denen Echtzeitdaten am meisten von
den heutigen abweichen.

**Korrektur:** Rückfüllung nur für Beobachtungen, deren erste Vintage *der Archivbeginn der Reihe* ist (ältestes
`realtime_start` des Vollabrufs). Verspätungen im Archiv behalten ihr echtes Datum. Test
`test_alfred_backfill_ignores_delayed_releases_inside_the_archive`; die 22 Rückfüllungen der CPI-Fixture bleiben.

*Zur Grösse des Restrisikos (Benchmark-Revisionen):* Der rückgefüllte Wert ist der älteste archivierte, nicht der
Erstwert. Die Revisionsstudie (`output/revisions/REPORT.md`) misst den Unterschied zwischen Echtzeit und heute am Rand
mit ~1 Pkt Jahresrate bei der Industrieproduktion, ≤ 0.14 Pkt beim CPI. Vor Archivbeginn ist der Store damit so gut wie
die Forschungsstudien (Lag-Modell auf revidierten Daten) – nicht besser, aber auch nicht schlechter. Der Hinweis
`alfred_backfilled` im Qualitätslog reicht; eine Markierung der Zeilen im Store ist nicht nötig, weil sich die
Rückfüllung aus `vintage_date == Lag(obs)` vor dem Archivbeginn rekonstruieren lässt.

## 3. Klemmen auf das Periodenende – bestätigt

Michigan-Vorabwerte tragen in ALFRED ein `realtime_start` vor dem Ende ihres eigenen Monats (FRED datiert die Beobachtung
auf den Monatsersten). Der Store klemmt die Vintage auf das Periodenende. Für Entscheide am Monatsende geht keine
Information verloren (Sichtbarkeit genau am Entscheidungstag) und keine gewonnen. Treffen Vorab- und Endwert auf
denselben Schlüssel, gewinnt der spätere (stabile Sortierung, `keep="last"`; getestet). Erst eine tägliche Schleife, die
Stimmungsdaten innerhalb des Monats nutzt, würde die Vorabwerte vermissen – Phase 3 nutzt dafür Marktdaten, nicht Umfragen.

## 4. Verspätete Ankunft – bestätigt

Gegenexperimente (`store.diff`, Toleranz 5 Tage):

| Fall | Ergebnis |
|---|---|
| Freitagsschluss, Lauf am Montag | pünktlich, Vintage = Freitag |
| Freitagsschluss, Cron eine Woche tot, Lauf am nächsten Freitag | `late = 1`, Vintage = Ankunftstag |
| Monatswert `1M`, am 10.10. abgerufen (Lag-Datum 31.10. liegt in der Zukunft) | Vintage bleibt 31.10., nicht verspätet; Sicht am 30.10. zeigt ihn nicht |
| CFTC (`7D` auf Dienstagsposition, Veröffentlichung Freitag) | Toleranz reicht bis Sonntag der Folgewoche; Nachlieferungen nach einem Shutdown werden auf Ankunft datiert |

Die Regel ist konservativ in der richtigen Richtung: Ein eigener Ausfall macht Daten im Backtest *später* bekannt als
in Wirklichkeit, nie früher. Die Erstladung behält Lag-Vintages (Historie für den Backtest; Hypothesis fand diesen Fall
als einzige Ausnahme der Unveränderlichkeit, ADR 026). Grenze: Liefert ein Provider bei der Erstladung nur einen Teil der
Historie, wird der Rest später auf Ankunft datiert – im Backtest dann unsichtbar. Für die Live-Provider ist das richtig;
für Nachladungen alter Historie ist `ingest --full` mit leerer Reihe der Weg (dokumentiert im RUNBOOK).

## 5. Lag-Tabelle FRED-MD – Lücke, behoben

**Empirischer Test** mit den drei echten Vintage-Dateien: Welche Spalten sind im jeweils letzten Monat der Datei leer?
Eine Datei des Monats M enthält, was bis Ende M veröffentlicht war; eine leere Spalte im Monat M−1 bedeutet, dass `1M`
zu kurz ist.

| Vintage | leer im letzten Monat (Lag in der Tabelle) |
|---|---|
| 2019-09 | CMRMTSPLx (2M), **HWI (1M)**, **HWIURATIO (1M)**, ACOGNO, BUSINVx, ISRATIOx, NONREVSL, CONSPI, DTCOLNVHFNM, DTCTHFNM (alle 2M), S&P div yield, S&P PE ratio (6M) |
| 2021-04 | dieselben, zusätzlich MZMSL (nicht mehr in FRED-MD 2026) |
| 2026-10 | wie 2019-09 ohne HWI (die Datei endet 2026-08) |

Alle `2M`- und `6M`-Reihen stimmen; einzig der Help-Wanted-Index (aus JOLTS, ~5 Wochen nach Monatsende) stand auf `1M`.
Korrektur: `HWI`, `HWIURATIO` → `2M` (`static.py::_FREDMD_SLOW`), Store neu aufgebaut. Keine Studie nutzt HWI, Goldens
unverändert.

Umgekehrt zeigt der Test, dass zehn `2M`-Reihen (Einkommen, Konsum, PCE-Preise, Auftragseingänge) im letzten Monat schon
gefüllt waren – `2M` kostet sie einen Monat Aktualität. Das ist die Forschungskonvention (`shift(2)` für PCE und
Realeinkommen in `macro_monthly`) und bleibt; die Echtzeitreihen `static:fredmd_rt:*` und ALFRED liefern live das
genaue Datum. Bekannte Grenze des Lag-Modells: In Shutdown-Monaten (2013-10, 2018-12/2019-01, 2025-10/11) ist `1M` für
BLS-Daten bis zu drei Wochen zu optimistisch (Beschäftigung September 2025: Lag-Datum 31.10., Veröffentlichung 20.11.).
Das betrifft nur `static:fredmd:*`, nicht die Echtzeitreihen und nicht ALFRED.

## 6. Vintage-Prinzip `0D` für Marktpreis-Derivate – bestätigt, ein Restrisiko

Die Regel „datiert, wann ein Live-System dieselbe Information haben konnte“ ist für French-Portfolios, World-Bank-Mittel,
Monatsmittel von Zinsen und Shillers Monatsmittel des S&P konsistent: Die zugrunde liegenden Preise sind öffentlich,
live liefern ETFs und Indizes dieselbe Information am Monatsende. Dass die *Zahlen von French* erst Wochen später
erscheinen, fängt die Verspätungsregel live korrekt ab (Ankunftsdatum); im Backtest zählt die Information, nicht der
Bote.

Restrisiko: Der tägliche Dollarindex der Fed (H.10) erscheint wöchentlich am Montag für die Vorwoche. Live steht
`fred:DTWEXBGS` deshalb richtig auf `7D`; das Forschungskonstrukt `static:USD_IDX` (Monatsende aus Tageswerten) bleibt
`0D` für die Parität mit `macro_monthly`. Die Rohstoffstudie verzögert den Dollar ohnehin um einen Monat; in der
Gold/Silber-Studie geht `Δ log Dollar 3M` am Monatsende ungelagged in die Diagnose ein (kein Golden, kein Signal mit
Prognosekraft). Für Phase 2 gilt: Features auf dem Dollar nutzen die Live-Reihe mit `7D` oder `shift(1)`.

## 7. Splits – Fehler, behoben

**Gegenexperiment** (`store.diff` + `StoreViewFactory`): Split 2:1 am 12.01., Lauf am 14.01. mit rebasierter Historie
und zwei neuen Sitzungen. Vorher:

```
TR-Sicht am 13.01. (alte Basis):  100.0  101.0  102.0  103.0  104.5  105.5  53.25  53.76   ← −49.5 % am Split-Tag
TR-Sicht am 14.01. (neue Basis):  100.0  101.0  102.0  103.0  104.5  105.5  106.5  107.5
```

Ursache: Revisionen der Historie bekamen `max(heute, Lag)` = 14.01., die *neuen* Sitzungen 12./13.01. aber ihr
Lag-Datum `0D` = 12./13.01. Jede Sicht zwischen Split und Lauf sah alte Basis bis zum 09.01. und neue Basis danach.
Das trifft auch den Normalbetrieb mit täglichem Cron: Der Lauf am Morgen nach dem Split-Tag liefert den Split-Tag-Schluss
(`0D`) und die rebasierte Historie (heute) – die Sicht *am Split-Tag* zeigt den Einbruch. Live wäre das ein
Stop-Auslöser der Risikoschicht, im Backtest ein Ausreisser an jedem ETF-Split (SPY 1997, XLK 2024 …).

Der bestehende Test prüfte die Sicht am Lauftag und eine Woche vor dem Split, nicht die Sicht am Split-Tag.

**Korrektur:** Erkennt der Ingest eine gleichförmige Reskalierung der gespeicherten Historie (`_is_rebase`, jetzt auch
bei `--full`), gilt für alle Reihen des Symbols in diesem Lauf (Kurse zuerst, dann Dividenden und Splits):
`new_from_today=True` → neue Zeilen tragen `max(Lag, heute)`. Keine Sicht mischt die Basen: bis zum Vortag des Laufs die
alte Basis ohne die jüngsten Sitzungen (sie wurden erst heute gelernt), ab dem Lauftag die neue Basis vollständig.
Dividenden auf alter Basis bleiben mit alter Vintage, die rebasierte Dividende kommt als Revision am Lauftag – konsistent
mit den Kursen derselben Sicht. Test erweitert (`test_split_rebases_history_without_a_fake_jump`: Sicht am 2024-06-10
endet am 06-07, keine Rendite > 8 %).

Preis der Korrektur: Am Tag eines Splits ist der Split-Tag-Schluss erst mit dem Lauftag sichtbar, ein Tag später als
sonst. Für Monatsend-Entscheide ohne Folgen, für die tägliche Risikoschleife ein Tag Verzögerung an vielleicht einem Tag
pro Jahr.

Offen bleibt die Adjustierungsbasis von Stooq (Split ja, Dividenden?); die Kette Yahoo→Stooq nutzt Stooq nur zum
Füllen von Rändern mit Verhältnis-Spleiss, und der Quellenabgleich warnt bei Abweichung > 0.5 %. Der erste Lauf des
`network`-Workflows beantwortet das.

## 8. Monatslabels – bestätigt, Hinweis für Phase 2/3

`resample_last` labelt den laufenden Monat mit `min(Monatsende, D)`: Sicht am 18.03. → `[31.01., 28.02., 18.03.]`.
Am Entscheidungstag (Monatsende) fallen beide Regeln zusammen; `1M`-Daten des Vormonats werden genau dann sichtbar, wenn
die Forschung `shift(1)` anwendet (Paritätstest mit 40 Zufallsdaten). Für Phase 3 (tägliche Schleife) muss der
Feature-Vertrag festhalten: Ein letztes Label `< Monatsende(Label)` ist ein *Teilmonat*. Rollierende Monatsfenster
(10M-Trend, 12M-Momentum) dürfen ihn nicht als vollen Monat zählen. Vorschlag: `MarketView` liefert `period_complete`
mit, oder die Features vergleichen Label und `view.date`. Kein Änderungsbedarf in Phase 1.

## 9. Revisionen und Überschreiben vor Sichtbarkeit – bestätigt

`max(Lauftag, Lag)` ist richtig: Eine Revision kann nicht vor ihrem Lauftag bekannt sein, ein Lag-Modell-Wert nicht vor
seinem Lag-Datum. Gegenexperiment: Septemberwert am 10.10. als 3.0 geholt (Vintage 31.10.), am 20.10. als 3.3 → derselbe
Schlüssel `(30.09., 31.10.)`, spätere `ingested_at` gewinnt; die Sicht am 31.10. zeigt 3.3, die Sicht am 30.10. nichts.
Keine der beiden Zahlen war je sichtbar, also wurde keine Vergangenheit verändert. Beabsichtigt, und `compact` entfernt
genau solche überholten Duplikate (Hypothesis-Eigenschaft: keine As-of-Antwort ändert sich).

## 10. Ketten – Ungenauigkeit, behoben

Fehlt der Ersatzreihe das exakte Übergangsdatum, nahm `_anchor_scale` den letzten Ersatzwert davor. Gegenexperiment:
Primär ab 07.01., Ersatz mit 05., 06., 08.01. → Skalierung über den 06.01., der skalierte Wert vom 06. ist gleich dem
Primärwert vom 07.: eine Nullrendite zwischen 06. und 07., obwohl der Ersatz zwischen 06. und 08. +1.96 % zeigte. Jetzt
wird am *nächstliegenden gemeinsamen Handelstag* verankert (beide Reihen preisen dasselbe Asset, jeder gemeinsame Tag
liefert das Verhältnis ohne erfundene Rendite); nur ohne jede Überlappung gilt die alte Regel. Makroketten (Werte, Faktor
1) füllen bewusst keine Lücken im Inneren der primären Reihe – Lücken meldet der Qualitätscheck.

Hinweis für Phase 2: Eine Kette `[static:fredmd_rt:X, static:fredmd:X]` würde den Backtest vor Archivbeginn mit dem
Lag-Modell füllen (nur „davor“, nie innen) – praktisch, aber am rechten Rand füllt der Spleiss auch *nach* dem letzten
Echtzeitwert mit Lag-Modell-Werten, wenn das Lag-Modell optimistischer ist als die Wirklichkeit. Mit der korrigierten
Tabelle ist das selten; wer die Kette nutzt, kauft diesen Rest.

## 11. Echtzeit-FRED-MD – bestätigt

Vintage M wird während M erstellt und enthält, was bis Ende M erschien (Datei 2019-09 enthält das Einkommen vom
27.09.2019; Datei 2021-04 den PCE vom 30.04.2021). `Monatsende + 7 Tage` ist damit konservativ für Monatsend-Entscheide
(die Datei kann frühestens am Monatsende vollständig sein). Für eine tägliche Schleife wäre ein um wenige Tage zu frühes
Datum möglich, falls McCracken später im Folgemonat veröffentlicht; Makrodaten gehören nicht in die tägliche Schleife.

Die Datei `2026-10` reicht nur bis 2026-08 – inhaltlich eine 2026-09-Vintage im Sinne der Benennung. Für den Store ist
das Label kosmetisch; massgeblich ist `vintage_date = 2026-10-10`, das Datum, an dem der Snapshot belegt existierte.
Alle Werte darin waren an diesem Tag bekannt. Die Nur-Änderungs-Darstellung (`_realtime_frame`) ist korrekt: `prev` ist
der letzte nicht leere Vorwert, ein verschwundener Wert (NaN in einer späteren Vintage) ist nicht darstellbar und wird
übersprungen – akzeptabel, weil eine spätere Vintage ihn wieder zeigt oder die Reihe eingestellt ist.

Design-Entscheid, nicht Fehler: `static:fredmd_rt:*` hat keine Rückfüllung vor der ersten Vintage; ein Backtest vor
2019 (nach dem Archiv-Download: vor 1999) sieht nichts. Das trennt Echtzeit und Lag-Modell sauber; die Verbindung läuft
über eine Kette (Punkt 10) oder über ALFRED.

## Was der Review nicht abdeckt

- Echte Antworten der Live-Provider (FRED, BLS, Yale, French, CFTC, Stooq) – Bauumgebung ohne Zugang; erster Lauf des
  `network`-Workflows.
- Das vollständige FRED-MD-Archiv (Workflow `fredmd-archive`); mit ihm lohnt sich ein zweiter empirischer Lag-Test über
  alle ~320 Vintages statt drei.
- Phase 2/3: Verwendung der Sicht in Features (Teilmonate, Dollar-Lag, Echtzeitketten) – Hinweise oben.

## Geänderte Dateien

`rotationlab/data/providers/fred.py` (Rückfüllung), `rotationlab/data/providers/static.py` (HWI-Lag),
`rotationlab/data/store.py` (`new_from_today`), `rotationlab/data/ingest.py` (Rebase-Erkennung auch bei `--full`,
Symbolweite Datierung), `rotationlab/data/view.py` (`_anchor_scale`), drei Tests erweitert/ergänzt, `docs/ADR.md` (034),
`docs/ARCHITECTURE.md` §3, `data/store` neu aufgebaut.
