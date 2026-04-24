"""Remediates SEC001/SEC002 issues in Python files."""
import shutil
import difflib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from ._internal.secret_fixer import SecretFixer, BatchFixResult
from .policy import (
    evaluate_finding_policy, PolicyInputs, DecisionTrace,
    check_env_contract, default_confidence,
)


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
    decision_trace: Optional[dict] = None


# Atomic write

def _atomic_write(file_path: Path, content: str) -> Path:
    """Write content to file_path with a .bak backup."""
    backup = file_path.with_suffix(file_path.suffix + ".bak")
    shutil.copy2(file_path, backup)
    file_path.write_text(content, encoding="utf-8")
    return backup


# Public API

def process_findings_with_policy(
    code: str,
    file_path: Path,
    file: str,
    issues: List[Dict[str, Any]],
    repo_path: Path,
    parse_valid: bool,
    env_contract: bool,
    write: bool,
    finding_counter_start: int = 0,
) -> Tuple[List["FixOutcome"], Optional[str], List[DecisionTrace]]:
    """Single orchestration path: policy evaluation → fix execution for one file.

    Guarantees policy always runs before any write. Returns outcomes, a unified
    diff patch (if applicable), and the list of DecisionTrace objects in issue order.
    """
    traces: List[DecisionTrace] = []
    for i, issue in enumerate(issues):
        rule_id = issue.get("id", "")
        pattern = issue.get("pattern_type", "unknown")
        traces.append(evaluate_finding_policy(
            finding_id=f"{rule_id}-{finding_counter_start + i + 1:04d}",
            inputs=PolicyInputs(
                file=file,
                line=issue.get("line", 0),
                rule_id=rule_id,
                pattern=pattern,
                confidence=default_confidence(rule_id, pattern),
                parse_valid=parse_valid,
                env_contract_exists=env_contract,
                file_type=file_path.suffix,
                single_literal_replacement=issue.get("single_literal_replacement", True),
            ),
        ))

    outcomes, diff_patch = fix_file_issues(
        code=code,
        file_path=file_path,
        issues=issues,
        repo_path=repo_path,
        write=write,
        traces=traces,
    )
    return outcomes, diff_patch, traces


def fix_file_issues(
    code: str,
    file_path: Path,
    issues: List[Dict[str, Any]],
    repo_path: Path,
    write: bool = True,
    traces: Optional[List] = None,
) -> Tuple[List[FixOutcome], Optional[str]]:
    """Batch-fix all issues for a single file.

    traces: optional list of DecisionTrace objects (one per issue, same order).
    If provided, issues whose trace.final_action != 'preview_then_apply' are
    refused before reaching SecretFixer.
    """
    outcomes: List[FixOutcome] = []
    try:
        rel_file = str(file_path.relative_to(repo_path))
    except ValueError:
        rel_file = str(file_path)

    # Policy must always run. If traces were not supplied, delegate to the
    # canonical orchestration path rather than duplicating input construction.
    if traces is None:
        # A PARSE_ERROR finding signals the file could not be parsed safely.
        parse_valid = not any(i.get("id") == "PARSE_ERROR" for i in issues)
        outcomes, diff_patch, _ = process_findings_with_policy(
            code=code,
            file_path=file_path,
            file=rel_file,
            issues=issues,
            repo_path=repo_path,
            parse_valid=parse_valid,
            env_contract=check_env_contract(repo_path),
            write=write,
        )
        return outcomes, diff_patch

    # Filter: only HIGH severity SEC001/SEC002 go to the fixer.
    # Policy gate: issues with final_action != "preview_then_apply" are refused here.
    # Everything else is SKIPPED immediately.
    fixable_issues = []
    fixable_indices = []

    for i, issue in enumerate(issues):
        issue_id = issue.get("id", "")
        severity = str(issue.get("severity", "")).lower()
        trace = traces[i]

        if trace.final_action == "block_with_reason":
            # Policy hard-blocked this issue (e.g. parse failure, missing env contract).
            # Refuse unconditionally regardless of rule_id or severity.
            outcomes.append(FixOutcome(
                state=REFUSED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason="policy_block",
                message=trace.rationale,
                truncated_secret=issue.get("truncated_secret"),
                provider=issue.get("provider") or "Unknown",
                fingerprint=issue.get("fingerprint", "sha256:unknown"),
                timestamp=datetime.utcnow().isoformat() + "Z",
                decision_trace=asdict(trace),
            ))
        elif issue_id not in ("SEC001", "SEC002"):
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
                decision_trace=asdict(trace),
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
                decision_trace=asdict(trace),
            ))
        elif trace.final_action != "preview_then_apply":
            outcomes.append(FixOutcome(
                state=REFUSED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason="policy_block",
                message=trace.rationale,
                truncated_secret=issue.get("truncated_secret"),
                provider=issue.get("provider", "Unknown"),
                fingerprint=issue.get("fingerprint", "sha256:unknown"),
                timestamp=datetime.utcnow().isoformat() + "Z",
                decision_trace=asdict(trace),
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
                decision_trace=asdict(traces[idx]),
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
            decision_trace=asdict(traces[idx]),
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
