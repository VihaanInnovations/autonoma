"""
Autonoma — Tests for Git History Scanning
"""
import subprocess
from pathlib import Path
from autonoma.history import HistoryEngine


def _run_git(cmd: list[str], cwd: Path):
    subprocess.run(["git"] + cmd, cwd=cwd, check=True, capture_output=True)


def test_history_scanner_detects_removed_secrets(tmp_path: Path):
    """
    Simulate a user adding an API key, committing it, and then removing it
    in the next commit. The scanner should flag the first commit's diff.
    """
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # 1. Init git repo
    _run_git(["init"], cwd=repo)
    _run_git(["config", "user.name", "Tester"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)

    # 2. Add an innocent file
    main_py = repo / "main.py"
    main_py.write_text("print('hello world')\n")
    _run_git(["add", "main.py"], cwd=repo)
    _run_git(["commit", "-m", "Initial commit"], cwd=repo)

    # 3. Add a hardcoded API key (THE LEAK)
    db_py = repo / "db.py"
    db_py.write_text("TWILIO_AUTH_TOKEN = 'tw-live-abcdef1234567890'\n")
    _run_git(["add", "db.py"], cwd=repo)
    _run_git(["commit", "-m", "Added DB config"], cwd=repo)

    # 4. Remove the API key (THE FIX)
    db_py.write_text("import os\nTWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')\n")
    _run_git(["add", "db.py"], cwd=repo)
    _run_git(["commit", "-m", "Removed hardcoded secret"], cwd=repo)

    # 5. Run HistoryEngine
    engine = HistoryEngine(allowed_extensions={".py"})
    report = engine.run(repo)

    # 6. Assertions
    # It should have scanned 3 commits
    assert report.commits_scanned == 3
    
    # It should find EXACTLY 1 secret in history
    assert report.total_findings == 1
    
    finding = report.findings[0]
    assert finding.file == "db.py"
    assert finding.rule_id == "SEC002"
    assert finding.commit_message == "Added DB config"
    assert finding.severity == "high"


def test_history_scanner_ignores_non_python_files(tmp_path: Path):
    """Verify history scanner respects allowed extensions."""
    repo = tmp_path / "test_repo_ext"
    repo.mkdir()

    _run_git(["init"], cwd=repo)
    _run_git(["config", "user.name", "Tester"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)

    # Add secret to a .js file
    js_file = repo / "app.js"
    js_file.write_text("const AWS_SECRET = 'AKIAIOSFODNN7EXAMPLE';\\n")
    _run_git(["add", "app.js"], cwd=repo)
    _run_git(["commit", "-m", "Added AWS secret to JS"], cwd=repo)

    # By default, HistoryEngine only allows extensions={".py"} if we pass it
    engine = HistoryEngine(allowed_extensions={".py"})
    report = engine.run(repo)

    # The JS file diff should be completely ignored
    assert report.total_findings == 0
