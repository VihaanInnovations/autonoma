from typing import Optional
import json
from .db.db import log_audit_event
from daemon.logging.structured_logger import StructuredLogger

class AuditLogger:
    def __init__(self, project_id: str, user_id: str = "local_user"):
        self.project_id = project_id
        self.user_id = user_id
        self.structured_logger = StructuredLogger(service_name="autonoma-audit")

    def log(self, action: str, target: str, details: Optional[dict] = None):
        details_str = json.dumps(details) if details else ""
        # 1. Legacy DB Log
        try:
            log_audit_event(self.project_id, self.user_id, action, target, details_str)
        except Exception:
            pass # Fail open if DB is down
            
        # 2. Enterprise JSON Log
        self.structured_logger.log("INFO", action, {
            "target": target,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "details": details
        })
