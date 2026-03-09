"""
Autonoma — Reporter

Text and JSON output formatting.
Deterministic ordering guaranteed.
"""
import json
import sys
from datetime import datetime, timezone
from typing import TextIO

from . import __version__
from .engine import AnalysisReport
from .history import HistoryReport


# ── Constants ───────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

# Rule metadata — descriptions for all known rules.
# CI integrations can rely on these IDs being stable.
RULE_METADATA = {
    "SEC001": {
        "name": "Hardcoded Password",
        "description": "Detects passwords, credentials, and passphrases "
                       "assigned as string literals.",
        "severity": "high",
        "fixable": True,
        "fix_strategy": "Replace with os.environ[]",
    },
    "SEC002": {
        "name": "Hardcoded Secret/Token",
        "description": "Detects API keys, tokens, secrets, and credentials "
                       "assigned as string literals.",
        "severity": "high",
        "fixable": True,
        "fix_strategy": "Replace with os.environ[]",
    },
}


# ── ANSI colors ─────────────────────────────────────────────────────────

class _Colors:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls):
        cls.RED = cls.YELLOW = cls.GREEN = cls.CYAN = ""
        cls.DIM = cls.BOLD = cls.RESET = ""


def _init_colors():
    if not sys.stdout.isatty():
        _Colors.disable()


def _severity_color(severity: str) -> str:
    s = severity.lower()
    if s == "high":
        return _Colors.RED
    elif s == "medium":
        return _Colors.YELLOW
    return _Colors.DIM


_FIX_STATE_COLORS = {
    "FIXED": "\033[92m",
    "REFUSED": "\033[93m",
    "SKIPPED": "\033[2m",
    "FAILED": "\033[91m",
}


