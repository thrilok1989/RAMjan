-- 031_dispatch_history: the Telegram Message Registry (Stage 72.9).
--
-- Every alert MIOS emits is traceable: which decision produced it, whether the
-- record was intact, which Telegram message carries it, and what happened to
-- that message afterwards.
--
-- APPEND-ONLY. A decision that was READY and then SENT is two rows, so the
-- history says what happened rather than only where it ended. Nothing is ever
-- updated in place except `status`/`updated_at` on a message that was EDITED or
-- DELETED — which is the message's fate, not the dispatch's.
--
-- `telegram_message_id` is what makes an EDIT possible: when Stage 73 moves a
-- trade from HOLD to EXIT, the dispatcher updates the message already on screen
-- instead of posting a second one that reads like a new signal.

CREATE TABLE IF NOT EXISTS dispatch_history (
    id                  BIGSERIAL PRIMARY KEY,
    decision_id         TEXT NOT NULL,          -- EntryDecision.id
    decision_hash       TEXT NOT NULL,          -- EntryDecision.hash
    lifecycle_id        TEXT,                   -- TradeLifecycleDecision.id
    dispatch_id         TEXT NOT NULL,          -- DispatchDecision.id
    dispatch_state      TEXT NOT NULL,          -- READY · SENT · BLOCKED · …
    telegram_message_id TEXT,                   -- the handle an EDIT needs
    chat_id             TEXT,
    status              TEXT NOT NULL DEFAULT 'NOT_SENT',
                                                -- NOT_SENT · SENT · FAILED ·
                                                -- EDITED · DELETED · RETRY ·
                                                -- RATE_LIMIT · UNKNOWN
    payload             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- the duplicate check reads this on every cycle
CREATE INDEX IF NOT EXISTS idx_dispatch_history_hash
    ON dispatch_history (decision_hash);

-- supersession and `live_message` both walk backwards from newest
CREATE INDEX IF NOT EXISTS idx_dispatch_history_decision
    ON dispatch_history (decision_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_history_created
    ON dispatch_history (created_at DESC);

-- A hash may be DELIVERED exactly once. This is the duplicate guarantee at the
-- database level rather than only in the dispatcher: two app instances racing
-- on the same decision cannot both win.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_dispatch_sent_hash
    ON dispatch_history (decision_hash)
    WHERE status = 'SENT';

-- single-user dashboard authenticating via the anon key — no RLS
ALTER TABLE IF EXISTS dispatch_history DISABLE ROW LEVEL SECURITY;
