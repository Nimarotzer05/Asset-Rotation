# Phase 2 – Features, Module, Engine: Abnahme

Stand 2026-10-25. Die fünf Strategie-Module laufen durch eine Engine, lesen nur über `MarketView` und die
Feature-Registry, und reproduzieren die Forschung aus dem Point-in-time-Store: die Kennzahlen auf 0.002
Sharpe, die Zielgewichte Monat für Monat auf 1e-9. 247 Tests grün (davon 20 Golden, 1 übersprungen: Replay
echter Antworten bis zur ersten Aufzeichnung), Abdeckung 97 %, ruff und mypy strict ohne Befund.

## Abnahmekriterien (ARCHITECTURE.md §12)

| Kriterium | Nachweis |
|---|---|
| Goldens reproduziert | `tests/golden/test_module_goldens.py`; Tabelle unten; `rotationlab golden --walkforward` |
| Alle Features bestehen den Harness | `tests/lookahead/test_modules_lookahead.py`: 33 Features an 13 Stichtagen (7 Stress, 6 zufällig) auf dem echten Forschungspanel; Leck-Kontrolle greift |
| Panel ≡ punktweise | dieselbe Datei: alle 33 Panel-Varianten bitidentisch zum punktweisen Wert (ADR 036) |
| Module bestehen den Harness | alle fünf Module, der Edelmetall-Satellit mit Hedge und der Walk-forward; Leck-Kontrolle für Strategien greift |
| Engine, Book, Kosten, Walk-forward | `tests/unit/test_engine.py` (inkl. Hypothesis: Rebalancing trifft die Ziele und verliert genau die Kosten), `test_strategies.py`, `test_phase2_edges.py` |

## Goldens

Sharpe ex Cash (Spread-Strategien: Sharpe des Spreads). „Forschung“ = exakter Wert der Studien-CSV;
`same_close` = Umsetzung zum Entscheidungsschluss wie in den Studien; `next_close` = Produktion (ADR 011).

| Modul | Stichprobe | Forschung | Engine `same_close` | Δ | Engine `next_close` | Rendite p.a. | Max DD |
|---|---|---|---|---|---|---|---|
| Aktien-Exposure | 1927-07 – 2026-07 | 0.5732 | 0.5732 | +0.0000 | 0.5732 | 9.86 % (9.9) | −41.1 % |
| Sektor-Rotation | 1928 – 2026-07 | 0.5913 | 0.5904 | −0.0009 | 0.5904 | 11.10 % (11.1) | −45.8 % |
| Multi-Asset | 1972-12 – 2025-12 | 0.5703 | 0.5713 | +0.0010 | 0.5855 | 11.90 % (11.9) | −23.8 % |
| Multi-Asset Walk-forward (OOS) | 1982-12 – 2025-12 | 0.7725 | 0.7721 | −0.0004 | – | 9.78 % (9.8) | −10.8 % |
| Rohstoff-Trend | 1972-12 – 2025-12 | 0.7407 | 0.7421 | +0.0014 | 0.7421 | 10.06 % (10.1) | −16.7 % |
| Gold/Silber-MR | 1975-12 – 2026-02 | 0.2201 | 0.2192 | −0.0009 | 0.2103 | 3.02 % (3.0, arithm.) | – |

Weitere Goldens: Walk-forward wählt wie die Forschung in allen 44 Jahren Top-4 mit Trendfilter (erste Wahl
1982-11-30). Crash-Hedge: dieselben 8 Aktien-Drawdowns > 15 % seit 1971, Gold schlägt Silber in 8/8 mit den
Spread-Werten der Studie (0.11 … 0.43). Optionale Bewertungsskalierung (aus in v1): 0.5872 gegen 0.5873
(1931–2023).

**Gewichte:** An jedem Entscheidungsdatum sind die Zielgewichte der Engine gleich denen des Forschungscodes
(`src/signals.py`, `src/commodity_model.py`, Formeln aus `run_equity.py` und `run_gold_silver.py`) auf
denselben Store-Daten, Abweichung ≤ 1e-9 (Exposure, Gold/Silber ≤ 1e-12). Die verbleibenden Kennzahl-
Unterschiede kommen aus zwei Stellen: die Studien rechneten auf auf 6 Stellen gerundeten CSV-Dateien, und
die Engine zahlt Kosten auf den tatsächlich gehandelten (gedrifteten) Gewichten statt auf Zielgewicht-
Differenzen; die erste Position kostet in der Engine Gebühren, in den Studien nicht.

