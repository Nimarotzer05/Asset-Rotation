# Look-ahead-Audit Phase 2 (Features, Module, Engine)

Stand 2026-10-25, zwei Durchgänge.

1. **Erstprüfung** durch Claude (Fable 5.1) in der Sitzung, in der der Code entstand – mit Zugriff auf Code,
   Store und Tests, aber kein fremder Leser.
2. **Zweitprüfung** durch einen frischen Prüfer ohne Sitzungskontext, der nur Repo und diesen Bericht bekam
   und den Auftrag, ihn zu widerlegen. Er fand zwei Lecks im Code, die der ersten Prüfung entgangen waren,
   eine faktisch falsche Aussage im Bericht und eine Timing-Verzerrung, die der Bericht unterschätzt hatte.

Geprüft wurde die 10-Punkte-Liste aus `PHASE2_ABNAHME.md`. Belege liegen in
`tests/lookahead/test_audit_phase2.py` (16 Tests, 63 s, laufen in der normalen CI). Die beiden Lecks sind
behoben (ADR 041); sonst wurde kein Produktionscode geändert.

## Ergebnis

**Für die Goldens und die Monatsentscheidungen auf dem Forschungsstore: kein Look-ahead.** Alle 33 Features,
alle fünf Module, der Walk-forward und die Engine liefern bit-identische Ergebnisse, ob der Store die
Zukunft enthält oder nicht – an Monatsenden und mitten im Monat, ob die Zukunft überschrieben oder entfernt
wird, und über den Engine-Lauf an fünf Schnittstellen. Beide Prüfer haben nichts gefunden, das die
Forschungskennzahlen verändert.

**Zwei Lecks im Code, die heute nicht wirken, aber Garantien verletzten** (gefunden von der Zweitprüfung,
behoben): eine verspätet erfasste Dividende stand im schnellen Total-Return-Pfad vor ihrer Vintage im Niveau;
eine Datenlücke machte aus „unbekannt“ drei Monate „fallend“.

**Eine materielle Konvention, die der erste Bericht unterschätzt hat:** Für Assets, die zu Monatsmitteln
bewertet sind (World-Bank-Rohstoffe), ist das Ausführungsniveau ein Preis, dessen Mittelungsfenster vor der
Entscheidung liegt. Der Rohstoff-Golden 0.74 trägt diesen Effekt; `next_close` ändert daran nichts.

## Methode

Die Phase-2-Abnahme prüfte Features und Module an 13 Monatsenden mit dem Harness: alle Werte, die an D
nicht bekannt sein konnten (`obs_date > D` oder `vintage_date > D`), werden durch Rauschen ersetzt; das
Ergebnis an D muss gleich bleiben. Das Audit ergänzt drei Prüfungen:

| Prüfung | Was sie sieht | Was sie nicht sieht |
|---|---|---|
| Harness an 7 Tagen mitten im Monat (aufsteigend sortiert, damit Modulzustände vorwärts laufen) | Lesen von Daten nach D im laufenden Monat | Deterministische Fehler aus bekannten Daten (Befund C) |
| Zukunft **entfernt** statt überschrieben; Features und Module an 5 Daten bit-identisch | Lecks über die *Form* des Stores: Präfixlängen, Rasterenden, `ffill` über Zeilen, die nur wegen der Zukunft existieren | Metadaten, die nicht Teil des Stores sind – der Handelskalender (Befund B) |
| Trunkierungs-Invarianz der Engine: Lauf auf dem vollen Store = Lauf auf dem bei T abgeschnittenen Store bis T, für alle fünf Module (`next_close`, Aktien auch `same_close`) an **fünf** Schnitten 2003–2007, Walk-forward an einem Schnitt mit Vergleich der Wahl und aller gebuchten Kandidatenrenditen | Book-Bewertung, Ausführungspreise, Walk-forward-Buchung – an jedem Schnitt die Entscheidung *am* Schnitt | Entscheidungen zwischen den Schnitten: vor einem Schnitt sind beide Stores identisch. Ein Leck, das nur in bestimmten Monaten auftritt, braucht einen Schnitt in genau so einem Monat (Zweitprüfung, Probe: ein Modul, das nur im März vorausschaut, bestand den Ein-Schnitt-Test). Deshalb fünf Schnitte statt einem; vollständig ist das nicht. |

