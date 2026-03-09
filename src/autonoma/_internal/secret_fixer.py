"""
Autonoma - Secret Fixer (AST-based, batched per file)

Applies deterministic fixes for SEC001/SEC002 using Python AST.
All fixes for a single file are computed on one parse and applied in one
write - no second pass needed.

Patches are applied bottom-to-top so line numbers never shift.
`import os` is inserted once after the last module-level import.
Syntax is validated once on the final patched code.

Refusal/skip semantics:
    SKIPPED  - nothing to do (already compliant, not a string literal)
    REFUSED  - safety constraint prevents fix (no env contract, ambiguous name)
    FAILED   - attempted but errored (parse failure, syntax break)
    (SUCCESS maps to FIXED in the outer fixer.py layer)
"""
import ast
import re
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# -- Structured reason codes ---------------------------------------------
#
#   SKIPPED = not applicable / already compliant
#   REFUSED = found the issue but chose not to touch it
#   FAILED  = attempted the fix and errored
#

# REFUSED — found but won't touch (safety / complexity constraints):
REASON_ENV_CONTRACT_MISSING = "env_var_contract_not_found"
REASON_ENV_NAME_AMBIGUOUS = "env_var_name_ambiguous"
REASON_UNSUPPORTED_CONTEXT = "unsupported_context"

# SKIPPED — not applicable / already compliant:
REASON_ISSUE_NOT_SUPPORTED = "issue_type_not_supported"
REASON_NO_FILE_PATH = "no_file_path"
REASON_UNSUPPORTED_LANGUAGE = "unsupported_language"
REASON_ALREADY_SAFE = "already_safe"
REASON_NOT_STRING_LITERAL = "not_string_literal"
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
    per_issue: List[SecretFixResult] = field(default_factory=list)
    any_fixed: bool = False


# -- Env var name mapping ------------------------------------------------

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


# -- AST helpers ---------------------------------------------------------

def _find_assignment_at_line(tree: ast.Module, target_line: int) -> Optional[ast.Assign]:
    """Find ast.Assign whose target lives on target_line (1-indexed)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.lineno == target_line:
            return node
    return None


def _extract_var_name(target: ast.expr) -> Optional[str]:
    """
    Extract variable name from assignment target.
    Handles Name, self.attr, cls.attr, os.environ["KEY"].
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
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    return sl.value
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
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


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


def _is_unsupported_context(assign_node: ast.Assign) -> Optional[str]:
    """
    Return a reason string if the assignment is in a context we can't
    safely patch, or None if it's patchable.
    """
    value = assign_node.value

    # f-string containing the secret
    if isinstance(value, ast.JoinedStr):
        return "Value is an f-string; cannot extract secret safely."

    # Function call (e.g. encrypt("secret"))
    if isinstance(value, ast.Call) and not _value_is_already_safe(value):
        return "Value is a function call; cannot determine if it contains a secret."

    # Dict / List / Tuple containing the value
    if isinstance(value, (ast.Dict, ast.List, ast.Tuple)):
        return "Value is a compound literal; per-element fixes not supported."

    # BinOp (e.g. "prefix" + secret)
    if isinstance(value, ast.BinOp):
        return "Value is a concatenation; cannot isolate the secret."

    return None


def _has_import_os(tree: ast.Module) -> bool:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'os':
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
            and isinstance(tree.body[0].value, ast.Constant)):
        return tree.body[0].end_lineno

    return 0


# -- Env contract checker ------------------------------------------------

