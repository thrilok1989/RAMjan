-- 🎯 MIOS V5 — Bias prediction log (Stage 40: Prediction Validation & Learning).
-- Run in Supabase SQL Editor. In pure decision-support mode MIOS makes no
-- trades, so instead it logs its own DIRECTIONAL READ periodically and grades
-- it against the realised spot move ~15 min later. That turns the dashboard
-- into a self-validating engine: accuracy by confidence band and by bias.
-- One row per logged prediction; graded in place when it resolves.

CREATE TABLE IF NOT EXISTS bias_predictions (
    id             BIGSERIAL PRIMARY KEY,
    trading_day    DATE        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    due_at         TIMESTAMPTZ NOT NULL,          -- when to grade (ts + horizon)
    horizon_min    INTEGER     NOT NULL DEFAULT 15,
    spot_at        NUMERIC     NOT NULL,

    preferred_bias   TEXT,
    confidence       NUMERIC,
    conflict_severity TEXT,
    battle_type      TEXT,                          -- SUPPORT | RESISTANCE | null
    expected_winner  TEXT,
    target           NUMERIC,
    invalidation     NUMERIC,
    regime           TEXT,
    session_phase    TEXT,
    dealer_bias      TEXT,
    intent_bias      TEXT,
    orderflow_bias   TEXT,

    -- graded on resolution
    spot_then     NUMERIC,
    realized_move NUMERIC,        -- % move over the horizon
    correct       BOOLEAN,
    resolved_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bias_pred_day
    ON bias_predictions (trading_day DESC, ts DESC);
CREATE INDEX IF NOT EXISTS idx_bias_pred_open
    ON bias_predictions (resolved_at) WHERE resolved_at IS NULL;

-- optional purge (keep ~1 year)
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- DELETE FROM bias_predictions WHERE trading_day < CURRENT_DATE - INTERVAL '365 days';
