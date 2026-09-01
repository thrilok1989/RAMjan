-- Stage 74 telemetry — the calibration evidence, collected before injection.
-- Contract: docs/STAGE74_LEVEL_CONTRACT.md · module: mios_v5/liquidity_telemetry.py
--
-- Stage 74's confidence curve, cluster tolerance and POC regime bands were set
-- from reasoning, because there was nothing to measure. This table is how they
-- stop being reasoning: one row per sample, a week of sessions, then a verdict
-- on whether the curve discriminates.
--
-- It exists BEFORE the S/R injection on purpose. Once Stage 42 consumes these
-- values, changing the scoring changes downstream engine behaviour too, and the
-- cheap window to calibrate closes.
--
-- ⚠️ The app samples at most once a minute, not once per 20-second rerun.
--    A trading day is ~375 rows, a week ~1,900. Small, and retention is set in
--    db/retention.py (180 days) so it cannot grow forever like every other
--    table in this schema did.

CREATE TABLE IF NOT EXISTS liquidity_telemetry (
    id                   BIGSERIAL PRIMARY KEY,
    ts                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day          DATE        NOT NULL,
    cycle                INTEGER,
    version              TEXT,

    -- ── the calibration readings ──
    -- Histograms as JSONB: the bucket boundaries live in the module, and a
    -- column per bucket would need a migration every time they are revised.
    confidence_hist      JSONB,      -- {"0-20": n, "20-40": n, …}
    confidence_scored    INTEGER,
    confidence_unscored  INTEGER,    -- clusters whose confidence was UNKNOWN —
                                     -- NOT low-confidence, and counted apart
    confidence_mean      NUMERIC,
    engines_hist         JSONB,      -- {"1": n, "2": n, … "6+": n}
    engines_mean         NUMERIC,
    engines_max          INTEGER,
    clusters             INTEGER,
    sources              INTEGER,
    tolerance_pct        NUMERIC,    -- the adaptive band this sample used
    atr                  NUMERIC,    -- …and the ATR that set it

    -- ── the context the calibration must be read against ──
    poc_regime           TEXT,       -- Stable · Normal · Rotating
    poc_trend            TEXT,       -- Rising · Falling · Stable
    poc_stability        NUMERIC,
    liquidity_shift      TEXT,
    dominance            TEXT,
    imbalance_pct        NUMERIC,
    net_sentiment        NUMERIC,
    divergence           TEXT,
    reaction             TEXT,       -- Stage 42's own state, consumed
    ready                BOOLEAN,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per sample instant. The writer upserts on this, so a retried write
-- corrects its row instead of appending a second and skewing the distribution.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_liq_telemetry_ts
    ON liquidity_telemetry (ts);

-- The read is always "this window, newest first" — sized for the sort.
CREATE INDEX IF NOT EXISTS idx_liq_telemetry_day_ts
    ON liquidity_telemetry (trading_day, ts DESC);

CREATE INDEX IF NOT EXISTS idx_liq_telemetry_ts
    ON liquidity_telemetry (ts DESC);

ALTER TABLE liquidity_telemetry ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS liquidity_telemetry_all ON liquidity_telemetry;
CREATE POLICY liquidity_telemetry_all ON liquidity_telemetry
    FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE liquidity_telemetry IS
    'Stage 74 calibration evidence. Advisory — nothing reads it to make a decision; a human reads the distribution and decides whether to freeze.';

COMMENT ON COLUMN liquidity_telemetry.confidence_unscored IS
    'Clusters whose confidence was UNKNOWN. Counted apart from the histogram: an unscored cluster is not a low-confidence one, and folding it in would drag the distribution toward TOO_HARSH for the wrong reason.';

-- ⚙️ Retention: 180 days, declared in db/retention.py. Long enough to compare
--    this quarter's calibration against last quarter's, short enough that a
--    per-minute sample never becomes a storage problem.
