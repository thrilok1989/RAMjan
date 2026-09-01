-- 026_trade_signals: the MIOS Signal Lifecycle store.
--
-- The Decision Engine doesn't just fire a signal — it opens a full, auditable
-- TRADE LIFECYCLE and follows it to a terminal state:
--
--   WAIT_ENTRY → ENTERED → (TARGET_HIT | STOP_HIT | EXPIRED | CANCELLED)
--
-- One row per signal (SIG-YYYYMMDD-NNN), updated in place as it advances. Only
-- ONE signal is active (non-terminal) at a time — no new signal is generated
-- until the current one resolves or expires. Signals that never trigger are kept
-- (status EXPIRED / never_entered) so the history explains the misses too.
--
-- This is the record the Excel history + analytics read: win-rate, avg R:R,
-- holding time, best quality, which gate blocked losers, which engine combos win.
--
-- Run in the Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS trade_signals (
    id               BIGSERIAL PRIMARY KEY,
    signal_id        TEXT UNIQUE NOT NULL,        -- SIG-20260723-001
    trading_day      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- the setup
    side             TEXT,                        -- CALL / PUT
    quality          TEXT,                        -- A+ / A (only these are stored/alerted)
    confidence       DOUBLE PRECISION,
    zone_side        TEXT,                        -- SUPPORT / RESISTANCE
    entry_price      DOUBLE PRECISION,            -- the entry zone / trigger level
    stop             DOUBLE PRECISION,
    target           DOUBLE PRECISION,
    rr               DOUBLE PRECISION,
    -- lifecycle
    status           TEXT NOT NULL DEFAULT 'WAIT_ENTRY',
                     -- WAIT_ENTRY / ENTERED / TARGET_HIT / STOP_HIT / EXPIRED / CANCELLED
    signal_spot      DOUBLE PRECISION,            -- spot when the signal was generated
    entered_price    DOUBLE PRECISION,            -- spot at entry trigger
    entered_at       TIMESTAMPTZ,
    exit_price       DOUBLE PRECISION,
    exit_at          TIMESTAMPTZ,
    outcome          TEXT,                        -- win / loss / never_entered / cancelled / open
    pnl_points       DOUBLE PRECISION,            -- exit - entry (signed by side)
    holding_secs     DOUBLE PRECISION,
    -- provenance
    reason           JSONB,                       -- gates passed / warnings / reasons
    engine_snapshot  JSONB                        -- compact read of the engines at signal time
);

CREATE INDEX IF NOT EXISTS idx_trade_signals_day    ON trade_signals (trading_day);
CREATE INDEX IF NOT EXISTS idx_trade_signals_status ON trade_signals (status);
CREATE INDEX IF NOT EXISTS idx_trade_signals_sig    ON trade_signals (signal_id);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS trade_signals DISABLE ROW LEVEL SECURITY;
