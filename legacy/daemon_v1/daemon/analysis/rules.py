from typing import List, Dict, Any
from ..db.db import get_db_connection

class RuleEngine:
    def __init__(self):
        pass

    def get_rules_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all rules enabled for the project
        cursor.execute("""
            SELECT rule_id, priority, enabled 
            FROM RuleConfig 
            WHERE project_id = ? AND enabled = 1
        """, (project_id,))
        
        rules = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return rules

    def update_rule_config(self, project_id: str, rule_id: str, enabled: bool, priority: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO RuleConfig (rule_id, project_id, enabled, priority, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (rule_id, project_id, enabled, priority))
        conn.commit()
        conn.close()
