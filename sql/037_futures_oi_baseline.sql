-- The day's first observed NIFTY futures OI — the anchor `chg_oi` never had.
-- Audit: docs/AUDIT_STAGE_71_90_CLOSING_AUCTION.md · module: mios_v5/futures_oi.py
--
-- `get_nifty_futures_data()` computes OI change like this:
--
--     prev = st.session_state.get('_nifty_fut_prev_oi')
--     chg_oi = (oi - prev) if (prev is not None and oi) else 0.0
--
-- That is the delta since the previous ~20-second refresh, held in
-- session_state. Two problems, and the second is the dangerous one:
--
--   1. a 20-second delta is noise at closing-auction volumes; and
--   2. session_state resets when the app restarts or the tab reloads, so the
--      counter silently reports 0.0 — indistinguishable from "OI was flat".
--
-- Short Covering ("futures up, OI falling") and Long Unwinding are claims about
-- the DAY's open interest. This table is that day anchor, and it survives a
-- restart, which is the whole point.
--
-- ⚠️ ONE ROW PER TRADING DAY. Written once, when the day's first futures quote
--    is seen, and never rewritten — a baseline that moves is not a baseline.
--    The app reads it once per day and caches it, so this table costs one write
--    and one read per session, not one per 20-second rerun. That restraint is
--    deliberate: unbounded per-cycle writes are what made egress 0.59 GB/day.

CREATE TABLE IF NOT EXISTS futures_oi_baseline (
    id              BIGSERIAL PRIMARY KEY,
    trading_day     DATE        NOT NULL,
    symbol          TEXT        NOT NULL,   -- e.g. NIFTY-Aug2026-FUT
    expiry          TEXT,

    -- ── the anchor ──
    open_oi         NUMERIC     NOT NULL,   -- first OI observed today
    open_price      NUMERIC,                -- …and the futures price with it
    open_basis      NUMERIC,                -- …and the basis vs spot
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Which contract the anchor belongs to. On rollover day the near-month
    -- symbol changes and its OI is a different series entirely; comparing
    -- across that boundary would read a contract switch as a collapse in
    -- open interest.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One anchor per day PER CONTRACT. The symbol is in the key on purpose: see
-- the rollover note above.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_fut_oi_baseline_day_symbol
    ON futures_oi_baseline (trading_day, symbol);

CREATE INDEX IF NOT EXISTS idx_fut_oi_baseline_day
    ON futures_oi_baseline (trading_day DESC);

ALTER TABLE futures_oi_baseline ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS futures_oi_baseline_all ON futures_oi_baseline;
CREATE POLICY futures_oi_baseline_all ON futures_oi_baseline
    FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE futures_oi_baseline IS
    'The day''s first observed NIFTY futures OI. One row per trading day per contract, written once and never rewritten — a baseline that moves is not a baseline.';

COMMENT ON COLUMN futures_oi_baseline.symbol IS
    'Part of the unique key because near-month OI is a different series after rollover; comparing across the boundary reads a contract switch as an OI collapse.';

-- ⚙️ Retention: 365 days, declared in db/retention.py. One row per day is
--    nothing, and a year lets this expiry cycle be compared with the last.
