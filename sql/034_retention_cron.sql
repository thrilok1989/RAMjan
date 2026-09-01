-- Background cleanup — retention that runs without the app being open.
-- Companion to db/retention.py. Findings: docs/AUDIT_QUERY_INDEXES.md
--
-- db/retention.py runs in-process, on a Streamlit rerun. That means it only
-- ever runs while somebody has the dashboard open, and it deletes over HTTP
-- through PostgREST — the wrong place for a maintenance job. This moves it into
-- the database, where a purge is a DELETE next to the rows instead of a
-- round-trip per window, and where nobody needs to be watching.
--
-- ══════════════════════════════════════════════════════════════════════
-- TWO GATES, same as the Python side
-- ══════════════════════════════════════════════════════════════════════
--   1. retention_policy.enabled — FALSE for every row on install. Nothing is
--      deleted until you enable a policy, one table at a time if you like.
--   2. the cron job is NOT scheduled by this file. You schedule it, once you
--      have read a preview.
--
-- So installing this migration deletes nothing and schedules nothing. It gives
-- you retention_preview() to look at first.
--
-- ══════════════════════════════════════════════════════════════════════
-- ONE OWNER FOR THE POLICY NUMBERS
-- ══════════════════════════════════════════════════════════════════════
-- The seed below is GENERATED from db/retention.py's POLICIES — same tables,
-- same windows, same source attribution. A test parses this file and asserts
-- the two match exactly, so they cannot drift. If you change a window, change
-- it in db/retention.py and regenerate; do not hand-edit the seed.


