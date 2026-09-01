-- 🎯 ENTRY GATE signal log — one row per gate ACTIVATION (BUY CALL/PUT ZONE
-- ACTIVE: spot at a strong/building S/R zone with engines aligned). Run in
-- Supabase SQL Editor. Each row carries the gate context plus the full factor
-- snapshot at activation (same columns as signal_outcomes), so gate quality
-- can be validated later against realised moves.

CREATE TABLE IF NOT EXISTS entry_gate_signals (
    id            BIGSERIAL PRIMARY KEY,
    trading_day   DATE        NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- gate context
    side          TEXT,                 -- CALL | PUT
    zone_type     TEXT,                 -- SUPPORT | RESISTANCE
    level         NUMERIC,              -- the zone price
    dist_pts      NUMERIC,              -- spot distance from the level
    strength      NUMERIC,              -- S/R strength % at activation
    building      BOOLEAN,              -- writers building the zone (ΔOI)
    engines_net   NUMERIC,              -- market-picture vote net
    spot          NUMERIC,
    telegram_sent BOOLEAN,

    -- factor snapshot at activation (mirrors signal_outcomes)
    market_label        TEXT,
    market_kind         TEXT,
    regime              TEXT,
    call_mode           TEXT,
    put_mode            TEXT,
    call_strength       NUMERIC,
    put_strength        NUMERIC,
    support_strength    NUMERIC,
    resistance_strength NUMERIC,
    breakout            NUMERIC,
    gamma_blast         TEXT,
    dealer_score        NUMERIC,
    dealer_dir          TEXT,
    dex_net             NUMERIC,
    gex_total           NUMERIC,
    gex_signal          TEXT,
    skew_ratio          NUMERIC,
    skew_bias           TEXT,
    institution_score   NUMERIC,
    institution_bias    TEXT,
    short_squeeze       NUMERIC,
    overall_conf        NUMERIC,
    vanna               NUMERIC,
    charm               NUMERIC,
    cross_expiry        TEXT
);

CREATE INDEX IF NOT EXISTS idx_entry_gate_day
    ON entry_gate_signals (trading_day DESC, ts DESC);

-- optional purge (keep ~1 year)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM entry_gate_signals WHERE trading_day < CURRENT_DATE - INTERVAL '365 days';
