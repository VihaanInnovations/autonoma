import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "reviewer.db"
SCHEMA_SQL = """
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

-- FileAnalysisCache table
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

-- API Keys table
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    last_used TIMESTAMP,
    rate_limit_per_minute INTEGER DEFAULT 60,
    allowed_ips TEXT,
    FOREIGN KEY(user_id) REFERENCES User(user_id)
);
CREATE INDEX IF NOT EXISTS idx_api_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_key_user ON api_keys(user_id);

-- API Key Rate Limiting table
CREATE TABLE IF NOT EXISTS api_key_rate_limits (
    key_hash TEXT NOT NULL,
    window_start TIMESTAMP NOT NULL,
    request_count INTEGER DEFAULT 0,
    PRIMARY KEY (key_hash, window_start),
    FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_key ON api_key_rate_limits(key_hash, window_start);
"""

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Check if critical table 'AuditLog' exists
    try:
        conn.execute("SELECT 1 FROM AuditLog LIMIT 1")
    except sqlite3.OperationalError:
        # Tables missing, initialize from embedded schema
        try:
             conn.executescript(SCHEMA_SQL)
             conn.commit()
        except Exception as e:
            print(f"DB Auto-Init Failed: {e}")
            
    return conn

def init_db():
    conn = get_db_connection()
    # Force run schema if invoked directly
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

from .crypto import encrypt

def save_analysis_result(file_path: str, content: str, issues: list, project_id: str, user_id: str = None):
    """
    Save analysis results to DB with encryption for sensitive fields.
    Also creates/updates Project entry if user_id is provided.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create/update Project entry if user_id is provided
        if user_id:
            cursor.execute(
                """
                INSERT OR REPLACE INTO Project (project_id, user_id, path, last_scanned)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (project_id, user_id, file_path)
            )
        
        # Encrypt sensitive content
        encrypted_content = encrypt(content)
        
        # Insert File Analysis Record
        cursor.execute(
            """
            INSERT INTO file_analysis (project_id, file_path, file_hash, content, timestamp)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (project_id, file_path, "HASH_PLACEHOLDER", encrypted_content)
        )
        analysis_id = cursor.lastrowid
        
        analysis_id = cursor.lastrowid
        
        # Insert Issues (Batch Write)
        if issues:
            issues_data = []
            for issue in issues:
                encrypted_message = encrypt(issue.get("message", ""))
                issues_data.append((
                    analysis_id,
                    issue.get("id", "UNKNOWN"),
                    issue.get("line", 0),
                    issue.get("type", "info"),
                    encrypted_message, # Swap order to match schema?
                    # Schema: analysis_id, rule_id, line, type, message, severity ...
                    # Wait, SQL below: (analysis_id, rule_id, line, message, type, severity)
                    # Let's align with the SQL statement below.
                    issue.get("severity", "low")
                ))
            
            # Re-check alignment with query below!
            # Query: VALUES (?, ?, ?, ?, ?, ?)
            # Columns: analysis_id, rule_id, line, message, type, severity
            
            final_data = []
            for issue in issues:
                 final_data.append((
                    analysis_id,
                    issue.get("id", "UNKNOWN"),
                    issue.get("line", 0),
                    encrypt(issue.get("message", "")),
                    issue.get("type", "info"),
                    issue.get("severity", "low")
                 ))
                 
            cursor.executemany(
                """
                INSERT INTO issues (analysis_id, rule_id, line, message, type, severity)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                final_data
            )
        
        conn.commit()
    except Exception as e:
        print(f"DB Insert Failed: {e}")
        conn.rollback()
    finally:
        conn.close()

        conn.close()

def log_audit_event(project_id: str, user_id: str, action: str, target: str, details: str = ""):
    """
    Log an event to the AuditLog table.
    """
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO AuditLog (project_id, user_id, action, target, details, timestamp)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (project_id, user_id, action, target, details)
        )
        conn.commit()
    except Exception as e:
        print(f"Audit Log Failed: {e}")
    finally:
        conn.close()

def get_user_tier(user_id: str) -> str:
    """Get user tier from database. Default to 'free'."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT tier FROM User WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row['tier'] if row else 'free'
    finally:
        conn.close()

def count_user_repositories(user_id: str) -> int:
    """Count number of unique repositories (projects) for a user"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # For GitHub Actions: project_id = "github-owner-repo-runId"
        # Extract owner-repo part to count unique repos
        cursor.execute("SELECT DISTINCT project_id FROM Project WHERE user_id = ?", (user_id,))
        projects = cursor.fetchall()
        
        # Extract unique repository identifiers
        repos = set()
        for project in projects:
            project_id = project['project_id']
            if project_id.startswith("github-"):
                # Format: github-owner-repo-runId -> extract owner-repo
                parts = project_id.split("-", 3)
                if len(parts) >= 3:
                    repos.add(f"{parts[1]}-{parts[2]}")
                else:
                    repos.add(project_id)
            else:
                repos.add(project_id)
        
        return len(repos)
    finally:
        conn.close()

def count_files_in_project(project_id: str) -> int:
    """Count number of files analyzed in a project"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT file_path) FROM file_analysis WHERE project_id = ?", (project_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()

def get_project_owner(project_id: str) -> str:
    """Get owner user_id for a project. Returns None if not found."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM Project WHERE project_id = ?", (project_id,))
        row = cursor.fetchone()
        return row['user_id'] if row else None
    finally:
        conn.close()

def get_all_users():
    """Get all users (for revenue calculation)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, tier FROM User")
        return cursor.fetchall()
    finally:
        conn.close()

def set_user_tier(user_id: str, tier: str):
    """Set user tier. Upsert if user doesn't exist."""
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO User (user_id, tier) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET tier = ?
            """,
            (user_id, tier, tier)
        )
        conn.commit()
    finally:
        conn.close()

def update_user_tier(user_id: str, tier: str):
    """Update user tier (alias for set_user_tier for compatibility)."""
    set_user_tier(user_id, tier)

def update_user_stripe_info(user_id: str, customer_id: str, subscription_id: str):
    """Update Stripe customer and subscription IDs for a user."""
    conn = get_db_connection()
    try:
        # Check if columns exist (for migration compatibility)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(User)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'stripe_customer_id' not in columns:
            # Run migration if columns don't exist
            cursor.execute("ALTER TABLE User ADD COLUMN stripe_customer_id TEXT")
            cursor.execute("ALTER TABLE User ADD COLUMN stripe_subscription_id TEXT")
            cursor.execute("ALTER TABLE User ADD COLUMN subscription_status TEXT DEFAULT 'active'")
        
        conn.execute(
            """
            UPDATE User 
            SET stripe_customer_id = ?, stripe_subscription_id = ?
            WHERE user_id = ?
            """,
            (customer_id, subscription_id, user_id)
        )
        conn.commit()
    except Exception as e:
        print(f"Failed to update Stripe info: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
