import json
import subprocess
from pathlib import Path
import os

def test_cli_detect_only(tmp_path):
    # 1. Create a dummy file with a secret
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    # 2. Create a .env.example (to satisfy remediation contract)
    env_file = tmp_path / ".env.example"
    env_file.write_text("PASSWORD=\n", encoding="utf-8")
    
    # 3. Run autonoma analyze --detect-only
    # Note: we use sys.executable to ensure we use the same python environment
    import sys
    cmd = [sys.executable, "-m", "autonoma.cli", "scan", str(tmp_path), "--json"]
    
    # Set PYTHONPATH so it can find the local 'src'
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    # Exit code 1 because findings are present
    assert result.returncode == 1
    
    # stdout should be clean JSON
    data = json.loads(result.stdout)
    assert data["schema_version"] == "1.0"
    assert data["generated_at"] != ""
    assert data["mode"] == "detect-only"
    
    # summary check
    assert data["summary"]["total_findings"] == 1
    assert data["summary"]["files_processed"] == 1
    
    # stderr should contain the summary
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
    
    # 5. Verify NO file writes occurred (no .bak, content unchanged)
    assert src_file.read_text() == "password = 'supersecret'\n"
    assert not (tmp_path / "settings.py.bak").exists()

def test_cli_detect_only_refused(tmp_path):
    # 1. Create a dummy file with a secret in UNSUPPORTED context (f-string)
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = f'prefix_{secret}'\n", encoding="utf-8")
    
    # 2. Create a .env.example
    env_file = tmp_path / ".env.example"
    env_file.write_text("PASSWORD=\n", encoding="utf-8")
    
    import sys
    cmd = [sys.executable, "-m", "autonoma.cli", "scan", str(tmp_path), "--json"]
    
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    # Exit code 1 because findings are present
    assert result.returncode == 1
    data = json.loads(result.stdout)
    
    finding = data["findings"][0]
    assert finding["safe_to_fix"] is False
    assert finding["refusal_reason"] == "refuse_fstring_mixed_expression"
    assert finding["suggested_env_var"] is None

def test_cli_detect_only_clean(tmp_path):
    # 1. Create a clean file
    src_file = tmp_path / "clean.py"
    src_file.write_text("x = 10\n", encoding="utf-8")
    
    import sys
    cmd = [sys.executable, "-m", "autonoma.cli", "scan", str(tmp_path), "--json"]
    
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    # Exit code 0 because NO findings
    assert result.returncode == 0
    
    data = json.loads(result.stdout)
    assert len(data["findings"]) == 0
    
    # stderr should contain the summary
    assert "Autonoma detect-only summary" in result.stderr
    assert "findings=0" in result.stderr
    
    # Check JSON summary
    assert data["summary"]["total_findings"] == 0

def test_cli_fix(tmp_path):
    # 1. Create a dummy file with a secret
    src_file = tmp_path / "settings.py"
    src_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    
    # 2. .env.example
    env_file = tmp_path / ".env.example"
    env_file.write_text("PASSWORD=\n", encoding="utf-8")
    
    import sys
    cmd = [sys.executable, "-m", "autonoma.cli", "fix", str(tmp_path)]
    
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    # Fix command: exit 1 because findings were present (security policy)
    assert result.returncode == 1
    
    # Verify file was modified
    content = src_file.read_text()
    assert "os.environ[\"PASSWORD\"]" in content
    assert "import os" in content