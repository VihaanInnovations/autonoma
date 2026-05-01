"""Remediates SEC001/SEC002 issues in Python files."""
import re
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

def _suggest_env_var(var_name: str) -> str:
    """Convert a variable name to a suggested env var name."""
    return re.sub(r'[^A-Z0-9_]', '_', var_name.upper())


def _generate_preview_diff(
    code: str,
    file_path: Path,
    issues: List[Dict[str, Any]],
    rel_file: str,
) -> Optional[str]:
    """Generate a text-based preview diff for any file type (read-only, no writes)."""
    from ._internal.heuristics import _file_ext
    ext = _file_ext(str(file_path))
    lines = code.splitlines()
    preview_lines = list(lines)
    changed_indices: set = set()

    for issue in issues:
        line_num = issue.get("line")
        if not line_num or line_num > len(lines):
            continue
        line_idx = line_num - 1
        if line_idx in changed_indices:
            continue

        original_line = lines[line_idx]
        var_name = issue.get("var_name") or ""
        if not var_name:
            parts = re.split(r'[:=]', original_line, 1)
            var_name = parts[0].strip().strip('"\'').strip()
        env_var = _suggest_env_var(var_name) if var_name else "SECRET"

        if ext == ".py":
            # Replace string literal value with os.environ["VAR"]
            new_line = re.sub(r'(=\s*)["\'][^"\']*["\']', rf'\1os.environ["{env_var}"]', original_line)
        elif ext in {".yaml", ".yml"}:
            new_line = re.sub(r'(:\s+)\S.*', rf'\1${{{env_var}}}', original_line)
        elif ext == ".json":
            new_line = re.sub(r'(":\s*)"[^"]*"', rf'\1"${{{env_var}}}"', original_line)
        elif ext in {".toml", ".tf"}:
            new_line = re.sub(r'(=\s*)["\'][^"\']*["\']', rf'\1"${{{env_var}}}"', original_line)
        else:  # .env, .config, .ini, .properties, .sh
            new_line = re.sub(r'(=\s*)\S.*', rf'\1${{{env_var}}}', original_line)

        if new_line != original_line:
            preview_lines[line_idx] = new_line
            changed_indices.add(line_idx)

    if not changed_indices:
        return None

    orig_norm = "\n".join(lines)
    if not orig_norm.endswith("\n"):
        orig_norm += "\n"
    prev_norm = "\n".join(preview_lines)
    if not prev_norm.endswith("\n"):
        prev_norm += "\n"

    diff_lines = list(difflib.unified_diff(
        orig_norm.splitlines(keepends=True),
        prev_norm.splitlines(keepends=True),
        fromfile=f"a/{rel_file}",
        tofile=f"b/{rel_file}",
        n=3,
    ))
    return "".join(diff_lines) if diff_lines else None


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
    dry_run: bool = False,
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
                dry_run=dry_run,
            ),
        ))

    outcomes, diff_patch = fix_file_issues(
        code=code,
        file_path=file_path,
        issues=issues,
        repo_path=repo_path,
        write=write,
        traces=traces,
        dry_run=dry_run,
    )
    return outcomes, diff_patch, traces


def fix_file_issues(
    code: str,
    file_path: Path,
    issues: List[Dict[str, Any]],
    repo_path: Path,
    write: bool = True,
    traces: Optional[List] = None,
    dry_run: bool = False,
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
            dry_run=dry_run,
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
        var_name = issue.get("var_name", "")
        suggested_env = _suggest_env_var(var_name) if var_name else None

        if trace.final_action == "block_with_reason":
            outcomes.append(FixOutcome(
                state=REFUSED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason="policy_block",
                message=trace.rationale,
                env_var=suggested_env,
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
            reason = "policy_block" if trace.final_action == "block_with_reason" else "preview_only"
            outcomes.append(FixOutcome(
                state=REFUSED,
                issue_id=issue_id,
                file=rel_file,
                line=issue.get("line"),
                reason=reason,
                message=trace.rationale,
                env_var=suggested_env,
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
        # In dry-run mode with refused/preview-only findings, generate a text-based preview diff.
        if not write:
            preview_diff = _generate_preview_diff(code, file_path, issues, rel_file)
            return outcomes, preview_diff
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
