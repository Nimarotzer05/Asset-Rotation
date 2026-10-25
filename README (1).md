# Cross-Asset Rotation Model

> **Neu: `rotationlab`** – das Produktionssystem. Phase 0 (Gerüst), Phase 1 (Datenschicht) und Phase 2 (Features,
> Module, Engine) sind gebaut: Point-in-time-Store mit Vintages, acht Provider, `MarketView`; 33 registrierte Features,
> fünf Strategie-Module und Walk-forward, eine Engine für Backtest/Walk-forward/Live; die Engine reproduziert alle
> Forschungskennzahlen aus dem Store (Sharpe ≤ 0.002, Gewichte ≤ 1e-9; `docs/PHASE2_ABNAHME.md`). 268 Tests (davon 20 Golden),
> Abdeckung 97 %, ruff und mypy strict ohne Befund; Fable-Review der Vintage-Logik bestanden (`docs/AUDIT_phase1_vintage.md`),
> Look-ahead-Audit von Features, Modulen und Engine in zwei Durchgängen (`docs/AUDIT_phase2_lookahead.md`, ADR 041).
> Architektur `docs/ARCHITECTURE.md`, Entscheidungen `docs/ADR.md`, Betrieb `docs/RUNBOOK.md`.
>
> ```bash
> python -m rotationlab.cli validate                                   # 58 Assets, 478 Reihen
> python -m rotationlab.cli ingest --full --provider static            # Forschungshistorie in den Store
> python -m rotationlab.cli asof --date 2008-06-30 --series static:fredmd:CPIAUCSL   # was war damals bekannt?
> python -m rotationlab.cli calendar --year 2026                       # Entscheidungs- und Ausführungstage
> python -m rotationlab.cli store health                               # Datenqualität im Verlauf
> python scripts/revision_study.py                                     # was Revisionen an den Makrosignalen ändern
> python -m rotationlab.cli golden --walkforward                       # alle Module gegen die Forschung
> python -m rotationlab.cli backtest --strategy us_equity_exposure     # ein Modul durch die Engine, Run-Record
> ```
> Die Studien unten bleiben als Forschung erhalten; die Module in `rotationlab/strategies/` sind ihre Produktionsfassung.


Systematisches Modell, das monatlich die relative Attraktivität von Anlageklassen (Aktien, Treasuries,
Gold, Silber, Energie, Basismetalle; alternativ ein ETF-Universum) bewertet und ein Portfolio aus den
stärksten Assets bildet. Signale: Momentum, Trend, Volatilität und ein Makro-Regime
(Wachstum × Inflation). Dazu eine vollständige statistische Studie auf 53 Jahren Daten (1973–2025):
Regime-Renditen, Treiber-Regressionen, Information Coefficients, Walk-forward-Backtest, Sensitivität.

**Ergebnisse:** `output/long/REPORT.md` (Tabellen + Grafiken). Datenquellen: `data/DATA_SOURCES.md`.

## Struktur

```
asset-rotation/
├── run.py                      # Schneller Backtest (--dataset long | etf | synthetic)
├── config.py                   # Universen, FRED-Reihen, Parameter, Kosten, Regime-Tilts
├── scripts/
│   ├── build_dataset.py        # Rohquellen (data/raw) → data/assets_monthly.csv, data/macro_monthly.csv
│   ├── collect_data.py         # Yahoo + FRED auf dem eigenen Rechner laden (ETFs, TIPS, HY-Spread, ...)
│   ├── run_analysis.py         # Vollständige Studie → output/long/REPORT.md + CSV + PNG
│   ├── run_commodities.py      # Rohstoff-Rotation + Wegweiser → output/commodities/REPORT.md
│   └── run_gold_silver.py      # Gold/Silber-Spread: Signale, Mean Reversion, Wegweiser → output/gold_silver/REPORT.md
├── src/
│   ├── data.py                 # Laden der drei Datensätze
│   ├── features.py             # Asset-Features, Makro-Features, Regime-Definitionen
│   ├── signals.py              # z-Score-Composite → Top-N, inverse Vol, Trendfilter
│   ├── backtest.py             # Rebalancing, Kosten, synthetische Benchmarks, Walk-forward
│   ├── metrics.py              # Sharpe (ex Cash), Drawdown, Calmar, Turnover, Regime-Breakdown
│   └── analysis.py             # Regime-Tabellen, OLS mit Newey-West, ICs, Mean-Reversion, Sensitivität
├── data/
│   ├── raw/                    # Rohquellen (FRED-MD, LBMA, World Bank, Shiller, VIX, ...)
│   ├── assets_monthly.csv      # Monatspanel Anlageklassen 1960–2025
│   ├── macro_monthly.csv       # Monatspanel Makro/Zinsen/Risiko 1959–2026
│   ├── coverage.csv            # Start/Ende jeder Reihe
│   └── DATA_SOURCES.md         # Herkunft, Konstruktion, bekannte Schwächen
├── output/long/                # Multi-Asset-Studie: REPORT.md, CSV, PNG
└── output/commodities/         # Rohstoff-Rotation: REPORT.md, CSV, PNG
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                       # Backtest auf dem Langfrist-Panel (offline)
python scripts/run_analysis.py      # vollständige Studie (ca. 3–4 Minuten)
python scripts/run_gold_silver.py    # Gold/Silber-Pair-Trade: wann long Gold / short Silber?
python scripts/run_commodities.py   # Rohstoff-Rotation (Gold, Silber, Platin, Öl, Gas, Kupfer, Alu, Nickel, Agrar) + Wegweiser
python scripts/collect_data.py      # optional: aktuelle Yahoo/FRED-Daten laden (Internet)
python run.py --dataset etf         # ETF-Universum ab 2004
```

