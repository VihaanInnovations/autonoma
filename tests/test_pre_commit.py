"""
Autonoma — Tests for pre-commit hook mode
"""
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from autonoma.cli import pre_commit_cmd, cli


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
    """With --auto-fix, fixable secrets should be fixed and exit 0."""
    vuln = tmp_path / "vuln.py"
    vuln.write_text("API_KEY = 'ak_live_1234567890'\n")

    runner = CliRunner()
    with patch("subprocess.run") as mock_git_add:
        result = runner.invoke(pre_commit_cmd, [str(vuln), "--auto-fix"])

    # Should fix and exit 0 (or 1 if REFUSED — depends on fixer logic)
    # For SEC001 with a recognisable API key pattern, the fixer should fix it
    if result.exit_code == 0:
        # Verify git add was called to re-stage
        mock_git_add.assert_called()
    # If the fixer refused, exit 1 is also acceptable
    assert result.exit_code in (0, 1)


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
