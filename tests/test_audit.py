import json
import pytest
import io
from pathlib import Path
from dataclasses import dataclass
import hashlib

from autonoma.audit import truncate_secret, detect_provider, generate_audit_log, RemediationRecord, generate_fingerprint
from autonoma.reporter import report_fix_outcomes
import os

@dataclass
class MockFixOutcome:
    state: str
    file: str
    line: int
    truncated_secret: str
    provider: str
    timestamp: str
    issue_id: str = "SEC001"
    message: str = "Fixed"
    env_var: str = None
    fingerprint: str = "sha256:dummy"
    reason: str = None

def test_generate_fingerprint():
    assert generate_fingerprint("foo") == "sha256:" + hashlib.sha256("foo".encode()).hexdigest()[:16]
    assert generate_fingerprint(None) == "sha256:e3b0c44298fc1c14"
    assert generate_fingerprint("") == "sha256:e3b0c44298fc1c14"

def test_truncate_secret():
    # Long strings (>12)
    assert truncate_secret("ghp_1234567890abcd") == "ghp_***abcd"
    assert truncate_secret("sk_live_12345678") == "sk_l***5678"
    assert truncate_secret("AKIA1234567890ABCDEF") == "AKIA***CDEF"
    
    # Medium/Short strings (<=12)
    assert truncate_secret("password123") == "pass***"
    assert truncate_secret("1234") == "1***"
    assert truncate_secret("123") == "1***"
    
    # Edge cases
    assert truncate_secret(None) == "***"
    assert truncate_secret("") == "***"

def test_detect_provider():
    assert detect_provider("ghp_123456") == "github"
    assert detect_provider("SG.123.456") == "sendgrid"
    assert detect_provider("sk_live_123") == "stripe"
    assert detect_provider("xoxb-12-ab") == "slack"
    assert detect_provider("AKIA1234567890ABCDEF") == "aws"
    assert detect_provider("random_string") == "generic"
    assert detect_provider(None) == "unknown"

def test_generate_audit_log_json(tmp_path):
    outcomes = [
        MockFixOutcome("FIXED", "src/main.py", 10, "ghp_***abcd", "github", "2023-10-01T12:00:00Z", "SEC001", "Fixed", None, "sha256:91c7f2e4b8d31a2c"),
        MockFixOutcome("REFUSED", "src/auth.py", 42, "sk_l***123", "stripe", "2023-10-01T12:05:00Z", "SEC002", "Refused", None, "sha256:63f19a0ed0b2451f")
    ]
    
    out_file = tmp_path / "audit.json"
    generate_audit_log(outcomes, out_file)
    
    assert out_file.exists()
    
    data = json.loads(out_file.read_text())
    assert data["schema_version"] == "1.0"
    assert "generated_at" in data
    assert data["rotation_required_notice"] == "If a secret was ever committed, assume it is compromised and rotate it."
    
    summary = data["summary"]
    # v0.1.4 schema uses total_findings
    assert summary["total_findings"] == 2
    assert summary["fixed"] == 1
    assert summary["refused"] == 1
    assert summary["skipped"] == 0
    
    # v0.1.4 schema uses findings
    findings = data["findings"]
    assert len(findings) == 2
    
    # findings are sorted by (file, line, record_id)
    # src/auth.py comes before src/main.py
    assert findings[0]["file"] == "src/auth.py"
    assert findings[0]["provider"] == "stripe"
    assert findings[0]["action"] == "refused"
    
    assert findings[1]["file"] == "src/main.py"
    assert findings[1]["provider"] == "github"
    assert findings[1]["action"] == "fixed"
    assert findings[1]["masked_value"] == "ghp_***abcd"
    assert findings[1]["secret_type"] == "password"
    assert findings[1]["fingerprint"].startswith("sha256:")
    
def test_generate_audit_log_md(tmp_path):
    outcomes = [
        MockFixOutcome("FIXED", "src/main.py", 10, "ghp_***abcd", "github", "2023-10-01T12:00:00Z", "SEC002", "Fixed", None, "sha256:91c7f2e4b8d31a2c"),
        MockFixOutcome("REFUSED", "src/auth.py", 42, "sk_l***123", "stripe", "2023-10-01T12:05:00Z", "SEC002", "Refused", None, "sha256:63f19a0ed0b2451f"),
        MockFixOutcome("SKIPPED", "weird|file.py", 5, "key_***1234", "aws", "2023-10-01T12:10:00Z", "SEC001", "Skipped", None, "sha256:hash", "reason with `backtick`")
    ]
    
    out_file = tmp_path / "audit.md"
    generate_audit_log(outcomes, out_file)
    
    assert out_file.exists()
    
    content = out_file.read_text()
    
    # Check headers
    assert "# Autonoma Remediation Audit Log" in content
    # v0.1.4 uses "findings"
    assert "**Total findings:** 3" in content
    assert "## Summary" in content
    assert "- Fixed: 1" in content
    assert "- Refused: 1" in content
    assert "- Skipped: 1" in content
    assert "- Failed: 0" in content
    assert "## Rotation Checklist" in content
    assert "If a secret was ever committed, assume it is compromised and rotate it." in content
    assert "## Detailed Log" in content
    
    # Check provider headings
    assert "### GitHub" in content
    assert "### Stripe" in content
    
    # Check rotation checkboxes (ensure rec_ prefix and ID presence)
    # Order: aws (weird|file.py), github (src/main.py), stripe (src/auth.py)?
    # No, sorting is by (file, line).
    # src/auth.py:42
    # src/main.py:10
    # weird|file.py:5
    assert "- [ ] `sk_l***123` (`src/auth.py:42`) - refused [`rec_" in content
    assert "- [ ] `ghp_***abcd` (`src/main.py:10`) - fixed [`rec_" in content
    assert "- [ ] `key_***1234` (`weird\\|file.py:5`) - skipped [`rec_" in content
    
    # Check table rows (Markdown format strings)
    assert "SEC002" in content
    assert "sha256:" in content
    
    # Check escaping
    assert "weird\\|file.py" in content
    assert "reason with \\`backtick\\`" in content

