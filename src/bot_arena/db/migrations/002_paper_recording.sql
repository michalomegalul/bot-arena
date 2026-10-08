-- Recording a live paper run from the event log (pipeline/recorder.py).
-- event_id makes re-recording the same log events a no-op; backtest rows leave it NULL.

ALTER TABLE runs ADD COLUMN topic text UNIQUE;  -- the event log a paper run is recorded from
ALTER TABLE trades ADD COLUMN event_id text UNIQUE;
ALTER TABLE risk_events ADD COLUMN event_id text UNIQUE;

-- Where each log consumer resumes after a restart.
CREATE TABLE log_offsets (
    consumer     text PRIMARY KEY,
    next_offset  bigint NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);
