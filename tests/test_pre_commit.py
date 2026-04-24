"""
Autonoma — Tests for pre-commit hook mode
"""
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from autonoma.cli import pre_commit_cmd, cli


def _git_add_mock(returncode: int) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    return m


def _git_rev_parse_mock() -> MagicMock:
    """Simulate git rev-parse returning non-zero (not a git repo) so
    _find_project_root falls back to the start path without error."""
    m = MagicMock()
    m.returncode = 1
    return m


def _make_subprocess_side_effect(git_add_returncode: int):
    """Return a side_effect for subprocess.run that routes git rev-parse calls
    (issued by _find_project_root) separately from git add calls."""
    def _side_effect(cmd, **kwargs):
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1] == "rev-parse":
            return _git_rev_parse_mock()
        return _git_add_mock(git_add_returncode)
    return _side_effect


def test_no_files_exits_0():
    """No filenames passed → exit 0 (nothing to scan)."""
    runner = CliRunner()
    result = runner.invoke(pre_commit_cmd, [])
    assert result.exit_code == 0


def test_clean_file_exits_0(tmp_path: Path):
    """A clean Python file → exit 0."""
    clean = tmp_path / "clean.py"
    clean.write_text("print('hello world')\n")

    runner = CliRunner()
    result = runner.invoke(pre_commit_cmd, [str(clean)])
    assert result.exit_code == 0


def test_secret_found_exits_1(tmp_path: Path):
    """A file with a hardcoded secret → exit 1 (commit blocked)."""
    vuln = tmp_path / "vuln.py"
    vuln.write_text("API_KEY = 'ak_live_1234567890'\n")

    runner = CliRunner()
    result = runner.invoke(pre_commit_cmd, [str(vuln)])
    assert result.exit_code == 1


def test_non_python_file_exits_0(tmp_path: Path):
    """Non-Python file should be filtered out → exit 0."""
    txt = tmp_path / "readme.txt"
    txt.write_text("API_KEY = 'ak_live_1234567890'\n")

    runner = CliRunner()
    result = runner.invoke(pre_commit_cmd, [str(txt)])
    assert result.exit_code == 0


def test_auto_fix_cleans_up(tmp_path: Path):
    """With --auto-fix and no env contract, the fix is refused and git add is never called."""
    vuln = tmp_path / "vuln.py"
    vuln.write_text("API_KEY = 'ak_live_1234567890'\n")
    # No .env.example — fixer refuses, git add must not be called

    runner = CliRunner()
    with patch("subprocess.run", side_effect=_make_subprocess_side_effect(0)) as mock_sub:
        result = runner.invoke(pre_commit_cmd, [str(vuln), "--auto-fix"])

    git_add_calls = [c for c in mock_sub.call_args_list if c.args[0][:2] == ["git", "add"]]
    assert git_add_calls == [], "git add must not be called when fix is refused"
    assert result.exit_code == 1


def test_auto_fix_restage_success(tmp_path: Path):
    """Fixable secret + git add succeeds → exit 0, 'Fixed and re-staged' printed."""
    vuln = tmp_path / "vuln.py"
    vuln.write_text("password = 'supersecret'\n")
    (tmp_path / ".env.example").write_text("PASSWORD=\n")

    runner = CliRunner()
    with patch("subprocess.run", side_effect=_make_subprocess_side_effect(0)) as mock_sub:
        result = runner.invoke(pre_commit_cmd, [str(vuln), "--auto-fix"])

    git_add_calls = [c for c in mock_sub.call_args_list if c.args[0][:2] == ["git", "add"]]
    assert len(git_add_calls) == 1, f"expected exactly one git add call, got {git_add_calls}"
    assert git_add_calls[0].args[0] == ["git", "add", str(vuln)]
    assert git_add_calls[0].kwargs == {"capture_output": True}
    assert result.exit_code == 0
    assert "Fixed and re-staged" in result.output


def test_auto_fix_restage_failure_blocks_commit(tmp_path: Path):
    """Fixable secret + git add fails → exit 1, error message emitted, commit blocked."""
    vuln = tmp_path / "vuln.py"
    vuln.write_text("password = 'supersecret'\n")
    (tmp_path / ".env.example").write_text("PASSWORD=\n")

    runner = CliRunner()
    with patch("subprocess.run", side_effect=_make_subprocess_side_effect(128)) as mock_sub:
        result = runner.invoke(pre_commit_cmd, [str(vuln), "--auto-fix"])

    git_add_calls = [c for c in mock_sub.call_args_list if c.args[0][:2] == ["git", "add"]]
    assert len(git_add_calls) == 1, f"expected exactly one git add call, got {git_add_calls}"
    assert result.exit_code == 1
    # Error must appear in output — do not silently swallow the git add failure
    assert "ERROR" in result.output
    assert "git add failed" in result.output
    # Must NOT claim the file was successfully re-staged
    assert "Fixed and re-staged" not in result.output


def test_multiple_files_mixed(tmp_path: Path):
    """Mix of clean and dirty files → exit 1 if any dirty."""
    clean = tmp_path / "clean.py"
    clean.write_text("x = 42\n")

    vuln = tmp_path / "vuln.py"
    vuln.write_text("API_KEY = 'ak_live_1234567890'\n")

    runner = CliRunner()
    result = runner.invoke(pre_commit_cmd, [str(clean), str(vuln)])
    assert result.exit_code == 1


def test_quiet_suppresses_output(tmp_path: Path):
    """With --quiet, non-essential output should be suppressed."""
    vuln = tmp_path / "vuln.py"
    vuln.write_text("API_KEY = 'ak_live_1234567890'\n")

    runner = CliRunner()
    result = runner.invoke(pre_commit_cmd, [str(vuln), "--quiet"])
    assert result.exit_code == 1
    # Quiet mode should produce minimal stdout
    assert len(result.output.strip()) == 0 or "issue" not in result.output.lower()


def test_via_cli_group(tmp_path: Path):
    """Ensure the pre-commit command is accessible via the top-level CLI group."""
    clean = tmp_path / "clean.py"
    clean.write_text("print('hello')\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["pre-commit", str(clean)])
    assert result.exit_code == 0
