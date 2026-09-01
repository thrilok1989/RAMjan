-- 021_fix_rls_conflicts_missing_tables: repair pass for a fresh Supabase
-- project. Fixes three things discovered from live Postgres logs on a
-- brand-new project, run 001-020 in order:
--
--   1. 42501 "new row violates row-level security policy" — new Supabase
--      projects default every table to RLS-enabled with zero policies, which
--      silently denies the anon key on every insert/upsert. This app has no
--      Supabase Auth / per-row ownership model — it's a single-user
--      dashboard authenticating purely via the anon key — so RLS is disabled
--      on every app table rather than adding policies that would just
--      allow-all anyway.
--   2. 42P10 "no unique or exclusion constraint matching ON CONFLICT" — a
--      few tables' existing unique indexes are expression-based (using
--      COALESCE for nullable columns) and don't match the plain column list
--      the app's .upsert(..., on_conflict="col1,col2") calls send. Adds a
--      plain-column unique index alongside the existing one so ON CONFLICT
--      resolves. Also a blanket safety net for every other on_conflict
--      target used in db/supabase_client.py, in case any table's live
--      schema drifted from what's in sql/001-020.
--   3. 5 tables the app writes to (db/supabase_client.py: upsert_bid_ask_history,
--      upsert_volume_delta_history, upsert_oc_signal, upsert_master_signal,
--      save_trade_config) were never created by any prior migration.
--
-- Safe to re-run: every statement is idempotent.

-- ── 1. Disable RLS on every app table ──────────────────────────────────────
ALTER TABLE IF EXISTS alert_log             DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS alerts_history        DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS atm_strike_data       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS backfill_progress     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bias_predictions      DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS candles_data          DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS detected_patterns     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS engine_errors         DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS engine_state          DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS entry_gate_signals    DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS gex_history           DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS iv_history            DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS leg_entry_signals     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS leg_flow_snapshots    DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS macro_data            DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS market_analytics      DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS market_events         DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS market_stories        DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS max_pain_history      DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS my_analysis           DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS nifty_spot_data       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS option_chain_data     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS orderbook_data        DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS pcr_history           DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS signal_outcomes       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS story_stats           DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS story_validations     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS telegram_sent_log     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS user_preferences      DISABLE ROW LEVEL SECURITY;

