-- 018_engine_state: Stage-scoring snapshot per MIOS V5 pipeline pass.
--
-- The "derived" half of the two-table design. `candles_data`,
-- `option_chain_data`, `pcr_history`, `gex_history`, `detected_patterns`
-- (migration 001) are the immutable raw layer, already collected every
-- cycle. This table is what the scoring engines (stage02_structure,
-- stage05_regime, stage11_dealer, ...) compute FROM that raw data, one row
-- per pipeline pass, so later similarity search / backtesting reads scores
-- directly instead of recomputing them from raw candles every time.
--
-- engine_version tags which scoring logic produced each row — if a stage's
-- formula changes later, old and new rows must never be silently compared
-- as if they were computed the same way.

CREATE TABLE IF NOT EXISTS engine_state (
    id                     BIGSERIAL PRIMARY KEY,
    ts                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day            DATE NOT NULL,
    spot                   NUMERIC(12,2),
    engine_version         TEXT NOT NULL,

    structure_bias         TEXT,
    structure_confidence   NUMERIC(5,2),
    structure_score        NUMERIC(5,2),
    structure_decision     TEXT,          -- TRADE ZONE / WATCH / NO TRADE

    regime_bias            TEXT,
    regime_confidence      NUMERIC(5,2),
    dealer_bias            TEXT,
    dealer_confidence      NUMERIC(5,2),
    options_bias           TEXT,
    options_confidence     NUMERIC(5,2),
    institutional_bias     TEXT,
    institutional_confidence NUMERIC(5,2),
    orderflow_bias         TEXT,
    orderflow_confidence   NUMERIC(5,2),
    intent_bias            TEXT,
    intent_confidence      NUMERIC(5,2),
    probability_bias       TEXT,
    probability_confidence NUMERIC(5,2),
    reaction_zone_bias     TEXT,
    reaction_zone_confidence NUMERIC(5,2),

    conflict_severity      TEXT,
    conflict_agreement_pct NUMERIC(5,2),

    full_state             JSONB NOT NULL,   -- every engine's status/bias/confidence/data

    -- filled in later once a trade closes near this snapshot (not wired yet)
    trade_id               BIGINT,
    outcome                TEXT,             -- WIN / LOSS / BREAKEVEN
    points_moved           NUMERIC(10,2)
);

CREATE INDEX IF NOT EXISTS idx_engine_state_ts ON engine_state(ts DESC);
CREATE INDEX IF NOT EXISTS idx_engine_state_day ON engine_state(trading_day);
CREATE INDEX IF NOT EXISTS idx_engine_state_version ON engine_state(engine_version);
CREATE INDEX IF NOT EXISTS idx_engine_state_structure_score ON engine_state(structure_score);
CREATE INDEX IF NOT EXISTS idx_engine_state_outcome ON engine_state(outcome);

-- optional purge (run manually or as a scheduled job — nothing purges
-- ⚙️ NOW EXECUTED: db/retention.py reads this policy and applies it (see POLICIES).
--    The line below stays as the declaration of record; do not run it by hand.
-- automatically today, same as the raw tables in migration 001)
-- DELETE FROM engine_state WHERE trading_day < CURRENT_DATE - INTERVAL '730 days';
