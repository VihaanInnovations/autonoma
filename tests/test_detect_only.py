import json
import subprocess
import sys
import os
from pathlib import Path


def _env():
    e = os.environ.copy()
    e["PYTHONPATH"] = "src"
    return e


def _scan(path, extra_args=None):
    cmd = [sys.executable, "-m", "autonoma.cli", "scan", str(path)] + (extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=_env())


def _fix(path, extra_args=None):
    cmd = [sys.executable, "-m", "autonoma.cli", "fix", str(path)] + (extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=_env())


# ---------------------------------------------------------------------------
# Exit-code contract (explicit documentation of semantics)
# ---------------------------------------------------------------------------

def test_exit_codes_documented(tmp_path):
    """Explicitly verifies documented exit-code semantics for scan and fix."""
    secret_file = tmp_path / "settings.py"
    secret_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    (clean_dir / "ok.py").write_text("x = 10\n", encoding="utf-8")

    # scan: 0 = no findings, 1 = findings present
    assert _scan(clean_dir).returncode == 0, "scan clean → exit 0"
    assert _scan(tmp_path).returncode == 1, "scan with findings → exit 1"

    # fix: 1 after first run (findings were present), 0 after second run (already clean)
    fix_dir = tmp_path / "fixme"
    fix_dir.mkdir()
    (fix_dir / "secrets.py").write_text("password = 'supersecret'\n", encoding="utf-8")
    (fix_dir / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    r1 = _fix(fix_dir)
    assert r1.returncode == 1, "fix with findings → exit 1 (findings were present)"

    r2 = _fix(fix_dir)
    assert r2.returncode == 0, "fix on already-clean repo → exit 0"


# ---------------------------------------------------------------------------
# scan: findings present
# ---------------------------------------------------------------------------

def test_cli_detect_only(tmp_path):
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    result = _scan(tmp_path)

    assert result.returncode == 1

    data = json.loads(result.stdout)
    assert data["schema_version"] == "1.0"
    assert data["generated_at"] != ""
    assert data["mode"] == "detect-only"

    assert data["summary"]["total_findings"] == 1
    assert data["summary"]["files_processed"] == 1

    assert "Autonoma detect-only summary" in result.stderr
    assert "findings=1" in result.stderr

    finding = data["findings"][0]
    assert finding["file"] == "settings.py"
    assert finding["line"] == 1
    assert finding["pattern_type"] == "password"
    assert finding["rule_id"] == "SEC001"
    assert finding["safe_to_fix"] is True
    assert finding["suggested_env_var"] == "PASSWORD"
    assert "sha256:" in finding["fingerprint"]

    assert src_file.read_text() == "password = 'supersecret'\n"
    assert not (tmp_path / "settings.py.bak").exists()


# ---------------------------------------------------------------------------
# scan: refused (unsafe context)
# ---------------------------------------------------------------------------

def test_cli_detect_only_refused(tmp_path):
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = f'prefix_{secret}'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    result = _scan(tmp_path)

    assert result.returncode == 1
    data = json.loads(result.stdout)

    finding = data["findings"][0]
    assert finding["safe_to_fix"] is False
    assert finding["refusal_reason"] == "refuse_fstring_mixed_expression"
    assert finding["suggested_env_var"] is None


# ---------------------------------------------------------------------------
# scan: no findings
# ---------------------------------------------------------------------------

def test_cli_detect_only_clean(tmp_path):
    (tmp_path / "clean.py").write_text("x = 10\n", encoding="utf-8")

    result = _scan(tmp_path)

    assert result.returncode == 0

    data = json.loads(result.stdout)
    assert len(data["findings"]) == 0
    assert data["summary"]["total_findings"] == 0

    assert "Autonoma detect-only summary" in result.stderr
    assert "findings=0" in result.stderr


# ---------------------------------------------------------------------------
# fix: applies remediation
# ---------------------------------------------------------------------------

def test_cli_fix(tmp_path):
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    result = _fix(tmp_path)

    # exit 1: findings were present (security policy — do not silently pass)
    assert result.returncode == 1

    content = src_file.read_text()
    assert "os.environ[\"PASSWORD\"]" in content
    assert "import os" in content


# ---------------------------------------------------------------------------
# fix: idempotent — second run makes no additional changes
# ---------------------------------------------------------------------------

def test_cli_fix_idempotent(tmp_path):
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    r1 = _fix(tmp_path)
    assert r1.returncode == 1
    content_after_first = src_file.read_text()
    assert "os.environ" in content_after_first

    r2 = _fix(tmp_path)
    # Second run: no findings remain, exit 0
    assert r2.returncode == 0
    # File must be identical — no duplicate imports or double rewrites
    assert src_file.read_text() == content_after_first
