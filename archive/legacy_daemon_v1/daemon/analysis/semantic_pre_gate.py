import ast
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SemanticVerdict:
    valid: bool
    violation_class: Optional[str] = None # e.g. "SPG-01"
    reason: Optional[str] = None
    details: Optional[str] = None

class SemanticPreGate:
    """
    Deterministic Static Analysis Gate.
    Rejects syntactically valid but semantically invalid patches.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config

    def check_safety(self, code: str, context_files: List[Dict]) -> SemanticVerdict:
        """
        Run all semantic checks on the code.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return SemanticVerdict(False, "SYNTAX", "Syntax Error during semantic parse")
            # Should have been caught by Syntactic Gate, but defensive coding.

        # SPG-01: Type Contract Violation
        verdict = self._check_type_contracts(tree, context_files)
        if not verdict.valid: return verdict

        # SPG-02: Illegal State Mutation
        verdict = self._check_state_mutation(tree)
        if not verdict.valid: return verdict

        # SPG-03: API Misuse
        verdict = self._check_api_misuse(tree)
        if not verdict.valid: return verdict
        
        # SPG-04: Unreachable or Dead Logic
        verdict = self._check_dead_logic(tree)
        if not verdict.valid: return verdict

        # SPG-05: Resource & Environment Violation
        verdict = self._check_resource_violations(tree)
        if not verdict.valid: return verdict

        return SemanticVerdict(True)

    def _check_type_contracts(self, tree: ast.AST, context_files: List[Dict]) -> SemanticVerdict:
        """SPG-01: infer return types and checking against docstrings/hints."""
        # Simple heuristic: Check for obvious mismatch like returning dict for List[T]
        # This is a refined version of "Minimal Contract Awareness"
        
        # 1. Identify return nodes
        returns_literals = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and node.value:
                if isinstance(node.value, ast.List):
                    returns_literals.append("list")
                elif isinstance(node.value, ast.Dict):
                    returns_literals.append("dict")
                elif isinstance(node.value, ast.Constant):
                     if isinstance(node.value.value, str): returns_literals.append("str")
                     elif isinstance(node.value.value, int): returns_literals.append("int")
        
        if not returns_literals:
            # If no literals returned, we can't easily static check.
            return SemanticVerdict(True)

        # 2. Identify Expected Type from Test Context (if avail)
        # We search specifically for the test file content in context
        expected_type = None
        test_content = ""
        for f in context_files:
             if f.get("type") == "test":
                 test_content = f.get("content", "")
                 break
        
        if test_content:
             try:
                test_tree = ast.parse(test_content)
                for node in ast.walk(test_tree):
                    if isinstance(node, ast.Assert):
                        # match: isinstance(..., Type) or assert type(x) == Type
                         if isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name) and node.test.func.id == 'isinstance':
                             if len(node.test.args) == 2:
                                 type_arg = node.test.args[1]
                                 if isinstance(type_arg, ast.Name):
                                     expected_type = type_arg.id.lower()
             except: pass

        if expected_type:
            unique_returns = set(returns_literals)
            if len(unique_returns) == 1:
                code_type = list(unique_returns)[0]
                
                # Violation table
                if expected_type == 'list' and code_type == 'dict':
                    return SemanticVerdict(False, "SPG-01", "Type Contract Violation", "Test expects list, code returns dict")
                if expected_type == 'dict' and code_type == 'list':
                    return SemanticVerdict(False, "SPG-01", "Type Contract Violation", "Test expects dict, code returns list")
                if expected_type == 'int' and code_type == 'str':
                    return SemanticVerdict(False, "SPG-01", "Type Contract Violation", "Test expects int, code returns str")

        return SemanticVerdict(True)

    def _check_state_mutation(self, tree: ast.AST) -> SemanticVerdict:
        """SPG-02: Check for global keyword or mutating UPPER_CASE globals."""
        for node in ast.walk(tree):
            # 1. 'global' keyword
            if isinstance(node, ast.Global):
                return SemanticVerdict(False, "SPG-02", "Illegal State Mutation", f"Use of 'global' keyword: {node.names}")
            
            # 2. Assignment to UPPER_CASE variables (rudimentary constant check)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id.isupper() and len(target.id) > 1:
                             # Heuristic: Don't allow modifying constants
                             # Context: In fix generation, modifying constants is often a workaround vs fixing logic
                             # Exception: If it's a definition (module level), it's fine.
                             # But hard to distinguish scope purely via simple walk without symbol table.
                             # Relaxed: Only reject if we are inside a FunctionDef
                             pass 

        # Refined check: Modifying globals inside functions
        for node in ast.walk(tree):
             if isinstance(node, ast.FunctionDef):
                 for child in ast.walk(node):
                     if isinstance(child, ast.Assign):
                         for target in child.targets:
                             if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 2:
                                 # Modifying a Constant-looking variable inside a function? Suspicious.
                                 # But without 'global', it's just a local variable shadowing. 
                                 # So purely 'global' check is the strongest invariant for now.
                                 pass
        
        return SemanticVerdict(True)

    def _check_api_misuse(self, tree: ast.AST) -> SemanticVerdict:
        """SPG-03: API Misuse (e.g. requests.get args)."""
        # Critical APIs that are often hallucinated or misused
        known_signatures = {
            'requests.get': {'max_args': 2, 'kwargs': ['params', 'headers', 'timeout', 'auth', 'verify']},
            'requests.post': {'max_args': 2, 'kwargs': ['data', 'json', 'headers', 'timeout', 'auth', 'verify']},
            'json.loads': {'max_args': 1, 'kwargs': ['cls', 'object_hook', 'parse_float', 'parse_int', 'parse_constant', 'object_pairs_hook']},
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Attribute):
                     if isinstance(node.func.value, ast.Name):
                         func_name = f"{node.func.value.id}.{node.func.attr}"
                
                if func_name and func_name in known_signatures:
                    sig = known_signatures[func_name]
                    # Check Positional Args
                    if len(node.args) > sig['max_args']:
                         return SemanticVerdict(False, "SPG-03", "API Misuse", f"{func_name} called with {len(node.args)} args (max {sig['max_args']})")
                    
                    # Check Unknown Kwargs (Weak check, just common hallucinations)
                    # We won't be too strict here to avoid false positives on legitimate obscure args
                    pass

        return SemanticVerdict(True)

    def _check_dead_logic(self, tree: ast.AST) -> SemanticVerdict:
        """SPG-04: Unreachable code detection."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.If, ast.For, ast.While)):
                body = node.body
                for i, stmt in enumerate(body):
                    # Check if stmt is a terminal return/raise/break/continue
                    if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                        # If there are statements AFTER this one in the same block, they are dead
                        if i < len(body) - 1:
                            return SemanticVerdict(False, "SPG-04", "Unreachable Logic", f"Dead code detected after {type(stmt).__name__} at line {stmt.lineno}")
            
            # Check for 'if False' or 'if 0'
            if isinstance(node, ast.If):
                if isinstance(node.test, ast.Constant):
                    if node.test.value is False or node.test.value == 0:
                         return SemanticVerdict(False, "SPG-04", "Unreachable Logic", f"if False/0 detected block at line {node.lineno}")

        return SemanticVerdict(True)

    def _check_resource_violations(self, tree: ast.AST) -> SemanticVerdict:
        """SPG-05: Resource & Environment violations using Contextual Visitor."""
        visitor = SPGResourceVisitor(self.config)
        try:
            visitor.visit(tree)
        except SPGViolation as e:
            return SemanticVerdict(False, "SPG-05", "Resource Violation", str(e))
        
        return SemanticVerdict(True)

class SPGViolation(Exception):
    pass

class SPGResourceVisitor(ast.NodeVisitor):
    def __init__(self, config: Optional[Dict] = None):
        # Default strict policy
        self.disallowed_imports = {'os', 'sys', 'subprocess', 'shutil', 'pathlib'} 
        self.disallowed_funcs = {'exec', 'eval'}
        
        # Override with config if provided
        if config and 'constraints' in config:
            constraints = config['constraints']
            if 'banned_imports' in constraints:
                self.disallowed_imports = set(constraints['banned_imports'])
                
        self.in_router_context = False
        
        # Prefixes that indicate we are in a routing context
        # Check against function names or keyword arguments
        self.router_funcs = {
            'APIRouter', 'include_router', 
            'get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace', 'route'
        }

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            if alias.name.split('.')[0] in self.disallowed_imports:
                 raise SPGViolation(f"Importing '{alias.name}' is restricted.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module and node.module.split('.')[0] in self.disallowed_imports:
             raise SPGViolation(f"Importing from '{node.module}' is restricted.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Check if call is forbidden
        func_name = self._get_func_name(node.func)
        if func_name in self.disallowed_funcs:
             raise SPGViolation(f"Function '{func_name}' is forbidden.")

        # Check for Router Context
        # Heuristic: If calling a method named like a HTTP verb or Router component
        # We assume the arguments (especially string literals) are safe(r).
        
        # We need to detect: @app.get(...), APIRouter(prefix=...), include_router(..., prefix=...)
        is_router_call = False
        if func_name:
            # Simple name check: 'APIRouter', 'include_router'
            if func_name in self.router_funcs:
                is_router_call = True
            # Attribute check: 'app.get', 'router.post'
            elif '.' in func_name:
                attr = func_name.split('.')[-1]
                if attr in self.router_funcs:
                    is_router_call = True
        
        if is_router_call:
            prev_context = self.in_router_context
            self.in_router_context = True
            try:
                self.generic_visit(node)
            finally:
                self.in_router_context = prev_context
        else:
            self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            val = node.value
            if self._is_potential_abs_path(val):
                if self.in_router_context:
                    # Allow, but check for Safety (Stage 2)
                    if self._is_unsafe_system_path(val):
                        raise SPGViolation(f"System path detected even in router: '{val}'. Violation.")
                    # Otherwise Contextual Pass
                else:
                    # Not in context -> Hard Block
                    raise SPGViolation(f"Absolute path detected: '{val}'. Use relative paths or router context.")

    def _get_func_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_func_name(node.value)}.{node.attr}"
        return ""

    def _is_potential_abs_path(self, val: str) -> bool:
        # Heuristic for Linux/Windows absolute paths
        import os
        # Ignore short strings or obviously not paths
        if len(val) < 2: return False
        
        # Check if it looks like a path
        if not (val.startswith("/") or (len(val) > 2 and val[1] == ":" and val[2] == "\\")):
             return False
        
        # Is it absolute?
        if val.startswith("/") or (len(val) > 2 and val[1] == ":"):
             # Extra filter: Must contain typical path characters
             # Avoid blocking generic text starting with /
             # But strictly, SPG says NO absolute paths.
             return True
        return False

    def _is_unsafe_system_path(self, val: str) -> bool:
        # Block known system roots even in routers
        # e.g. /etc, /bin, /usr, /var, /Windows, /Program Files
        normalized = val.replace("\\", "/").lower()
        unsafe_prefixes = {
            "/etc", "/bin", "/sbin", "/usr", "/var", "/tmp", "/root", 
            "/home", "/proc", "/sys", "/dev", "/opt", "/boot",
            "/windows", "/program files", "/users" # Mac/Win users dir? actually /users is also a common API route!
            # Conflict: /users vs /Users (Mac). 
            # Smart check: API routes usually lower case or camelCase, but rarely /Users/username...
            # Actually, blocking `/users` is exactly the problem we are solving (API route).
            # So we typically shouldn't block /users in Router Context.
            # We strictly block ONLY OS paths.
        }
        # Refined Unsafe
        unsafe_roots = {"/etc/", "/bin/", "/var/", "/usr/", "/tmp/", "/proc/", "/sys/"}
        for root in unsafe_roots:
            if normalized.startswith(root) or normalized == root[:-1]:
                return True
        return False
