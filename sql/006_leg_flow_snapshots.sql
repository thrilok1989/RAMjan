-- 📊 Per-cycle CALL/PUT order-flow snapshots (CVD / Cum Buy / Cum Sell) for
-- the ATM±1 legs, so the graphs can be replayed date-wise. Run in Supabase
-- SQL Editor. One row per snapshot (~1/min); each value is the running
-- intraday cumulative up to that timestamp (resets each trading day).

CREATE TABLE IF NOT EXISTS leg_flow_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    trading_day DATE        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    call_cvd    NUMERIC,   -- CE side cumulative Buy − Sell
    put_cvd     NUMERIC,   -- PE side cumulative Buy − Sell
    call_buy    NUMERIC,   -- CE cumulative Buy volume
    put_buy     NUMERIC,   -- PE cumulative Buy volume
    call_sell   NUMERIC,   -- CE cumulative Sell volume
    put_sell    NUMERIC    -- PE cumulative Sell volume
);

CREATE INDEX IF NOT EXISTS idx_leg_flow_day
    ON leg_flow_snapshots (trading_day, ts);

-- optional purge (run manually or as a scheduled job)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM leg_flow_snapshots WHERE trading_day < CURRENT_DATE - INTERVAL '60 days';
