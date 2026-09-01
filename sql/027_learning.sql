-- 027_learning: MIOS V6 Phase 6 — Learning & Validation store.
--
-- The Learning Engine is NOT part of the live decision path. It observes,
-- measures, explains, recommends and validates. It never writes back into the
-- Decision Engine, never mutates a threshold, never mutates an engine weight.
-- These tables exist so that claim is enforceable: the live pipeline only ever
-- INSERTs here, and nothing in the live path reads from here.
--
-- ── The one rule these tables are shaped around: NEVER OVERWRITE HISTORY. ──
--
-- Every table below is append-only. Nothing is UPDATEd. A trade that changes
-- (trail moved, partial taken, stop adjusted, flow shifted) appends an EVENT;
-- it does not rewrite the row it came from. That is what makes replay and
-- backtesting honest — the record shows what was known *at the time*, not what
-- the last write happened to leave behind.
--
--   trade_attribution        one row at signal birth   (INSERT once)
--   engine_attribution       one row per engine, per trade, at birth (INSERT)
--   trade_events             append-only life of the trade (MFE/MAE/trail/…)
--   trade_results            one row at exit           (INSERT once)
--   learning_snapshots       append-only history of the learning output itself
--
-- Run in the Supabase SQL editor. Idempotent.

-- ── Stage 55 · Trade Attribution — the state of the world at signal birth ──
CREATE TABLE IF NOT EXISTS trade_attribution (
    id               BIGSERIAL PRIMARY KEY,
    signal_id        TEXT UNIQUE NOT NULL,        -- SIG-YYYYMMDD-NNN
    trading_day      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- the trade as proposed
    direction        TEXT,                        -- CALL / PUT
    entry_price      DOUBLE PRECISION,
    stop             DOUBLE PRECISION,
    target           DOUBLE PRECISION,
    trail            DOUBLE PRECISION,
    rr               DOUBLE PRECISION,
    confidence       DOUBLE PRECISION,
    quality          TEXT,
    -- the market as read
    market_quality   TEXT,
    market_controller TEXT,
    market_state     TEXT,
    market_bias      TEXT,
    bias_transition  TEXT,
    ltp_behaviour    TEXT,
    acceptance       TEXT,
    absorption       TEXT,
    flow_shift       TEXT,
    sr_state         TEXT,
    dealer_state     TEXT,
    order_flow       TEXT,
    options_state    TEXT,
    htf_alignment    TEXT,
    -- the reasoning
    ai_thesis        TEXT,
    decision_reason  JSONB,
    -- the full read, verbatim, for replay
    snapshot         JSONB
);

CREATE INDEX IF NOT EXISTS idx_trade_attr_day ON trade_attribution (trading_day);
CREATE INDEX IF NOT EXISTS idx_trade_attr_sig ON trade_attribution (signal_id);

-- ── Stage 55b · per-engine attribution: what each engine said, per trade ──
-- This is the table that makes Stages 56-60 possible. Without a row per engine
-- per trade there is no per-engine accuracy — only a single blended win rate
-- that cannot tell you which engine to fix.
CREATE TABLE IF NOT EXISTS engine_attribution (
    id               BIGSERIAL PRIMARY KEY,
    signal_id        TEXT NOT NULL,
    trading_day      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    engine           TEXT NOT NULL,               -- stage42_acceptance, …
    stage            INTEGER,
    output           TEXT,                        -- the engine's headline read
    bias             TEXT,                        -- STRONG_BULL … STRONG_BEAR / NONE
    status           TEXT,                        -- OK / NEUTRAL / DEGRADED / …
    confidence       DOUBLE PRECISION,
    strength         DOUBLE PRECISION,
    weight           DOUBLE PRECISION,            -- family weight at that moment
    agreement        BOOLEAN,                     -- agreed with the trade direction
    conflict         BOOLEAN,                     -- actively opposed it
    reliability      DOUBLE PRECISION,            -- historical accuracy AT THAT TIME
    freshness_min    DOUBLE PRECISION,            -- how long this read had held
    data             JSONB,
    UNIQUE (signal_id, engine)
);

