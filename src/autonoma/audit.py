"""Remediation audit logging and report generation."""
import json
import re
import hashlib
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Literal

from . import __version__

Action = Literal["fixed", "refused", "skipped", "failed"]
SecretType = Literal["api_key", "password", "token", "generic_secret", "unknown"]

@dataclass(frozen=True)
class RemediationRecord:
    record_id: str
    file: str
    line: int
    rule_id: str
    secret_type: SecretType
    provider: Optional[str]
    masked_value: str
    fingerprint: str
    timestamp: str
    action: Action
    env_var_name: Optional[str] = None
    reason: Optional[str] = None

@dataclass(frozen=True)
class RemediationSummary:
    total_findings: int
    fixed: int
    refused: int
    skipped: int
    failed: int

@dataclass(frozen=True)
class RemediationReport:
    schema_version: str
    tool_name: str
    tool_version: str
    generated_at: str
    rotation_required_notice: str
    summary: RemediationSummary
    findings: List[RemediationRecord]


# Patterns ordered from most specific to least specific
_PROVIDER_PATTERNS = {
    "github": re.compile(r"^(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9_]+$"),
    "sendgrid": re.compile(r"^SG\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+$"),
    "stripe": re.compile(r"^(sk|rk)_(live|test)_[a-zA-Z0-9]+$"),
    "slack": re.compile(r"^xox[baprs]-[0-9]+-[a-zA-Z0-9_]+$"),
    "aws": re.compile(r"^(AKIA[0-9A-Z]{16})$"),
}

_PROVIDER_TITLES = {
    "github": "GitHub",
    "sendgrid": "SendGrid",
    "stripe": "Stripe",
    "slack": "Slack",
    "aws": "AWS",
    "generic": "Generic",
    "unknown": "Unknown"
}


def detect_provider(secret_value: str) -> str:
    """Identify the secret provider based on signature patterns."""
    if not secret_value:
        return "unknown"
        
    for provider, pattern in _PROVIDER_PATTERNS.items():
        if pattern.match(secret_value):
            return provider
            
    return "generic"


def generate_fingerprint(secret_value: str) -> str:
    """Generate a stable, unsalted identity fingerprint from the raw secret."""
    if not secret_value:
        return "sha256:e3b0c44298fc1c149afbf4c8"
    return "sha256:" + hashlib.sha256(secret_value.encode('utf-8')).hexdigest()[:24]


def truncate_secret(secret_value: str) -> str:
    """
    Securely truncate a secret. 
    Always keeps the first 4 chars. Keeps the last 4 chars only if the string is long enough (> 12).
    Short secrets (<=4) only keep the first byte.
    """
    if not secret_value:
        return "***"
    n = len(secret_value)
    if n <= 4:
        return secret_value[:1] + "***"
    if n <= 12:
        return secret_value[:4] + "***"
    
    return secret_value[:4] + "***" + secret_value[-4:]


def _atomic_write(content: str, out_path: Path):
    """Write content to out_path atomically using a temporary file and fsync."""
    fd, tmp_path_str = tempfile.mkstemp(dir=out_path.parent, prefix=".tmp_audit_")
    tmp_path = Path(tmp_path_str)
    
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, out_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _escape_md(text: str) -> str:
    """Escape Markdown table control characters natively."""
    if not text:
        return ""
    # Prevent structural breaks and preserve spacing bounds
    return text.replace("|", "\\|").replace("`", "\\`").replace("\n", " ").replace("\r", "")


def _generate_json_report(report: RemediationReport, out_path: Path):
    """Write records to a JSON file."""
    _atomic_write(json.dumps(asdict(report), indent=2), out_path)