Kontrollen, dass die Prüfungen greifen: ein Modul, das einen Monat vorausschaut, fällt an der Schnittstelle
durch; das ehrliche Gegenstück besteht. Die Kontrollen für Features und Module aus Phase 2 bleiben in
`test_modules_lookahead.py`.

## Die zehn Punkte

Schwere: **Leck** = Zukunftsinformation fließt ein · **Bug** = falsches Ergebnis aus bekannten Daten ·
**Konvention** = kein Leck, aber eine Annahme, die Ergebnisse schönt oder die Phase 3 entscheiden muss ·
**Robustheit** = Randfall ohne Wirkung auf heutige Läufe · **sauber**.

### 1. as-of-Panel, Teilmonate im Tagesloop — sauber als Leck, ein Bug, eine Konvention

`month_grid` endet mit dem Monat von D, der laufende Monat trägt das Label D; `resample_last` und
`_Prefix.periods` kappen genauso (`_panel.py:26`, `view.py:72/119`). Die letzte Zeile enthält den letzten
Wert ≤ D. Beleg: Harness mitten im Monat ohne Befund.

**Bug (behoben, Befund C der Zweitprüfung):** Der erste Bericht behauptete, Makro-Features mit `lag = 1`
seien mitten im Monat NaN und `quadrant` melde „unknown“. Das war falsch. `_direction` bildete
`np.where(m > m.shift(3), 1, −1)`; `NaN > x` ist False, also wurde ein fehlender Mittelwert zu **−1**
(„fallend“), maskiert wurde nur ein fehlendes `m.shift(3)`. Auf dem echten Store: 2008-10-10
`quadrant = "low_low"`, 2020-03-16 `"low_low"`, 2020-03-31 `"high_high"` – das Regime kippte mitten im
Monat nach Publikationskalender, und jede Datenlücke galt drei Monate als „fallend“. Kein Leck
(deterministisch aus bekannten Daten; genau deshalb für den Harness unsichtbar). Fix: Maske
`m.notna() & m.shift(3).notna()` (`macro.py:69`); `test_direction_is_unknown_not_falling_on_missing_data`.
Goldens unverändert, die Module lesen keine Regime-Features.

**Konvention:** Mitten im Monat ist die letzte Rasterzeile ein **Teilmonat**, und rollierende Fenster zählen
sie wie einen vollen Monat (`test_mid_month_features_see_a_partial_running_month`): `mom_12` vergleicht
einen Stand vom 15. mit einem Monatsende vor 12 Monaten, `vol_12m` nimmt eine 10-Tage-Rendite als eine von
12 Monatsrenditen (zu niedrig → `inv_vol`-Gewichte zu hoch). Empfehlung für Phase 3: Monatsmodule
entscheiden nur an Monatsenden; der Tagesloop wendet ausschließlich Risikoregeln auf Tagespreise an. Falls
Features doch täglich gelesen werden: Option `running_month: "drop" | "partial"` in `_on_grid`.

### 2. Verschiebungen in Features vs. Store-Lags — sauber

Jede `shift` liest eine *vergangene* Rasterzeile; der Store entscheidet, ob sie an D bekannt ist. Die
Zweitprüfung stellt die Argumentation richtig: Ein zu kurzer Shift kann kein Leck sein (er liest an
Monatsenden NaN); das einzige Leckrisiko sind zu *kurze Store-Lags*, und die gehören zur Phase-1-Prüfung
(`AUDIT_phase1_vintage.md`). Abgleich Shift ↔ Store-Lag:

| Feature | Shift | Reihe | Lag statisch | Lag live |
|---|---|---|---|---|
| Regime, Sahm, `d_cpi_yoy_3m`, `d_real_yield_3m` | 1 | CPIAUCSL, INDPRO, UNRATE | 1M (`_fredmd_lag_kind`) | ALFRED-Vintages (exakt), Fallback 1M |
| `commodity_state` | `usd_lag` 1 | USD_IDX | 0D | – (konservativ um einen Monat, wie die Studie) |
| CAPE/ECY | `cpi_lag` 1, `earnings_lag` 6 | Shiller CPI, Earnings | 1M, 6M (`SHILLER_COLUMNS`) | 1M, 6M (`series.yaml`) |
| Marktzinsen GS10, Baa, Aaa, TB3MS, Fedfunds | 0 | FRED-MD / FRED | 0D | 0D |

