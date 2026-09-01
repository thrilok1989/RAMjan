-- 029_session_log: Stage 69 Market Session Intelligence history.
--
-- One row per pipeline cycle while the market is open — this is deliberately
-- denser than the day-type log, because the question it has to answer is
-- "which SESSIONS produce wins, and were the published modifiers right?" and
-- that needs the measures as they stood, not just the transitions.
--
-- `modifiers_applied` is the row that matters most. Stage 69 publishes its
-- contextual modifiers but does NOT apply them (session.SESSION_AWARE is
-- False) until live data shows the session-adjusted stack beats the flat one.
-- Logging both the modifier set and whether it was live is what makes that
-- comparison possible later: every row records what MIOS would have done.
--
-- Append-only. Run in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS session_log (
    id                 BIGSERIAL PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day        TEXT,
    session            TEXT NOT NULL,
                       -- PRE_OPEN / OPENING_AUCTION / OPENING_DRIVE /
                       -- MORNING_TREND / MIDDAY_BALANCE / AFTERNOON_TREND /
                       -- CLOSING / CLOSED
    behaviour          TEXT,
                       -- TRENDING / SIDEWAYS / CHOPPY / EXPANDING /
                       -- COMPRESSING / EXPIRY / RANGE_BUILDING /
                       -- TREND_BUILDING / TREND_EXHAUSTION
    conviction         DOUBLE PRECISION,   -- carried from Stage 6, not recomputed
    minutes_remaining  INTEGER,
    measures           JSONB,   -- the nine session measures, as read
    measures_available INTEGER, -- how many engines actually reported
    modifiers          JSONB,   -- what Stage 69 published for each engine
    modifiers_applied  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_session_log_day     ON session_log (trading_day);
CREATE INDEX IF NOT EXISTS idx_session_log_session ON session_log (session);
CREATE INDEX IF NOT EXISTS idx_session_log_ts      ON session_log (ts DESC);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS session_log DISABLE ROW LEVEL SECURITY;
