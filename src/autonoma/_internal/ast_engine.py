"""Detect hardcoded secrets using native Python AST."""
import ast
import hashlib
from typing import List, Dict, Any, Optional, Set
import logging

from ..audit import truncate_secret, detect_provider, generate_fingerprint

logger = logging.getLogger(__name__)


class SecretVisitor(ast.NodeVisitor):
    """AST visitor for secret detection."""

    def __init__(self, engine):
        self.engine = engine
        self.issues: List[Dict[str, Any]] = []
        self.handled_nodes: Set[int] = set()

    def visit_ClassDef(self, node: ast.ClassDef):
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        """Handle module/function-level assignments and os.environ assignments."""
        if id(node) in self.handled_nodes:
            return

        # Simple assignment candidate (Module or Function level)
        if self.engine._is_simple_assignment_candidate(node):
            var_name = node.targets[0].id
            self.engine._collect_issue(node, node.value, var_name, var_name, self.issues)
        
        # Also support os.environ["KEY"] = "secret" (detection consistency)
        else:
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    is_environ = False
                    if isinstance(target.value, ast.Attribute):
                        if (isinstance(target.value.value, ast.Name) 
                                and target.value.value.id == 'os' 
                                and target.value.attr == 'environ'):
                            is_environ = True

                    if is_environ:
                        sl = target.slice
                        if isinstance(sl, (ast.Constant, ast.Str)):
                            key_name = sl.s if isinstance(sl, ast.Str) else sl.value
                            if key_name and isinstance(key_name, str):
                                self.engine._collect_issue(node, node.value, key_name, key_name, self.issues, is_environ=True)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Handle keyword arguments."""
        for kw in node.keywords:
            # kw.arg is None means **kwargs unpacking (REFUSE)
            if kw.arg and self.engine._is_secret_string_literal(kw.value, kw.arg):
                self.engine._collect_issue(kw, kw.value, kw.arg, kw.arg, self.issues)
        
        self.generic_visit(node)


class ASTEngine:
    """AST-based security analyzer for hardcoded secrets detection."""

    def __init__(self):
        self.parser = None
        logger.debug("ASTEngine initialized (native Python AST mode)")

    def cleanup(self):
        """Cleanup resources."""
        pass

    def compute_semantic_hash(self, content: str) -> str:
        """Compute hash of content for caching."""
        try:
            return hashlib.sha256(content.encode('utf-8')).hexdigest()
        except Exception:
            return ""

    def analyze(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        """
        Analyze source code for hardcoded secrets.
        Only SEC001 (passwords) and SEC002 (API keys).
        """
        if not file_path.endswith('.py'):
            return []

        try:
            tree = ast.parse(content)
            visitor = SecretVisitor(self)
            visitor.visit(tree)
            issues = visitor.issues
        except SyntaxError:
            return []
        except Exception as e:
            logger.debug(f"AST analysis failed: {e}")
            return []

        # Final deduplication by (line, col) to be safe
        seen = set()
        unique_issues = []
        for i in issues:
            key = (i["line"], i["col_offset"], i["id"])
            if key not in seen:
                seen.add(key)
                unique_issues.append(i)

        return unique_issues

    def _is_simple_assignment_candidate(self, node: ast.Assign) -> bool:
        if len(node.targets) != 1:
            return False
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            return False
        return self._is_secret_string_literal(node.value, target.id)

    def _is_secret_string_literal(self, node: ast.AST, name: str) -> bool:
        if self._is_metadata_variable(name):
            return False

        if not isinstance(node, (ast.Constant, ast.Str, ast.JoinedStr)):
            return False
        
        if isinstance(node, ast.JoinedStr):
            # For JoinedStr, we don't have a single literal value.
            # However, if the variable NAME looks like a secret, we should detect it
            # so the fixer can explicitly refuse it.
            return self._looks_like_secret("", name)

        val = getattr(node, 's', getattr(node, 'value', None))
        if not isinstance(val, str) or len(val) == 0:
            return False
        
        # Skip values that already look like environment lookups
        if 'os.getenv' in val or 'os.environ' in val:
            return False

        return self._looks_like_secret(val, name)

    def _looks_like_secret(self, value: str, name: str) -> bool:
        check_name_lower = name.lower()
        secret_keywords = [
            'password', 'passwd', 'pwd',
            'api_key', 'apikey', 'secret', 'token',
            'auth_token', 'auth', 'credential', 'key',
            'azure_vision_key', 'openai_api_key'
        ]
        return any(k in check_name_lower for k in secret_keywords)
    # Issue collection

    def _collect_issue(self, node, value_node, check_name, original_name, issues, is_environ=False):

        val = getattr(value_node, 's', getattr(value_node, 'value', None))
        
        check_name_lower = check_name.lower()
        is_password = any(k in check_name_lower for k in ['password', 'passwd', 'pwd'])
        pattern_type = "password" if is_password else "api_key"
        issue_id = "SEC001" if is_password else "SEC002"

        msg_target = f'os.environ["{original_name}"]' if is_environ else f"'{original_name}'"

        issues.append({
            "id": issue_id,
            "line": node.lineno,
            "col_offset": value_node.col_offset,
            "end_col_offset": getattr(value_node, 'end_col_offset', None),
            "message": f"Hardcoded {'password' if is_password else 'secret'} {msg_target} detected.",
            "type": "security",
            "severity": "high",
            "source": "ast_engine_native",
            "pattern_type": pattern_type,
            "truncated_secret": truncate_secret(val),
            "provider": detect_provider(val),
            "fingerprint": generate_fingerprint(val),
        })

    # Suffixes that indicate metadata about secrets, not actual secrets.
    _METADATA_SUFFIXES = (
        '_chars', '_characters', '_charset',
        '_min_length', '_max_length', '_length', '_len',
        '_pattern', '_regex', '_regexp', '_format',
        '_policy', '_rules', '_requirements',
        '_expiry', '_ttl', '_timeout', '_age',
        '_hash', '_algorithm', '_algo', '_method',
        '_header', '_field', '_name', '_label', '_prompt',
        '_prefix', '_suffix', '_separator',
        '_encoding', '_salt_length',
        '_file', '_path', '_dir', '_url', '_env',
        '_type', '_mode', '_level', '_version',
    )

    def _is_metadata_variable(self, name: str) -> bool:
        """Return True if the variable is about secret metadata, not a secret."""
        lower = name.lower()
        return any(lower.endswith(s) for s in self._METADATA_SUFFIXES)