Lag 1M heißt: der Augustwert gilt ab 30. September als bekannt (`Lag.apply`) – später als die echte
Veröffentlichung Mitte September, also konservativ.

### 3. Expandierende Statistiken — sauber, eine bekannte Einschränkung

`ecy_percentile`, `risk_appetite`, `risk_appetite_pct` rechnen an D ihre Historie auf dem as-of-Panel
neu: die Vergangenheit, wie sie an D bekannt war. Kein Leck. Einschränkung: Im Forschungspanel sind alle
Reihen Endstände; dort ist die Vergangenheit an jedem D die *heutige*. Das betrifft die Studien genauso
wie die Engine, ist in `output/revisions/REPORT.md` quantifiziert und wird live durch die ALFRED-Ketten
behoben.

Konfiguration: `ecy_percentile` hat `pct_start = None`; die Studie begann 1926-07 (Golden 0.5872 so geprüft).
Wird `valuation_scaling` eingeschaltet, gehört `pct_start: 1926-07-31` in die YAML, sonst beginnt die
Perzentil-Historie 1881.

### 4. Base-100-Punkt von Rendite-Indizes — sauber

`_return_index` setzt 100 eine Periode vor der ersten Rendite. Der Punkt existiert erst mit der ersten
Rendite: im Referenzpfad aus der as-of-Reihe, im schnellen Pfad über `k + offset if k else 0`
(`view.py:361`). Beleg: `test_return_index_base_appears_with_the_first_return` (vor der ersten Rendite leer,
danach [Basis, 1. Rendite], schneller = Referenzpfad). Das Aktien-Golden 0.5732 stimmt seit ADR 037 exakt.

### 5. Engine-Preise — ein Leck im schnellen Pfad (behoben), sonst sauber

`prices_at` liest das Total-Return-Niveau als letzten Wert ≤ Tag (`engine/core.py:38`). Der erste Bericht
schrieb, der View filtere „selbst `obs_date ≤ D` und `vintage_date ≤ D`“. **Das galt nicht für den
schnellen Total-Return-Pfad mit Dividenden (Befund A der Zweitprüfung, Leck):** `_build_tr_prefix` baute
`_close_tr(full_close, full_dividend)` auf den *vollständigen* Reihen und schnitt mit `k = prefix_len(close,
D)`. Dividenden gingen über ihre Position im Kursindex ein; ihre `vintage_date` wurde nie gelesen (geprüft
wurden nur Katalog-Lag `0D` und `is_simple`). Eine Dividende mit `obs_date ≤ D < vintage_date` – im Store
die Regel für eine verspätet erfasste Beobachtung – stand im Niveau an D. Probe: Kurs täglich, Dividende
Ex 2000-02-15 mit Vintage +30 Tage, View 2000-02-29: Referenzpfad 104.10, schneller Pfad 106.12 (+1.9 %).
Heute ohne Wirkung: alle ETF-Kurse sind Zweierketten (kein schneller Pfad), das Forschungsuniversum hat
keine Dividenden. Garantie 2 des Views war trotzdem verletzt. Fix: `PitIndex.is_causal` (jede Zeile am
Beobachtungstag veröffentlicht) als Bedingung für den schnellen Pfad, sonst Referenzpfad;
`test_fast_total_return_path_respects_dividend_vintages` (schnell = Referenz, Dividende erst ab Vintage).

Verspätete Monatsreihen: am Folgetag mit dem Vormonatswert bewertet, nie mit einem späteren
(`test_next_close_execution_view_reads_no_new_monthly_value`, Fall „L“). Trunkierungstests an fünf Schnitten
ohne Befund.

### 6. `next_close` an Monatsgrenzen — sauber als Leck, zwei Konventionen (eine materiell)

Der Ausführungs-View am ersten Handelstag des Folgemonats enthält für Monatsreihen denselben Monatsend-
wert wie der Entscheidungs-View; für Tagesreihen den Schlusskurs des Ausführungstags (Market-on-close).
Beleg: Toy-Test oben; Trunkierungstests mit `next_close`.

