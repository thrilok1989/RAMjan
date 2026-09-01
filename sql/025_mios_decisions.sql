-- 025_mios_decisions: the Decision Engine v0 log (for validation).
--
-- The Decision Engine consolidates the reads into one gated DECISION
-- (CALL / PUT / WAIT / STAND ASIDE / MANAGE) with a Quality grade (A+/A/B/C), the
-- gates that passed, the warnings, and — crucially — every REJECTION (spot was at
-- a zone, a trade was possible, but a gate blocked it) with the blocking reason.
--
-- Logging rejected opportunities is what lets us later learn "the Event Veto
-- prevented 73% of losing trades" / "ignoring Zone Health cut win-rate 71%→58%".
-- Observation only; v0 never drives the trade. One row per state change.
--
-- Run in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS mios_decisions (
    id            BIGSERIAL PRIMARY KEY,
    trading_day   TEXT,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decision      TEXT,                       -- CALL / PUT / WAIT / STAND ASIDE / MANAGE
    state         TEXT,                       -- WAIT / ARMED / CONFIRMED / IN_TRADE
    side          TEXT,                       -- CALL / PUT
    quality       TEXT,                       -- A+ / A / B / C (when actionable)
    quality_avg   DOUBLE PRECISION,
    rejected      BOOLEAN DEFAULT FALSE,       -- at a zone but a gate blocked it
    entry         DOUBLE PRECISION,
    target        DOUBLE PRECISION,
    stop          DOUBLE PRECISION,
    rr            DOUBLE PRECISION,
    confidence    DOUBLE PRECISION,
    zone_side     TEXT,                        -- SUPPORT / RESISTANCE
    zone_life     TEXT,                        -- building / holding / fading / …
    passed        TEXT,                        -- gates that passed
    warnings      TEXT,                        -- overlay warnings
    blocked_by    TEXT,                        -- the reason it's WAIT / rejected
    spot          DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_mios_decisions_ts ON mios_decisions (ts DESC);
CREATE INDEX IF NOT EXISTS idx_mios_decisions_day ON mios_decisions (trading_day);
CREATE INDEX IF NOT EXISTS idx_mios_decisions_rej ON mios_decisions (rejected);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS mios_decisions DISABLE ROW LEVEL SECURITY;
