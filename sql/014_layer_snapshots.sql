-- 🎯 7-Layer Scorecard snapshot on each ENTRY GATE signal (for SHADOW
-- weight-learning). Additive columns on entry_gate_signals — the layer leans
-- captured at signal time are graded later against the trade's own outcome
-- (points_moved), so the shadow learner can compute per-layer hit rates.
--
-- Safe to run multiple times (IF NOT EXISTS). Does NOT change any existing
-- column or signal behaviour.

ALTER TABLE entry_gate_signals
    ADD COLUMN IF NOT EXISTS layer_leans    jsonb,   -- {layer_key: BULL/BEAR/NEUTRAL/N/A}
    ADD COLUMN IF NOT EXISTS layer_grade    text,    -- A+/A/B/C at signal time
    ADD COLUMN IF NOT EXISTS layer_composite integer;-- 0-100 composite at signal time