def _utc_iso() -> str:
    """Deterministic UTC timestamp for footer."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Text reporter ──────────────────────────────────────────────────────

def report_text(report: AnalysisReport, verbose: bool = False, quiet: bool = False, out: TextIO = None):
    """Print human-readable text report to stdout."""
    out = out or sys.stdout
    _init_colors()

    issues = report.all_issues

    if quiet and report.total_issues == 0:
        return

    if verbose and report.files_scanned > 0:
        out.write(f"\n{_Colors.DIM}Scanned {report.files_scanned} file(s){_Colors.RESET}\n")

    if issues:
        out.write(f"\n{_Colors.BOLD}{'SEVERITY':<10} {'RULE':<8} {'FILE':<40} {'LINE':<6} MESSAGE{_Colors.RESET}\n")
        out.write(f"{'-' * 90}\n")

        for issue in issues:
            sev = str(issue.get("severity", "?")).upper()
            rule = issue.get("id", "?")
            file = issue.get("file", "?")
            line = issue.get("line", "?")
            msg = issue.get("message", "")
            color = _severity_color(sev)

            out.write(f"{color}{sev:<10}{_Colors.RESET} {rule:<8} {file:<40} {str(line):<6} {msg}\n")

        out.write(f"\n")

        out.write(f"\n")

    if quiet:
        return

    # Deterministic summary footer
    out.write(f"{_Colors.BOLD}=== Analysis Complete ==={_Colors.RESET}\n")
    out.write(f"Files scanned: {report.files_scanned}\n")

    if report.files_skipped > 0:
        out.write(f"Files skipped: {report.files_skipped}\n")

    out.write(f"Issues found:  {report.total_issues}\n")

    if report.high_count > 0:
        out.write(f"{_Colors.RED}HIGH severity: {report.high_count}{_Colors.RESET}\n")
    elif report.total_issues == 0:
        out.write(f"{_Colors.GREEN}No issues found.{_Colors.RESET}\n")

def report_history_text(report: HistoryReport, verbose: bool = False, quiet: bool = False, out: TextIO = None):
    """Print human-readable text report for history scans to stdout."""
    out = out or sys.stdout
    _init_colors()

    if quiet and report.total_findings == 0:
        return

    if report.commits_scanned == 0:
        out.write(f"\n{_Colors.DIM}No commits found with supported extensions.{_Colors.RESET}\n")
        return

    if verbose and report.commits_scanned > 0 and not quiet:
        out.write(f"\n{_Colors.DIM}Scanned {report.commits_scanned} commit(s){_Colors.RESET}\n")

    if report.findings:
        if not quiet:
            out.write(f"\n{_Colors.BOLD}=== Leaked Secrets Found in History ==={_Colors.RESET}\n")
        
        for finding in report.findings:
            color = _severity_color(finding.severity)
            out.write(f"\n")
            out.write(f"Commit: {finding.commit_hash[:7]} (Date: {finding.author_date})\n")
            out.write(f"File:   {finding.file}:{finding.line_number}\n")
            out.write(f"Secret: {color}{finding.rule_id}{_Colors.RESET} ({finding.message})\n")
            out.write(f"Status: {_Colors.RED}leaked in history{_Colors.RESET}\n")
            

    if quiet:
        return

    # Deterministic summary footer
    out.write(f"\n{_Colors.BOLD}=== History Analysis Complete ==={_Colors.RESET}\n")
    out.write(f"Commits scanned: {report.commits_scanned}\n")
    out.write(f"Secrets found:   {report.total_findings}\n")

    if report.total_findings == 0:
        out.write(f"{_Colors.GREEN}No secrets found in git history.{_Colors.RESET}\n")

def report_history_json(report: HistoryReport, out: TextIO = None):
    """Print machine-readable JSON history report to stdout."""
    out = out or sys.stdout

    findings_list = []
    for f in report.findings:
        findings_list.append({
            "commit_hash": f.commit_hash,
            "author_date": f.author_date,
            "commit_message": f.commit_message,
            "file": f.file,
            "line_number": f.line_number,
            "rule_id": f.rule_id,
            "severity": f.severity,
            "message": f.message,
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "autonoma_version": __version__,
        "timestamp": _utc_iso(),
        "summary": {
            "commits_scanned": report.commits_scanned,
            "secrets_found": report.total_findings,
        },
        "findings": findings_list,
    }

    out.write(json.dumps(payload, indent=2))
    out.write("\n")


# ── JSON reporter ──────────────────────────────────────────────────────

def report_json(report: AnalysisReport, out: TextIO = None, fix_outcomes: list = None, dry_run: bool = False):
    """Print machine-readable JSON report to stdout."""
    out = out or sys.stdout

    # Collect which rules appear in the results
    seen_rules = {issue.get("id") for issue in report.all_issues if issue.get("id")}
    rules_block = {
        rid: RULE_METADATA[rid]
        for rid in sorted(seen_rules)
        if rid in RULE_METADATA
    }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "autonoma_version": __version__,
        "timestamp": _utc_iso(),
        "summary": {
            "files_scanned": report.files_scanned,
            "files_skipped": report.files_skipped,
            "total_issues": report.total_issues,
            "high_count": report.high_count,
        },
        "rules": rules_block,
        "issues": report.all_issues,
    }

    if fix_outcomes is not None:
        counts = {"FIXED": 0, "REFUSED": 0, "SKIPPED": 0, "FAILED": 0}
        entries = []
        for o in fix_outcomes:
            counts[o.state] = counts.get(o.state, 0) + 1
            entry = {
                "state": o.state,
                "issue_id": o.issue_id,
                "file": o.file,
                "line": o.line,
                "message": o.message,
            }
            if o.reason:
                entry["reason"] = o.reason
            if o.env_var:
                entry["env_var"] = o.env_var
            entries.append(entry)

        payload["summary"]["fixed"] = counts["FIXED"]
        payload["summary"]["refused"] = counts["REFUSED"]
        payload["summary"]["skipped"] = counts["SKIPPED"]
        payload["fix_results"] = entries
        if dry_run:
            payload["dry_run"] = True

    out.write(json.dumps(payload, indent=2))
    out.write("\n")


# ── Fix outcomes reporter ──────────────────────────────────────────────

def report_fix_outcomes(outcomes: list, fmt: str = "text", out: TextIO = None,
                        dry_run: bool = False, diff_patches: list[str] = None, quiet: bool = False):
    """Print fix outcomes using the stable FIXED/REFUSED/SKIPPED/FAILED states."""
    out = out or sys.stdout
    _init_colors()

    if quiet:
        return

    counts = {"FIXED": 0, "REFUSED": 0, "SKIPPED": 0, "FAILED": 0}
    for o in outcomes:
        counts[o.state] = counts.get(o.state, 0) + 1

    if fmt == "json":
        # Handled by unified report_json() now
        return

    # Text mode
    if dry_run:
        out.write(f"\n{_Colors.BOLD}{_Colors.YELLOW}=== DRY RUN — no files modified ==={_Colors.RESET}\n")
    else:
        out.write(f"\n{_Colors.BOLD}=== Auto-Fix Results ==={_Colors.RESET}\n")

    for o in outcomes:
        color = _FIX_STATE_COLORS.get(o.state, "")
        reset = _Colors.RESET

        if not sys.stdout.isatty():
            color = ""
            reset = ""

        label = o.state
        if dry_run and o.state == "FIXED":
            label = "WOULD_FIX"

        out.write(f"  {color}{label:<10}{reset} {o.issue_id:<8} {o.file}")
        if o.line:
            out.write(f":{o.line}")
        if o.message:
            out.write(f"  — {o.message}")
        out.write("\n")
        
    if diff_patches:
        out.write(f"\n{_Colors.BOLD}=== Proposed Code Changes ==={_Colors.RESET}\n")
        for patch in diff_patches:
            for line in patch.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    out.write(f"{_Colors.GREEN}{line}{_Colors.RESET}\n")
                elif line.startswith("-") and not line.startswith("---"):
                    out.write(f"{_Colors.RED}{line}{_Colors.RESET}\n")
                elif line.startswith("@@"):
                    out.write(f"{_Colors.CYAN}{line}{_Colors.RESET}\n")
                elif line.startswith("---") or line.startswith("+++"):
                    out.write(f"{_Colors.BOLD}{line}{_Colors.RESET}\n")
                else:
                    out.write(f"{line}\n")
            out.write("\n")

    # Deterministic summary footer
    out.write(f"\n")
    summary_parts = []
    for state in ("FIXED", "REFUSED", "SKIPPED", "FAILED"):
        if counts[state] > 0:
            prefix = "WOULD_FIX" if (dry_run and state == "FIXED") else state
            summary_parts.append(f"{counts[state]} {prefix}")
    out.write(f"Summary: {', '.join(summary_parts)}\n")
