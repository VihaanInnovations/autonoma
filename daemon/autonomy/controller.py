import logging
import uuid
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Reuse Firewall types if possible or define shared types
from daemon.autonomy.firewall import FirewallDecision
from daemon.autonomy.retry_distance import RetryDistanceCalculator
from daemon.autonomy.strategy_memory import StrategyMemory

logger = logging.getLogger("autonomy-controller")

class AutonomyController:
    """
    The 'Cortex' of the Autonomous Engineer.
    Decides whether a plan is good enough to execute, based on past failures.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.memory = StrategyMemory()
        self.distance_calculator = RetryDistanceCalculator()
        
        # Hyperparameters (can be tuned via config)
        self.min_retry_distance = 0.3 # Minimum AST distance required (0.0 - 1.0)
        
    def evaluate_plan(self, task_id: str, proposed_code: str, attempt_idx: int) -> FirewallDecision:
        """
        Evaluate if a proposed fix strategy (code) is distinct enough from previous failed attempts.
        """
        # If it's the first attempt, always allow (unless other heuristics fail, handled elsewhere)
        history = self.memory.get_history(task_id)
        if not history:
            self.memory.add_attempt(task_id, proposed_code, "PENDING")
            return FirewallDecision(action="ALLOW", reason="First attempt for this task")
            
        # Check distance against ALL previous failures for this task
        # We want to avoid repeating ANY mistake, not just the last one.
        for past_attempt in history:
            distance = self.distance_calculator.compute_distance(proposed_code, past_attempt['code'])
            logger.info(f"Task {task_id}: Distance to attempt {past_attempt['id']} = {distance:.4f}")
            
            if distance < self.min_retry_distance:
                return FirewallDecision(
                    action="REJECT", 
                    reason=f"Strategy too similar to failed attempt {past_attempt['id']} (Distance: {distance:.2f} < {self.min_retry_distance})"
                )
        
        # If we pass all checks, log this new attempt and allow
        self.memory.add_attempt(task_id, proposed_code, "PENDING")
        return FirewallDecision(action="ALLOW", reason="Strategy is sufficiently distinct")

    def get_negative_constraints(self, filename: str) -> str:
        """
        Return prompts to guide the LLM away from bad patterns for this file type.
        """
        constraints = []
        if filename.endswith(".py"):
            constraints.append("Avoid using 'eval()' or 'exec()' for dynamic code execution.")
            constraints.append("Do not hardcode 'password' or 'api_key' variable names with string literals.")
        
        if filename == "credentials.py":
             constraints.append("STRICT: Do NOT generate actual secrets. Use os.getenv() for EVERYTHING.")
             
        return "\n".join(constraints)

    def record_outcome(self, task_id: str, success: bool):
        """
        Update the last attempt's status.
        """
        status = "SUCCESS" if success else "FAILURE"
        self.memory.update_last_status(task_id, status)
