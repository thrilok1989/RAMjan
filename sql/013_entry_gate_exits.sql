-- 🚪 ENTRY GATE exit tracking — adds the exit half to entry_gate_signals so
-- every gate activation becomes a measurable entry→exit pair. Run in Supabase
-- SQL Editor (after sql/012). The app fills target/invalidation at activation
-- and updates the exit columns when the exit monitor triggers.

ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS target        NUMERIC;
ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS invalidation  NUMERIC;
ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS exit_ts       TIMESTAMPTZ;
ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS exit_spot     NUMERIC;
ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS exit_reason   TEXT;
-- TARGET_HIT | INVALIDATED | TIME_EXIT | SUPERSEDED
ALTER TABLE entry_gate_signals ADD COLUMN IF NOT EXISTS points_moved  NUMERIC;
-- spot move from activation to exit, signed in the trade's favour
