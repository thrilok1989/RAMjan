-- 017_market_stories: Market story timeline with recognition & validation

CREATE TABLE IF NOT EXISTS market_stories (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    story_id INTEGER NOT NULL,
    market_time_start TIMESTAMP WITH TIME ZONE NOT NULL,
    market_time_end TIMESTAMP WITH TIME ZONE,
    symbol TEXT NOT NULL,
    story_type TEXT,  -- "bullish_continuation", etc. (null until classified)
    confidence NUMERIC,  -- 0-100 (null until classified)
    summary TEXT,  -- human-readable narrative
    event_count INTEGER,
    duration_seconds INTEGER,
    related_trade_id BIGINT  -- optional link to entry_gate_signals
);

CREATE INDEX IF NOT EXISTS idx_market_stories_type ON market_stories(story_type);
CREATE INDEX IF NOT EXISTS idx_market_stories_time ON market_stories(market_time_start DESC);
CREATE INDEX IF NOT EXISTS idx_market_stories_trade ON market_stories(related_trade_id);

-- Story validation outcomes linked to trades
CREATE TABLE IF NOT EXISTS story_validations (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    trade_id BIGINT NOT NULL,
    story_id INTEGER NOT NULL,
    story_type TEXT NOT NULL,
    outcome TEXT NOT NULL,  -- "win", "loss", "breakeven"
    points_moved NUMERIC NOT NULL,
    mae NUMERIC,
    mfe NUMERIC,
    r_multiple NUMERIC,  -- points_moved / risk
    exit_reason TEXT,
    duration_seconds INTEGER
);

CREATE INDEX IF NOT EXISTS idx_story_validations_type ON story_validations(story_type);
CREATE INDEX IF NOT EXISTS idx_story_validations_outcome ON story_validations(outcome);
CREATE INDEX IF NOT EXISTS idx_story_validations_trade ON story_validations(trade_id);

-- Story type win-rate statistics (materialized)
CREATE TABLE IF NOT EXISTS story_stats (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    story_type TEXT NOT NULL UNIQUE,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    breakevens INTEGER DEFAULT 0,
    win_rate NUMERIC,
    avg_points NUMERIC,
    avg_r_multiple NUMERIC,
    avg_mae NUMERIC,
    avg_mfe NUMERIC,
    total_pnl NUMERIC,
    best_win NUMERIC,
    max_loss NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_story_stats_type ON story_stats(story_type);