CREATE INDEX IF NOT EXISTS idx_eng_attr_sig    ON engine_attribution (signal_id);
CREATE INDEX IF NOT EXISTS idx_eng_attr_engine ON engine_attribution (engine);

-- ── Stage 55c · the life of the trade, append-only ──
-- MFE/MAE progression, trail updates, stop adjustments, partial exits, scale
-- in/out, flow-shift events, bias changes, state changes. One row per event.
CREATE TABLE IF NOT EXISTS trade_events (
    id               BIGSERIAL PRIMARY KEY,
    signal_id        TEXT NOT NULL,
    trading_day      TEXT,
    ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind             TEXT NOT NULL,   -- excursion / trail / stop / partial /
                                      -- scale_in / scale_out / flow_shift /
                                      -- bias_change / state_change / note
    spot             DOUBLE PRECISION,
    mfe              DOUBLE PRECISION,
    mae              DOUBLE PRECISION,
    detail           JSONB
);

CREATE INDEX IF NOT EXISTS idx_trade_events_sig ON trade_events (signal_id);
CREATE INDEX IF NOT EXISTS idx_trade_events_ts  ON trade_events (ts);

-- ── Stage 55d · the outcome, written once at exit ──
CREATE TABLE IF NOT EXISTS trade_results (
    id               BIGSERIAL PRIMARY KEY,
    signal_id        TEXT UNIQUE NOT NULL,
    trading_day      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_price       DOUBLE PRECISION,
    exit_at          TIMESTAMPTZ,
    exit_reason      TEXT,   -- TARGET_HIT / TRAILING_STOP / MANUAL / FLOW_SHIFT /
                             -- DEALER_FLIP / BIAS_CHANGE / ACCEPTANCE_FAILED /
                             -- STOP_LOSS / TIME_EXIT / AI_EXIT
    outcome          TEXT,   -- win / loss / scratch / never_entered
    pnl_points       DOUBLE PRECISION,
    return_pct       DOUBLE PRECISION,
    holding_secs     DOUBLE PRECISION,
    mfe              DOUBLE PRECISION,
    mae              DOUBLE PRECISION,
    max_drawdown     DOUBLE PRECISION,
    expected_move    DOUBLE PRECISION,
    actual_move      DOUBLE PRECISION,
    efficiency       DOUBLE PRECISION,   -- captured / available
    trade_quality    TEXT,               -- EXCELLENT / GOOD / FAIR / POOR / BAD
    notes            JSONB
);

CREATE INDEX IF NOT EXISTS idx_trade_results_day ON trade_results (trading_day);

-- ── Stages 56-60 · the learning output, itself append-only ──
-- Learning conclusions are also history. Storing each computation lets you ask
-- "what did MIOS believe about itself last month, and was that right?" — and it
-- makes the promotion rule auditable: a threshold change can be traced to the
-- exact snapshot that recommended it.
CREATE TABLE IF NOT EXISTS learning_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day      TEXT,
    stage            TEXT NOT NULL,   -- accuracy / calibration / thresholds /
                                      -- contribution / false_signal
    window_label     TEXT,             -- last30 / last100 / last500 / lifetime
    sample_size      INTEGER,
    payload          JSONB NOT NULL,
    -- suggestions are RECOMMENDATIONS. Nothing here is applied automatically.
    applied          BOOLEAN NOT NULL DEFAULT FALSE,
    applied_at       TIMESTAMPTZ,
    applied_by       TEXT
);

CREATE INDEX IF NOT EXISTS idx_learning_stage ON learning_snapshots (stage);
CREATE INDEX IF NOT EXISTS idx_learning_day   ON learning_snapshots (trading_day);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS trade_attribution  DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS engine_attribution DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS trade_events       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS trade_results      DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS learning_snapshots DISABLE ROW LEVEL SECURITY;
