-- Stage: data retention — the audit trail for db/retention.py
--
-- Every purge appends a row here: which table, which policy, where the cutoff
-- fell, how many rows were there before, how many went, and whether the run
-- finished or ran out of windows.
--
-- A deletion with no record of what it deleted is indistinguishable from data
-- loss. This table is the difference.
--
-- It is deliberately NOT in db/retention.py's own POLICIES: the log of what was
-- removed must outlive the data it describes.

CREATE TABLE IF NOT EXISTS retention_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    table_name      TEXT         NOT NULL,
    keep_days       INTEGER,
    day_col         TEXT,
    cutoff          DATE,
    rows_before     BIGINT,
    rows_removed    BIGINT,
    windows         INTEGER,
    complete        BOOLEAN,
    policy_source   TEXT,          -- 'sql/009_engine_errors.sql' | 'this module'
    error           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- One row per table per run instant. The upsert in `_log` conflicts on exactly
-- this, so a retried write corrects its row instead of appending a second one.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_retention_log_ts_table
    ON retention_log (ts, table_name);

CREATE INDEX IF NOT EXISTS idx_retention_log_table
    ON retention_log (table_name, ts DESC);

CREATE INDEX IF NOT EXISTS idx_retention_log_ts
    ON retention_log (ts DESC);

ALTER TABLE retention_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS retention_log_all ON retention_log;
CREATE POLICY retention_log_all ON retention_log
    FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE retention_log IS
    'Audit trail for db/retention.py. Never auto-purged: the record of what was removed must outlive the data it describes.';
