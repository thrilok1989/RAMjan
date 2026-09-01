-- 🧪 Signal → Outcome log — the durable, factor-tagged record that turns the
-- in-memory entry journal into a queryable backtest dataset. Run in Supabase
-- SQL Editor. One row per CONFIRMED ENTRY: the row is inserted when the signal
-- triggers (with the full factor snapshot at that moment), then UPDATED in place
-- when it closes (T1_HIT / SL_HIT / TIME_EXIT) with the outcome + MFE/MAE/P&L.
-- Query it later to see which factors actually improve hit-rate.

CREATE TABLE IF NOT EXISTS signal_outcomes (
    id            BIGSERIAL PRIMARY KEY,
    trading_day   DATE        NOT NULL,
    ts_entry      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tag           TEXT,                 -- e.g. 'ATM CE 24150'
    side          TEXT,                 -- CE | PE
    spot          NUMERIC,
    entry_fill    NUMERIC,
    sl            NUMERIC,
    t1            NUMERIC,
    rr            NUMERIC,
    score         NUMERIC,
    confidence    NUMERIC,

    -- ── factor snapshot at entry (from the Final AI read + Market Picture) ──
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
    cross_expiry        TEXT,

    -- ── outcome (filled on close) ──
    state         TEXT,                 -- T1_HIT | SL_HIT | TIME_EXIT | STALE_DAY
    ts_close      TIMESTAMPTZ,
    exit_price    NUMERIC,
    mfe           NUMERIC,
    mae           NUMERIC,
    pnl_lot       NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_day
    ON signal_outcomes (trading_day DESC, ts_entry DESC);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_state
    ON signal_outcomes (state);

-- optional purge (keep ~1 year)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM signal_outcomes WHERE trading_day < CURRENT_DATE - INTERVAL '365 days';