class _EnvContractChecker:
    def __init__(self, repo_path: Optional[Path]):
        self.repo_path = repo_path
        self._checked = False
        self._result = False

    def has_contract(self) -> bool:
        if self._checked:
            return self._result
        self._checked = True
        self._result = self._check()
        return self._result

    def _check(self) -> bool:
        if not self.repo_path or not self.repo_path.exists():
            return False
        try:
            for name in ('.env', '.env.example', '.env.sample', '.env.local'):
                if (self.repo_path / name).exists():
                    return True

            req = self.repo_path / 'requirements.txt'
            if req.exists():
                text = req.read_text(encoding='utf-8', errors='ignore')
                if 'python-dotenv' in text or 'dotenv' in text:
                    return True

            pkg = self.repo_path / 'package.json'
            if pkg.exists():
                text = pkg.read_text(encoding='utf-8', errors='ignore')
                if 'dotenv' in text:
                    return True

            for root, dirs, files in os.walk(self.repo_path):
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', 'venv', '.venv'}]
                for fname in files:
                    if fname.endswith(('.py',)):
                        try:
                            fpath = Path(root) / fname
                            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                                head = ''.join(f.readline() for _ in range(100))
                            if 'os.getenv' in head or 'os.environ' in head:
                                return True
                        except Exception:
                            continue
        except Exception as e:
            logger.debug(f"Error checking env contract: {e}")
        return False


# -- Main fixer ----------------------------------------------------------

