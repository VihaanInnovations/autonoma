"""
Autonoma — AST Engine
Detects hardcoded secrets (SEC001/SEC002) using native Python AST.
"""
import ast
import hashlib
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


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
        issues = []

        if not file_path.endswith('.py'):
            return issues

        try:
            issues = self._analyze_python_native(content)
        except Exception as e:
            logger.debug(f"AST analysis failed: {e}")

        return issues

    def _analyze_python_native(self, content: str) -> List[Dict[str, Any]]:
        """Native Python AST analysis for hardcoded secrets."""
        issues = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        except Exception:
            return []

        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            var_name = target.id
                            self._check_secret_assignment(node, var_name, var_name, issues)

                        elif isinstance(target, ast.Subscript):
                            is_environ = False
                            if isinstance(target.value, ast.Attribute):
                                if isinstance(target.value.value, ast.Name) and target.value.value.id == 'os':
                                    if target.value.attr == 'environ':
                                        is_environ = True

                            if is_environ:
                                key_name = None
                                slice_node = target.slice
                                if isinstance(slice_node, (ast.Constant, ast.Str)):
                                    key_name = slice_node.s if isinstance(slice_node, ast.Str) else slice_node.value

                                if key_name and isinstance(key_name, str):
                                    self._check_secret_assignment(node, key_name, key_name, issues, is_environ=True)

        except Exception as e:
            logger.debug(f"AST walk failed: {e}")

        return issues

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

    def _check_secret_assignment(self, node, check_name, original_name, issues, is_environ=False):
        """Helper to check if an assignment value is a hardcoded secret."""
        check_name_lower = check_name.lower()

        # Skip metadata variables (PASSWORD_CHARS, SECRET_KEY_LENGTH, etc.)
        if self._is_metadata_variable(check_name):
            return

        secret_keywords = [
            'password', 'passwd', 'pwd',
            'api_key', 'apikey', 'secret', 'token',
            'auth_token', 'auth', 'credential', 'key',
            'azure_vision_key', 'openai_api_key'
        ]

        if any(k in check_name_lower for k in secret_keywords):
            if isinstance(node.value, (ast.Constant, ast.Str)):
                try:
                    val = node.value.s if isinstance(node.value, ast.Str) else node.value.value
                except AttributeError:
                    val = getattr(node.value, 'value', None)

                if isinstance(val, str) and len(val) > 0:
                    if 'os.getenv' in val or 'os.environ' in val:
                        return

                    is_password = any(k in check_name_lower for k in ['password', 'passwd', 'pwd'])
                    issue_id = "SEC001" if is_password else "SEC002"

                    msg_target = f'os.environ["{original_name}"]' if is_environ else f"'{original_name}'"

                    issues.append({
                        "id": issue_id,
                        "line": node.lineno,
                        "col_offset": node.value.col_offset,
                        "end_col_offset": getattr(node.value, 'end_col_offset', None),
                        "message": f"Hardcoded {'password' if is_password else 'secret'} {msg_target} detected.",
                        "type": "security",
                        "severity": "high",
                        "source": "ast_engine_native"
                    })
