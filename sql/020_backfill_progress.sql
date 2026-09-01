-- 020_backfill_progress: resumable state for the Stage 2 historical
-- backfill. One row per named job — if the app restarts mid-backfill, the
-- button picks up from last_completed_day instead of starting over.

CREATE TABLE IF NOT EXISTS backfill_progress (
    job_name            TEXT PRIMARY KEY,
    last_completed_day  DATE,
    total_rows_written  BIGINT NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'idle',  -- idle | running | done | error
    error_message       TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