class SecretFixer:
    """
    AST-based batched fixer for SEC001/SEC002.

    fix_file() processes ALL issues for a file in a single pass:
      1. Parse AST once
      2. Evaluate each issue → SUCCESS / REFUSED / SKIPPED
      3. Collect all line patches (replacement strings)
      4. Apply patches bottom-to-top (no line-shift)
      5. Insert import os once (if needed)
      6. Validate syntax once
      7. Return BatchFixResult with per-issue outcomes
    """

    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path
        self._env_checker = _EnvContractChecker(repo_path)

    def check_env_contract(self) -> bool:
        return self._env_checker.has_contract()

    def fix_file(
        self,
        code: str,
        file_path: Path,
        issues: List[Dict[str, Any]],
    ) -> BatchFixResult:
        """
        Batch-fix all issues in a single file.

        Args:
            code: Full file content.
            file_path: Absolute path.
            issues: List of issue dicts from scanner (each has id, line, ...).

        Returns:
            BatchFixResult with per-issue outcomes and (optionally) patched code.
        """
        result = BatchFixResult()

        # ── Pre-flight checks (apply to entire file) ────────────────

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

        if not self.check_env_contract():
            for issue in issues:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue.get("id", ""),
                    line=issue.get("line"),
                    reason=REASON_ENV_CONTRACT_MISSING,
                    message="No environment contract found",
                ))
            return result

        # ── Parse AST once ──────────────────────────────────────────

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

        source_lines = code.splitlines()

        # ── Evaluate each issue ─────────────────────────────────────
        # Collect patches: list of (line_idx_0based, replacement_str, result)
        patches: List[Tuple[int, str]] = []

        for issue in issues:
            issue_id = issue.get("id", "")
            line = issue.get("line")

            # Not a fixable issue type
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

            # Find assignment node
            assign = _find_assignment_at_line(tree, line)
            if assign is None:
                result.per_issue.append(SecretFixResult(
                    outcome="FAILED", issue_id=issue_id, line=line,
                    reason=REASON_NODE_NOT_FOUND,
                    message=f"No assignment found at line {line}.",
                ))
                continue

            if not assign.targets:
                result.per_issue.append(SecretFixResult(
                    outcome="FAILED", issue_id=issue_id, line=line,
                    reason=REASON_NODE_NOT_FOUND,
                    message=f"Assignment at line {line} has no targets.",
                ))
                continue

            # Fallback pattern?
            if _is_inside_getenv_call(assign.value):
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ENV_FALLBACK_PATTERN,
                    message="Value is already environment-guarded with a fallback.",
                ))
                continue

            # Already safe?
            if _value_is_already_safe(assign.value):
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ALREADY_SAFE,
                    message=f"Line {line} already uses os.getenv() or os.environ[].",
                ))
                continue

            # Not a string literal?
            if not _is_string_literal(assign.value):
                ctx_reason = _is_unsupported_context(assign)
                if ctx_reason:
                    result.per_issue.append(SecretFixResult(
                        outcome="REFUSED", issue_id=issue_id, line=line,
                        reason=REASON_UNSUPPORTED_CONTEXT,
                        message=f"Line {line}: {ctx_reason}",
                    ))
                else:
                    result.per_issue.append(SecretFixResult(
                        outcome="SKIPPED", issue_id=issue_id, line=line,
                        reason=REASON_NOT_STRING_LITERAL,
                        message=f"Value at line {line} is not a string literal.",
                    ))
                continue

            # Extract variable name
            var_name = _extract_var_name(assign.targets[0])
            if var_name is None:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_ENV_NAME_AMBIGUOUS,
                    message=f"Cannot extract variable name at line {line}.",
                ))
                continue

            # Determine env var name
            env_var_name = _get_env_var_name(var_name)
            if env_var_name is None:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_ENV_NAME_AMBIGUOUS,
                    message=f"Cannot determine safe env var name for '{var_name}'.",
                ))
                continue

            # Prevent redundant os.environ["KEY"] = os.environ["KEY"]
            if _is_os_environ_target(assign.targets[0]) and var_name == env_var_name:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_REDUNDANT_ENV_ASSIGNMENT,
                    message="Target is already assigning to the target os.environ key.",
                ))
                continue

            # Check for unsupported context (redundant with non-string check,
            # but catches edge cases like ternary with string)
            ctx_reason = _is_unsupported_context(assign)
            if ctx_reason:
                result.per_issue.append(SecretFixResult(
                    outcome="REFUSED", issue_id=issue_id, line=line,
                    reason=REASON_UNSUPPORTED_CONTEXT,
                    message=f"Line {line}: {ctx_reason}",
                ))
                continue

            # ── Compute patch ─────────────────────────────────────
            # Rewrite the value portion using column offsets
            line_idx = line - 1
            original_line = source_lines[line_idx]

            col_start = assign.value.col_offset
            col_end = assign.value.end_col_offset
            replacement = f'os.environ["{env_var_name}"]'
            patched_line = original_line[:col_start] + replacement + original_line[col_end:]

            # Check for duplicate patch on same line (e.g. two issues on same line)
            already_patched = any(p[0] == line_idx for p in patches)
            if already_patched:
                result.per_issue.append(SecretFixResult(
                    outcome="SKIPPED", issue_id=issue_id, line=line,
                    reason=REASON_ALREADY_SAFE,
                    message=f"Line {line} already has a pending fix.",
                ))
                continue

            patches.append((line_idx, patched_line))
            result.per_issue.append(SecretFixResult(
                outcome="SUCCESS", issue_id=issue_id, line=line,
                env_var_name=env_var_name,
                message=f'Replaced with os.environ["{env_var_name}"].',
            ))

        # ── Apply all patches ───────────────────────────────────────

        if not patches:
            return result

        # Sort patches by line index descending (bottom-to-top)
        # so earlier patches don't shift later line numbers.
        patches.sort(key=lambda p: p[0], reverse=True)

        patched_lines = list(source_lines)
        for line_idx, patched_line in patches:
            patched_lines[line_idx] = patched_line

        # Insert `import os` once (if needed)
        if not _has_import_os(tree):
            insert_at = _find_import_insert_line(tree)
            patched_lines.insert(insert_at, "import os")

        fixed_code = "\n".join(patched_lines)

        # ── Final syntax validation ─────────────────────────────────

        try:
            ast.parse(fixed_code)
        except SyntaxError as e:
            # Mark ALL SUCCESS outcomes as FAILED
            for r in result.per_issue:
                if r.outcome == "SUCCESS":
                    r.outcome = "FAILED"
                    r.reason = REASON_SYNTAX_BROKEN
                    r.message = f"Batch fix would break syntax: {e}"
            return result

        result.fixed_code = fixed_code
        result.any_fixed = True
        return result
