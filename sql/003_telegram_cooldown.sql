-- Telegram message dedup / cooldown log
-- Run in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS telegram_sent_log (
    id        BIGSERIAL PRIMARY KEY,
    msg_hash  TEXT        NOT NULL,
    sent_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alert_type TEXT,
    preview   TEXT
);

-- fast lookup: hash + time range
CREATE INDEX IF NOT EXISTS idx_tg_log_hash_time
    ON telegram_sent_log (msg_hash, sent_at DESC);

-- auto-purge rows older than 24 h to keep the table small
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM telegram_sent_log WHERE sent_at < NOW() - INTERVAL '24 hours';
