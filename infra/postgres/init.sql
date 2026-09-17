-- =============================================================================
-- LogSentinel — PostgreSQL Init Script
-- Runs once when the postgres container is first created
-- =============================================================================

-- Create the alerts table
CREATE TABLE IF NOT EXISTS alerts (
    id                   SERIAL PRIMARY KEY,
    alert_id             TEXT UNIQUE NOT NULL,
    log_id               TEXT,
    service              TEXT,
    level                TEXT,
    message              TEXT,
    anomaly_score        DOUBLE PRECISION,
    host                 TEXT,
    response_time_ms     DOUBLE PRECISION,
    error_code           INTEGER,
    detected_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    slack_sent           BOOLEAN DEFAULT FALSE,
    email_sent           BOOLEAN DEFAULT FALSE,
    deduplicated         BOOLEAN DEFAULT FALSE,
    notification_channels TEXT[],
    features             JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_detected_at  ON alerts (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_service       ON alerts (service);
CREATE INDEX IF NOT EXISTS idx_alerts_level         ON alerts (level);
CREATE INDEX IF NOT EXISTS idx_alerts_deduplicated  ON alerts (deduplicated);

-- Grant permissions to the logsentinel user
GRANT ALL PRIVILEGES ON TABLE alerts TO logsentinel;
GRANT USAGE, SELECT ON SEQUENCE alerts_id_seq TO logsentinel;