## Methodik (Kurzfassung)

1. **Daten:** Monatsendpanel aus FRED-MD (127 Makroreihen), LBMA Gold/Silber, World-Bank-Rohstoffindizes,
   S&P 500 Total Return, synthetische Treasury-Returns aus CMT-Renditen, VIX, Dollar-Index, Kreditspreads.
2. **Features (nur Vergangenheitsdaten):** Momentum 3/6/12M mit 1-Monats-Skip, Abstand zum 10M-Schnitt,
   inverse 12M-Vol, relative Stärke. Makro: Realzins, Dollar, Inflation, Kreditspread, Zinskurve, VIX
   (Niveau, Änderung, rollierender z-Score).
3. **Regime:** Trendrichtung von Industrieproduktion (yoy) × CPI (yoy) → 4 Quadranten, um einen Monat
   verzögert. Zusätzlich binäre Regimes (Realzins, Dollar, Zinskurve, Kredit, Fed Funds, VIX).
4. **Signal:** z-Standardisierung über Assets, gewichtete Summe, optional Regime-Tilt (a-priori gesetzt,
   nicht gefittet). Top-N, inverse-Vol-Gewichtung, Trendfilter (unter 10M-Schnitt → T-Bills).
5. **Backtest:** Monatsende-Rebalancing, 15 bp Kosten auf Turnover, Sharpe stets auf Überschussrendite
   über T-Bills. Walk-forward: erstes Fenster 10 Jahre, Parameter jährlich neu auf Vergangenheit gewählt.
   Benchmarks: Equal Weight, 60/40, US-Aktien, Gold, T-Bills.
6. **Statistik:** Renditen je Regime mit t-Werten, OLS der Überschussrenditen auf Faktoränderungen
   (Newey-West), Information Coefficients (Spearman), Tercil-Spreads, AR(1)-Halbwertszeit der
   Gold/Silber-Ratio, Sensitivitäts-Heatmaps.

## Zentrale Befunde (1973–2025)

- Rotation (Top-3, Trendfilter): 11.9 % p.a., Vol 13.5 %, Sharpe ex Cash 0.57, Max-DD −24 %;
  60/40: 9.4 %, Sharpe 0.51, Max-DD −29 %; Equal Weight: Sharpe 0.40. Walk-forward OOS 1983–2025:
  Sharpe 0.77, Max-DD −11 % (wählt durchgehend Top-4 + Trendfilter).
- 12M-Momentum ist das stärkste Querschnittssignal (IC 0.07–0.10, t ≈ 3.4–3.7); inverse Vol und
  36M-Reversal haben keinen Erklärungswert.
- Gold: beste Überschussrendite in "Wachstum fällt, Inflation steigt" (+9.5 % p.a.) und bei fallenden
  Fed Funds; negativ in "Wachstum steigt, Inflation fällt" (−6 % p.a.). Dollar ist der stabilste
  Treiber (t ≈ −7); der "Realzins"-Kanal war in den 1970/80ern ein Inflationskanal, seit 2006 ein
  Nominalzinskanal.
- Gold/Silber-Ratio: Halbwertszeit ≈ 29 Monate, nicht signifikant stationär; kein verlässliches
  Timing-Signal für Silber vs. Gold.
- Basismetalle: einziges Asset mit klarem Wachstumsbezug (+13.6 % p.a. in "Wachstum + Inflation steigen", t = 3.3).

## Bekannte Limitationen (ehrlich bleiben!)

- World-Bank-Rohstoffindizes sind Monatsdurchschnitte (künstliche Autokorrelation) und Spotpreise
  (keine Roll-/Collateral-Rendite). Kernaussagen werden mit dem Monatsend-Universum gegengeprüft.
- Makrodaten sind revidierte Endstände (FRED-MD); echte Echtzeit-Tests bräuchten ALFRED-Vintages.
- Ex-post-Realzins statt TIPS; Markt-Realzins und Breakevens erst ab 2003 (über `collect_data.py`).
- Universum ex post gewählt; Transaktionskosten pauschal; keine Steuern, Slippage, Finanzierung.
- Regime-t-Werte sind wegen Autokorrelation der Regimes optimistisch.