**Produktions-Timing:** Nur wo Tagesschlusskurse existieren, ändert `next_close` etwas: Multi-Asset (US-Aktien
und Silber täglich) +0.016, Gold/Silber (beide Metalle täglich) −0.010. Monatsreihen werden am Folgetag zu
ihrem Monatsend-Wert bewertet.

## Ehrliches Timing (ADR 042)

Die Goldens oben reproduzieren die Studien und damit auch deren Umsetzungskonvention. Für Assets, die zu
World-Bank-**Monatsmitteln** bewertet sind, ist diese Konvention optimistisch: das Signal entsteht aus dem
Mittel des Monats und wird zum selben Mittel „umgesetzt“, einem Preis, dessen Fenster vor der Entscheidung
liegt. `next_tradable` setzt Schlusskurs-Assets am Folgetag und Mittelwert-Assets am nächsten
Entscheidungsdatum um (`output/execution/TIMING.md`, `scripts/execution_timing_study.py`):

| Modul | Mittelwert-Assets | Studie (`same_close`) | **ehrlich (`next_tradable`)** | alles einen Monat später |
|---|---|---|---|---|
| Rohstoff-Trend | 9/9 | 0.742 | **0.423** | 0.423 |
| Multi-Asset | 2/6 | 0.571 | **0.557** | 0.534 |
| Multi-Asset Walk-forward (OOS) | 2/6 | 0.772 | **0.691** | 0.715 |
| Aktien-Exposure, Sektoren | 0 | 0.573, 0.590 | **unverändert** | 0.495, 0.521 |
| Gold/Silber-MR | 0 | 0.219 | **0.210** (= `next_close`) | 0.235 |

Der Rohstoff-Trend verliert gut 40 % seines Sharpe; das deckt sich mit der Forschung, die die Trendprämie von
Gold und Silber auf Monatsenden um 40–45 % kleiner misst als auf Monatsmitteln (`output/commodities/REPORT.md`
§3b). Für Risikobudgets und Erwartungen in Phase 3 zählen die ehrlichen Werte; beide sind in
`tests/golden/test_module_goldens.py` gepinnt.

## Befunde beim Bau

1. **Konfiguration wich von der Forschung ab** (ADR 035). Die Multi-Asset-YAML trug das Rezept der Sektor-
   Rotation; 0.570 stammt aus dem 5-Feature-z-Composite von `config.py`. Die Langfrist-Universen nannten
   TBILL als Cash (beginnt 1959, Aktien-Goldens ab 1927 brauchen den French-T-Bill), LBMA-Monatsenden statt
   der World-Bank-Mittel für die Rohstoffe. Korrigiert; Universen haben jetzt genau ein Cash-Asset (Cross-Check).
2. **Erste Rendite ging verloren** (ADR 037). Ein Index aus Periodenrenditen begann mit der ersten Rendite;
   die Juli-1926-Rendite fehlte und jedes French-Signal kam einen Monat zu spät (Aktien 0.568 statt 0.573).
   Der Index beginnt jetzt mit 100 eine Periode davor.
3. **Edelmetall-Satellit als Ganzes nie getestet** (ADR 040, offen). Gemessen in
   `output/precious/HEDGE_VARIANTS.md` (`scripts/precious_hedge_study.py`):

   | Variante | Sharpe | Max DD | Korrelation Aktien | Aktienmonate < −5 % p.a. |
   |---|---|---|---|---|
   | MR allein (Golden) | 0.22 | −35 % | −0.00 | +8.5 % |
   | MR + Basis 0.25 + bedingt (Konfiguration v1) | 0.11 | −53 % | −0.07 | +14.4 % |
   | MR + nur bedingt (Basis 0) | 0.18 | −41 % | −0.01 | +8.5 % |
   | nur Hedge (Basis 0.25 + bedingt) | −0.07 | −57 % | −0.15 | +9.2 % |

   Der Hedge kostet seit 1976 im Mittel Geld und halbiert den MR-Sharpe; er schützt etwas. Entscheidung nach dem
   Portfolio-Test des Combiners in Phase 3; bis dahin Konfiguration v1.
4. **Leistung.** Features einer Entscheidung lesen dasselbe Panel mehrfach → Total-Return- und Feature-Cache je
   View; täglicher Cash-Index über einen Sitzungs-Cache (Live-Universum 70 s → 6 s). Goldens: Aktien 17 s,
   Sektoren 17 s, Multi-Asset 16 s, Rohstoffe 6 s, Gold/Silber 15 s, Walk-forward (6 Kandidaten) 38 s; alle
   zusammen mit `rotationlab golden --walkforward` 96 s.