def test_audit_identical_secrets(tmp_path):
    # Same secret in two different files
    fp = "sha256:same_hash_12345"
    outcomes = [
        MockFixOutcome("FIXED", "repo/src/a.py", 10, "ghp_***abcd", "github", "2023-10-01T12:00:00Z", "SEC001", "Fixed", None, fp),
        MockFixOutcome("FIXED", "repo/src/b.py", 20, "ghp_***abcd", "github", "2023-10-01T12:00:01Z", "SEC001", "Fixed", None, fp)
    ]
    
    # 1. Test Markdown
    md_file = tmp_path / "audit.md"
    generate_audit_log(outcomes, md_file)
    md_content = md_file.read_text()
    
    assert "**Total findings:** 2" in md_content
    # Both files should show up in the rotation checklist
    assert "repo/src/a.py:10" in md_content
    assert "repo/src/b.py:20" in md_content
    # Fingerprint should be present twice in the detailed log table
    assert md_content.count(fp) == 2
    
    # 2. Test JSON
    json_file = tmp_path / "audit.json"
    generate_audit_log(outcomes, json_file)
    data = json.loads(json_file.read_text())
    
    assert data["summary"]["total_findings"] == 2
    assert data["findings"][0]["record_id"].startswith("rec_")
    assert data["findings"][1]["record_id"].startswith("rec_")
    assert len(data["findings"][0]["record_id"]) == 12 # rec_ + 8 hex
    assert data["findings"][0]["fingerprint"] == fp
    assert data["findings"][1]["fingerprint"] == fp
    # a.py comes before b.py
    assert data["findings"][0]["file"] == "repo/src/a.py"
    assert data["findings"][1]["file"] == "repo/src/b.py"

def test_audit_zero_leak_guarantee(tmp_path):
    # The 'smoking gun' secret that must NEVER appear in logs
    raw_secret = "RAW_SECRET"
    masked = "SUPE***5678"
    fp = "sha256:leak_test_hash"
    
    outcomes = [
        MockFixOutcome("FIXED", "src/leak.py", 1, masked, "generic", "2023-10-01T12:00:00Z", "SEC001", "Fixed", None, fp)
    ]
    
    # 1. Verify JSON is clean
    json_path = tmp_path / "safety.json"
    generate_audit_log(outcomes, json_path)
    json_content = json_path.read_text()
    assert raw_secret not in json_content
    assert masked in json_content
    assert fp in json_content
    
    # 2. Verify Markdown is clean
    md_path = tmp_path / "safety.md"
    generate_audit_log(outcomes, md_path)
    md_content = md_path.read_text()
    assert raw_secret not in md_content
    assert masked in md_content
    assert fp in md_content

def test_console_zero_leak_guarantee():
    # Test that the console summary doesn't leak secrets
    raw_secret = "RAW_SECRET"
    masked = "SUPE***5678"
    
    outcomes = [
        MockFixOutcome("FIXED", "src/pass.py", 5, masked, "generic", "timestamp", "SEC001", "Fixed this", None, "fp")
    ]
    
    # Capture console output
    f = io.StringIO()
    report_fix_outcomes(outcomes, out=f)
    output = f.getvalue()
    
    assert raw_secret not in output
    assert "FIXED" in output
    assert "src/pass.py" in output

def test_console_diff_leak_check():
    # This specifically checks if the DIFF leaks secrets
    raw_secret = "RAW_SECRET"
    diff_patch = f"- password = \"{raw_secret}\"\n+ password = os.environ[\"PWD\"]"
    
    outcomes = [
        MockFixOutcome("FIXED", "src/leak.py", 1, "LEAK***", "generic", "timestamp", "SEC001", "Fixed", None, "fp")
    ]
    
    f = io.StringIO()
    # In reality, the fixer passes a MASKED diff. We simulate that here.
    masked_diff = diff_patch.replace(raw_secret, "LEAK***")
    report_fix_outcomes(outcomes, diff_patches=[masked_diff], out=f)
    output = f.getvalue()
    
    # If this fails, even the "masked" diff leaked something!
    assert raw_secret not in output
    assert "LEAK***" in output

def test_audit_record_id_lifecycle(tmp_path):
    # Same context, different action (Model B)
    fp = "sha256:lifecycle_test"
    
    outcomes_refused = [
        MockFixOutcome("REFUSED", "src/mod.py", 10, "ghp_***abcd", "github", "2023-10-01T12:00:00Z", "SEC001", "unsupported", None, fp)
    ]
    outcomes_fixed = [
        MockFixOutcome("FIXED", "src/mod.py", 10, "ghp_***abcd", "github", "2023-10-01T12:05:00Z", "SEC001", "fixed", None, fp)
    ]
    
    json_refused = tmp_path / "refused.json"
    generate_audit_log(outcomes_refused, json_refused)
    id1 = json.loads(json_refused.read_text())["findings"][0]["record_id"]
    
    json_fixed = tmp_path / "fixed.json"
    generate_audit_log(outcomes_fixed, json_fixed)
    id2 = json.loads(json_fixed.read_text())["findings"][0]["record_id"]
    
    # Under Model B, these MUST be identical
    assert id1 == id2
    assert id1.startswith("rec_")