**Konvention 1:** Für reine Monatsdaten ist `next_close` rechnerisch gleich `same_close` – Umsetzung zum
Schlusskurs, der das Signal erzeugt hat, weil es keinen anderen Preis gibt (ARCHITECTURE §7, ADR 038).

**Konvention 2 (Befund D der Zweitprüfung, materiell):** Für Assets, deren Monatswert ein **Monatsmittel**
ist – alle neun Assets von `commodity_trend`, zwei von sechs in `multi_asset_rotation` (World-Bank-
Rohstoffe) – ist der Ausführungspreis `avg(t)` ein Preis, dessen Mittelungsfenster vollständig vor D liegt.
Ein Trendsignal aus `avg(t)`, „ausgeführt“ zu `avg(t)`, kauft im Aufwärtstrend unter dem Monatsendkurs. Die
eigene Forschung misst die Größe (`output/commodities/REPORT.md` §3b): Trendprämie Gold 0.171 → **0.104**
p.a. auf LBMA-Monatsenden, Silber 0.238 → **0.129** (t 3.7 → 1.9 bzw. 3.0 → 1.4). Der Rohstoff-Golden 0.74
trägt diesen Effekt für alle Assets; `next_close` ändert daran nichts. Der erste Bericht schlug
`next_month_close` als „obere Schranke“ vor – für Mittelwert-Assets ist er nicht Schranke, sondern die
einzige Ausführung, deren Preisfenster nach D liegt. Phase 3: Modus `next_month_close` bauen, für
Mittelwert-Assets als Produktionskonvention, Rohstoff-Golden neu messen und beide Zahlen nebeneinander
berichten (ADR 041 d).

### 7. Walk-forward — sauber

`_book_returns` läuft **vor** den Kandidaten-Vorschlägen an D und bucht Gewichte der vorigen Entscheidung ×
Renditen bis D, abzüglich der an der vorigen Entscheidung berechneten Umschichtungskosten und der Cash-
Rendite (`walkforward.py:118–131`). Beleg: `test_walk_forward_books_previous_weights_times_realised_returns`
(Formel) und `test_walk_forward_choices_are_invariant_to_truncating_the_store` – nach der Zweitprüfung
vergleicht er neben der Wahl 1982-11-30 auch **alle gebuchten Kandidatenrenditen** bis zum Schnitt
(≥ 100 Monate je Kandidat), also das, worauf die Wahl beruht. Kostenkonvention: Zielgewicht-Differenzen im
Walk-forward, gedriftete Gewichte in der Engine – kleine systematische Differenz, kein Leck.

### 8. Feature-Cache je View — sauber

Der Cache hängt am View-Objekt, ein View gehört zu einem Datum, `views.at(d)` erzeugt ein neues Objekt
(`view.py:181/265`). Schlüssel: Name, Assets, sortierte Parameter; Rückgaben werden kopiert.

### 9. Golden-Läufe, Abschneiden ab `data_from` — sauber, ein Randfall

`research_factory` entfernt Beobachtungen vor dem Monatsersten von `data_from`: Vergangenheit, nie Zukunft.
Robustheit: `pd.Timestamp(data_from) - MonthBegin(1)` springt für ein Datum, das selbst Monatserster ist,
einen Monat zu weit (1972-12-01 → 1972-11-01). Heutige Werte sind Monatsenden. Vorschlag:
`pd.Timestamp(data_from).to_period("M").start_time`.

### 10. Edelmetall-Satellit — sauber

Tranchen, Einstiegsratio und Hedge-Zuschlag kommen aus dem View bei D und dem Zustand; `ratio_entry` wird
beim Vorzeichenwechsel auf `gs_ratio(D)` gesetzt und bleibt sonst stehen (`precious_metals.py:76–86`).
Beleg: `test_precious_metals_entry_ratio_is_fixed_at_the_sign_change` (1976–1981 auf dem echten Store).

## Weitere Befunde der Zweitprüfung

