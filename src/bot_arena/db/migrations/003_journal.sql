-- What LLM bots decided and why (the "AI Journal" in the UI).
CREATE TABLE journal (
    id          bigserial PRIMARY KEY,
    bot_id      bigint NOT NULL REFERENCES bots (id) ON DELETE CASCADE,
    ts          timestamptz NOT NULL,      -- the close the decision was made after
    model       text NOT NULL,
    targets     jsonb,                     -- weights after cleanup; NULL = held (the model failed)
    reasoning   text NOT NULL DEFAULT '',
    confidence  double precision,
    notes       jsonb NOT NULL DEFAULT '[]',  -- what the cleanup had to fix
    stats       jsonb NOT NULL DEFAULT '{}',  -- tokens, seconds
    UNIQUE (bot_id, ts)
);
