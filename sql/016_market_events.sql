-- 016_market_events: Market intelligence event timeline
-- Stores structured market events for live Discord feed and validation dataset

CREATE TABLE IF NOT EXISTS market_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    event_time TIMESTAMP WITH TIME ZONE NOT NULL,
    event_type TEXT NOT NULL,  -- "put_writing", "cvd_divergence", etc.
    severity TEXT NOT NULL,    -- "info", "warning", "alert"
    headline TEXT NOT NULL,    -- "Heavy Put Writing at 24850"
    detail TEXT NOT NULL,      -- "Dealers hedging upside; expect support hold"
    price_point NUMERIC,       -- strike/level where event occurred
    snapshot JSONB             -- market snapshot at event time
);

CREATE INDEX IF NOT EXISTS idx_market_events_time ON market_events(event_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_type ON market_events(event_type);
CREATE INDEX IF NOT EXISTS idx_market_events_severity ON market_events(severity);
