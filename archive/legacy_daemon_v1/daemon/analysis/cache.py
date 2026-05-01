import hashlib
import json
from datetime import datetime
from ..db.db import get_db_connection
from .ast_engine import ASTEngine

class AnalysisCache:
    def __init__(self):
        self.ast_engine = ASTEngine()

    def compute_hash(self, content: str) -> str:
        # Use Semantic Hash (AST-based)
        if self.ast_engine.parser:
            return self.ast_engine.compute_semantic_hash(content)
        # Fallback to byte hash
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def generate_cache_key(self, file_hash: str, rule_version: str, llm_model: str, config_version: str) -> str:
        # Cache key structure as per spec: file_hash + rule_set_version + llm_model + config_version
        combined = f"{file_hash}:{rule_version}:{llm_model}:{config_version}"
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()

    def get(self, cache_key: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT issues_json, created_at FROM file_analysis_cache WHERE cache_key = ?", (cache_key,))
        row = cursor.fetchone()
        
        result = None
        if row:
            # Check TTL (24 hours)
            created_at_str = row['created_at']
            try:
                # Handle potential format differences (ISO vs SQLite default)
                created_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                # Fallback implementation if format varies
                created_at = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")

            age = datetime.utcnow() - created_at
            if age.total_seconds() > 86400: # 24 hours
                # Expired
                cursor.execute("DELETE FROM file_analysis_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()
            else:
                result = json.loads(row['issues_json'])
        
        conn.close()
        return result

    def set(self, cache_key: str, issues: list):
        conn = get_db_connection()
        cursor = conn.cursor()
        issues_json = json.dumps(issues)
        now = datetime.utcnow()
        
        # 1. Insert or Replace
        cursor.execute("""
            INSERT OR REPLACE INTO file_analysis_cache (cache_key, issues_json, created_at)
            VALUES (?, ?, ?)
        """, (cache_key, issues_json, now))
        
        # 2. Enforce Size Limit (LRU-ish: Delete oldest)
        # Limit hardcoded to 1000 for now, could be config
        LIMIT = 1000
        cursor.execute("SELECT COUNT(*) FROM file_analysis_cache")
        count = cursor.fetchone()[0]
        
        if count > LIMIT:
            # Delete oldest (smallest created_at)
            # We delete count - LIMIT oldest entries to be safe
            to_delete = count - LIMIT
            cursor.execute("""
                DELETE FROM file_analysis_cache 
                WHERE cache_key IN (
                    SELECT cache_key FROM file_analysis_cache 
                    ORDER BY created_at ASC 
                    LIMIT ?
                )
            """, (to_delete,))
            
        conn.commit()
        conn.close()

    def clear(self):
        """Explicitly clear the entire cache."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM file_analysis_cache")
        conn.commit()
        conn.close()
