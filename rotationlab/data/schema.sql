-- rotationlab point-in-time store: logical schema.
-- Physical storage (ADR 020): `observations` is an append-only log of gzip CSV files under
-- data/store/observations/ listed in manifest.json; `series` is written as data/store/series.csv;
-- quality_log/ingest_log are CSV files. Later phases (runs, signals, targets, risk_events, journal,
-- relationships) follow the same pattern. Any SQL engine can load the files; with DuckDB:
--   CREATE VIEW observations AS SELECT * FROM read_csv('data/store/observations/*.csv.gz');

CREATE TABLE IF NOT EXISTS series (
    series_id             VARCHAR PRIMARY KEY,     -- "yahoo:SPY:close", "fred:CPIAUCSL"
    provider              VARCHAR NOT NULL,        -- static | yahoo | stooq | fred | french | cftc
    provider_code         VARCHAR NOT NULL,
    kind                  VARCHAR NOT NULL,        -- price | dividend | split | total_return | return | yield | index | macro | positioning
    frequency             VARCHAR NOT NULL,        -- D | W | M | Q
    unit                  VARCHAR,
    asset_id              VARCHAR,                 -- NULL for pure macro
    lag                   VARCHAR NOT NULL DEFAULT '0D', -- '<n>D' days after obs_date, '<n>M' month-end n months later
    vintages              VARCHAR NOT NULL DEFAULT 'none', -- 'alfred' = real publication dates
    required              BOOLEAN NOT NULL DEFAULT FALSE,
    name                  VARCHAR,
    first_obs             DATE,
    last_obs              DATE
);

-- Every observation carries two dates. obs_date = END of the period the value is for.
-- vintage_date = when this value (this revision) became public knowledge.
-- Duplicate keys across files: the row with the later ingested_at wins.
CREATE TABLE IF NOT EXISTS observations (
    series_id     VARCHAR NOT NULL,
    obs_date      DATE    NOT NULL,
    vintage_date  DATE    NOT NULL,
    value         DOUBLE,
    ingested_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (series_id, obs_date, vintage_date),
    CHECK (vintage_date >= obs_date)
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id     VARCHAR PRIMARY KEY,
    name         VARCHAR NOT NULL,
    asset_class  VARCHAR NOT NULL,                 -- equity | bond | precious | energy | base_metal | agri | cash
    instrument   VARCHAR NOT NULL,                 -- etf | spot | future | index
    tradable     BOOLEAN NOT NULL,
    cost_bps     DOUBLE  NOT NULL,
    borrow_bps   DOUBLE  NOT NULL DEFAULT 0,
    proxy_of     VARCHAR                           -- long-history asset this instrument stands in for
);

CREATE TABLE IF NOT EXISTS runs (
    run_id         VARCHAR PRIMARY KEY,
    mode           VARCHAR NOT NULL,               -- backtest | walkforward | live
    started_at     TIMESTAMP NOT NULL,
    finished_at    TIMESTAMP,
    git_sha        VARCHAR NOT NULL,
    config_hash    VARCHAR NOT NULL,
    data_snapshot  TIMESTAMP NOT NULL,             -- max(observations.ingested_at) at run start
    start_date     DATE,
    end_date       DATE,
    seed           INTEGER,
    status         VARCHAR NOT NULL                -- running | ok | failed | halted
);

CREATE TABLE IF NOT EXISTS signals (
    run_id         VARCHAR NOT NULL,
    decision_date  DATE    NOT NULL,
    strategy_id    VARCHAR NOT NULL,
    asset_id       VARCHAR NOT NULL,
    target_weight  DOUBLE  NOT NULL,
    confidence     DOUBLE  NOT NULL,
    horizon_months INTEGER NOT NULL,
    diagnostics    JSON,
    PRIMARY KEY (run_id, decision_date, strategy_id, asset_id)
);

CREATE TABLE IF NOT EXISTS targets (
    run_id         VARCHAR NOT NULL,
    decision_date  DATE    NOT NULL,
    asset_id       VARCHAR NOT NULL,
    weight         DOUBLE  NOT NULL,
    scale          DOUBLE  NOT NULL,
    reason         VARCHAR,
    PRIMARY KEY (run_id, decision_date, asset_id)
);

CREATE TABLE IF NOT EXISTS risk_events (
    run_id   VARCHAR NOT NULL,
    at_date  DATE    NOT NULL,
    rule     VARCHAR NOT NULL,
    action   VARCHAR NOT NULL,
    scope    VARCHAR,
    factor   DOUBLE,
    detail   VARCHAR
);

-- Append-only. Corrections are new rows referencing `supersedes`.
CREATE TABLE IF NOT EXISTS journal (
    entry_id          VARCHAR PRIMARY KEY,
    decision_date     DATE    NOT NULL,
    asset_id          VARCHAR NOT NULL,
    target_weight     DOUBLE  NOT NULL,
    prev_weight       DOUBLE  NOT NULL,
    ref_price         DOUBLE,
    ref_price_date    DATE,
    strategy_breakdown JSON,
    note              VARCHAR,
    config_version    VARCHAR NOT NULL,
    realized_return   DOUBLE,                      -- filled at the next decision date
    supersedes        VARCHAR,
    written_at        TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_log (
    ingested_at  TIMESTAMP NOT NULL,
    series_id    VARCHAR,
    check_name   VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,                 -- ok | warn | blocking
    detail       VARCHAR
);

CREATE TABLE IF NOT EXISTS relationships (
    run_id   VARCHAR NOT NULL,
    as_of    DATE    NOT NULL,
    metric   VARCHAR NOT NULL,                     -- corr36 | beta120 | regime_ret | ic36 | hedge_eff | half_life | channel_corr
    a        VARCHAR NOT NULL,                     -- asset or feature
    b        VARCHAR,                              -- second asset, factor or regime label
    value    DOUBLE,
    stderr   DOUBLE,
    n        INTEGER,
    window   VARCHAR,
    PRIMARY KEY (run_id, as_of, metric, a, b)
);

-- Point-in-time read: latest revision of every observation that was public by $D.
-- This is the only query features and strategies ever see (through MarketView).
-- SELECT series_id, obs_date, value
-- FROM (
--   SELECT *, ROW_NUMBER() OVER (PARTITION BY series_id, obs_date ORDER BY vintage_date DESC) AS rn
--   FROM observations
--   WHERE obs_date <= $D AND vintage_date <= $D
-- ) WHERE rn = 1;
