from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any

class InvariantType(Enum):
    AI_01_MONOTONICITY = "AI-01: Retry Monotonicity"
    AI_02_EXCLUSIVITY = "AI-02: Strategy Exclusivity"
    AI_03_SAFETY_DOMINANCE = "AI-03: Safety Dominance"
    AI_04_BOUNDED_EXPLORATION = "AI-04: Bounded Exploration"

@dataclass
class InvariantResult:
    passed: bool
    invariant: InvariantType
    violation_code: Optional[str] = None # e.g. "LOOP_DETECTED"
    message: Optional[str] = None

class AutonomyInvariants:
    """
    Enforces Hard Laws of Autonomy.
    """
    
    @staticmethod
    def check_ai_01_monotonicity(distance: float, threshold: float) -> InvariantResult:
        """
        AI-01: Each retry must be structurally different from the last failure.
        """
        if distance < threshold:
            return InvariantResult(
                passed=False,
                invariant=InvariantType.AI_01_MONOTONICITY,
                violation_code="LOOP_DETECTED",
                message=f"Plan too similar to failed attempt (Distance: {distance:.2f} < {threshold})"
            )
        return InvariantResult(True, InvariantType.AI_01_MONOTONICITY)

    @staticmethod
    def check_ai_02_exclusivity(is_banned: bool, strategy_name: str) -> InvariantResult:
        """
        AI-02: A failed strategy may not reappear in the same task.
        """
        if is_banned:
             return InvariantResult(
                passed=False,
                invariant=InvariantType.AI_02_EXCLUSIVITY,
                violation_code="STRATEGY_REUSE",
                message=f"Strategy '{strategy_name}' is banned for this task."
            )
        return InvariantResult(True, InvariantType.AI_02_EXCLUSIVITY)

    @staticmethod
    def check_ai_03_safety(prev_failure_type: str, constraints_present: bool) -> InvariantResult:
        """
        AI-03: No retry may weaken safety constraints.
        If previous attempt hit SPG/FC-07, next must include constraints.
        """
        safety_failures = {"SPG-05", "FC-07", "SPG-02", "SPG-03", "SPG-04", "SPG-01"}
        if any(sf in prev_failure_type for sf in safety_failures):
            if not constraints_present:
                 return InvariantResult(
                    passed=False,
                    invariant=InvariantType.AI_03_SAFETY_DOMINANCE,
                    violation_code="SAFETY_WEAKENING",
                    message=f"Previous failure {prev_failure_type} requires explicit constraint reinforcement."
                )
        return InvariantResult(True, InvariantType.AI_03_SAFETY_DOMINANCE)

    @staticmethod
    def check_ai_04_boundedness(retry_count: int, max_retries: int) -> InvariantResult:
        """
        AI-04: Maximum strategy branches per task.
        """
        if retry_count >= max_retries:
             return InvariantResult(
                passed=False,
                invariant=InvariantType.AI_04_BOUNDED_EXPLORATION,
                violation_code="MAX_RETRIES",
                message=f"Maximum retries ({max_retries}) reached."
            )
        return InvariantResult(True, InvariantType.AI_04_BOUNDED_EXPLORATION)
