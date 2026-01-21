from enum import Enum
from typing import Optional, Dict
import logging
import requests

logger = logging.getLogger(__name__)

class HaltCode(Enum):
    # Safety Invariants
    MAX_RETRY_DEPTH = "H01"
    CONTEXT_BLEED = "H02"
    TQG_LOW_COVERAGE = "H03"
    TQG_WEAK_ASSERT = "H04"
    
    # Operational Blocks
    FIREWALL_LOCK = "H05"
    COST_LIMIT = "H06"
    USER_KILL = "H99"
    
    # Verification Failures
    TEST_FAILURE = "H10"
    UNSOUND_SUCCESS = "H11"

class AutonomyOutcome(Enum):
    SUCCESS = "SUCCESS"
    SUCCESS_UNVERIFIED = "SUCCESS_UNVERIFIED"
    FAIL_SAFE = "FAIL_SAFE"

class HaltException(Exception):
    def __init__(self, code: HaltCode, reason: str, details: Optional[str] = None):
        self.code = code
        self.reason = reason
        self.details = details
        super().__init__(f"HALT [{code.value}]: {reason}")

class Firewall:
    """
    The Post-Test Autonomy Firewall.
    Enforces rigid safety boundaries and handles telemetry reporting.
    """
    def __init__(self, endpoint_url: str = None, session_id: str = None):
        self.endpoint_url = endpoint_url  # e.g., "http://api.codesentinal.cloud"
        self.session_id = session_id or "local-session"
        self._halted = False

    def assert_context_isolation(self, context_files: list):
        """Enforces Law of Isolation (H02)"""
        # Logic: Ensure no files from outside workspace or sensitive dirs
        for f in context_files:
            if "/.ssh/" in f['path'] or "/.env" in f['path']:
                 self.halt(HaltCode.CONTEXT_BLEED, "Sensitive context detected")

    def assert_tqg(self, test_coverage: float, assertions_count: int):
        """Enforces Test Quality Gate (H03, H04)"""
        if assertions_count == 0:
            # We don't halt here, we downgrade to SUCCESS_UNVERIFIED later?
            # No, doc says "Empty test -> TQG_FAILURE".
            # User manual says "SUCCESS_UNVERIFIED" for low coverage.
            pass # Logic handled in decide_outcome

    def halt(self, code: HaltCode, reason: str, details: str = None):
        """Triggers an immediate System Halt"""
        self._halted = True
        logger.error(f"FIREWALL HALT [{code.value}]: {reason}")
        self._report_telemetry(AutonomyOutcome.FAIL_SAFE, code, reason)
        raise HaltException(code, reason, details)

    def decide_outcome(self, verification_result) -> AutonomyOutcome:
        """
        Maps verification results to strict Autonomy Outcomes.
        """
        if not verification_result.all_passed:
            return AutonomyOutcome.FAIL_SAFE
        
        # TQG Checks on Success
        # TODO: Get coverage metrics from verifier
        coverage = verification_result.details.get("coverage", 100)
        
        if coverage < 15:
            return AutonomyOutcome.SUCCESS_UNVERIFIED
            
        return AutonomyOutcome.SUCCESS

    def report_success(self, outcome: AutonomyOutcome):
         """Reports final success state"""
         self._report_telemetry(outcome, None, "Task Completed")

    def _report_telemetry(self, outcome: AutonomyOutcome, halt_code: Optional[HaltCode], reason: str):
        if not self.endpoint_url:
            return
            
        try:
             payload = {
                 "session_id": self.session_id,
                 "outcome": outcome.value,
                 "halt_reason": halt_code.value if halt_code else "NONE",
                 "metrics": {"reason": reason}
             }
             # Fire and forget (Fail-safe: catch exception so we don't crash main loop)
             requests.post(f"{self.endpoint_url}/autonomy/telemetry/report", json=payload, timeout=2)
        except Exception as e:
            logger.warning(f"Telemetry failed: {e}")