-- ── the policy table ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS retention_policy (
    table_name      TEXT PRIMARY KEY,
    keep_days       INTEGER NOT NULL CHECK (keep_days > 0),
    day_col         TEXT    NOT NULL,
    policy_source   TEXT,
    why             TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE retention_policy ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS retention_policy_all ON retention_policy;
CREATE POLICY retention_policy_all ON retention_policy
    FOR ALL USING (true) WITH CHECK (true);

COMMENT ON COLUMN retention_policy.enabled IS
    'FALSE on install. retention_purge() skips every disabled row.';


-- ── the seed · GENERATED from db/retention.py, do not hand-edit ─────
-- ON CONFLICT updates the window but NEVER the enabled flag: re-running this
-- migration must not switch a purge back on, or off, behind your back.
INSERT INTO retention_policy
    (table_name, keep_days, day_col, policy_source, why)
VALUES
    ('day_type_log', 730, 'trading_day', 'this module', ''),
    ('engine_attribution', 730, 'trading_day', 'this module', ''),
    ('engine_state', 730, 'trading_day', 'sql/018_engine_state.sql', ''),
    ('iv_history', 730, 'trading_day', 'sql/007_iv_history.sql', ''),
    ('learning_snapshots', 730, 'trading_day', 'this module', ''),
    ('session_log', 730, 'trading_day', 'this module', ''),
    ('session_recommendations', 730, 'trading_day', 'this module', ''),
    ('session_validation_log', 730, 'trading_day', 'this module', ''),
    ('trade_attribution', 730, 'trading_day', 'this module', ''),
    ('trade_events', 730, 'trading_day', 'this module', ''),
    ('trade_results', 730, 'trading_day', 'this module', ''),
    ('candles_data', 400, 'trading_day', 'this module', 'the backfill and market memory read the full collected range'),
    ('auto_trades', 365, 'trading_day', 'this module', ''),
    ('bias_predictions', 365, 'trading_day', 'sql/011_bias_predictions.sql', ''),
    ('dispatch_history', 365, 'created_at', 'this module', 'the duplicate-suppression index only looks at recent hashes'),
    ('entry_gate_signals', 365, 'trading_day', 'sql/012_entry_gate_signals.sql', ''),
    ('event_impact_log', 365, 'trading_day', 'this module', ''),
    ('futures_oi_baseline', 365, 'trading_day', 'this module', 'the day''s futures OI anchor — one row per day'),
    ('market_events', 365, 'created_at', 'this module', ''),
    ('market_stories', 365, 'created_at', 'this module', ''),
    ('mios_decisions', 365, 'trading_day', 'this module', ''),
    ('opening_auction_log', 365, 'trading_day', 'this module', ''),
    ('signal_outcomes', 365, 'trading_day', 'sql/008_signal_outcomes.sql', ''),
    ('story_validations', 365, 'created_at', 'this module', ''),
    ('trade_signals', 365, 'trading_day', 'this module', ''),
    ('liquidity_telemetry', 180, 'trading_day', 'this module', 'calibration evidence — kept across quarters, not forever'),
    ('alerts_history', 90, 'trading_day', 'this module', ''),
    ('atm_strike_data', 90, 'trading_day', 'this module', ''),
    ('gex_history', 90, 'trading_day', 'this module', ''),
    ('master_signals', 90, 'trading_day', 'this module', ''),
    ('max_pain_history', 90, 'trading_day', 'this module', ''),
    ('nifty_spot_data', 90, 'trading_day', 'this module', 'the day-open print is read same-day; history comes from candles'),
    ('oc_signal_history', 90, 'trading_day', 'this module', ''),
    ('pcr_history', 90, 'trading_day', 'this module', ''),
    ('leg_flow_snapshots', 60, 'trading_day', 'sql/006_leg_flow_snapshots.sql', ''),
    ('bid_ask_history', 30, 'trading_day', 'this module', ''),
    ('detected_patterns', 30, 'trading_day', 'this module', ''),
    ('dhan_sweeps', 30, 'created_at', 'this module', ''),
    ('engine_errors', 30, 'trading_day', 'sql/009_engine_errors.sql', ''),
    ('leg_entry_signals', 30, 'trading_day', 'sql/004_leg_entry_signals.sql', ''),
    ('option_chain_data', 30, 'trading_day', 'this module', 'a chain snapshot is a same-day artefact'),
    ('orderbook_data', 30, 'trading_day', 'this module', ''),
    ('volume_delta_history', 30, 'trading_day', 'this module', ''),
    ('alert_log', 14, 'trading_day', 'sql/005_alert_log.sql', ''),
    ('telegram_sent_log', 1, 'sent_at', 'sql/003_telegram_cooldown.sql', 'a send cooldown is meaningless once the cooldown has passed')
ON CONFLICT (table_name) DO UPDATE SET
    keep_days     = EXCLUDED.keep_days,
    day_col       = EXCLUDED.day_col,
    policy_source = EXCLUDED.policy_source,
    why           = EXCLUDED.why,
    updated_at    = NOW();


-- ══════════════════════════════════════════════════════════════════════
-- retention_purge(dry_run, max_rows_per_table)
-- ══════════════════════════════════════════════════════════════════════
-- Deletes in chunks by ctid rather than one statement per table. A single
-- DELETE across two years of option_chain_data holds one long transaction and
-- bloats WAL; chunked, each statement is short and an interrupted run has
-- still removed everything it committed.
--
-- Returns one row per policy, always — including the ones it skipped and why.
-- A maintenance job that reports only what it touched hides the table it could
-- not find.
--
-- DEFAULTS TO DRY RUN. retention_purge() alone deletes nothing.

CREATE OR REPLACE FUNCTION retention_purge(
    p_dry_run   BOOLEAN DEFAULT TRUE,
    p_max_rows  BIGINT  DEFAULT 500000,
    p_chunk     INTEGER DEFAULT 10000
)
RETURNS TABLE (
    table_name    TEXT,
    keep_days     INTEGER,
    cutoff        DATE,
    rows_before   BIGINT,
    rows_removed  BIGINT,
    complete      BOOLEAN,
    note          TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    pol        RECORD;
    v_cutoff   DATE;
    v_before   BIGINT;
    v_removed  BIGINT;
    v_chunk    BIGINT;
BEGIN
    FOR pol IN
        SELECT * FROM retention_policy WHERE enabled ORDER BY table_name
    LOOP
        table_name   := pol.table_name;
        keep_days    := pol.keep_days;
        cutoff       := NULL;
        rows_before  := NULL;
        rows_removed := 0;
        complete     := TRUE;
        note         := NULL;

        -- A policy for a table that does not exist is reported, not raised:
        -- one missing table must not abort the other forty-two.
        IF to_regclass('public.' || quote_ident(pol.table_name)) IS NULL THEN
            note := 'no such table';
            complete := FALSE;
            RETURN NEXT;
            CONTINUE;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = pol.table_name
               AND column_name = pol.day_col
        ) THEN
            note := format('no column %I', pol.day_col);
            complete := FALSE;
            RETURN NEXT;
            CONTINUE;
        END IF;

        v_cutoff := CURRENT_DATE - pol.keep_days;
        cutoff   := v_cutoff;

        EXECUTE format('SELECT count(*) FROM %I WHERE %I < $1',
                       pol.table_name, pol.day_col)
           INTO v_before USING v_cutoff;
        rows_before := v_before;

        IF v_before = 0 THEN
            note := 'nothing over retention';
            RETURN NEXT;
            CONTINUE;
        END IF;

        IF p_dry_run THEN
            note := 'dry run — nothing deleted';
            RETURN NEXT;
            CONTINUE;
        END IF;

        v_removed := 0;
        LOOP
            EXECUTE format(
                'DELETE FROM %I WHERE ctid IN '
                '(SELECT ctid FROM %I WHERE %I < $1 LIMIT %s)',
                pol.table_name, pol.table_name, pol.day_col, p_chunk)
              USING v_cutoff;
            GET DIAGNOSTICS v_chunk = ROW_COUNT;
            EXIT WHEN v_chunk = 0;
            v_removed := v_removed + v_chunk;
            IF v_removed >= p_max_rows THEN
                complete := FALSE;
                note := format('stopped at the %s-row cap — next run resumes',
                               p_max_rows);
                EXIT;
            END IF;
        END LOOP;

        rows_removed := v_removed;

        INSERT INTO retention_log
            (ts, table_name, keep_days, day_col, cutoff,
             rows_before, rows_removed, windows, complete, policy_source, error)
        VALUES
            (NOW(), pol.table_name, pol.keep_days, pol.day_col, v_cutoff,
             v_before, v_removed, NULL, complete, pol.policy_source, note)
        ON CONFLICT (ts, table_name) DO NOTHING;

        RETURN NEXT;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION retention_purge IS
    'Applies enabled rows of retention_policy. Dry run by default. '
    'Chunked by ctid so no single statement holds a long transaction.';


-- ══════════════════════════════════════════════════════════════════════
-- retention_preview() — the safe one, callable from the app
-- ══════════════════════════════════════════════════════════════════════
-- Counts what a purge WOULD remove, for every policy including the disabled
-- ones, so you can read the numbers before enabling anything.

CREATE OR REPLACE FUNCTION retention_preview()
RETURNS TABLE (
    table_name   TEXT,
    keep_days    INTEGER,
    day_col      TEXT,
    cutoff       DATE,
    rows_over    BIGINT,
    enabled      BOOLEAN,
    note         TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    pol      RECORD;
    v_cutoff DATE;
    v_count  BIGINT;
BEGIN
    FOR pol IN SELECT * FROM retention_policy ORDER BY table_name LOOP
        table_name := pol.table_name;
        keep_days  := pol.keep_days;
        day_col    := pol.day_col;
        enabled    := pol.enabled;
        cutoff     := NULL;
        rows_over  := NULL;
        note       := NULL;

        IF to_regclass('public.' || quote_ident(pol.table_name)) IS NULL THEN
            note := 'no such table';
            RETURN NEXT;
            CONTINUE;
        END IF;

        v_cutoff := CURRENT_DATE - pol.keep_days;
        cutoff   := v_cutoff;
        BEGIN
            EXECUTE format('SELECT count(*) FROM %I WHERE %I < $1',
                           pol.table_name, pol.day_col)
               INTO v_count USING v_cutoff;
            rows_over := v_count;
        EXCEPTION WHEN OTHERS THEN
            -- NULL, never 0. "I could not count" and "nothing to remove" must
            -- not render the same.
            note := 'could not count';
        END;
        RETURN NEXT;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION retention_preview IS
    'Row counts a purge would remove, per policy. Never deletes.';


-- ══════════════════════════════════════════════════════════════════════
-- SCHEDULING — you do this, deliberately, after reading a preview
-- ══════════════════════════════════════════════════════════════════════
-- Nothing below runs on install. Every statement is commented out.
--
-- STEP 1 — enable pg_cron. Supabase: Database → Extensions → pg_cron.
--
--   CREATE EXTENSION IF NOT EXISTS pg_cron;
--
-- STEP 2 — look before you delete.
--
--   SELECT * FROM retention_preview() ORDER BY rows_over DESC NULLS LAST;
--
-- STEP 3 — enable the policies you accept, one at a time or in groups. The
--          short-window microstructure tables are the safe place to start;
--          they hold same-day artefacts and reclaim the most.
--
--   UPDATE retention_policy SET enabled = TRUE
--    WHERE table_name IN ('option_chain_data', 'orderbook_data',
--                         'bid_ask_history', 'detected_patterns',
--                         'volume_delta_history');
--
-- STEP 4 — dry-run the real function against exactly what is enabled.
--
--   SELECT * FROM retention_purge(p_dry_run => true);
--
-- STEP 5 — the first real purge, by hand, watching it.
--          Years of accumulated rows will not clear in one call: the row cap
--          exists so it cannot. Re-run until `complete` is true everywhere.
--
--   SELECT * FROM retention_purge(p_dry_run => false);
--
-- STEP 6 — only now, schedule it. 20:00 IST = 14:30 UTC, well after the close.
--
--   SELECT cron.schedule(
--       'mios-retention-nightly',
--       '30 14 * * 1-5',
--       $job$ SELECT retention_purge(p_dry_run => false); $job$);
--
-- STEP 7 — turn OFF the in-process pass, so there is exactly one purger.
--          In db/retention.py leave ENABLED = False: the app-side preview keeps
--          working, and only cron deletes. Two schedulers purging the same
--          tables is not twice as safe.
--
-- ── operating it ────────────────────────────────────────────────────
--
--   SELECT * FROM cron.job;                            -- what is scheduled
--   SELECT * FROM cron.job_run_details                 -- what happened
--    ORDER BY start_time DESC LIMIT 20;
--   SELECT * FROM retention_log                        -- what was removed
--    ORDER BY ts DESC LIMIT 50;
--
--   SELECT cron.unschedule('mios-retention-nightly');  -- stop it
--
-- ── after the first big purge ────────────────────────────────────────
-- DELETE marks rows dead; it does not return their space to the filesystem.
-- Autovacuum reclaims it for reuse, but the file stays as large as it ever was.
-- To actually shrink on disk, once, outside market hours:
--
--   VACUUM (ANALYZE, VERBOSE) option_chain_data;   -- reuse, no lock
--   -- or, to give space back to the OS (takes an ACCESS EXCLUSIVE lock):
--   VACUUM FULL option_chain_data;
--
-- If a table has never been purged before, expect the dashboard's storage
-- figure to stay flat until one of those runs. That is not the purge failing.
