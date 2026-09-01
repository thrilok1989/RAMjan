-- 📈 Daily ATM IV history — powers true multi-day IV Rank and IV Percentile.
-- Run in Supabase SQL Editor. One row per trading day; the app upserts the
-- latest ATM IV through the session, so the row always holds that day's most
-- recent reading. IV Rank/Percentile become meaningful once ~20+ days of
-- history accumulate (it cannot be back-filled — Dhan does not serve historical
-- IV, so collection starts from the day this table goes live).

CREATE TABLE IF NOT EXISTS iv_history (
    trading_day DATE PRIMARY KEY,
    atm_iv      NUMERIC     NOT NULL,   -- session-latest ATM implied volatility (%)
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_iv_history_day
    ON iv_history (trading_day DESC);

-- optional purge (keep ~2 years)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM iv_history WHERE trading_day < CURRENT_DATE - INTERVAL '730 days';
