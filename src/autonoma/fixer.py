"""Remediates SEC001/SEC002 issues in Python files."""
import shutil
import difflib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from ._internal.secret_fixer import SecretFixer, BatchFixResult


# Public output states

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
    truncated_secret: Optional[str] = None
    provider: Optional[str] = None
    fingerprint: Optional[str] = None
    timestamp: Optional[str] = None


# Atomic write

def _atomic_write(file_path: Path, content: str) -> Path:
    """Write content to file_path with a .bak backup."""
    backup = file_path.with_suffix(file_path.suffix + ".bak")
    shutil.copy2(file_path, backup)
    file_path.write_text(content, encoding="utf-8")
    return backup


# Public API

def fix_file_issues(
    code: str,
    file_path: Path,
    issues: List[Dict[str, Any]],
    repo_path: Path,
    write: bool = True,
) -> Tuple[List[FixOutcome], Optional[str]]:
    """Batch-fix all issues for a single file."""
    outcomes: List[FixOutcome] = []
    try:
        rel_file = str(file_path.relative_to(repo_path))
    except ValueError:
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
                truncated_secret=issue.get("truncated_secret"),
                provider=issue.get("provider", "Unknown"),
                fingerprint=issue.get("fingerprint", "sha256:unknown"),
                timestamp=datetime.utcnow().isoformat() + "Z",
            ))
        elif severity != "high":
            outcomes.append(FixOutcome(
                state=SKIPPED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason="severity_not_high",
                message=f"Severity is '{severity}', only HIGH is auto-fixed.",
                truncated_secret=issue.get("truncated_secret"),
                provider=issue.get("provider", "Unknown"),
                fingerprint=issue.get("fingerprint", "sha256:unknown"),
                timestamp=datetime.utcnow().isoformat() + "Z",
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
                truncated_secret=issue.get("truncated_secret"),
                provider=issue.get("provider", "Unknown"),
                fingerprint=issue.get("fingerprint", "sha256:unknown"),
                timestamp=datetime.utcnow().isoformat() + "Z",
            )
        return outcomes, None

    # Map per-issue results to FixOutcome
    for j, fix_result in enumerate(batch_result.per_issue):
        idx = fixable_indices[j]
        public_state = _OUTCOME_MAP.get(fix_result.outcome, FAILED)

        issue = issues[idx]
        outcomes[idx] = FixOutcome(
            state=public_state,
            issue_id=fix_result.issue_id or issue.get("id", ""),
            file=rel_file,
            line=fix_result.line or issue.get("line"),
            reason=fix_result.reason,
            message=fix_result.message,
            env_var=fix_result.env_var_name,
            truncated_secret=issue.get("truncated_secret"),
            provider=issue.get("provider", "Unknown"),
            fingerprint=issue.get("fingerprint", "sha256:unknown"),
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

    diff_patch = None
    if batch_result.any_fixed and batch_result.fixed_code and batch_result.safe_code:
        # Normalize both versions to ensure they end with a newline.
        # We use the safe_code (masked) as the base for the diff to prevent raw secret leaks.
        orig_base = batch_result.safe_code
        orig_norm = orig_base if orig_base.endswith("\n") else orig_base + "\n"
        fixed_norm = batch_result.fixed_code if batch_result.fixed_code.endswith("\n") else batch_result.fixed_code + "\n"

        # Generate unified diff
        diff_lines = list(difflib.unified_diff(
            orig_norm.splitlines(keepends=True),
            fixed_norm.splitlines(keepends=True),
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
