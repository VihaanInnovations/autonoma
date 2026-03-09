from typing import Optional
import json
import logging

logger = logging.getLogger("autonoma")

try:
    from .db.db import log_audit_event
except ImportError:
    log_audit_event = None


class AuditLogger:
    def __init__(self, project_id: str, user_id: str = "local_user"):
        self.project_id = project_id
        self.user_id = user_id

    def log(self, action: str, target: str, details: Optional[dict] = None):
        details_str = json.dumps(details) if details else ""
        # DB Log
        try:
            if log_audit_event:
                log_audit_event(self.project_id, self.user_id, action, target, details_str)
        except Exception:
            pass  # Fail open if DB is down

        # Console log
        logger.info(f"[AUDIT] {action} on {target} (project={self.project_id})")
