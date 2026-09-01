-- 📨 Alert log — every Telegram alert the app sends, for side counts and
-- signal-cluster detection. Run in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS alert_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day DATE        NOT NULL,
    alert_class TEXT,                 -- vob_entry / sr_confluence / confirmed_entry / ...
    side        TEXT,                 -- CALL | PUT | NULL
    spot        NUMERIC,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_log_day
    ON alert_log (trading_day, ts DESC);

-- optional purge (run manually or as a scheduled job)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM alert_log WHERE trading_day < CURRENT_DATE - INTERVAL '14 days';
