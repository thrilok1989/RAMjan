-- 030_session_validation: Stage 70 Session Intelligence Validation.
--
-- Stage 69 publishes contextual modifiers and applies none of them. This is
-- where the evidence for ever applying them accumulates.
--
-- `session_recommendations` stores every recommendation WITH the win rate it
-- was made at. That is the whole point of Part 6: comparing a recommendation
-- to what the session did AFTERWARDS is the only way to tell a genuine session
-- edge from a run of luck that has since reverted. A recommendation stored
-- without the number it was made on cannot be scored later.
--
-- Append-only. Nothing here is ever applied automatically — `applied` exists
-- so a human's decision is recorded, not so the system can set it.
--
-- Run in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS session_recommendations (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day   TEXT,
    key           TEXT NOT NULL,      -- WINDOW|CONDITION, e.g. MIDDAY_BALANCE|NORMAL
    -- NOT `window` — WINDOW is a reserved word in Postgres and will not parse
    -- unquoted. Renamed rather than quoted so no caller has to remember.
    session_window TEXT,              -- Stage 69 session window
    label         TEXT,
    win_rate      DOUBLE PRECISION,   -- the rate this was recommended ON
    sample        INTEGER,            -- graded trades behind it
    recommend     JSONB,              -- what to do
    avoid         JSONB,              -- what not to do
    source        TEXT,               -- measured / a-priori
    applied       BOOLEAN NOT NULL DEFAULT FALSE,
    applied_at    TIMESTAMPTZ,
    applied_by    TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_rec_key ON session_recommendations (key);
CREATE INDEX IF NOT EXISTS idx_session_rec_day ON session_recommendations (trading_day);

-- The counterfactual, snapshotted so the comparison itself has a history:
-- "what did MIOS believe about its own session modifiers last month, and was
-- that right?" A validation with no memory can drift without anyone noticing.
CREATE TABLE IF NOT EXISTS session_validation_log (
    id                      BIGSERIAL PRIMARY KEY,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day             TEXT,
    sample                  INTEGER,   -- graded trades in the WITHOUT arm
    kept_sample             INTEGER,   -- graded trades left in the WITH arm
    win_rate_without        DOUBLE PRECISION,
    win_rate_with           DOUBLE PRECISION,
    improvement_pct         DOUBLE PRECISION,
    false_signal_reduction  INTEGER,   -- losers the modifiers would have removed
    winners_lost            INTEGER,   -- winners they would have removed too
    avg_profit_increase     DOUBLE PRECISION,
    avg_drawdown_reduction  DOUBLE PRECISION,
    significant             BOOLEAN NOT NULL DEFAULT FALSE,
    promotable              BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE always, for now: the modifiers were designed before this history
    -- and evaluated against it. Recorded so a future out-of-sample run is
    -- distinguishable from these.
    in_sample               BOOLEAN NOT NULL DEFAULT TRUE,
    verdict                 TEXT,
    payload                 JSONB
);

CREATE INDEX IF NOT EXISTS idx_session_val_day ON session_validation_log (trading_day);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS session_recommendations  DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS session_validation_log   DISABLE ROW LEVEL SECURITY;
