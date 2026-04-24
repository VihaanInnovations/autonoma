"""AST-based batched fixer for SEC001/SEC002."""
import ast
import re
import logging
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Reason codes

# REFUSED — found but won't touch (safety / complexity constraints):
REASON_ENV_CONTRACT_MISSING = "env_var_contract_not_found"
REASON_ENV_NAME_AMBIGUOUS = "env_var_name_ambiguous"
REASON_NON_CONSTANT_VALUE = "refuse_non_constant_value"
REASON_FSTRING_MIXED = "refuse_fstring_mixed_expression"
REASON_STRING_CONCATENATION = "refuse_string_concatenation"
REASON_UNSUPPORTED_NODE_TYPE = "refuse_unsupported_node_type"
REASON_UNSAFE_REWRITE_BOUNDARY = "refuse_unsafe_rewrite_boundary"
REASON_MULTIPLE_TARGETS = "refuse_multiple_targets"
REASON_TUPLE_UNPACKING = "refuse_tuple_unpacking"

# SKIPPED — not applicable / already compliant:
REASON_ISSUE_NOT_SUPPORTED = "issue_type_not_supported"
REASON_NO_FILE_PATH = "no_file_path"
REASON_UNSUPPORTED_LANGUAGE = "unsupported_language"
REASON_ALREADY_SAFE = "already_safe"
REASON_NO_TARGET_LINE = "no_target_line"
REASON_REDUNDANT_ENV_ASSIGNMENT = "redundant_env_assignment"
REASON_ENV_FALLBACK_PATTERN = "env_fallback_pattern"

# FAILED — attempted and errored:
REASON_PARSE_FAILED = "parse_failed"
REASON_SYNTAX_BROKEN = "fix_would_break_syntax"
REASON_NODE_NOT_FOUND = "target_node_not_found"


@dataclass
class SecretFixResult:
    """Result of attempting to fix a single issue within a batch."""
    outcome: str  # "SUCCESS", "REFUSED", "SKIPPED", "FAILED"
    reason: Optional[str] = None
    message: Optional[str] = None
    env_var_name: Optional[str] = None
    issue_id: Optional[str] = None
    line: Optional[int] = None


@dataclass
class BatchFixResult:
    """Result of batched fixing for an entire file."""
    fixed_code: Optional[str] = None
    safe_code: Optional[str] = None  # Original code with secrets masked
    per_issue: List[SecretFixResult] = field(default_factory=list)
    any_fixed: bool = False


# Env var mapping

_ENV_VAR_PATTERNS = {
    'password': 'PASSWORD',
    'passwd': 'PASSWORD',
    'pwd': 'PASSWORD',
    'api_key': 'API_KEY',
    'apikey': 'API_KEY',
    'api_secret': 'API_SECRET',
    'secret': 'SECRET',
    'token': 'TOKEN',
    'auth_token': 'AUTH_TOKEN',
    'auth_key': 'AUTH_KEY',
    'access_key': 'ACCESS_KEY',
    'secret_key': 'SECRET_KEY',
}


def _get_env_var_name(var_name: str) -> Optional[str]:
    """Determine env var name. Returns None if ambiguous."""
    var_lower = var_name.lower().replace('-', '_')

    # Specific, clear identifiers >6 chars → use directly
    if re.match(r'^[a-z][a-z0-9_]*$', var_lower) and len(var_lower) > 6:
        return var_lower.upper()

    for pattern, env_name in _ENV_VAR_PATTERNS.items():
        if pattern in var_lower:
            return env_name

    return None


# AST helpers

def _find_target_node_at_line(tree: ast.Module, target_line: int) -> Optional[ast.AST]:
    """Find ast.Assign or ast.keyword whose target/arg lives on target_line (1-indexed)."""
    for node in ast.walk(tree):
        if hasattr(node, "lineno") and node.lineno == target_line:
            if isinstance(node, (ast.Assign, ast.keyword)):
                return node
    return None


def _extract_var_name(target: ast.expr) -> Optional[str]:
    """
    Extract variable name from assignment target.
    Handles Name, os.environ["KEY"].
    """
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript):
        if isinstance(target.value, ast.Attribute):
            if (isinstance(target.value.value, ast.Name)
                    and target.value.value.id == 'os'
                    and target.value.attr == 'environ'):
                sl = target.slice
                if isinstance(sl, (ast.Constant, ast.Str)):
                    return sl.s if isinstance(sl, ast.Str) else sl.value
    return None


def _is_os_environ_target(target: ast.expr) -> bool:
    if isinstance(target, ast.Subscript):
        if isinstance(target.value, ast.Attribute):
            if (isinstance(target.value.value, ast.Name)
                    and target.value.value.id == 'os'
                    and target.value.attr == 'environ'):
                return True
    return False


def _is_string_literal(node: ast.expr) -> bool:
    return isinstance(node, (ast.Constant, ast.Str)) and isinstance(getattr(node, 's', getattr(node, 'value', None)), str)


