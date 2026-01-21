import json
import enum
import hashlib
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Optional, Any, Set
import logging

logger = logging.getLogger(__name__)

class FailureClass(str, enum.Enum):
    INFRASTRUCTURE_FAULT = "FC-01"
    SYNTAX_INVALID = "FC-02"
    STATIC_VIOLATION = "FC-03"
    CONTEXT_MISMATCH = "FC-04"
    FUNCTIONAL_REGRESSION = "FC-05"
    FUNCTIONAL_INEFFECTIVE = "FC-06"
    UNSOUND_SUCCESS = "FC-07"

@dataclass
class FailureSignature:
    failure_class_id: FailureClass
    failure_subclass_id: str
    language: str
    timestamp: str
    retry_count: int
    diff_shape: Dict[str, Any]
    invariant_failed: Dict[str, Any]
    preventable: bool = True
    mutation_applied: Optional[str] = None
    repo_fingerprint: str = "unknown"
    signature_id: str = ""

    def compute_hash(self) -> str:
        """Compute stable hash of the error signature (excluding timestamp/retry)."""
        # We hash the class, subclass, language, and diff shape to identify 'same error'
        payload = {
            "class": self.failure_class_id,
            "subclass": self.failure_subclass_id,
            "diff_shape": self.diff_shape,
            "invariant": self.invariant_failed
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def __post_init__(self):
        if not self.signature_id:
            self.signature_id = self.compute_hash()

class SafetyMonitor:
    """
    Enforces the Autonomous Failure Taxonomy constraints.
    Manages retry budgets, autonomy decay, and failure persistence.
    """
    
    # Retry Budgets (Per Failure Class)
    MAX_RETRIES = {
        FailureClass.INFRASTRUCTURE_FAULT: 3,
        FailureClass.SYNTAX_INVALID: 5,
        FailureClass.STATIC_VIOLATION: 3,
        FailureClass.CONTEXT_MISMATCH: 2,
        FailureClass.FUNCTIONAL_REGRESSION: 2,
        FailureClass.FUNCTIONAL_INEFFECTIVE: 5,
        FailureClass.UNSOUND_SUCCESS: 1 # Strict limit for semantic unsafe operations
    }

    def __init__(self, memory_path: Path):
        self.memory_path = memory_path / "failures"
        self.memory_path.mkdir(parents=True, exist_ok=True)
        self.active_failures: List[FailureSignature] = []
        self.global_consecutive_failures = 0
        
    def record_failure(self, signature: FailureSignature) -> None:
        """
        Persist a failure signature and update internal state.
        """
        self.active_failures.append(signature)
        self.global_consecutive_failures += 1
        
        # Persist to disk
        file_path = self.memory_path / f"{signature.signature_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(asdict(signature), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist failure signature: {e}")

    def check_autonomy_decay(self) -> Dict[str, Any]:
        """
        Check if autonomy should decay or stop based on recent failures.
        Returns explicit decision dictionary.
        """
        decision = {
            "should_abort": False,
            "mode": "NORMAL",
            "reason": ""
        }

        # Rule 1: Regression Overload
        # If we have > 2 regressions in current session, abort
        regressions = [f for f in self.active_failures if f.failure_class_id == FailureClass.FUNCTIONAL_REGRESSION]
        if len(regressions) > 2:
            decision["should_abort"] = True
            decision["mode"] = "SAFE_MODE"
            decision["reason"] = "Autonomy Decay Triggered: Excessive Functional Regressions (FC-05 > 2)"
            return decision

        # Rule 2: Syntax Spin (Model Degradation)
        # If last 3 errors are Syntax Errors
        if len(self.active_failures) >= 3:
            last_3 = self.active_failures[-3:]
            if all(f.failure_class_id == FailureClass.SYNTAX_INVALID for f in last_3):
                 decision["should_abort"] = True
                 decision["mode"] = "STOP"
                 decision["reason"] = "Autonomy Decay Triggered: Consecutive Syntax Errors (Model Degradation Signal)"
                 return decision
                 
        # Rule 3: Unsound Success attempt (Deception Risk)
        # If we detect ANY FC-07, we want to warn heavily or stop if repeated.
        # For now, immediate abort on 2nd occurrence. 
        # (Taxonomy says Immediate decay, but let's allow 1 retry if budget allows, else stop)
        unsound_failures = [f for f in self.active_failures if f.failure_class_id == FailureClass.UNSOUND_SUCCESS]
        if len(unsound_failures) >= 2:
             decision["should_abort"] = True
             decision["mode"] = "STOP"
             decision["reason"] = "Autonomy Decay Triggered: Repeated Unsound Success Attempts (Deception Risk FC-07)"
             return decision

        return decision

    def get_strategy_mutation(self, failure_class: FailureClass, subclass_id: str) -> str:
        """
        Map failure to required strategy mutation (Mechanism, not Policy).
        """
        mutations = {
             FailureClass.INFRASTRUCTURE_FAULT: "backoff_wait",
             FailureClass.SYNTAX_INVALID: "reduce_diff_size",
             FailureClass.STATIC_VIOLATION: "compliance_mode",
             FailureClass.CONTEXT_MISMATCH: "rebuild_index",
             FailureClass.FUNCTIONAL_REGRESSION: "revert_and_isolate",
             FailureClass.FUNCTIONAL_INEFFECTIVE: "switch_logic_path",
             FailureClass.UNSOUND_SUCCESS: "ban_test_edits" # Default for FC-07
        }
        
        # Specific subclass overrides for FC-07
        if failure_class == FailureClass.UNSOUND_SUCCESS:
            if subclass_id == "FC-07-A": return "ban_test_edits"
            if subclass_id == "FC-07-B": return "enforce_control_flow"
            if subclass_id == "FC-07-C": return "generalization_prompt"
            
        return mutations.get(failure_class, "retry_standard")

    def get_remaining_retries(self, failure_class: FailureClass, current_retry_count: int) -> int:
        """Get remaining retries for a specific class."""
        max_allowed = self.MAX_RETRIES.get(failure_class, 3)
        return max(0, max_allowed - current_retry_count)
