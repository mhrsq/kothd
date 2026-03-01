-- =============================================================
-- KoTH CTF Platform - Database Schema
-- =============================================================

-- Teams
CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    display_name VARCHAR(128),
    vpn_ip VARCHAR(45),
    token VARCHAR(128),
    category VARCHAR(32) DEFAULT 'default',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Hills (target servers to capture)
CREATE TABLE IF NOT EXISTS hills (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    description TEXT,
    ip_address VARCHAR(45) NOT NULL,
    ssh_port INTEGER DEFAULT 22,
    sla_check_url VARCHAR(256),
    sla_check_port INTEGER,
    sla_check_type VARCHAR(32) DEFAULT 'http',  -- 'http', 'tcp', 'custom'
    king_file_path VARCHAR(256) DEFAULT '/root/king.txt',
    base_points INTEGER DEFAULT 10,
    multiplier FLOAT DEFAULT 1.0,
    is_behind_pivot BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Ticks
CREATE TABLE IF NOT EXISTS ticks (
    id SERIAL PRIMARY KEY,
    tick_number INTEGER UNIQUE NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(16) DEFAULT 'running',  -- 'running', 'completed', 'failed'
    details JSONB DEFAULT '{}'
);

-- Tick Results (per tick per hill)
CREATE TABLE IF NOT EXISTS tick_results (
    id SERIAL PRIMARY KEY,
    tick_id INTEGER REFERENCES ticks(id) ON DELETE CASCADE,
    hill_id INTEGER REFERENCES hills(id) ON DELETE CASCADE,
    king_team_id INTEGER REFERENCES teams(id),
    sla_status BOOLEAN DEFAULT false,
    points_awarded INTEGER DEFAULT 0,
    raw_king_txt TEXT,
    check_duration_ms INTEGER,
    error_message TEXT,
    checked_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tick_id, hill_id)
);

-- Aggregated Scores
CREATE TABLE IF NOT EXISTS scores (
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    hill_id INTEGER REFERENCES hills(id) ON DELETE CASCADE,
    total_points INTEGER DEFAULT 0,
    ticks_as_king INTEGER DEFAULT 0,
    current_king BOOLEAN DEFAULT false,
    consecutive_ticks INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (team_id, hill_id)
);

-- Total team scores (materialized view for fast leaderboard)
CREATE TABLE IF NOT EXISTS team_scores (
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE PRIMARY KEY,
    total_points INTEGER DEFAULT 0,
    hills_owned INTEGER DEFAULT 0,
    total_ticks_as_king INTEGER DEFAULT 0,
    first_bloods INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW()
);

-- First blood tracking
CREATE TABLE IF NOT EXISTS first_bloods (
    hill_id INTEGER REFERENCES hills(id) PRIMARY KEY,
    team_id INTEGER REFERENCES teams(id),
    tick_number INTEGER,
    bonus_points INTEGER DEFAULT 50,
    captured_at TIMESTAMP DEFAULT NOW()
);

-- Game state & configuration
CREATE TABLE IF NOT EXISTS game_config (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(32) NOT NULL,
    actor VARCHAR(64),
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_tick_results_tick ON tick_results(tick_id);
CREATE INDEX IF NOT EXISTS idx_tick_results_hill ON tick_results(hill_id);
CREATE INDEX IF NOT EXISTS idx_tick_results_king ON tick_results(king_team_id);
CREATE INDEX IF NOT EXISTS idx_scores_team ON scores(team_id);
CREATE INDEX IF NOT EXISTS idx_ticks_number ON ticks(tick_number);
CREATE INDEX IF NOT EXISTS idx_audit_log_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log(created_at);

-- Insert default game configuration
INSERT INTO game_config (key, value, description) VALUES
    ('game_status', 'not_started', 'Current game state: not_started, running, paused, finished'),
    ('tick_interval', '60', 'Seconds between each tick'),
    ('grace_period', '300', 'Seconds before scoring begins after game start'),
    ('freeze_before_end', '1800', 'Seconds before game end to freeze scoreboard'),
    ('game_duration', '21600', 'Total game duration in seconds (6 hours)'),
    ('base_points', '10', 'Base points per tick per hill'),
    ('pivot_multiplier', '1.5', 'Score multiplier for hills behind pivot'),
    ('first_blood_bonus', '50', 'Bonus points for first capture of a hill'),
    ('defense_streak_bonus', '5', 'Bonus points per consecutive tick holding a hill'),
    ('game_start_time', '', 'Timestamp when game was started'),
    ('current_tick', '0', 'Current tick number')
ON CONFLICT (key) DO NOTHING;

-- Insert example hills (update IPs to match your infrastructure)
-- INSERT INTO hills (name, description, ip_address, ssh_port, sla_check_url, sla_check_port, sla_check_type, base_points, multiplier, is_behind_pivot) VALUES
--     ('Hill 1 - Web', 'Web application challenge server.', '10.x.x.2', 22, 'http://10.x.x.2:80', 80, 'http', 10, 1.0, false),
--     ('Hill 2 - Services', 'Multiple service challenge server.', '10.x.x.3', 22, NULL, 9999, 'tcp', 10, 1.0, false),
--     ('Hill 3 - API', 'API challenge behind pivot.', '10.x.x.10', 22, 'http://10.x.x.10:8080', 8080, 'http', 10, 1.5, true),
--     ('Hill 4 - Database', 'Database challenge behind pivot.', '10.x.x.11', 22, NULL, 27017, 'tcp', 10, 1.5, true)
-- ON CONFLICT DO NOTHING;
