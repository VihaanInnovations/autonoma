import ast
import logging
from typing import Set, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)

class RetryDistanceOptimizer:
    """
    Computes weighted structural distance between two code versions.
    Components:
    1. AST Structure (50%): Deep structural changes.
    2. Symbol Scope (30%): Which functions/classes were touched.
    3. Strategy Signature (20%): Logic pattern differences.
    """
    
    def calculate_distance(self, code_a: str, code_b: str, sig_a: Any = None, sig_b: Any = None) -> float:
        """
        Calculate weighted distance.
        Args:
            code_a: Previous failed code.
            code_b: New proposed code.
            sig_a: StrategySignature of code_a (optional).
            sig_b: StrategySignature of code_b (optional).
        Returns:
            0.0 (identical) to 1.0 (completely different).
        """
        try:
            tree_a = ast.parse(code_a)
            tree_b = ast.parse(code_b)
        except SyntaxError:
            # If one is syntax invalid, we cannot compare structure robustly.
            # Return 1.0 to allow retry (FixEngine handles syntax errors separately).
            return 1.0

        # 1. AST Diff Score (0.5 weight)
        ast_dist = self._calculate_ast_distance(tree_a, tree_b)
        
        # 2. Symbol Scope Overlap (0.3 weight)
        scope_dist = self._calculate_scope_distance(tree_a, tree_b)
        
        # 3. Behavioral/Strategy Signature (0.2 weight)
        if sig_a and sig_b:
            strat_dist = self._calculate_strategy_distance(sig_a, sig_b)
        else:
            # Fallback if signatures missing: assume no strategy change if AST is close
            strat_dist = 0.0 # Conservative: don't boost distance artificially
            
        weighted_score = (0.5 * ast_dist) + (0.3 * scope_dist) + (0.2 * strat_dist)
        
        logger.debug(f"Distance Components: AST={ast_dist:.2f}, Scope={scope_dist:.2f}, Strat={strat_dist:.2f} -> Total={weighted_score:.2f}")
        
        return weighted_score

    def _calculate_ast_distance(self, tree_a: ast.AST, tree_b: ast.AST) -> float:
        """
        Jaccard distance of structural fingerprints.
        """
        fingerprint_a = self._generate_fingerprint(tree_a)
        fingerprint_b = self._generate_fingerprint(tree_b)
        
        intersection = len(fingerprint_a.intersection(fingerprint_b))
        union = len(fingerprint_a.union(fingerprint_b))
        
        if union == 0:
            return 0.0
            
        similarity = intersection / union
        return 1.0 - similarity

    def _calculate_scope_distance(self, tree_a: ast.AST, tree_b: ast.AST) -> float:
        """
        Distance based on touched symbols (functions/classes modified).
        Use NodeTransformer logic or simple walk to identify definition nodes.
        Actually, we want 'touched' as in 'modified'. 
        Comparing sets of ALL symbols isn't 'touched', it's 'present'.
        
        Better proxy: compare sets of (Name, Type) present in the AST.
        If a function body changes, its internal nodes change (captured by AST diff).
        This component should capture "Did I move to a different function?".
        """
        scopes_a = self._extract_scopes(tree_a)
        scopes_b = self._extract_scopes(tree_b)
        
        # If sets are identical, we are working in exactly the same functions/classes -> Low distance
        # If sets differ (added/removed function, or changed signature), distance increases.
        
        intersection = len(scopes_a.intersection(scopes_b))
        union = len(scopes_a.union(scopes_b))
        
        if union == 0: return 0.0
        
        similarity = intersection / union
        return 1.0 - similarity

    def _calculate_strategy_distance(self, sig_a: Any, sig_b: Any) -> float:
        """
        Compare StrategySignatures.
        """
        # If logic_pattern changed (e.g. from 'conditional_check' to 'exception_handling'), that's a big shift.
        if sig_a.logic_pattern != sig_b.logic_pattern:
            return 1.0
        
        # If AST shape hash is different, it's a minor shift (already captured by AST diff, but this reinforces it)
        if sig_a.ast_shape != sig_b.ast_shape:
            return 0.5
            
        return 0.0

    def _generate_fingerprint(self, tree: ast.AST) -> Set[str]:
        """
        Generate a set of structural tokens.
        Includes Node Type + Depth (to capture structure).
        """
        tokens = set()
        for node in ast.walk(tree):
            # Include Node Type
            node_type = type(node).__name__
            
            # Capture essential attributes for semantic anchoring
            suffix = ""
            if isinstance(node, ast.Name):
                suffix = f":{node.id}"
            elif isinstance(node, ast.FunctionDef):
                suffix = f":{node.name}"
            elif isinstance(node, ast.ClassDef):
                suffix = f":{node.name}"
            elif isinstance(node, ast.Attribute):
                suffix = f":{node.attr}"
            elif isinstance(node, (ast.Constant, ast.Str, ast.Num)):
                # Ignore literal values to allow variable tuning, 
                # UNLESS it's a semantic constant logic change. 
                # For now, simplistic: ignore values to focus on structure.
                pass 
            
            tokens.add(f"{node_type}{suffix}")
            
        return tokens

    def _extract_scopes(self, tree: ast.AST) -> Set[str]:
        """
        Extract names of top-level constructs (Functions, Classes).
        """
        scopes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                 scopes.add(f"{type(node).__name__}:{node.name}")
        return scopes

    def should_reject(self, distance: float, threshold: float = 0.15) -> bool:
        """
        Returns True if the plan is too similar (distance < threshold).
        """
        return distance < threshold