**B. Kalender im täglichen Cash-Index (`view.py:496–508`), nicht kausal, ökonomisch irrelevant.**
`_yield_index` verteilt die Monatsrendite gleichmäßig auf `n` = Sitzungen des ganzen Monats. Der NYSE-
Kalender kennt Sonderschließungen im Voraus (9/11): Ausführung 2001-09-04 bewertet CASH mit 15 statt 19
Sitzungen → 4.1e-5 relativ; Monatsenden identisch. Betrifft nur das Yield-Cash des Live-Universums unter
`next_close`/Tagesloop. Die Trunkierungs-Invarianz kann das prinzipiell nicht finden (der Kalender wird
nicht trunkiert). Offen; Option: Verteilung auf Kalendertage statt Sitzungen (dann weichen Monatsenden um
~3e-5 vom Monatsindex ab) oder ein Kalender nur mit geplanten Schließungen.

**E. Ein-Schnitt-Test** – siehe Methode; behoben durch fünf Schnitte, mit der genannten Restlücke.

**F. Testschwächen** – unsortierte Mid-Month-Daten (Zustände liefen rückwärts), `excess` im Walk-forward
nie verglichen; beides behoben.

## Grenzen

- Geprüft ist der Forschungspfad (statischer Store, Monatsentscheidungen). Der Live-Pfad hat erst seit
  heute Daten; seine Vintage-Logik ist durch Phase 1 und den ALFRED-Orakel-Test abgedeckt, der Tagesloop
  existiert noch nicht.
- Trunkierung prüft die Entscheidung am Schnitt; fünf Schnitte sind eine Stichprobe. Für Phase 3 sollte der
  Test mit jährlichen Schnitten über den ganzen Lauf parametrisiert werden (Laufzeit dann als Golden-Job).
- Metadaten außerhalb des Stores (Kalender) bleiben eine Leckquelle, die kein Store-basierter Test sieht.
  `vintage_date` wird außerhalb des Filters nirgends gelesen (`grep` in features/, strategies/, engine/,
  portfolio/ ohne Treffer).

## Umsetzung der Empfehlungen (2026-10-25, nach der Zweitprüfung)

| Empfehlung | Stand |
|---|---|
| 1 Tagesloop nur Risikoregeln | Vorgabe für Phase 3 |
| 2 Timing der Monatsmittel | **umgesetzt**: `next_tradable` und `next_month_close` (ADR 042); Rohstoff-Trend ehrlich 0.42 statt 0.74, Multi-Asset 0.557 statt 0.571, Walk-forward 0.69 statt 0.77 (`output/execution/TIMING.md`), gepinnt |
| 3 `pct_start` | **umgesetzt**: `pct_start: 1926-07-31` in `us_equity_exposure.yaml` |
| 4 `research_factory` | **umgesetzt**: Monatsanfang über `to_period("M")`; Test für 1., 15. und Monatsende |
| 5 Kalender im Cash-Index (Befund B) | **umgesetzt**: Sonderschließungen nach D zählen als Sitzung; Test mit 9/11 |
| 6 Mehr Schnitte | **umgesetzt**: Truncation-Sweep, 17 Schnitte je Modul 1976–2024 (Januar, Mai, September wechselnd), alle fünf Module unter `next_tradable`, 85 Schnitte ohne Befund; wöchentlich im `network`-Workflow (~10 min) |

## Empfehlungen

1. Phase 3: Monatsmodule entscheiden an Monatsenden, der Tagesloop führt nur Risikoregeln aus (Punkt 1).
2. Phase 3: Ausführungsmodus `next_month_close`; für Mittelwert-Assets Produktionskonvention; Rohstoff- und
   Multi-Asset-Golden damit neu messen und beide Werte berichten (Punkt 6, Befund D).
3. Beim Einschalten von `valuation_scaling`: `pct_start: 1926-07-31` (Punkt 3).
4. `research_factory`: Monatsanfang über `to_period("M")` (Punkt 9).
5. Cash-Index: Kalenderfrage entscheiden (Befund B).
6. Engine-Trunkierung mit mehreren Schnitten und der Harness mitten im Monat sind Abnahmekriterium jeder
   weiteren Phase (Combiner, Risikoschicht, Szenarien laufen durch dieselbe Schleife). Ein zweiter Prüfer
   ohne Sitzungskontext hat sich bezahlt gemacht; das sollte Teil jeder Abnahme sein.
