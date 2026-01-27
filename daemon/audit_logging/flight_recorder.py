import json
import time
import os
import hashlib
from typing import Dict, Any, Optional
from pathlib import Path
import asyncio

# Try to import EventBus, handle circular/missing imports gracefully
try:
    from daemon.events.event_bus import get_event_bus
except ImportError:
    get_event_bus = None

class FlightRecorder:
    def __init__(self, session_id: str, log_dir: str = "logs/flights"):
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"flight_{session_id}.jsonl"
        self.event_bus = get_event_bus() if get_event_bus else None
        
    def log_event(self, event_type: str, payload: Dict[str, Any]):
        """
        Log an immutable event to the flight record and stream it.
        """
        detailed_payload = payload.copy()
        
        entry = {
            "timestamp": time.time(),
            "session_id": self.session_id,
            "event_type": event_type,
            "payload": detailed_payload,
            "prev_hash": self._get_last_hash() # Chain of custody
        }
        
        # Calculate hash of this entry for integrity
        entry_str = json.dumps(entry, sort_keys=True)
        entry["hash"] = hashlib.sha256(entry_str.encode()).hexdigest()
        
        # Write to disk
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Publish to EventBus for Live Dashboard
        if self.event_bus:
            try:
                # We need a running loop to publish. 
                # If we are in a sync context (unlikely for this app), this might fail.
                # using create_task to fire and forget
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.event_bus.publish(event_type, detailed_payload))
            except Exception:
                # Don't break logging if event bus fails
                pass
            
    def _get_last_hash(self) -> str:
        """Get the hash of the last line for blockchain-style linking."""
        if not self.log_file.exists():
            return "0" * 64
            
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if not lines: return "0" * 64
                last_entry = json.loads(lines[-1])
                return last_entry.get("hash", "0" * 64)
        except:
            return "0" * 64

    def record_input(self, file_path: str, content: str):
        self.log_event("INPUT_SNAPSHOT", {
            "file_path": file_path,
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "content_preview": content[:200]
        })

    def record_reasoning(self, prompt: str, response: str, model: str):
        self.log_event("LLM_REASONING", {
            "model": model,
            "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
            "response": response # Full reasoning for audit
        })

    def record_decision(self, decision_type: str, details: Dict[str, Any]):
        self.log_event("DECISION_MADE", {
            "type": decision_type,
            "details": details
        })
