"""Detect hardcoded secrets using native Python AST."""
import ast
import hashlib
import re
from typing import List, Dict, Any, Optional, Set
import logging

from ..audit import truncate_secret, detect_provider, generate_fingerprint

logger = logging.getLogger(__name__)


# FIX 5: Known placeholder/fake secret substrings — skip these to reduce false positives
_PLACEHOLDER_SUBSTRINGS = frozenset([
    "test-key", "test_key", "dummy", "placeholder", "example", "sample",
    "your-api-key-here", "your-secret-here", "changeme", "replace-me",
    "secret123", "password123", "postgres", "mysql", "redis",
    "none", "null", "undefined", "empty", "dev", "development",
    "fake", "mock", "stub", "todo", "fixme", "xxx",
    # OAuth2 / permission scope strings — never real secrets
    "write", "read", "tokens",
])

# Keyword argument names that carry URL paths or permission scopes, never secret values.
# e.g. OAuth2PasswordBearer(tokenUrl="token"), redirect_uri="...", scope="read"
_NON_SECRET_KWARG_NAMES = frozenset({
    "tokenurl", "url", "scope", "permission", "redirect_uri",
})


def _is_placeholder_value(value: str) -> bool:
    """Return True if value looks like a known placeholder, not a real secret."""
    if not value:
        return False
    lower = value.lower().strip()
    return any(p in lower for p in _PLACEHOLDER_SUBSTRINGS)


# Plain word values that are never real secrets regardless of variable name.
_PLAIN_WORD_VALUES: frozenset = frozenset({
    # HTTP methods
    "post", "get", "put", "patch", "delete", "head", "options",
    # Common non-secret literals
    "token", "key", "apikey", "api_key", "secret", "password", "passwd",
    "set-password", "set_password", "bearer",
})


def _looks_like_identifier_or_word(value: str) -> bool:
    """Return True if value is a plain word/identifier unlikely to be a real secret."""
    v = value.strip()
    if not v:
        return True
    lower = v.lower()
    # Known non-secret literals (HTTP methods, common keyword-style values)
    if lower in _PLAIN_WORD_VALUES:
        return True
    # Two-word lowercase phrase: Python operators ("is not"), SQL ("not in"), etc.
    if re.match(r'^[a-z]+ [a-z]+$', lower):
        return True
    # Underscore-prefixed Python identifier (e.g. _password_reset_token).
    # Values like these are key references, not credential values.
    if v.startswith('_') and re.match(r'^[_a-zA-Z][a-zA-Z_]*$', v):
        return True
    return False


def _mirrors_variable_name(name: str, value: str) -> bool:
    """Return True if value closely mirrors the variable name after normalization.

    Catches patterns like apiKey="apiKey" and tokenUrl="token".
    """
    def _norm(s: str) -> str:
        # Collapse camelCase and strip non-alphanumeric characters
        s = re.sub(r'([A-Z])', lambda m: m.group(0).lower(), s)
        return re.sub(r'[^a-z0-9]', '', s)

    n = _norm(name)
    v = _norm(value)
    if not v or not n:
        return False
    return v == n or v in n or n in v


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
                        if isinstance(sl, ast.Constant):
                            key_name = sl.value
                            if key_name and isinstance(key_name, str) and self.engine._looks_like_secret("", key_name):
                                self.engine._collect_issue(node, node.value, key_name, key_name, self.issues, is_environ=True)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Handle keyword arguments."""
        for kw in node.keywords:
            # kw.arg is None means **kwargs unpacking (REFUSE)
            if not kw.arg:
                continue
            # Skip kwargs whose names indicate URL paths or permission scopes.
            if kw.arg.lower() in _NON_SECRET_KWARG_NAMES:
                continue
            if self.engine._is_secret_string_literal(kw.value, kw.arg):
                self.engine._collect_issue(kw, kw.value, kw.arg, kw.arg, self.issues)
        
        self.generic_visit(node)


class ASTEngine:
    """AST-based security analyzer for hardcoded secrets detection."""

    def __init__(self):
        self.parser = None
        logger.debug("ASTEngine initialized (native Python AST mode)")

    def cleanup(self):
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
        # FIX 2: Skip dunder metadata (e.g. __author__, __version__)
        if target.id.startswith("__") and target.id.endswith("__"):
            return False
        return self._is_secret_string_literal(node.value, target.id)

    def _is_secret_string_literal(self, node: ast.AST, name: str) -> bool:
        if self._is_metadata_variable(name):
            return False

        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            return False
        
        if isinstance(node, ast.JoinedStr):
            # For JoinedStr, we don't have a single literal value.
            # However, if the variable NAME looks like a secret, we should detect it
            # so the fixer can explicitly refuse it.
            return self._looks_like_secret("", name)

        val = getattr(node, 'value', None)
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
            'auth_token', 'credential',
            'azure_vision_key', 'openai_api_key'
        ]
        return any(k in check_name_lower for k in secret_keywords)
    # Issue collection

    def _collect_issue(self, node, value_node, check_name, original_name, issues, is_environ=False):

        val = getattr(value_node, 'value', None)
        if isinstance(val, str):
            if _is_placeholder_value(val):
                return
            if _looks_like_identifier_or_word(val):
                return
            if _mirrors_variable_name(check_name, val):
                return
        
        check_name_lower = check_name.lower()
        is_password = any(k in check_name_lower for k in ['password', 'passwd', 'pwd'])
        if is_password:
            is_abbreviated = any(k in check_name_lower for k in ['passwd', 'pwd']) and 'password' not in check_name_lower
            pattern_type = "passwd" if is_abbreviated else "password"
        else:
            pattern_type = "api_key"
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
