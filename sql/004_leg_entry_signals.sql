-- 🎯 Leg Entry Decision Engine — qualifying signals history
-- Run in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS leg_entry_signals (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day DATE        NOT NULL,
    leg         TEXT        NOT NULL,   -- e.g. 'ATM CE 24150'
    side        TEXT,                   -- CE | PE
    score       NUMERIC,
    confidence  NUMERIC,
    band        TEXT,                   -- GOOD / STRONG / VERY STRONG ...
    entry       NUMERIC,
    entry_src   TEXT,                   -- MFP20 POC / max-buy print / zone mid
    sl          NUMERIC,
    t1          NUMERIC,
    rr          NUMERIC,
    chase       TEXT,                   -- OK | WAIT
    ltp         NUMERIC,
    spot        NUMERIC,
    reasons     TEXT
);

-- fast lookup: day + newest first
CREATE INDEX IF NOT EXISTS idx_leg_entry_signals_day
    ON leg_entry_signals (trading_day, ts DESC);

-- optional purge of old rows (run manually or as a scheduled job)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM leg_entry_signals WHERE trading_day < CURRENT_DATE - INTERVAL '30 days';