def _value_is_already_safe(node: ast.expr) -> bool:
    """True if value is os.getenv() or os.environ[]."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if (isinstance(func.value, ast.Name)
                    and func.value.id == 'os'
                    and func.attr == 'getenv'):
                return True
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute):
            if (isinstance(node.value.value, ast.Name)
                    and node.value.value.id == 'os'
                    and node.value.attr == 'environ'):
                return True
    return False


def _is_inside_getenv_call(node: ast.expr) -> bool:
    """True if value is os.getenv('KEY', 'secret') or os.environ.get('KEY', 'secret')."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id == 'os' and func.attr == 'getenv':
                return len(node.args) > 1 or len(node.keywords) > 0
            if (isinstance(func.value, ast.Attribute) and 
                isinstance(func.value.value, ast.Name) and 
                func.value.value.id == 'os' and 
                func.value.attr == 'environ' and 
                func.attr == 'get'):
                return len(node.args) > 1 or len(node.keywords) > 0
    return False


def _is_unsupported_context(node: ast.AST) -> Optional[str]:
    """
    Return a stable reason code if the assignment or keyword is in a context we can't
    safely patch, or None if it's patchable.
    """
    value = getattr(node, 'value', None)
    if value is None:
        return REASON_UNSUPPORTED_NODE_TYPE

    # f-string containing the secret
    if isinstance(value, ast.JoinedStr):
        return REASON_FSTRING_MIXED

    # Function call (e.g. encrypt("secret"))
    if isinstance(value, ast.Call) and not _value_is_already_safe(value):
        return REASON_UNSUPPORTED_NODE_TYPE

    # Dict / List / Tuple containing the value
    if isinstance(value, (ast.Dict, ast.List, ast.Tuple)):
        return REASON_UNSUPPORTED_NODE_TYPE

    # BinOp (e.g. "prefix" + secret)
    if isinstance(value, ast.BinOp):
        return REASON_STRING_CONCATENATION

    return None


def _has_import_os(tree: ast.Module) -> bool:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'os' and not alias.asname:
                    return True
    return False

