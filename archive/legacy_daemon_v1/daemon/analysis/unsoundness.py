import ast
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any

logger = logging.getLogger(__name__)

@dataclass
class UnsoundnessVerdict:
    is_unsound: bool
    failure_class_id: str = ""  # e.g., FC-07-A
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

class UnsoundnessDetector:
    """
    Detects FC-07 UNSOUND_SUCCESS: semantically unsafe changes that pass tests.
    """

    def check_safety(
        self,
        original_code: str,
        fixed_code: str,
        file_path: Path,
        test_file_path: Optional[Path] = None,
        test_file_content: Optional[str] = None
    ) -> UnsoundnessVerdict:
        """
        Analyze the fix for semantic safety violations.
        """
        try:
            # Parse ASTs
            try:
                tree_orig = ast.parse(original_code)
                tree_fix = ast.parse(fixed_code)
            except SyntaxError:
                # Syntax errors are FC-02, not FC-07. 
                # If we get here, it means tests somehow passed despite syntax error? 
                # Or interpreter logic varies. Assume safe here, handled by others.
                return UnsoundnessVerdict(is_unsound=False)

            # 1. FC-07-A: Test Evasion
            # Check if we are modifying a test file and removing assertions
            if self._is_test_file(file_path):
                orig_asserts = self._count_assertions(tree_orig)
                fix_asserts = self._count_assertions(tree_fix)
                if fix_asserts < orig_asserts:
                    delta = orig_asserts - fix_asserts
                    return UnsoundnessVerdict(
                        is_unsound=True,
                        failure_class_id="FC-07-A",
                        reason=f"Test Evasion: Assertion count decreased by {delta}",
                        details={"delta_asserts": -delta}
                    )

            # 2. FC-07-B: Logic Bypass / Early Exit
            # Check for new early returns (hardcoded)
            if self._detect_hardcoded_early_return(tree_orig, tree_fix):
                 return UnsoundnessVerdict(
                    is_unsound=True,
                    failure_class_id="FC-07-B",
                    reason="Logic Bypass: Hardcoded early return detected",
                    details={}
                 )

            # 3. FC-07-C: Overfitting (Literal Leakage)
            # If we have test content, check if new literals in fix match test literals
            if test_file_content:
                leakage = self._detect_literal_leakage(tree_fix, tree_orig, test_file_content)
                if leakage:
                     return UnsoundnessVerdict(
                        is_unsound=True,
                        failure_class_id="FC-07-C",
                        reason=f"Overfitting: Test literals found in code ({', '.join(leakage[:3])})",
                        details={"leaked_literals": leakage}
                     )

            return UnsoundnessVerdict(is_unsound=False)

        except Exception as e:
            logger.error(f"Unsoundness check failed: {e}")
            # Fail safe: If we can't verify safety, valid tests are usually okay, 
            # but strict mode might want to flag warning.
            return UnsoundnessVerdict(is_unsound=False)

    def _is_test_file(self, path: Path) -> bool:
        return "test" in path.name.lower() or "tests" in str(path).lower()

    def _count_assertions(self, tree: ast.AST) -> int:
        return sum(1 for node in ast.walk(tree) if isinstance(node, ast.Assert))

    def _detect_hardcoded_early_return(self, tree_orig: ast.AST, tree_fix: ast.AST) -> bool:
        """
        Detects if start of functions changed to just 'return <literal>'.
        """
        def get_func_signatures(tree):
            sigs = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Get first statement
                    first_stmt = None
                    if node.body:
                        stmt = node.body[0]
                        if isinstance(stmt, ast.Return):
                            # Check if returning a literal constant
                            if isinstance(stmt.value, (ast.Constant, ast.NameConstant, ast.Num, ast.Str, ast.Bytes)):
                                first_stmt = "return_literal"
                            # Check if returning a bool constant (NameConstant in older python, Constant in newer)
                            elif isinstance(stmt.value, ast.Name) and stmt.value.id in ['True', 'False', 'None']:
                                first_stmt = "return_literal"
                    sigs[node.name] = first_stmt
            return sigs

        orig_sigs = get_func_signatures(tree_orig)
        fix_sigs = get_func_signatures(tree_fix)

        for name, sig in fix_sigs.items():
            if sig == "return_literal":
                # If it wasn't a literal return before, it's suspicious
                if name in orig_sigs and orig_sigs[name] != "return_literal":
                    return True
                # If it's a new function that just returns a literal, might be okay (helper), 
                # but often a mock. Flag context-dependent? 
                # Strict mode: Flag it.
                if name not in orig_sigs:
                     # New function returning literal? Maybe less suspicious if it's a getter.
                     # But for a "Fix", replacing logic with return literal is the main signal.
                     pass 
        return False

    def _detect_literal_leakage(self, tree_fix: ast.AST, tree_orig: ast.AST, test_content: str) -> List[str]:
        """
        Check if new literals in code appear in test content.
        """
        try:
            test_literals = set()
            # extract literals from test source
            # simple regex/ast parse
            try:
                test_tree = ast.parse(test_content)
                for node in ast.walk(test_tree):
                    if isinstance(node, ast.Constant):
                         test_literals.add(str(node.value))
                    elif isinstance(node, ast.Str): # Python < 3.8
                         test_literals.add(node.s)
                    elif isinstance(node, ast.Num): # Python < 3.8
                         test_literals.add(str(node.n))
            except:
                pass
            
            # Remove common literals
            test_literals -= {'True', 'False', 'None', '0', '1', '', 'utf-8', 'r', 'w'}
            
            if not test_literals:
                return []

            def get_literals(tree):
                lits = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant):
                        lits.add(str(node.value))
                    elif isinstance(node, ast.Str):
                        lits.add(node.s)
                    elif isinstance(node, ast.Num):
                        lits.add(str(node.n))
                return lits

            orig_lits = get_literals(tree_orig)
            fix_lits = get_literals(tree_fix)
            
            # New literals introduced in fix
            new_lits = fix_lits - orig_lits
            
            # Check overlap with test literals
            leakage = list(new_lits.intersection(test_literals))
            return leakage
            
        except Exception:
            return []
