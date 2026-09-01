-- 023_opening_auction_log: observation log for the opening auction on gap days.
--
-- Pure OBSERVATION — no prediction, no weighting. One row per trading day,
-- upserted through the session so it captures the opening classification AND
-- how the gap resolved (acceptance / fill) as the day develops. After a month
-- of real gap sessions this is the evidence to validate — and only then build —
-- the Gap-Behavior classifications (Gap-and-Go / Fill / Reversal) and the
-- Opening-Auction-Quality score. "Validate before you weight."
--
-- Run this in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS opening_auction_log (
    trading_day     TEXT PRIMARY KEY,          -- one row per session
    gap_type        TEXT,                       -- GAP-UP / GAP-DOWN
    gap_pct         DOUBLE PRECISION,           -- open vs prior close, %
    open_spot       DOUBLE PRECISION,           -- the ~09:06 opening print
    prev_close      DOUBLE PRECISION,
    prev_vah        DOUBLE PRECISION,           -- yesterday's value area
    prev_val        DOUBLE PRECISION,
    prev_poc        DOUBLE PRECISION,
    value_location  TEXT,                       -- inside / outside-above / outside-below
    fill_pct        DOUBLE PRECISION,           -- % of the gap retraced toward prev close (latest)
    acceptance      TEXT,                       -- accepted / partial-fill / filled-rejected (latest)
    last_spot       DOUBLE PRECISION,
    day_high        DOUBLE PRECISION,
    day_low         DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opening_auction_updated
    ON opening_auction_log (updated_at DESC);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS opening_auction_log DISABLE ROW LEVEL SECURITY;
