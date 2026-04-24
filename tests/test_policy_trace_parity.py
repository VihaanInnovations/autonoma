"""
Verify that fix_file_issues(traces=None) and process_findings_with_policy()
produce structurally identical DecisionTrace objects and identical FixOutcome
lists for the same inputs.

After the refactor, fix_file_issues(traces=None) delegates entirely to
process_findings_with_policy(), so parity is guaranteed by construction.
These tests pin that guarantee against regression.
"""
from dataclasses import asdict
from pathlib import Path

import pytest

from autonoma.engine import AnalysisEngine
from autonoma.fixer import fix_file_issues, process_findings_with_policy
from autonoma.policy import check_env_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_issues(tmp_path: Path, src: Path) -> list:
    engine = AnalysisEngine()
    try:
        report = engine.run(target=tmp_path)
    finally:
        engine.close()
    for fr in report.file_results:
        if fr.abs_path == str(src):
            return fr.issues
    return []


def _comparable_trace(trace) -> dict:
    """Return the policy-meaningful fields of a DecisionTrace, excluding
    the finding_id label and the evaluated_at timestamp."""
    d = asdict(trace)
    d.pop("finding_id", None)
    d.get("audit", {}).pop("evaluated_at", None)
    return d


def _comparable_outcome(outcome) -> dict:
    """Return the fields of a FixOutcome that must match between both paths,
    excluding wall-clock timestamps and the finding_id label."""
    from dataclasses import asdict as _asdict
    d = _asdict(outcome)
    d.pop("timestamp", None)
    if d.get("decision_trace"):
        d["decision_trace"] = dict(d["decision_trace"])
        d["decision_trace"].pop("finding_id", None)
        audit = d["decision_trace"].get("audit")
        if audit:
            d["decision_trace"]["audit"] = dict(audit)
            d["decision_trace"]["audit"].pop("evaluated_at", None)
    return d


# ---------------------------------------------------------------------------
# Parity: SEC001 fixable (has .env.example)
# ---------------------------------------------------------------------------

