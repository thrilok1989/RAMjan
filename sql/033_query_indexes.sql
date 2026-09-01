-- Query/index audit — the indexes the real query shapes need.
-- Full findings and method: docs/AUDIT_QUERY_INDEXES.md
--
-- ⚠️ RUN THIS OUTSIDE MARKET HOURS.
--    A plain CREATE INDEX takes a SHARE lock and blocks writes on that table
--    until it finishes. On option_chain_data and candles_data that can be
--    minutes. If you must run it live, use the CONCURRENTLY variants at the
--    bottom of this file instead — they do not block writes, but they cannot
--    run inside a transaction block, so run them ONE AT A TIME.
--
-- Every index here exists because a query in db/supabase_client.py filters or
-- sorts on exactly these columns, in this order. Nothing is speculative: 110
-- distinct query shapes were extracted from the client's parse tree and matched
-- against all 238 declared indexes.
--
-- The column order is the query's, not alphabetical. A btree on (a, b, c)
-- serves equality on a, then a+b, then a+b+c, and a range or sort on the column
-- after the last equality — so the equality columns come first and the sorted
-- column comes last. An index in the wrong order serves the filter and leaves
-- the sort to a separate sort node, which is what most of these are fixing.


-- ══════════════════════════════════════════════════════════════════════
-- 1 · THE LEARNING TABLES — the biggest finding
-- ══════════════════════════════════════════════════════════════════════
-- `_learning_rows` runs `ORDER BY created_at DESC LIMIT n` with NO filter, and
-- three of the four tables it reads have no index on created_at at all. So
-- get_engine_attribution(8000) — the single heaviest read in the app — is a
-- full table scan plus a sort, every time it is not served from cache.
--
-- trade_events was already fine: idx_trade_events_ts (ts) serves its ORDER BY
-- ts DESC, since a btree can be scanned backwards.

