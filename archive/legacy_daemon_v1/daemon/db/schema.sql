-- User table
CREATE TABLE IF NOT EXISTS User (
    user_id TEXT PRIMARY KEY,
    email TEXT,
    tier TEXT DEFAULT 'free' -- free, pro, enterprise
);

-- Project table
CREATE TABLE IF NOT EXISTS Project (
    project_id TEXT PRIMARY KEY,
    user_id TEXT,
    path TEXT,
    language TEXT,
    last_scanned TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES User(user_id)
);

-- FileAnalysis table (Cache)
CREATE TABLE IF NOT EXISTS file_analysis (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    file_path TEXT,
    file_hash TEXT,
    content TEXT, -- Encrypted content
    timestamp TIMESTAMP
);

-- Issue table
CREATE TABLE IF NOT EXISTS issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER,
    rule_id TEXT,
    line INTEGER,
    type TEXT, -- lint, security, performance, refactor
    message TEXT, -- Encrypted message
    severity TEXT,
    suggested_fix TEXT,
    source TEXT, -- heuristic, llm_local, llm_cloud
    FOREIGN KEY(analysis_id) REFERENCES file_analysis(analysis_id)
);

-- TelemetryEvent table
CREATE TABLE IF NOT EXISTS TelemetryEvent (
    event_id TEXT PRIMARY KEY,
    user_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT,
    metadata TEXT -- JSON string
);

-- RuleConfig table
CREATE TABLE IF NOT EXISTS RuleConfig (
    rule_id TEXT PRIMARY KEY,
    project_id TEXT,
    enabled BOOLEAN DEFAULT 1,
    priority TEXT, -- low, medium, high
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES Project(project_id)
);

-- FileAnalysisCache table (as per spec item 5)
-- key: file_hash + rule_set_version + llm_model + config_version
CREATE TABLE IF NOT EXISTS file_analysis_cache (
    cache_key TEXT PRIMARY KEY,
    issues_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_project_id ON Project(project_id);
CREATE INDEX IF NOT EXISTS idx_file_analysis_project ON file_analysis(project_id);
CREATE INDEX IF NOT EXISTS idx_file_analysis_path ON file_analysis(file_path);
CREATE INDEX IF NOT EXISTS idx_file_analysis_ts ON file_analysis(timestamp);
CREATE INDEX IF NOT EXISTS idx_issues_analysis_id ON issues(analysis_id);

-- AuditLog table
CREATE TABLE IF NOT EXISTS AuditLog (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    user_id TEXT,
    action TEXT,
    target TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_project ON AuditLog(project_id);

-- API Keys table (for GitHub Actions and API access)
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    last_used TIMESTAMP,
    rate_limit_per_minute INTEGER DEFAULT 60,
    allowed_ips TEXT, -- JSON array of allowed IPs, NULL = all IPs allowed
    FOREIGN KEY(user_id) REFERENCES User(user_id)
);

CREATE INDEX IF NOT EXISTS idx_api_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_key_user ON api_keys(user_id);

-- API Key Rate Limiting table (tracks requests per API key)
CREATE TABLE IF NOT EXISTS api_key_rate_limits (
    key_hash TEXT NOT NULL,
    window_start TIMESTAMP NOT NULL,
    request_count INTEGER DEFAULT 0,
    PRIMARY KEY (key_hash, window_start),
    FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_key ON api_key_rate_limits(key_hash, window_start);