-- ── 2. Missing tables (used by db/supabase_client.py, never migrated) ─────
CREATE TABLE IF NOT EXISTS bid_ask_history (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    trading_day DATE NOT NULL,
    expiry DATE NOT NULL,
    strike_price NUMERIC(10,2) NOT NULL,
    atm_strike NUMERIC(10,2),
    bid_qty_ce BIGINT,
    bid_qty_pe BIGINT,
    ask_qty_ce BIGINT,
    ask_qty_pe BIGINT,
    volume_ce BIGINT,
    volume_pe BIGINT,
    oi_ce BIGINT,
    oi_pe BIGINT,
    chgoi_ce BIGINT,
    chgoi_pe BIGINT,
    ltp_ce NUMERIC(12,2),
    ltp_pe NUMERIC(12,2),
    data_source TEXT NOT NULL DEFAULT 'computed',
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(timestamp, expiry, strike_price)
);
CREATE INDEX IF NOT EXISTS idx_bid_ask_history_timestamp ON bid_ask_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_bid_ask_history_trading_day ON bid_ask_history(trading_day);
ALTER TABLE IF EXISTS bid_ask_history DISABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS volume_delta_history (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    trading_day DATE NOT NULL,
    symbol TEXT NOT NULL,
    buy_volume BIGINT,
    sell_volume BIGINT,
    delta BIGINT,
    cum_delta BIGINT,
    divergence BOOLEAN DEFAULT FALSE,
    bias TEXT,
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(timestamp, symbol)
);
CREATE INDEX IF NOT EXISTS idx_volume_delta_history_trading_day ON volume_delta_history(trading_day);
ALTER TABLE IF EXISTS volume_delta_history DISABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS oc_signal_history (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    trading_day DATE NOT NULL,
    spot_price NUMERIC(12,2),
    condition TEXT,
    confidence INTEGER,
    resistance_strikes JSONB,
    support_strikes JSONB,
    active_signals JSONB,
    breakout_level NUMERIC(12,2),
    breakdown_level NUMERIC(12,2),
    bias_reasoning JSONB,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_oc_signal_history_trading_day ON oc_signal_history(trading_day);
ALTER TABLE IF EXISTS oc_signal_history DISABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS master_signals (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    trading_day DATE NOT NULL,
    spot_price NUMERIC(12,2),
    signal TEXT,
    trade_type TEXT,
    score INTEGER,
    abs_score INTEGER,
    strength TEXT,
    confidence INTEGER,
    candle_pattern TEXT,
    candle_direction TEXT,
    volume_label TEXT,
    volume_ratio NUMERIC(10,4),
    location TEXT,
    resistance_levels TEXT,
    support_levels TEXT,
    net_gex NUMERIC(12,4),
    atm_gex NUMERIC(12,4),
    gamma_flip NUMERIC(12,2),
    gex_mode TEXT,
    pcr_gex_badge TEXT,
    market_bias TEXT,
    vix_value NUMERIC(8,2),
    vix_direction TEXT,
    oi_trend_signal TEXT,
    ce_activity TEXT,
    pe_activity TEXT,
    support_status TEXT,
    resistance_status TEXT,
    vidya_trend TEXT,
    vidya_delta_pct NUMERIC(10,4),
    delta_vol_trend TEXT,
    vwap NUMERIC(12,2),
    price_vs_vwap TEXT,
    reasons TEXT,
    alignment_summary TEXT,
    data_source TEXT NOT NULL DEFAULT 'master_signal',
    update_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(timestamp, trading_day)
);
CREATE INDEX IF NOT EXISTS idx_master_signals_trading_day ON master_signals(trading_day);
ALTER TABLE IF EXISTS master_signals DISABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS trade_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    support_zone_bottom NUMERIC(12,2),
    support_zone_top NUMERIC(12,2),
    resistance_zone_bottom NUMERIC(12,2),
    resistance_zone_top NUMERIC(12,2),
    selected_strike NUMERIC(10,2),
    call_entry NUMERIC(12,2),
    call_target NUMERIC(12,2),
    call_sl NUMERIC(12,2),
    put_entry NUMERIC(12,2),
    put_target NUMERIC(12,2),
    put_sl NUMERIC(12,2),
    auto_trade_enabled BOOLEAN DEFAULT FALSE,
    lot_size INTEGER DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE IF EXISTS trade_config DISABLE ROW LEVEL SECURITY;

-- ── 3. ON CONFLICT safety net — plain-column unique indexes matching every
--      upsert(on_conflict=...) call in db/supabase_client.py, so upserts
--      resolve regardless of what the live schema currently has. ──────────
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_candles_data
    ON candles_data(symbol, exchange, timeframe, timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_nifty_spot_data
    ON nifty_spot_data(timestamp, security_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_option_chain_data
    ON option_chain_data(timestamp, expiry, strike_price);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_atm_strike_data
    ON atm_strike_data(timestamp, expiry, strike_price);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_pcr_history
    ON pcr_history(timestamp, expiry, strike_price);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_gex_history
    ON gex_history(timestamp, expiry, strike_price);
-- detected_patterns / alerts_history: the original unique indexes (sql/001,
-- sql/002) use COALESCE(...) expressions for nullable columns, which
-- PostgREST's plain on_conflict="col1,col2,..." cannot target. Add a plain
-- version alongside (harmless duplicate coverage).
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_detected_patterns
    ON detected_patterns(timestamp, pattern_type, price_level, timeframe);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_alerts_history
    ON alerts_history(timestamp, alert_type, strike_price);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_orderbook_data
    ON orderbook_data(timestamp, expiry, strike_price);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_user_preferences
    ON user_preferences(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_market_analytics
    ON market_analytics(symbol, date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_max_pain_history
    ON max_pain_history(timestamp, expiry);
