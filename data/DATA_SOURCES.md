# Datenquellen und Konstruktion

Alle Rohdaten liegen in `data/raw/` (Stand Oktober 2026). Das Paket liest sie über `rotationlab/data/providers/static.py`
(Port von `scripts/build_dataset.py`, das mit dem ersten Forschungscode auf Branch `archive/legacy-research` liegt).
Alle Reihen sind auf **Monatsende** gestempelt.

## Rohquellen

| Datei | Inhalt | Quelle (Original) | Bezug | Frequenz | Abdeckung |
|---|---|---|---|---|---|
| `fred_md_2026-10.csv` | FRED-MD: 127 US-Makroreihen (Aktivität, Arbeitsmarkt, Preise, Zinsen, Geld, Dollar, S&P-Bewertung) | McCracken & Ng (2016), St. Louis Fed | Vintage aus [Sicco123/US-Macro-Forecast-Hub](https://github.com/Sicco123/US-Macro-Forecast-Hub) (target-data) | monatlich | 1959-01 – 2026-08 |
| `lbma_gold_daily.csv`, `lbma_silver_daily.csv` | LBMA Gold-PM-Fix und Silber-Fix in USD | LBMA | [unbalancedparentheses/forex-centuries](https://github.com/unbalancedparentheses/forex-centuries) | täglich | 1968 – 2026-02 |
| `wb_commodity_prices_monthly.xlsx` | World Bank "Pink Sheet": Rohstoffpreise und -indizes (Energie, Metalle, Agrar, Edelmetalle) | World Bank Commodity Markets | forex-centuries | monatlich (Durchschnitt) | 1960-01 – 2026-01 |
| `wb_gold_monthly.csv` | Gold, Monatsdurchschnitt | World Bank | [datasets/gold-prices](https://github.com/datasets/gold-prices) | monatlich | 1960 – 2026-09 |
| `us_market_data_daily.csv` | US-Aktien Total Return (S&P 500 inkl. Dividenden, SPY-ähnlich), T-Bill-Satz, CPI | Shiller, FRED, Yahoo | [SteelCerberus/us-market-data](https://github.com/SteelCerberus/us-market-data) | täglich | 1885 – 2025-12 |
| `shiller_sp500_monthly.csv` | Shiller: S&P 500 (Monatsdurchschnitt), Dividenden, Gewinne, CAPE, 10y-Rendite | R. Shiller | [datasets/s-and-p-500](https://github.com/datasets/s-and-p-500) | monatlich | 1871 – 2026-09 |
| `vix_daily.csv`, `vix_monthly.csv` | VIX Schlusskurse | CBOE | [datasets/finance-vix](https://github.com/datasets/finance-vix) | täglich | 1990 – 2026-09 |
| `wti_monthly.csv`, `brent_monthly.csv` | Rohöl WTI / Brent | EIA | [datasets/oil-prices](https://github.com/datasets/oil-prices) | monatlich | 1986/1987 – 2026-09 |
| `imf_commodity_prices_monthly.csv` | IMF Primary Commodity Prices (Indizes + 50 Einzelrohstoffe) | IMF | [datasets/commodity-prices](https://github.com/datasets/commodity-prices) | monatlich | 1990 – 2025-09 |
| `hy_oas_daily_1996_2021.csv` | ICE BofA US High Yield OAS (BAMLH0A0HYM2) | FRED | [csaladenes/eco-archive](https://github.com/csaladenes/eco-archive) | täglich | 1996-12 – 2021-03 |
| `fred_usd_major_index.csv` | Handelsgewichteter Dollar, Major Currencies (DTWEXM) | FRED | forex-centuries | täglich | 1973 – 2019 |
| `fred_usd_broad_index.csv` | Handelsgewichteter Dollar, Broad (DTWEXBGS) | FRED | forex-centuries | täglich | 2006 – 2025-12 |
| `ff_3_factors_monthly.csv` | Fama-French Markt (Mkt-RF), SMB, HML, RF | Kenneth French Data Library (CRSP 202607) | [ngweekiat/QF600_FactorNeutralPortfolioStressTest](https://github.com/ngweekiat/QF600_FactorNeutralPortfolioStressTest) | monatlich | 1926-07 – 2026-07 |
| `ff_10_industry_portfolios.csv` | 10 Branchen-Portfolios, value- und equal-weighted | Kenneth French Data Library (CRSP 202607) | dito | monatlich | 1926-07 – 2026-07 |
| `ff5_mom_monthly.csv.gz` | FF5 (Mkt, SMB, HML, RMW, CMA) + Momentum + RF | Kenneth French Data Library | [haribharadwaj/FamaFrench](https://github.com/haribharadwaj/FamaFrench) | monatlich | 1963-07 – 2026-08 |
| `cpi_nsa_monthly.csv` | CPI-U, nicht saisonbereinigt | BLS | [datasets/cpi-us](https://github.com/datasets/cpi-us) | monatlich | 1913 – 2026-08 |

Hinweis: Yahoo Finance und FRED waren aus der Build-Umgebung nicht direkt erreichbar; deshalb
Spiegelungen auf GitHub. `scripts/collect_data.py` lädt auf dem eigenen Rechner die aktuellen
Originalreihen (ETFs ab 2004, TIPS-Realzins, Breakevens, HY-Spread bis heute, NFCI usw.).

## Im Produktionssystem (`rotationlab`, Phase 1)

Alle Dateien oben liest der Static-Provider (`rotationlab/data/providers/static.py`) in den
Point-in-time-Store: 185 Reihen, 285 655 Zeilen, jede mit `obs_date` (Periodenende) und
`vintage_date` (ab wann bekannt). Konstrukte (GOLD mit World-Bank-Füllung vor 1968, TBILL, UST1/5/10,
USD_IDX, FF_MKT) werden mit denselben Formeln wie hier gebildet; `tests/golden/test_store_parity.py`
zeigt, dass der Store `assets_monthly.csv`, die Rohspalten von `macro_monthly.csv` (inkl. Sichtbarkeit
nach den Studien-Lags) und die French-Daten exakt reproduziert. Live kommen Yahoo, Stooq,
FRED/ALFRED, French und CFTC dazu (`configs/series.yaml`, `docs/ARCHITECTURE.md` §3).

Publikationslags im Store (Auszug; vollständig in `providers/static.py` und `configs/series.yaml`):

| Reihen | Lag | Begründung |
|---|---|---|
| Marktpreise, French-Renditen, World-Bank-Monatsmittel, Monatsmittel von Zinsen/FX, Shiller-Preis, VIX | `0D` | aus öffentlichen Preisen am Stichtag berechenbar |
| FRED-MD Aktivität, Arbeitsmarkt, Preise, Geld, Wohnungsbau | `1M` | Veröffentlichung im Folgemonat (= `shift(1)` der Studien) |
| Persönliche Einkommen/Konsum (PCE), Auftragseingänge M3, Lager, Konsumentenkredit | `2M` | Veröffentlichung > 4 Wochen nach Monatsende |
| Shiller-Gewinne und -Dividenden, CAPE, S&P-KGV und -Dividendenrendite (FRED-MD) | `6M` | quartalsweise interpoliert, Audit 2026-10-24 |
| ICE HY-OAS | `1D` | erscheint am nächsten Morgen |

### Echte FRED-MD-Vintages (`data/raw/fredmd_vintages/`)

| Datei | Vintage | ab | Quelle |
|---|---|---|---|
| `2019-09.csv` | 2019-09 (aus dem Inhalt erschlossen: letzte Beobachtung 2019-08 inkl. Einkommen vom 27.09.2019) | 2019-10-07 | [bashtage/python-introduction](https://github.com/bashtage/python-introduction) |
| `2021-04.csv` | 2021-04 (offizieller Dateiname) | 2021-05-07 | [elmarmertens/CCMMoutlierVAR-code](https://github.com/elmarmertens/CCMMoutlierVAR-code) |
| `2026-10.csv` | 2026-10 (Snapshot vom 10.10.2026) | 2026-10-10 | [Sicco123/US-Macro-Forecast-Hub](https://github.com/Sicco123/US-Macro-Forecast-Hub) |

Daraus entstehen die Echtzeitreihen `static:fredmd_rt:*`; `rotationlab fredmd-archive` ergänzt das Archiv
(monatlich seit 1999-08) dort, wo die St. Louis Fed erreichbar ist. Auswertung: `scripts/revision_study.py`.

### Live-Quellen ab der Optimierung

- **BLS** Public Data API v2 (CPI-U SA, Kern-CPI, Arbeitslosenquote, Beschäftigung) als zweite Quelle der Makroketten.
- **Shiller** `ie_data.xls` (Yale; URL konfigurierbar) für aktuelle S&P-Gewinne und CAPE; der GitHub-Spiegel oben
  meldet Gewinne nur bis 2023-06 und bleibt Rückfallquelle in `macro:SP_EARNINGS`.

Bekannte Eigenheiten, die die Qualitätschecks sichtbar machen: der VIX-Spiegel hat 4 fehlende
Sitzungen (1991-03-01, 1997-01-31, 1997-11-26, 1999-12-31) und 34 Werte an NYSE-Feiertagen (CBOE
rechnet seit 2022 an manchen Feiertagen); die S&P-Total-Return-Rekonstruktion hat 110 Tage vor 1990,
an denen die TR-Rendite bis 0.26 % unter der Preisrendite liegt.

## Konstruierte Reihen (`assets_monthly.csv`)

| Spalte | Konstruktion |
|---|---|
| `US_EQ` | Adjusted Close aus us-market-data (Kurs + Dividenden), letzter Handelstag des Monats |
| `UST10`, `UST5`, `UST1` | Synthetischer Total Return aus Constant-Maturity-Renditen (GS10/GS5/GS1): monatlich Kauf einer Par-Anleihe zur aktuellen Rendite, Bewertung nach einem Monat zur neuen Rendite plus Kuponabgrenzung (Standardansatz, vgl. Swinkels 2019). Fehler ggü. echten Indizes typ. < 0.5 % p.a. |
| `TBILL` | Kumulierter Index aus TB3MS (Vormonatssatz / 12) |
| `GOLD` | LBMA PM-Fix USD, letzter Fix des Monats; vor 1968-04 World-Bank-Monatsdurchschnitt (Preis fix 35 $) |
| `SILVER` | LBMA Silber-Fix USD, letzter Fix des Monats |
| `WB_ENERGY`, `WB_BASEMETALS`, `WB_METALS`, `WB_AGRI`, `WB_NONENERGY`, `WB_TOTAL`, `WB_PRECIOUS` | World-Bank-Preisindizes (2010 = 100), **Monatsdurchschnitte**, Spot (ohne Roll- und Collateral-Rendite) |
| `WB_OIL`, `WB_COPPER`, `WB_PLATINUM`, `WB_GOLD_AVG`, `WB_SILVER_AVG` | World-Bank-Einzelpreise, Monatsdurchschnitte |

## Makropanel (`macro_monthly.csv`), Auswahl

Aktivität: `INDPRO`, `CAPUTIL`, `PAYEMS`, `UNRATE`, `CLAIMS`, `HOUST`, `PERMIT`, `DURGOODS_ORD`, `RETAIL`, `REAL_INCOME`, `UMCSENT`
Preise: `CPI`, `CPI_CORE`, `PCE`, `PPI_METALS`, `OIL_FRED`; abgeleitet `CPI_YOY`, `CPI_CORE_YOY`, `CPI_3M_ANN`, `PCE_YOY`
Zinsen: `FEDFUNDS`, `TB3M`, `TB6M`, `GS1`, `GS5`, `GS10`, `AAA`, `BAA`; abgeleitet `REAL_GS10` (= GS10 − CPI yoy), `REAL_FF`, `CURVE_10Y3M`, `CURVE_10Y1Y`, `CREDIT_BAA_AAA`, `CREDIT_BAA_GS10`
Risiko/Dollar: `VIX` (Monatsende), `VIX_AVG` (FRED-MD, Monatsdurchschnitt; vor 1990 aus S&P-Volatilität rückgerechnet), `HY_OAS`, `USD_IDX` (DTWEXM bis 2005, dann DTWEXBGS verkettet), `USD_TW_AVG`, `USDCHF`, `USDJPY`, `GBPUSD`
Bewertung: `SP_DIVYIELD`, `SP_PE`, `SHILLER_CAPE`, `SHILLER_EPS`
Sonstiges: `M2`, `M2_YOY`, `BUSLOANS`, `GOLD_SILVER_RATIO`

## Bekannte Schwächen (im Interview ansprechen!)

1. **Monatsdurchschnitte** bei World-Bank-Indizes erzeugen künstliche Autokorrelation (Working-Effekt). Das Modell nutzt deshalb Momentum mit 1-Monats-Skip; alle Kernaussagen werden zusätzlich mit dem Monatsend-Universum (Aktien, Treasury, Gold, Silber) geprüft.
2. **Spot statt investierbar**: Energie-/Metallindizes enthalten keine Roll- und Collateral-Rendite. Gold/Silber sind als Spot (ETF-ähnlich, ohne Lagerkosten ~0.2–0.4 % p.a.) in Ordnung.
3. **Makro-Revisionen**: FRED-MD ist die aktuelle (revidierte) Vintage. Für echte Echtzeit-Tests ALFRED-Vintages verwenden. Das Modell verschiebt Makrosignale um einen Monat (Publikationslag), das Revisionsproblem bleibt.
4. **Ex-post-Realzins** (nominal − realisierte Inflation) statt Markt-Realzins (TIPS ab 2003). Letzterer kommt über `collect_data.py` (DFII10) dazu.
5. **Survivorship/Auswahl**: Universum ex post gewählt (Gold, Silber, Energie ... ), kein Universum, das 1973 jemand so gehandelt hätte.
6. **HY-Spread** endet 2021-03 (Spiegelung); Fortsetzung über `collect_data.py`.

### Assets für Phase 2 (universe.yaml)

- `FF_RF` – French 1-Monats-T-Bill (Rendite), Cash der Aktien- und Sektor-Goldens ab 1926.
- `WB_GOLD_AVG`, `WB_SILVER_AVG` – World-Bank-Monatsmittel; mit den übrigen WB-Reihen der konsistente Querschnitt der Rohstoffstudie.
- `XAU`, `XAG` – Gold- und Silber-Spot für die Ratio-Signale: Kette `[yahoo:GC=F|SI=F, static:lbma:GOLD|SILVER]` (täglich, Verhältnis-Spleiss; Futures-Rolls verschieben die Ratio um Zehntelprozente, für einen 60-Monats-z-Score unerheblich).
- Makroketten mit statischem FRED-MD als letztem Glied (`macro:INDPRO`, `macro:GS10`, `macro:BAA`, `macro:AAA`, `macro:FEDFUNDS`, `macro:TB3MS`, `macro:VIX`, `macro:SP_RATE`; `macro:CPI`, `macro:UNRATE`, `macro:PAYEMS` erweitert): live liest das Feature FRED/BLS, im Forschungspanel die eingefrorene Kopie. Kern-CPI hat keinen FRED-MD-Ersatz (FRED-MD führt nur „CPI ohne Nahrungsmittel“).

## P5: Monatsend-Schnitt des Live-Stores (`p5_live_monthend.csv.gz`)

Erzeugt von `scripts/p5_extract_live_monthend.py` aus dem Live-Store (GitHub-Branch `data`, Stand 2026-10-26; Yahoo,
FRED). Je Reihe ein Wert pro Monatsende: letzter Tagesschluss des Monats (jüngste Vintage je Beobachtung); für SPY,
IEF, TLT zusätzlich ein Total-Return-Index aus Schlusskursen plus Bardividenden (`rotationlab.data.view._close_tr`);
`DGS10_ME`, `DGS2_ME`, `DGS3MO_ME` = Constant-Maturity-Renditen (10 J., 2 J., 3 M.) am Monatsende. Eingabe für `scripts/forecast_investability.py`
(Investierbarkeit, Abnahme `docs/FORECAST_ABNAHME.md` P5) und seit ADR 047 Quelle der statischen Reihe
`static:fred:DGS10_ME` (Monatsrendite, Lag 0D wie alle Marktpreise des statischen Providers) und der Par-Bond-
Konstruktion `static:UST10_ME` (Asset `UST10_ME`, dieselbe Formel wie `static:UST10`); seit ADR 052 ebenso
`static:fred:DGS2_ME` → `static:UST2_ME` (Asset `UST2_ME`, Par-Bond 2 J., ab 1976-07; Live-Bein `SHY`) und
`static:fred:DGS3MO_ME` als Datenreihe; die übrigen Spalten bleiben Skript-Eingabe. Der laufende Monat des Extrakts (Zeile nach dem Stand) wird vom Provider verworfen; das Skript labelt
ihn seither nicht mehr.

## Runde 4: Forschungsdaten über den Workflow `research-data` (ADR 057)

Die Arbeitsumgebung der Forschung erreicht weder FRED noch die French-Bibliothek. Die Rohdateien für Runde 4 holt
deshalb einmalig der von Hand gestartete Workflow `.github/workflows/research-data.yml` mit
`scripts/fetch_research_data.py`: jede Antwort Byte für Byte (gzip), dazu `MANIFEST.json` mit Quell-URL (API-Schlüssel
geschwärzt), SHA-256 und Grösse der Rohbytes, Abrufzeit (UTC), Format und Status; alles auf dem Orphan-Branch
`research-data`. Der Workflow berührt weder Store noch Journal noch den Tageslauf.

| Quelle | Reihen | Pflicht |
|---|---|---|
| FRED H.10, täglich | DEXJPUS, DEXUSUK, DEXSZUS, DEXCAUS, DEXUSAL, DEXUSNZ, DEXSDUS, DEXNOUS, DEXUSEU (ab 1999) | ja |
| FRED H.10, täglich | DEXGEUS (DEM, bis 2001; Verkettung des Euro vor 1999) – seit dem 28.10.2026 von FRED nicht mehr geliefert (HTTP 400), ohne sie beginnt der Euro 1999 (ADR 059) | nein |
| FRED, täglich | DGS2, DGS5, DGS10 (Constant-Maturity-Renditen) | ja |
| FRED/OECD, monatlich | IR3TIB01{JP,GB,CH,CA,AU,NZ,SE,NO,DE,EZ}M156N (3-M-Interbank), IRSTCI01{…}M156N (Tagesgeld, Ersatz) | nein |
| Kenneth French | `10_Industry_Portfolios_daily_CSV.zip`, `F-F_International_Countries.zip` | ja |

`scripts/freeze_research_data.py --src <Checkout des Branches> --commit <SHA>` prüft jede Datei gegen das Manifest
(eine geänderte Zahl stoppt), verlangt alle Pflichtquellen und schreibt kompakte, deterministische Dateien nach
`data/raw/` (`r4_fred_daily.csv.gz`, `r4_oecd_rates_monthly.csv.gz`, `ff_10_industry_daily.csv.gz`,
`ff_intl_countries_monthly.csv.gz`) samt `r4_PROVENANCE.json` (Commit, Manifest, je Ausgabe Zeilen, erstes/letztes
Datum, SHA-256). Die Rohdateien bleiben auf dem Branch als Beleg. Lags: Spot und Renditen 0D (Marktpreise), OECD-Zinsen
1M (Monatswerte erscheinen im Folgemonat). Das Format der Länderdatei beschreibt die French-Seite nicht; der Parser wird
nach dem ersten Blick auf die echte Datei geschrieben (`--describe`), die Regel bei fehlender Marktspalte steht in ADR 057 (h).

**Präzisiert vor dem Download (ADR 058):** eingefroren wird der früheste vollständige Commit von `research-data`.
Länder: alle Länder der Datei in ihrer Reihenfolge, je Land `Mkt` der umfassenderen Gruppe (alle Firmen mit B/M-Daten),
keine US-Spalte; USD wird geprüft (`scripts/r4_data_check.py`, G5). Währungs-Einlagenindizes beginnen erst 1991-01
(Kapitalverkehrskontrollen: Schweden baute seine Devisenkontrollen 1986–1990 ab, Norwegen bis Ende der 1980er-Jahre);
ein Monatszins gilt bis drei Monate nach seinem Referenzmonat. Cash und Finanzierung in Runde 4: `TBILL_IY`, die
Investitionsrendite von TB3MS (Diskontbasis → Investitionsrendite eines 91-Tage-Papiers).

Verfügbarkeit der Zinsreihen laut FRED (Seiten abgerufen am 27.10.2026, nur Datumsbereiche – keine Werte): 3-M-Interbank
JP 2002-04 bis 2026-08 (Tagesgeld ab 1985-07), GB 1957-01 bis 2026-01, CH 1999-07 bis 2026-09 (Tagesgeld 1972-01 bis
2024-03), CA 1956-01 bis 2026-09, AU 1968-01 bis 2026-08, NZ 1973-12 bis 2026-09, SE 1982-01 bis 2026-09 (Tagesgeld 1955-01
bis 2020-10), NO 1979-01 bis 2026-08 (Tagesgeld ab 1982-01), DE 1960-01 bis 2026-09 (Tagesgeld ebenso), Euroraum 1994-01
bis 2026-01. Ab 1991 haben damit alle neun Währungen einen Zins; GB und Euroraum enden im Januar 2026 (ihre Indizes
enden drei Monate später, nach dem Fensterende).
