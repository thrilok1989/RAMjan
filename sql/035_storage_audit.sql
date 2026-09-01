-- Storage audit — where the bytes actually are.
-- Findings and method: docs/AUDIT_SUPABASE_STORAGE.md
--
-- ⚠️ FIRST, THE THING THAT SURPRISES PEOPLE:
--    Supabase "Storage" (buckets and files) and Supabase database storage are
--    two different products with one word between them. **This application does
--    not use Storage at all** — there is no `.storage`, no bucket, no upload
--    anywhere in the codebase. The only CSV it produces goes to an in-memory
--    buffer for a browser download and never leaves the browser.
--
--    So if the dashboard shows storage growing, it is the DATABASE, and these
--    functions are how you find out which table.
--
-- Delivered as functions rather than a script because PostgREST cannot run
-- arbitrary SQL: a function is the only way the app can ask these questions,
-- and `docs/AUDIT_QUERY_INDEXES.md` §9 noted the absence of RPCs as a gap.


-- ══════════════════════════════════════════════════════════════════════
-- storage_report() — every table, biggest first
-- ══════════════════════════════════════════════════════════════════════
-- `live_rows` is the planner's estimate from pg_stat_user_tables, not a
-- count(*). It is free and it is approximate, and on a table nobody has
-- ANALYZEd it can be badly wrong — which is why `dead_rows` sits next to it.
--
-- A large `dead_rows` means DELETEs happened and the space is waiting for
-- autovacuum to make it reusable. A large `total_bytes` with small `live_rows`
-- means it already did, and the file is holding space the table no longer
-- needs — that is when VACUUM FULL is the answer.

CREATE OR REPLACE FUNCTION storage_report()
RETURNS TABLE (
    table_name    TEXT,
    live_rows     BIGINT,
    dead_rows     BIGINT,
    total_bytes   BIGINT,
    table_bytes   BIGINT,
    index_bytes   BIGINT,
    toast_bytes   BIGINT,
    total_pretty  TEXT,
    index_pretty  TEXT,
    last_vacuum   TIMESTAMPTZ,
    last_analyze  TIMESTAMPTZ
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        c.relname::TEXT,
        s.n_live_tup,
        s.n_dead_tup,
        pg_total_relation_size(c.oid),
        pg_table_size(c.oid) - COALESCE(pg_relation_size(c.reltoastrelid), 0),
        pg_indexes_size(c.oid),
        COALESCE(pg_relation_size(c.reltoastrelid), 0),
        pg_size_pretty(pg_total_relation_size(c.oid)),
        pg_size_pretty(pg_indexes_size(c.oid)),
        GREATEST(s.last_vacuum, s.last_autovacuum),
        GREATEST(s.last_analyze, s.last_autoanalyze)
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY pg_total_relation_size(c.oid) DESC;
$$;

COMMENT ON FUNCTION storage_report IS
    'Per-table size, row estimates and vacuum state. Biggest first.';


-- ══════════════════════════════════════════════════════════════════════
-- unused_indexes() — dead weight
-- ══════════════════════════════════════════════════════════════════════
-- An index nothing scans costs write time on every INSERT and storage forever,
-- and serves nothing. Primary keys and unique constraints are excluded: they
-- enforce correctness whether or not a query ever reads them, and every upsert
-- in this client depends on one.
--
-- Read this only after a full trading day. `idx_scan` counts since the last
-- stats reset, so a freshly reset counter makes every index look unused.

CREATE OR REPLACE FUNCTION unused_indexes()
RETURNS TABLE (
    table_name  TEXT,
    index_name  TEXT,
    index_size  TEXT,
    size_bytes  BIGINT,
    scans       BIGINT
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        s.relname::TEXT,
        s.indexrelname::TEXT,
        pg_size_pretty(pg_relation_size(s.indexrelid)),
        pg_relation_size(s.indexrelid),
        s.idx_scan
    FROM pg_stat_user_indexes s
    JOIN pg_index i ON i.indexrelid = s.indexrelid
    WHERE s.schemaname = 'public'
      AND s.idx_scan = 0
      AND NOT i.indisprimary
      AND NOT i.indisunique
    ORDER BY pg_relation_size(s.indexrelid) DESC;
$$;

COMMENT ON FUNCTION unused_indexes IS
    'Non-constraint indexes with zero scans. Read after a full trading day.';


-- ══════════════════════════════════════════════════════════════════════
-- retention_pressure() — which table is big AND purgeable
-- ══════════════════════════════════════════════════════════════════════
-- Size alone does not tell you what to do. A big table with no policy needs a
-- policy; a big table with a policy nobody enabled needs one line of SQL. This
-- joins the two so the answer is in one place.
--
-- Depends on sql/034_retention_cron.sql for retention_policy.

CREATE OR REPLACE FUNCTION retention_pressure()
RETURNS TABLE (
    table_name    TEXT,
    total_pretty  TEXT,
    total_bytes   BIGINT,
    live_rows     BIGINT,
    keep_days     INTEGER,
    policy        TEXT,
    verdict       TEXT
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        r.table_name,
        r.total_pretty,
        r.total_bytes,
        r.live_rows,
        p.keep_days,
        COALESCE(p.policy_source, '—'),
        CASE
            WHEN p.table_name IS NULL      THEN 'no policy — grows forever'
            WHEN NOT p.enabled             THEN 'policy exists, NOT enabled'
            ELSE                                'policed'
        END
    FROM storage_report() r
    LEFT JOIN retention_policy p ON p.table_name = r.table_name
    ORDER BY r.total_bytes DESC;
$$;

COMMENT ON FUNCTION retention_pressure IS
    'Table size joined to its retention policy, biggest first.';


-- ══════════════════════════════════════════════════════════════════════
-- Reading it by hand
-- ══════════════════════════════════════════════════════════════════════
--
--   SELECT * FROM retention_pressure() LIMIT 20;   -- start here
--   SELECT * FROM storage_report()     LIMIT 20;
--   SELECT * FROM unused_indexes();
--
-- Total database size, the number the dashboard shows:
--
--   SELECT pg_size_pretty(pg_database_size(current_database()));
--
-- Space held by dead rows a purge left behind:
--
--   SELECT relname, n_dead_tup,
--          pg_size_pretty(pg_total_relation_size(relid)) AS size
--     FROM pg_stat_user_tables
--    WHERE n_dead_tup > 100000
--    ORDER BY n_dead_tup DESC;
--
-- Supabase Storage — buckets and files. This app writes none, so a non-empty
-- result here is something a human uploaded through the dashboard:
--
--   SELECT b.name AS bucket, count(o.id) AS files,
--          pg_size_pretty(COALESCE(SUM((o.metadata->>'size')::BIGINT), 0)) AS bytes
--     FROM storage.buckets b
--     LEFT JOIN storage.objects o ON o.bucket_id = b.id
--    GROUP BY b.name ORDER BY 3 DESC;
