-- Initial schema: runs and their bots, trades, equity curves, risk events, price bars,
-- plus live-trading state (positions, kill switch).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE runs (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('backtest', 'paper', 'live')),
    started_at  timestamptz NOT NULL DEFAULT now(),
    params      jsonb NOT NULL DEFAULT '{}',
    start_date  date,
    end_date    date
);

CREATE TABLE bots (
    id             bigserial PRIMARY KEY,
    run_id         bigint NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    name           text NOT NULL,
    emoji          text NOT NULL DEFAULT '',
    status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'eliminated')),
    starting_cash  numeric NOT NULL,
    UNIQUE (run_id, name)
);

CREATE TABLE trades (
    id      bigserial PRIMARY KEY,
    bot_id  bigint NOT NULL REFERENCES bots (id) ON DELETE CASCADE,
    ts      timestamptz NOT NULL,
    symbol  text NOT NULL,
    side    text NOT NULL CHECK (side IN ('buy', 'sell')),
    shares  numeric NOT NULL,
    price   numeric NOT NULL,
    fee     numeric NOT NULL DEFAULT 0
);
CREATE INDEX trades_bot_ts_idx ON trades (bot_id, ts);

CREATE TABLE equity_snapshots (
    bot_id    bigint NOT NULL REFERENCES bots (id) ON DELETE CASCADE,
    ts        timestamptz NOT NULL,
    equity    double precision NOT NULL,
    exposure  double precision NOT NULL,
    PRIMARY KEY (bot_id, ts)
);
SELECT create_hypertable('equity_snapshots', by_range('ts'), if_not_exists => TRUE);

CREATE TABLE risk_events (
    id      bigserial PRIMARY KEY,
    bot_id  bigint NOT NULL REFERENCES bots (id) ON DELETE CASCADE,
    ts      timestamptz NOT NULL,
    kind    text NOT NULL,
    detail  text NOT NULL DEFAULT ''
);
CREATE INDEX risk_events_bot_ts_idx ON risk_events (bot_id, ts);

CREATE TABLE bars (
    symbol  text NOT NULL,
    ts      timestamptz NOT NULL,
    open    double precision NOT NULL,
    high    double precision NOT NULL,
    low     double precision NOT NULL,
    close   double precision NOT NULL,
    volume  double precision NOT NULL,
    PRIMARY KEY (symbol, ts)
);
SELECT create_hypertable('bars', by_range('ts'), if_not_exists => TRUE);

-- Live trading state (phases 4+).
CREATE TABLE positions (
    bot_id  bigint NOT NULL REFERENCES bots (id) ON DELETE CASCADE,
    symbol  text NOT NULL,
    shares  numeric NOT NULL,
    PRIMARY KEY (bot_id, symbol)
);

CREATE TABLE kill_switch (
    id          int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    engaged     boolean NOT NULL DEFAULT false,
    reason      text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO kill_switch (id) VALUES (1);
