-- 022_vob_app_state: the app's live snapshot row.
--
-- The desktop app upserts a single JSON payload here every ~5 min
-- (save_app_state) — the Market Picture, news/leg bias, meters. Two things
-- read it back: the standalone discord_bot.py (!picture/!bias/!news commands)
-- and the ?view=mobile phone page. One row per client id.
--
-- This was missing from a fresh Supabase project (the app's write is wrapped
-- in try/except so it failed silently; the mobile page surfaced it with
-- PGRST205 "Could not find the table 'public.vob_app_state'"). Run this in the
-- Supabase SQL editor. Idempotent.

CREATE TABLE IF NOT EXISTS vob_app_state (
    id          TEXT PRIMARY KEY,          -- DHAN_CLIENT_ID (or 'default')
    payload     JSONB,                     -- serialized session snapshot
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vob_app_state_updated
    ON vob_app_state (updated_at DESC);

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS vob_app_state DISABLE ROW LEVEL SECURITY;
