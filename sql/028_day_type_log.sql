-- 028_day_type_log: Stage 68 Market Day Classification history.
--
-- One row every time the session CHANGES character — not one per cycle. The
-- classifier runs continuously, but the interesting record is the transition:
--
--   09:20 ↔ Range  →  10:45 🔄 Swing  →  13:10 📈 Trend  →  15:00 🧲 Expiry Pin
--
-- Append-only, like every other learning table. `previous_duration_min` is how
-- long the OUTGOING type held, which is what makes "how long does a trend day
-- usually last before it rotates?" answerable.
--
-- The Learning Engine joins this to `trade_results` on trading_day + time to
-- answer the question that actually changes behaviour: **which day types
-- produce the best performance, and which should be sat out.**
--
-- Run in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS day_type_log (
    id                    BIGSERIAL PRIMARY KEY,
    ts                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day           TEXT,
    previous_type         TEXT,     -- NULL on the session's first classification
    new_type              TEXT NOT NULL,
                          -- TREND / SWING / RANGE / CHOPPY / HIGH_VOLATILITY /
                          -- EXPIRY_PIN / NEWS_EVENT / LOW_PARTICIPATION
    confidence            DOUBLE PRECISION,
    previous_duration_min DOUBLE PRECISION,
    reason                TEXT,
    evidence              JSONB,    -- the signals behind the new classification
    groups_backing        INTEGER,  -- independent groups that agreed
    groups_available      INTEGER,  -- groups that could report at all
    -- TRUE when the type came from an external fact (live event, expiry pin)
    -- rather than from winning the vote
    forced                BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_day_type_day  ON day_type_log (trading_day);
CREATE INDEX IF NOT EXISTS idx_day_type_type ON day_type_log (new_type);
CREATE INDEX IF NOT EXISTS idx_day_type_ts   ON day_type_log (ts DESC);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS day_type_log DISABLE ROW LEVEL SECURITY;
