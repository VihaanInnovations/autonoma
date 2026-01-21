import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any
import ast

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class StrategySignature:
    """
    Fingerprint of a strategy/attempt.
    Includes logic pattern (rough intent) and AST shape (structure).
    Excludes failure reason (outcome) to ensure matching during proposal.
    """
    logic_pattern: str          # e.g. "early_return", "loop_refactor"
    ast_shape: str              # simplified AST fingerprint
    task_id: str

@dataclass
class StrategyOutcome:
    signature: StrategySignature
    success: bool
    attempt_index: int
    fc_code: str # "FC-06" etc

class StrategyMemory:
    """
    Records why a logic path failed and prevents repeating it.
    """
    def __init__(self):
        self.history: List[StrategyOutcome] = []
        self.bans: Set[StrategySignature] = set()
        
    def record_attempt(self, 
                      task_id: str, 
                      code_content: str, 
                      failure_reason: str, 
                      fc_code: str,
                      attempt_index: int):
        """
        Record a failed attempt.
        Analyze code to extract signature.
        """
        # Phase 5: Allow SPG-05 recording for Safety Penalty
        if fc_code != "FC-06" and "SPG-05" not in failure_reason:
            return # We only track functional ineffective or Safety failures

        # 1. Extract Signature
        sig = self.extract_signature(task_id, code_content, failure_reason)
        
        # 2. Record
        outcome = StrategyOutcome(
            signature=sig,
            success=False,
            attempt_index=attempt_index,
            fc_code=fc_code
        )
        self.history.append(outcome)
        
        # 3. Check for Ban 
        if "SPG-05" in failure_reason:
            # Immediate Ban for Safety Violation (1 Strike)
            self.bans.add(sig)
            logger.info(f"[AUTONOMY] Banned Strategy (Safety): {sig.logic_pattern} for {task_id}")
        else:
            # FC-06: 2 Strikes Rule
            prev_failures = [h for h in self.history 
                             if h.signature == sig 
                             and h.fc_code == "FC-06"
                             and h.signature.task_id == task_id]
                             
            if len(prev_failures) >= 2:
                self.bans.add(sig)
                logger.info(f"[AUTONOMY] Banned Strategy (Ineffective): {sig.logic_pattern} (Shape: {sig.ast_shape[:8]}...) for {task_id}")

    def get_bans(self, task_id: str) -> List[str]:
        """
        Get list of logic patterns blocked for this task.
        Used to inject negative constraints into Prompt.
        """
        return [b.logic_pattern for b in self.bans if b.task_id == task_id]

    def extract_signature(self, task_id: str, code: str, failure_reason: str) -> StrategySignature:
        """
        Create a fingerprint of the strategy.
        """
        # Logic Pattern: Heuristic based on code structure
        # Simple heuristics for now
        logic_pattern = "unknown_strategy"
        if "return" in code and "if" in code:
            logic_pattern = "conditional_return"
        if "try" in code and "except" in code:
            logic_pattern = "error_handling"
        if "for" in code or "while" in code:
            logic_pattern = "loop_modification"
            
        # Refined logic pattern extraction
        if "SPG-05" in failure_reason or "absolute path" in failure_reason.lower():
            logic_pattern = "absolute_path_violation"
        
        # AST Shape: Structural fingerprint
        ast_shape = "parse_error"
        try:
             tree = ast.parse(code)
             # Create a simplified tuple representation of the AST structure (Node types only)
             shape_tokens = []
             for node in ast.walk(tree):
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.If, ast.For, ast.While, ast.Try, ast.Return, ast.Raise)):
                     shape_tokens.append(type(node).__name__)
             ast_shape = "-".join(shape_tokens)
        except SyntaxError:
            pass

        return StrategySignature(
            logic_pattern=logic_pattern,
            ast_shape=ast_shape,
            task_id=task_id
        )
