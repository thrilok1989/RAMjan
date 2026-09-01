-- 📝 MIOS V5 — My Analysis notes (Stage 41 §My Analysis).
-- Run in Supabase SQL Editor. The trader's own pre-market / live / post-market
-- notes, stored permanently, one row per (trading_day, section). Upserted so
-- editing the same section on the same day overwrites in place.

CREATE TABLE IF NOT EXISTS my_analysis (
    trading_day DATE        NOT NULL,
    section     TEXT        NOT NULL,   -- premarket | live | postmarket
    note        TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trading_day, section)
);

CREATE INDEX IF NOT EXISTS idx_my_analysis_day
    ON my_analysis (trading_day DESC);