def _is_os_shadowed(tree: ast.Module) -> bool:
    """Check if 'os' is shadowed by an assignment, function, class, or import alias."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == 'os':
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == 'os':
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == 'os':
                return True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname == 'os':
                    return True
    return False


def _find_import_insert_line(tree: ast.Module) -> int:
    """
    0-indexed line to insert `import os` (after last module-level import).
    Falls back to after docstring, or 0.
    """
    last_import_end = -1
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_end = max(last_import_end, node.end_lineno - 1)

    if last_import_end >= 0:
        return last_import_end + 1

    if (tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, (ast.Constant, ast.Str))):
        return tree.body[0].end_lineno

    return 0


# Main fixer

class SecretFixer:
    """AST-based batched fixer for SEC001/SEC002."""

    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path

    def fix_file(
        self,
        code: str,
        file_path: Path,
        issues: List[Dict[str, Any]],
    ) -> BatchFixResult:
        """
        Batch-fix all issues in a single file.
        """
        result = BatchFixResult()

        if not file_path:
            for issue in issues:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue.get("id", ""),
                    line=issue.get("line"),
                    reason=REASON_NO_FILE_PATH,
                    message="No file path provided.",
                ))
            return result

        ext = file_path.suffix.lower()
        if ext != ".py":
            for issue in issues:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue.get("id", ""),
                    line=issue.get("line"),
                    reason=REASON_UNSUPPORTED_LANGUAGE,
                    message=f"AST fixer only supports Python, got '{ext}'.",
                ))
            return result

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            for issue in issues:
                result.per_issue.append(SecretFixResult(
                    outcome="FAILED", issue_id=issue.get("id", ""),
                    line=issue.get("line"),
                    reason=REASON_PARSE_FAILED,
                    message=f"Cannot parse source: {e}",
                ))
            return result

        if _is_os_shadowed(tree):
            for issue in issues:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue.get("id", ""),
                    line=issue.get("line"),
                    reason="refuse_os_shadowed",
                    message="The 'os' module is shadowed. Unsafe to use os.environ.",
                ))
            return result

        source_lines = code.splitlines()
        patches: List[Tuple[int, str, str]] = []

        for issue in issues:
            issue_id = issue.get("id", "")
            line = issue.get("line")

            if issue_id not in ("SEC001", "SEC002"):
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ISSUE_NOT_SUPPORTED,
                    message=f"Auto-fix not available for {issue_id}.",
                ))
                continue

            if line is None:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_NO_TARGET_LINE,
                    message="No target line number.",
                ))
                continue

            target_node = _find_target_node_at_line(tree, line)
            if target_node is None:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_UNSUPPORTED_NODE_TYPE,
                    message=f"Target at line {line} is inside a complex data structure (safely refused).",
                ))
                continue

            # Strict validation based on "provably safe" rules
            if isinstance(target_node, ast.Assign):
                # Multiple targets (A = B = "...") REFUSE
                if len(target_node.targets) > 1:
                    result.per_issue.append(SecretFixResult(
                        outcome="REFUSED", issue_id=issue_id, line=line,
                        reason=REASON_MULTIPLE_TARGETS,
                        message="Multiple assignment targets are not supported.",
                    ))
                    continue
                # Tuple unpacking (A, B = "...", "...") REFUSE
                if isinstance(target_node.targets[0], (ast.Tuple, ast.List)):
                    result.per_issue.append(SecretFixResult(
                        outcome="REFUSED", issue_id=issue_id, line=line,
                        reason=REASON_TUPLE_UNPACKING,
                        message="Tuple/list unpacking is not supported.",
                    ))
                    continue
                
                var_name = _extract_var_name(target_node.targets[0])
                value_node = target_node.value
                is_environ_target = _is_os_environ_target(target_node.targets[0])
            elif isinstance(target_node, ast.keyword):
                # **kwargs unpacking REFUSE
                if target_node.arg is None:
                    result.per_issue.append(SecretFixResult(
                        outcome="REFUSED", issue_id=issue_id, line=line,
                        reason=REASON_UNSUPPORTED_NODE_TYPE,
                        message="**kwargs unpacking is not supported.",
                    ))
                    continue
                var_name = target_node.arg
                value_node = target_node.value
                is_environ_target = False
            else:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_UNSUPPORTED_NODE_TYPE,
                    message="Unsupported node type for fixing.",
                ))
                continue

            # Fallback pattern?
            if _is_inside_getenv_call(value_node):
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ENV_FALLBACK_PATTERN,
                    message="Value is already environment-guarded with a fallback.",
                ))
                continue

            # Already safe?
            if _value_is_already_safe(value_node):
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ALREADY_SAFE,
                    message=f"Line {line} already uses os.getenv() or os.environ[].",
                ))
                continue

            # Not a string literal? (Refuse f-strings, concatenation, etc.)
            if not _is_string_literal(value_node):
                ctx_reason = _is_unsupported_context(target_node)
                if ctx_reason:
                    result.per_issue.append(SecretFixResult(
                        outcome="REFUSED", issue_id=issue_id, line=line,
                        reason=ctx_reason,
                        message=f"Line {line} refused: {ctx_reason}",
                    ))
                else:
                    result.per_issue.append(SecretFixResult(
                        outcome="REFUSED", issue_id=issue_id, line=line,
                        reason=REASON_NON_CONSTANT_VALUE,
                        message=f"Value at line {line} is not a string literal.",
                    ))
                continue

            if var_name is None:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_ENV_NAME_AMBIGUOUS,
                    message=f"Cannot extract variable name at line {line}.",
                ))
                continue

            env_var_name = _get_env_var_name(var_name)
            if env_var_name is None:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_ENV_NAME_AMBIGUOUS,
                    message=f"Cannot determine safe env var name for '{var_name}'.",
                ))
                continue

            if is_environ_target and var_name == env_var_name:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_REDUNDANT_ENV_ASSIGNMENT,
                    message="Target is already assigning to the target os.environ key.",
                ))
                continue

            # Final context check
            ctx_reason = _is_unsupported_context(target_node)
            if ctx_reason:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=ctx_reason,
                    message=f"Line {line} refused: {ctx_reason}",
                ))
                continue

            # Compute patch
            line_idx = line - 1
            original_line = source_lines[line_idx]
            col_start = value_node.col_offset
            col_end = getattr(value_node, 'end_col_offset', None)

            if col_end is None:
                result.per_issue.append(SecretFixResult(
                    outcome="FAILED", issue_id=issue_id, line=line,
                    reason=REASON_NODE_NOT_FOUND,
                    message="Missing column end offset.",
                ))
                continue

            replacement = f'os.environ["{env_var_name}"]'
            patched_line = original_line[:col_start] + replacement + original_line[col_end:]

            already_patched = any(p[0] == line_idx for p in patches)
            if already_patched:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ALREADY_SAFE,
                    message=f"Line {line} already has a pending fix.",
                ))
                continue

            trunc = issue.get("truncated_secret", "***")
            safe_line = original_line[:col_start] + f'"{trunc}"' + original_line[col_end:]

            patches.append((line_idx, patched_line, safe_line))
            result.per_issue.append(SecretFixResult(
                outcome="SUCCESS", issue_id=issue_id, line=line,
                env_var_name=env_var_name,
                message=f'Replaced with os.environ["{env_var_name}"].',
            ))

        if not patches:
            return result

        patches.sort(key=lambda p: p[0], reverse=True)
        patched_lines = list(source_lines)
        safe_lines = list(source_lines)
        for line_idx, patched_line, safe_line in patches:
            patched_lines[line_idx] = patched_line
            safe_lines[line_idx] = safe_line

        if not _has_import_os(tree):
            insert_at = _find_import_insert_line(tree)
            patched_lines.insert(insert_at, "import os")
            safe_lines.insert(insert_at, "") 

        fixed_code = "\n".join(patched_lines)
        safe_code = "\n".join(safe_lines)

        try:
            ast.parse(fixed_code)
        except SyntaxError as e:
            for r in result.per_issue:
                if r.outcome == "SUCCESS":
                    r.outcome = "FAILED"
                    r.reason = REASON_SYNTAX_BROKEN
                    r.message = f"Batch fix would break syntax: {e}"
            return result

        result.fixed_code = fixed_code
        result.safe_code = safe_code
        result.any_fixed = True
        return result
