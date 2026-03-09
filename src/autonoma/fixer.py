"""
Autonoma — Fixer

Wraps SecretFixer for deterministic SEC001/SEC002 remediation.
Maps results to the stable output contract: FIXED / REFUSED / SKIPPED / FAILED.

fix_file_issues() batches all issues per file → one parse, one write.
"""
import shutil
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from ._internal.secret_fixer import SecretFixer, BatchFixResult


# ── Stable output states (product contract) ────────────────────────────
# These are part of the public interface. Do not rename.

FIXED = "FIXED"
REFUSED = "REFUSED"
SKIPPED = "SKIPPED"
FAILED = "FAILED"

# Map internal outcomes to public states
_OUTCOME_MAP = {
    "SUCCESS": FIXED,
    "REFUSED": REFUSED,
    "SKIPPED": SKIPPED,
    "FAILED": FAILED,
}


@dataclass
class FixOutcome:
    """Result of attempting to fix one issue."""
    state: str               # FIXED | REFUSED | SKIPPED | FAILED
    issue_id: str
    file: str
    line: Optional[int] = None
    message: Optional[str] = None
    env_var: Optional[str] = None
    reason: Optional[str] = None


# ── Atomic write helper ────────────────────────────────────────────────

def _atomic_write(file_path: Path, content: str) -> Path:
    """
    Write content to file_path with a .bak backup.

    1. Copy current file → file.py.bak  (preserves metadata)
    2. Overwrite file with new content

    Returns the backup path.
    """
    backup = file_path.with_suffix(file_path.suffix + ".bak")
    shutil.copy2(file_path, backup)
    file_path.write_text(content, encoding="utf-8")
    return backup


# ── Public API ─────────────────────────────────────────────────────────

def fix_file_issues(
    code: str,
    file_path: Path,
    issues: List[Dict[str, Any]],
    repo_path: Path,
    write: bool = True,
) -> Tuple[List[FixOutcome], Optional[str]]:
    """
    Batch-fix all issues for a single file.

    One AST parse, one write. No second pass needed.

    Args:
        code: Current file content.
        file_path: Absolute path to the file.
        issues: All issue dicts for this file from the scanner.
        repo_path: Repository root (for env contract check).
        write: If True, write fixed file back (with .bak backup).

    Returns:
        Tuple:
          - List of FixOutcome, one per issue, in the same order as `issues`.
          - Optional string containing a unified diff patch if the file was modified.
    """
    outcomes: List[FixOutcome] = []
    rel_file = str(file_path)

    # Filter: only HIGH severity SEC001/SEC002 go to the fixer.
    # Everything else is SKIPPED immediately.
    fixable_issues = []
    fixable_indices = []

    for i, issue in enumerate(issues):
        issue_id = issue.get("id", "")
        severity = str(issue.get("severity", "")).lower()

        if issue_id not in ("SEC001", "SEC002"):
            outcomes.append(FixOutcome(
                state=SKIPPED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason="issue_type_not_supported",
                message=f"Auto-fix not available for {issue_id}.",
            ))
        elif severity != "high":
            outcomes.append(FixOutcome(
                state=SKIPPED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason="severity_not_high",
                message=f"Severity is '{severity}', only HIGH is auto-fixed.",
            ))
        else:
            fixable_issues.append(issue)
            fixable_indices.append(i)
            outcomes.append(None)  # placeholder

    if not fixable_issues:
        return outcomes, None

    # Delegate to batched fixer
    fixer = SecretFixer(repo_path=repo_path)

    try:
        batch_result: BatchFixResult = fixer.fix_file(code, file_path, fixable_issues)
    except Exception as e:
        for idx in fixable_indices:
            issue = issues[idx]
            outcomes[idx] = FixOutcome(
                state=FAILED,
                issue_id=issue.get("id", ""),
                file=rel_file,
                line=issue.get("line"),
                reason="unexpected_error",
                message=f"Unexpected error: {e}",
            )
        return outcomes, None

    # Map per-issue results to FixOutcome
    for j, fix_result in enumerate(batch_result.per_issue):
        idx = fixable_indices[j]
        public_state = _OUTCOME_MAP.get(fix_result.outcome, FAILED)

        outcomes[idx] = FixOutcome(
            state=public_state,
            issue_id=fix_result.issue_id or issues[idx].get("id", ""),
            file=rel_file,
            line=fix_result.line or issues[idx].get("line"),
            reason=fix_result.reason,
            message=fix_result.message,
            env_var=fix_result.env_var_name,
        )

    diff_patch = None
    if batch_result.any_fixed and batch_result.fixed_code:
        # Generate unified diff
        diff_lines = list(difflib.unified_diff(
            code.splitlines(keepends=True),
            batch_result.fixed_code.splitlines(keepends=True),
            fromfile=f"a/{rel_file}",
            tofile=f"b/{rel_file}",
            n=3
        ))
        if diff_lines:
            diff_patch = "".join(diff_lines)

        # Write once via atomic helper
        if write:
            _atomic_write(file_path, batch_result.fixed_code)

    return outcomes, diff_patch
