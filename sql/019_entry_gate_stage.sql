-- 019_entry_gate_stage: distinguish ARMED (watching, not yet entered) rows
-- from CONFIRMED (actually entered) rows in entry_gate_signals, so the
-- ARMED banner's activation is auditable in Supabase too, without
-- polluting the win/loss tabulation (only CONFIRMED rows have a real
-- entry price + target/invalidation to grade against).

ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'CONFIRMED';
-- ARMED | CONFIRMED

CREATE INDEX IF NOT EXISTS idx_entry_gate_stage ON entry_gate_signals(stage);
