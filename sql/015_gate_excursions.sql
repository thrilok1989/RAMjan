-- 🎯 Persist MAE/MFE (max adverse / favourable excursion) on each ENTRY GATE
-- trade so the Validation Dashboard can check the noise-band + patience
-- thresholds against real "how much heat did winners take" data.
-- Additive columns; idempotent; no behaviour change.

ALTER TABLE entry_gate_signals
    ADD COLUMN IF NOT EXISTS mae numeric,   -- max adverse excursion (pts, <= 0)
    ADD COLUMN IF NOT EXISTS mfe numeric;   -- max favourable excursion (pts, >= 0)
