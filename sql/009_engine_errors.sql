-- ⚙️ MIOS V5 — Engine error log (Stage 0: System Health & Diagnostics).
-- Run in Supabase SQL Editor. Every engine failure/limitation is stored as a
-- structured row (spec rule: fail → Neutral + error record, never fake values).
-- severity=INFO rows are expected data-limits (e.g. no L2 depth at retail
-- Dhan), not alarms — the Error Monitor renders them separately.

CREATE TABLE IF NOT EXISTS engine_errors (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day DATE        NOT NULL,
    engine      TEXT        NOT NULL,   -- e.g. stage00_health, stage11_dealer
    error_type  TEXT,                   -- MISSING_API | MISSING_DATA | FAILED_FORMULA |
                                        -- TIMEOUT | INVALID_CALCULATION | DATA_LIMIT | STALE_DATA
    reason      TEXT,
    severity    TEXT,                   -- INFO | WARNING | ERROR | CRITICAL
    data_source TEXT,                   -- e.g. dhan:optionchain, supabase
    recovery    TEXT                    -- pending | retrying | recovered | permanent
);

CREATE INDEX IF NOT EXISTS idx_engine_errors_day
    ON engine_errors (trading_day DESC, ts DESC);
CREATE INDEX IF NOT EXISTS idx_engine_errors_engine
    ON engine_errors (engine, ts DESC);

-- optional purge (keep ~30 days)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM engine_errors WHERE trading_day < CURRENT_DATE - INTERVAL '30 days';
