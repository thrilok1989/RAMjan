-- 024_event_impact_log: the Event History Library.
--
-- MIOS Stage-33 measures whether an event actually changed market structure
-- (gap / volume / gamma flip / dealer hedge / institution flow → LOW..VERY HIGH).
-- This logs each measured event so that, over months, "how does today compare to
-- past RBI / Fed / expiry days?" becomes answerable from YOUR OWN data — not
-- textbook assumptions. Pure observation: measure the effect → log it → weight
-- later. One row per (trading_day, event), upserted through the session so it
-- captures the peak impact as the day develops.
--
-- Run this in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS event_impact_log (
    trading_day    TEXT NOT NULL,
    event_name     TEXT NOT NULL,
    trigger        TEXT,                       -- shock / calendar / preparation
    impact         TEXT,                       -- LOW / MEDIUM / HIGH / VERY HIGH
    impact_score   DOUBLE PRECISION,           -- 0-100
    signal_count   INTEGER,
    signals        TEXT,                        -- the structure signals that fired
    reaction       TEXT,                        -- from Stage 28 when a shock
    spot           DOUBLE PRECISION,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trading_day, event_name)
);

CREATE INDEX IF NOT EXISTS idx_event_impact_updated
    ON event_impact_log (updated_at DESC);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS event_impact_log DISABLE ROW LEVEL SECURITY;