## Grenzen

- Das Live-Universum (ETFs) ist gebaut, aber ohne Live-Daten nur leer durchlaufen (alle Module im Warm-up):
  Yahoo/FRED waren in der Bauumgebung gesperrt. Der qualitative Vergleich ETF vs. Langfrist-Proxy (§13) folgt,
  sobald `network` und `daily` Daten liefern.
- Combiner mit Risikobudgets, Vol-Ziel, tägliche Risikoregeln, Stops und Kill-Switch sind Phase 3; die Module
  liefern Konfidenz und Stop-Regeln bereits mit (Gold/Silber: Ratio −15 % mit Einstiegsratio als Referenz).
- `cot_spec_net_z`, `tips_real_10y`, `breakeven_10y` haben im Forschungspanel keine Daten (live-only).

## Prüfliste für das Look-ahead-Audit (Fable)

Ergebnis: `AUDIT_phase2_lookahead.md` (2026-10-25, Erst- und Zweitprüfung) – kein Leck, das Goldens oder
Monatsentscheidungen verändert; zwei latente Lecks im Code behoben (Dividenden-Vintage im schnellen TR-Pfad,
NaN→„fallend“ in `_direction`; ADR 041); Monatsmittel als Signal und Ausführungspreis als materielle
Konvention – inzwischen umgesetzt (`next_tradable`, ADR 042, Abschnitt „Ehrliches Timing“). Belege in
`tests/lookahead/test_audit_phase2.py`; Truncation-Sweep über 85 Schnitte in `tests/golden/test_truncation_sweep.py`.

1. **as-of-Panel** (`features/_panel.py`): Monatsraster bis zum Monat von D, laufender Monat mit Label D. Zeigt
   eine Teilmonatszeile in der täglichen Schleife (Phase 3) je eine Information, die am Monatsende noch nicht
   feststand? Werden Teilmonate in rollierenden Fenstern wie volle Monate gezählt?
2. **Verschiebungen in Features** (CPI `shift(1)`, Shiller-Gewinne `shift(6)`, Regime `lag`, Dollar `usd_lag`):
   sind alle höchstens so lang wie der Store-Lag der Reihe, auch für die Live-Ketten (`macro:*`)?
3. **Expandierende Statistiken** (`ecy_percentile`, `risk_appetite`, `risk_appetite_pct`): Vergangenheitswerte
   werden auf dem as-of-Panel neu gerechnet – mit dem Datenstand von D, nicht dem von damals. Für revidierte
   Reihen (live: ALFRED, Shiller-Gewinne) ist das ein Unterschied; reicht der Hinweis?
4. **Base-100-Punkt** von Rendite-Indizes eine Periode vor der ersten Rendite (`data/view.py::_return_index`):
   existiert er nur, wenn die erste Rendite bekannt ist? Verschiebt er Fenster gegenüber den Studien?
5. **Engine-Preise** (`engine/core.py::prices_at`): letzter Wert ≤ Tag. Kann ein Monatswert, der am Folgetag
   der Entscheidung bewertet wird, dort schon einen späteren Wert sehen (verspätete Monatsreihen, French-Datei)?
6. **`next_close` an Monatsgrenzen**: Ausführungstag im Folgemonat – liest der Ausführungs-View neue
   Monatswerte (Label des neuen Monats), die die Entscheidung nicht kannte?
7. **Walk-forward** (`strategies/walkforward.py`): Schattenrenditen aus dem View bei D zwischen zwei
   Entscheidungsdaten; Wahl beim `min_train`-ten Entscheid. Gleiche Kostenkonvention wie der Lauf?
8. **Feature-Cache je View** (`registry.FeatureMeta.call`): Schlüssel aus Name, Assets, Parametern – kann ein
   Ergebnis zwischen Views oder zwischen Parametersätzen geteilt werden?
9. **Golden-Läufe** (`research_factory(data_from)`): Abschneiden ab dem Monat von `data_from` – ändert es
   etwas anderes als die Studien taten (z. B. Tagesreihen im ersten Monat)?
10. **Edelmetall-Satellit**: Tranchen im Zustand, Einstiegsratio bei Vorzeichenwechsel, Hedge-Zuschlag aus dem
   Perzentil des Risikoappetits – alles aus dem View bei D?
