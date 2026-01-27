import logging
import json
import os
import datetime
import uuid
from typing import Dict, Any, Optional

class StructuredLogger:
    """
    Enterprise-grade Structured Logger.
    Outputs logs in JSON format for easy ingestion by Splunk, Datadog, etc.
    """
    
    def __init__(self, service_name: str = "autonoma-engine"):
        self.service_name = service_name
        self.trace_id = str(uuid.uuid4())
        
        # Ensure log directory exists
        self.log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.log_file = os.path.join(self.log_dir, f"{service_name}.json.log")
        
        # Configure standard logging to output to console as well (for dev)
        self.console_logger = logging.getLogger(service_name)
        self.console_logger.setLevel(logging.INFO)
        if not self.console_logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.console_logger.addHandler(handler)

    def log(self, level: str, event: str, payload: Optional[Dict[str, Any]] = None):
        """
        Log an event in structured JSON format.
        """
        if payload is None:
            payload = {}
            
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "service": self.service_name,
            "trace_id": self.trace_id,
            "level": level.upper(),
            "event": event,
            "payload": payload
        }
        
        # Write to JSON log file
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
            
        # Also log to console for immediate visibility
        msg = f"[{event}] {json.dumps(payload)}"
        if level.lower() == "error":
            self.console_logger.error(msg)
        elif level.lower() == "warning":
            self.console_logger.warning(msg)
        else:
            self.console_logger.info(msg)

    def info(self, event: str, payload: Dict[str, Any] = None):
        self.log("INFO", event, payload)

    def error(self, event: str, payload: Dict[str, Any] = None):
        self.log("ERROR", event, payload)
        
    def warning(self, event: str, payload: Dict[str, Any] = None):
        self.log("WARNING", event, payload)
