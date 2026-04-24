"""
Tests for _find_project_root() and check_env_contract() in policy.py.

Covers:
  - git available and returns a valid nearby root
  - git unavailable (FileNotFoundError) → clean fallback to start
  - git returns non-zero exit → clean fallback to start
  - git returns a root too far above start (> _MAX_GIT_ROOT_DEPTH) → fallback
  - git returns a root unrelated to start (different path tree) → fallback
  - check_env_contract correctness under mocked git responses
  - optional integration test with a real git repo (skipped when git absent)
"""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autonoma.policy import (
    _MAX_GIT_ROOT_DEPTH,
    _find_project_root,
    check_env_contract,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_available() -> bool:
    try:
        r = subprocess.run(
            ["git", "--version"], capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


requires_git = pytest.mark.skipif(
    not _git_available(), reason="git not installed"
)


def _mock_git_success(stdout: str) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout.strip.return_value = stdout
    return m


def _mock_git_failure(returncode: int = 128) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout.strip.return_value = ""
    return m


# ---------------------------------------------------------------------------
# _find_project_root — unit tests (mocked subprocess)
# ---------------------------------------------------------------------------

class TestFindProjectRoot:
    def test_returns_git_root_when_start_is_directly_inside(self, tmp_path):
        """Git root one level above start → accepted."""
        root = tmp_path
        start = tmp_path / "src"
        start.mkdir()

        with patch("subprocess.run", return_value=_mock_git_success(str(root))):
            result = _find_project_root(start)

        assert result == root

    def test_returns_git_root_at_max_depth(self, tmp_path):
        """Git root exactly _MAX_GIT_ROOT_DEPTH levels above start → accepted."""
        parts = ["a", "b", "c"]
        assert len(parts) == _MAX_GIT_ROOT_DEPTH
        deep = tmp_path
        for p in parts:
            deep = deep / p
            deep.mkdir()

        with patch("subprocess.run", return_value=_mock_git_success(str(tmp_path))):
            result = _find_project_root(deep)

        assert result == tmp_path

    def test_falls_back_when_root_too_far_above_start(self, tmp_path):
        """Git root deeper than _MAX_GIT_ROOT_DEPTH above start → fallback."""
        # Build start that is _MAX_GIT_ROOT_DEPTH + 1 levels below tmp_path
        deep = tmp_path
        for char in "abcd"[: _MAX_GIT_ROOT_DEPTH + 1]:
            deep = deep / char
            deep.mkdir()

        with patch("subprocess.run", return_value=_mock_git_success(str(tmp_path))):
            result = _find_project_root(deep)

        assert result == deep  # fallback, not the git root

    def test_falls_back_when_git_not_installed(self, tmp_path):
        """FileNotFoundError (git absent) → no exception, returns start."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = _find_project_root(tmp_path)

        assert result == tmp_path

    def test_falls_back_on_non_zero_exit(self, tmp_path):
        """Non-zero exit (not a git repo) → returns start."""
        with patch("subprocess.run", return_value=_mock_git_failure(128)):
            result = _find_project_root(tmp_path)

        assert result == tmp_path

    def test_falls_back_on_timeout(self, tmp_path):
        """Timeout or other exception → no propagation, returns start."""
        with patch("subprocess.run", side_effect=TimeoutError("git timed out")):
            result = _find_project_root(tmp_path)

        assert result == tmp_path

    def test_falls_back_when_root_is_unrelated_path(self, tmp_path):
        """Git returns a root that start is not under → fallback."""
        # tmp_path is e.g. C:\Temp\xyz; root is some unrelated path
        unrelated = Path("/some/other/project")
        with patch("subprocess.run", return_value=_mock_git_success(str(unrelated))):
            result = _find_project_root(tmp_path)

        assert result == tmp_path

    @requires_git
    def test_real_git_repo_returns_correct_root(self, tmp_path):
        """Integration: git init + subdirectory → returns the repo root."""
        subprocess.run(
            ["git", "init", str(tmp_path)],
            capture_output=True,
            timeout=10,
        )
        sub = tmp_path / "src" / "app"
        sub.mkdir(parents=True)

        result = _find_project_root(sub)

        assert result.resolve() == tmp_path.resolve()


# ---------------------------------------------------------------------------
# check_env_contract — unit tests (mocked subprocess)
# ---------------------------------------------------------------------------

class TestCheckEnvContractWithMocks:
    def test_no_env_file_returns_false_when_git_absent(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_env_contract(tmp_path) is False

    def test_env_example_found_in_start_when_git_absent(self, tmp_path):
        (tmp_path / ".env.example").write_text("SECRET=\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_env_contract(tmp_path) is True

    def test_dot_env_found_in_start_when_git_absent(self, tmp_path):
        (tmp_path / ".env").write_text("SECRET=value\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_env_contract(tmp_path) is True

    def test_env_sample_found_in_start_when_git_absent(self, tmp_path):
        (tmp_path / ".env.sample").write_text("SECRET=\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_env_contract(tmp_path) is True

    def test_env_file_in_git_root_found_when_root_nearby(self, tmp_path):
        """Git root is the parent; .env.example is there → True."""
        (tmp_path / ".env.example").write_text("SECRET=\n")
        sub = tmp_path / "src"
        sub.mkdir()

        with patch("subprocess.run", return_value=_mock_git_success(str(tmp_path))):
            assert check_env_contract(sub) is True

    def test_env_file_in_distant_git_root_not_found(self, tmp_path):
        """Git root is too far above start → root ignored, env file not found."""
        (tmp_path / ".env.example").write_text("SECRET=\n")

        # Build start that is _MAX_GIT_ROOT_DEPTH + 1 levels below tmp_path
        deep = tmp_path
        for char in "abcd"[: _MAX_GIT_ROOT_DEPTH + 1]:
            deep = deep / char
            deep.mkdir()

        with patch("subprocess.run", return_value=_mock_git_success(str(tmp_path))):
            assert check_env_contract(deep) is False

    def test_nonexistent_path_returns_false(self, tmp_path):
        assert check_env_contract(tmp_path / "does_not_exist") is False

    def test_no_exception_propagated_on_git_error(self, tmp_path):
        """Any subprocess failure must never surface as an exception."""
        with patch("subprocess.run", side_effect=OSError("unexpected")):
            result = check_env_contract(tmp_path)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Integration: real git repo
# ---------------------------------------------------------------------------

class TestCheckEnvContractIntegration:
    @requires_git
    def test_env_example_in_git_root_found_from_subdir(self, tmp_path):
        """Real git repo: .env.example at repo root, scanning from subdir."""
        subprocess.run(
            ["git", "init", str(tmp_path)], capture_output=True, timeout=10
        )
        (tmp_path / ".env.example").write_text("SECRET=\n")
        sub = tmp_path / "src"
        sub.mkdir()

        assert check_env_contract(sub) is True

    @requires_git
    def test_no_env_file_in_git_repo_returns_false(self, tmp_path):
        """Real git repo with no env contract → False."""
        subprocess.run(
            ["git", "init", str(tmp_path)], capture_output=True, timeout=10
        )
        sub = tmp_path / "src"
        sub.mkdir()

        assert check_env_contract(sub) is False