def _generate_markdown_report(report: RemediationReport, out_path: Path):
    """Generate Markdown audit report with Rotation Checklist."""
    records = report.findings
    fixed_count = sum(1 for r in records if r.action == "fixed")
    refused_count = sum(1 for r in records if r.action == "refused")
    skipped_count = sum(1 for r in records if r.action == "skipped")
    failed_count = sum(1 for r in records if r.action == "failed")
    
    lines = [
        "# Autonoma Remediation Audit Log",
        "",
        f"**Generated:** {report.generated_at}  ",
        f"**Tool version:** {report.tool_version}  ",
        f"**Total findings:** {len(records)}",
        "",
        "## Summary",
        "",
        f"- Fixed: {fixed_count}",
        f"- Refused: {refused_count}",
        f"- Skipped: {skipped_count}",
        f"- Failed: {failed_count}",
        "",
        "## Rotation Checklist",
        "",
        "If a secret was ever committed, assume it is compromised and rotate it.",
        ""
    ]
    
    # Group by provider
    providers: Dict[str, List[RemediationRecord]] = {}
    for r in records:
        providers.setdefault(r.provider, []).append(r)
        
    if not providers:
        lines.append("*No secrets found.*")
    else:
        for provider in sorted(providers.keys()):
            provider_records = providers[provider]
            title = _PROVIDER_TITLES.get(provider, provider.title())
            lines.append(f"### {title}")
            for r in provider_records:
                file_disp = _escape_md(r.file.replace("\\", "/"))
                lines.append(f"- [ ] `{r.masked_value}` (`{file_disp}:{r.line}`) - {r.action} [`{r.record_id}`]")
            lines.append("")
            
    # Detailed log table
    lines.append("## Detailed Log")
    lines.append("")
    lines.append("| ID | Timestamp | Action | Provider | Masked Value | Fingerprint | File | Line | Rule | Reason |")
    lines.append("|---|---|---|---|---|---|---|---:|---|---|")
    
    for r in records:
        file_disp = _escape_md(r.file.replace("\\", "/"))
        reason_val = _escape_md(r.reason or "")
        lines.append(f"| {r.record_id} | {r.timestamp} | {r.action} | {r.provider or 'unknown'} | `{r.masked_value}` | `{r.fingerprint}` | `{file_disp}` | {r.line} | {r.rule_id} | {reason_val} |")
        
    _atomic_write("\n".join(lines), out_path)


def generate_audit_log(outcomes: List[Any], out_path: Path):
    """
    Given a list of FixOutcome objects, generate the audit report.
    Format is determined strictly by out_path's suffix.
    Returns a list of Paths written.
    """
    intermediate_records = []
    
    for o in outcomes:
        if not hasattr(o, "truncated_secret") or not o.truncated_secret:
            continue
            
        rule_id = getattr(o, "issue_id", "UNKNOWN")
        secret_type = "password" if rule_id == "SEC001" else "api_key"
        file_path = getattr(o, "file", "unknown")
        line = getattr(o, "line", 0) or 0
        fp = getattr(o, "fingerprint", "sha256:unknown")
        
        provider_val = getattr(o, "provider", "unknown") or "unknown"
        provider_val = provider_val.lower()
            
        intermediate_records.append({
            "file": file_path or "unknown",
            "line": line or 0,
            "rule_id": rule_id or "UNKNOWN",
            "secret_type": secret_type,
            "provider": provider_val,
            "masked_value": o.truncated_secret,
            "fingerprint": fp or "sha256:unknown",
            "timestamp": getattr(o, "timestamp", None) or datetime.utcnow().isoformat() + "Z",
            "action": str(getattr(o, "state", "skipped") or "skipped").lower(),
            "env_var_name": getattr(o, "env_var", None),
            "reason": getattr(o, "reason", None)
        })
        
    # Sort by stable fields to ensure deterministic report order across environments
    intermediate_records.sort(key=lambda r: (r["file"], r["line"], r["rule_id"], r["fingerprint"], r["action"]))

    records = []
    for data in intermediate_records:
        # Stable record ID based on finding context
        identity = f"{data['file']}|{data['line']}|{data['rule_id']}|{data['fingerprint']}"
        record_id = "rec_" + hashlib.md5(identity.encode()).hexdigest()[:8]
        
        records.append(RemediationRecord(
            record_id=record_id,
            **data
        ))
    
    fixed_count = sum(1 for r in records if r.action == "fixed")
    refused_count = sum(1 for r in records if r.action == "refused")
    skipped_count = sum(1 for r in records if r.action == "skipped")
    failed_count = sum(1 for r in records if r.action == "failed")
    
    summary = RemediationSummary(
        total_findings=len(records),
        fixed=fixed_count,
        refused=refused_count,
        skipped=skipped_count,
        failed=failed_count
    )
    
    report = RemediationReport(
        schema_version="1.0",
        tool_name="autonoma",
        tool_version=__version__,
        generated_at=datetime.utcnow().isoformat() + "Z",
        rotation_required_notice="If a secret was ever committed, assume it is compromised and rotate it.",
        summary=summary,
        findings=records
    )
    
    suffix = out_path.suffix.lower()
    if not suffix:
        do_json, do_md = True, True
    elif suffix == ".json":
        do_json, do_md = True, False
    elif suffix == ".md":
        do_json, do_md = False, True
    else:
        raise ValueError(f"Invalid audit log extension '{suffix}'. Must be .json, .md, or no extension.")
        
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written_paths = []
    
    if do_json:
        json_path = out_path.with_suffix(".json") if not suffix else out_path
        _generate_json_report(report, json_path)
        written_paths.append(json_path.resolve())
        
    if do_md:
        md_path = out_path.with_suffix(".md") if not suffix else out_path
        _generate_markdown_report(report, md_path)
        written_paths.append(md_path.resolve())
    
    return written_paths