CREATE INDEX IF NOT EXISTS idx_eng_attr_created
    ON engine_attribution (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_attr_created
    ON trade_attribution (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_results_created
    ON trade_results (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_learning_created
    ON learning_snapshots (created_at DESC);


-- ══════════════════════════════════════════════════════════════════════
-- 2 · CANDLES — every read misses `exchange`
-- ══════════════════════════════════════════════════════════════════════
-- idx_candles_symbol_tf is (symbol, timeframe, datetime), but all three reads
-- filter on (symbol, exchange, timeframe). Postgres can still use it, then
-- re-checks `exchange` on every row it returns.
--
-- get_candle_trading_days is the one that matters most: it reads `trading_day`
-- for an entire series to compute a DISTINCT, and compute_prev_day_value calls
-- it. These two indexes turn both of its queries into index-only scans.

CREATE INDEX IF NOT EXISTS idx_candles_series_day
    ON candles_data (symbol, exchange, timeframe, trading_day);

CREATE INDEX IF NOT EXISTS idx_candles_series_day_ts
    ON candles_data (symbol, exchange, timeframe, trading_day, timestamp);

CREATE INDEX IF NOT EXISTS idx_candles_series_datetime
    ON candles_data (symbol, exchange, timeframe, datetime);


-- ══════════════════════════════════════════════════════════════════════
-- 3 · PER-CYCLE READS — these run on the live path
-- ══════════════════════════════════════════════════════════════════════
-- get_active_trade_signal and get_latest_spot are LIVE reads in the cache
-- layer: they are allowed to expire every refresh cycle, so they are the reads
-- that actually reach the database most often. Both were filter-then-sort.

CREATE INDEX IF NOT EXISTS idx_trade_signals_status_created
    ON trade_signals (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_spot_sec_day_ts
    ON nifty_spot_data (security_id, trading_day, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_spot_sec_ts
    ON nifty_spot_data (security_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_auto_trades_status_entry
    ON auto_trades (status, entry_time DESC);

CREATE INDEX IF NOT EXISTS idx_auto_trades_day_entry
    ON auto_trades (trading_day, entry_time DESC);


-- ══════════════════════════════════════════════════════════════════════
-- 4 · THE CHAIN TABLES — highest row counts in the schema
-- ══════════════════════════════════════════════════════════════════════
-- Each of these had three single-column indexes (expiry, strike_price,
-- timestamp) and every query filters on two of them and sorts on the third.
-- Three single-column indexes do not add up to one composite.

CREATE INDEX IF NOT EXISTS idx_oc_expiry_day_ts
    ON option_chain_data (expiry, trading_day, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_oc_expiry_strike_day_ts
    ON option_chain_data (expiry, strike_price, trading_day, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_atm_expiry_day_ts
    ON atm_strike_data (expiry, trading_day, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ob_expiry_day_ts
    ON orderbook_data (expiry, trading_day, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_vol_delta_day_sym_ts
    ON volume_delta_history (trading_day, symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_oc_signal_day_ts
    ON oc_signal_history (trading_day, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_master_signals_day_ts
    ON master_signals (trading_day, timestamp DESC);


-- ══════════════════════════════════════════════════════════════════════
-- 5 · UNFILTERED "NEWEST N" READS
-- ══════════════════════════════════════════════════════════════════════
-- ORDER BY <col> DESC LIMIT n with no WHERE. An index on the sort column turns
-- a scan-and-sort into reading the first n index entries.

CREATE INDEX IF NOT EXISTS idx_bias_pred_ts
    ON bias_predictions (ts DESC);

CREATE INDEX IF NOT EXISTS idx_session_rec_created
    ON session_recommendations (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_val_created
    ON session_validation_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_entry
    ON signal_outcomes (ts_entry DESC);

CREATE INDEX IF NOT EXISTS idx_story_stats_winrate
    ON story_stats (win_rate DESC);


-- ══════════════════════════════════════════════════════════════════════
-- 6 · RETENTION SCANS
-- ══════════════════════════════════════════════════════════════════════
-- db/retention.py counts and deletes on `day_col`. Where that column is a
-- timestamp rather than trading_day, there was no index for it — so a purge
-- would scan the whole table to find the rows to remove, which is the wrong
-- shape of work for a job whose entire purpose is to make the table smaller.

CREATE INDEX IF NOT EXISTS idx_market_events_created
    ON market_events (created_at);

CREATE INDEX IF NOT EXISTS idx_market_stories_created
    ON market_stories (created_at);

CREATE INDEX IF NOT EXISTS idx_story_val_created
    ON story_validations (created_at);


-- ══════════════════════════════════════════════════════════════════════
-- CONCURRENTLY variants — for running during market hours
-- ══════════════════════════════════════════════════════════════════════
-- CREATE INDEX CONCURRENTLY does not block writes, but it cannot run inside a
-- transaction block. Run these ONE STATEMENT AT A TIME, not as a script. They
-- are slower and can leave an INVALID index if interrupted — check with:
--
--   SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
--
-- and DROP anything that turns up before retrying.
--
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_eng_attr_created
--     ON engine_attribution (created_at DESC);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oc_expiry_day_ts
--     ON option_chain_data (expiry, trading_day, timestamp DESC);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_candles_series_day
--     ON candles_data (symbol, exchange, timeframe, trading_day);


-- ══════════════════════════════════════════════════════════════════════
-- AFTERWARDS
-- ══════════════════════════════════════════════════════════════════════
-- Planner statistics do not update themselves immediately after a bulk index
-- build, and a stale estimate can make the planner ignore an index it should
-- use. Run this once when the indexes are in:
--
--   ANALYZE engine_attribution, trade_attribution, trade_results,
--           learning_snapshots, candles_data, option_chain_data,
--           nifty_spot_data, trade_signals;
--
-- To confirm an index is actually being used, and not merely present:
--
--   SELECT relname, indexrelname, idx_scan
--     FROM pg_stat_user_indexes
--    WHERE idx_scan = 0
--    ORDER BY relname;
--
-- An index with idx_scan = 0 after a full trading day is dead weight: it costs
-- write time and storage and serves nothing. Drop it rather than keep it.