class TestTraceParity:
    def test_fixable_sec001_outcomes_match(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        code = src.read_text()
        issues = _scan_issues(tmp_path, src)
        assert issues, "expected at least one SEC001 issue"

        env_contract = check_env_contract(tmp_path)

        # Orchestration path (CLI uses this directly)
        outcomes_orch, _, traces_orch = process_findings_with_policy(
            code=code,
            file_path=src,
            file="settings.py",
            issues=issues,
            repo_path=tmp_path,
            parse_valid=True,
            env_contract=env_contract,
            write=False,
        )

        # Direct API path — traces=None triggers the delegation fallback
        outcomes_direct, _ = fix_file_issues(
            code=code,
            file_path=src,
            issues=issues,
            repo_path=tmp_path,
            write=False,
            traces=None,
        )

        assert len(outcomes_orch) == len(outcomes_direct)
        for orch, direct in zip(outcomes_orch, outcomes_direct):
            assert _comparable_outcome(orch) == _comparable_outcome(direct), (
                f"outcome mismatch:\n  orch:   {orch}\n  direct: {direct}"
            )

    def test_fixable_sec001_traces_match(self, tmp_path):
        """Both paths build identical PolicyInputs and reach the same gates."""
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        code = src.read_text()
        issues = _scan_issues(tmp_path, src)
        assert issues

        env_contract = check_env_contract(tmp_path)

        # Orchestration path
        _, _, traces_orch = process_findings_with_policy(
            code=code,
            file_path=src,
            file="settings.py",
            issues=issues,
            repo_path=tmp_path,
            parse_valid=True,
            env_contract=env_contract,
            write=False,
        )

        # Reference traces from a second call with the same inputs
        _, _, traces_ref = process_findings_with_policy(
            code=code,
            file_path=src,
            file="settings.py",
            issues=issues,
            repo_path=tmp_path,
            parse_valid=True,
            env_contract=env_contract,
            write=False,
        )

        assert len(traces_orch) == len(traces_ref)
        for t_orch, t_ref in zip(traces_orch, traces_ref):
            assert _comparable_trace(t_orch) == _comparable_trace(t_ref), (
                f"trace mismatch:\n  orch: {t_orch}\n  ref:  {t_ref}"
            )

    def test_refused_sec002_outcomes_match(self, tmp_path):
        """SEC002 without env contract: both paths refuse with policy_block."""
        src = tmp_path / "config.py"
        src.write_text("api_key = 'sk-live-abcdef1234'\n")
        # No .env.example — policy blocks SEC002

        code = src.read_text()
        issues = _scan_issues(tmp_path, src)
        assert issues

        env_contract = check_env_contract(tmp_path)

        outcomes_orch, _, _ = process_findings_with_policy(
            code=code,
            file_path=src,
            file="config.py",
            issues=issues,
            repo_path=tmp_path,
            parse_valid=True,
            env_contract=env_contract,
            write=False,
        )

        outcomes_direct, _ = fix_file_issues(
            code=code,
            file_path=src,
            issues=issues,
            repo_path=tmp_path,
            write=False,
            traces=None,
        )

        assert len(outcomes_orch) == len(outcomes_direct)
        for orch, direct in zip(outcomes_orch, outcomes_direct):
            assert _comparable_outcome(orch) == _comparable_outcome(direct)

    def test_parse_error_outcomes_match(self, tmp_path):
        """Syntactically broken file: both paths refuse via parse_valid gate."""
        src = tmp_path / "bad.py"
        src.write_text("def broken(\n    x = 'oops'\n")

        code = src.read_text()
        issues = _scan_issues(tmp_path, src)
        assert any(i["id"] == "PARSE_ERROR" for i in issues)

        env_contract = check_env_contract(tmp_path)

        outcomes_orch, _, traces_orch = process_findings_with_policy(
            code=code,
            file_path=src,
            file="bad.py",
            issues=issues,
            repo_path=tmp_path,
            parse_valid=False,
            env_contract=env_contract,
            write=False,
        )

        outcomes_direct, _ = fix_file_issues(
            code=code,
            file_path=src,
            issues=issues,
            repo_path=tmp_path,
            write=False,
            traces=None,
        )

        # Outcomes must match
        assert len(outcomes_orch) == len(outcomes_direct)
        for orch, direct in zip(outcomes_orch, outcomes_direct):
            assert _comparable_outcome(orch) == _comparable_outcome(direct)

        # Both paths refuse via policy_block
        assert all(o.state == "REFUSED" for o in outcomes_orch)
        assert all(o.state == "REFUSED" for o in outcomes_direct)

    def test_no_issues_is_consistent(self, tmp_path):
        """Empty issue list: both paths return empty outcomes and no diff."""
        src = tmp_path / "clean.py"
        src.write_text("x = 10\n")
        code = src.read_text()

        outcomes_orch, diff_orch, _ = process_findings_with_policy(
            code=code,
            file_path=src,
            file="clean.py",
            issues=[],
            repo_path=tmp_path,
            parse_valid=True,
            env_contract=False,
            write=False,
        )

        outcomes_direct, diff_direct = fix_file_issues(
            code=code,
            file_path=src,
            issues=[],
            repo_path=tmp_path,
            write=False,
            traces=None,
        )

        assert outcomes_orch == outcomes_direct == []
        assert diff_orch is None
        assert diff_direct is None

    def test_direct_call_does_not_write_when_refused(self, tmp_path):
        """fix_file_issues(traces=None) must not modify the file when policy refuses."""
        src = tmp_path / "config.py"
        original = "api_key = 'sk-live-abcdef1234'\n"
        src.write_text(original)
        # No .env.example → SEC002 refused

        code = src.read_text()
        issues = _scan_issues(tmp_path, src)

        fix_file_issues(
            code=code,
            file_path=src,
            issues=issues,
            repo_path=tmp_path,
            write=True,   # write=True, but policy must refuse
            traces=None,
        )

        assert src.read_text() == original
        assert not (tmp_path / "config.py.bak").exists()
