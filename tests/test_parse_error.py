"""
Tests: parse failure → synthetic PARSE_ERROR finding → policy gate 1 blocks.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from autonoma.engine import AnalysisEngine
from autonoma.fixer import process_findings_with_policy
from autonoma.policy import check_env_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYNTAX_ERROR_SRC = "def broken(\n    x = 'oops'\n"  # missing closing paren


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
# Unit: engine produces exactly one PARSE_ERROR finding
# ---------------------------------------------------------------------------

class TestParseErrorFinding:
    def test_syntax_error_produces_one_finding(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        engine = AnalysisEngine()
        try:
            report = engine.run(target=tmp_path)
        finally:
            engine.close()

        file_results = [fr for fr in report.file_results if not fr.skipped]
        assert len(file_results) == 1
        fr = file_results[0]

        assert fr.parse_valid is False
        assert len(fr.issues) == 1

        issue = fr.issues[0]
        assert issue["id"] == "PARSE_ERROR"
        assert issue["pattern_type"] == "parse_error"
        assert issue["severity"] == "high"
        assert "syntax error" in issue["message"].lower()
        assert issue["line"] >= 1

    def test_valid_file_has_parse_valid_true(self, tmp_path):
        ok = tmp_path / "ok.py"
        ok.write_text("x = 10\n", encoding="utf-8")

        engine = AnalysisEngine()
        try:
            report = engine.run(target=tmp_path)
        finally:
            engine.close()

        fr = next(r for r in report.file_results if not r.skipped)
        assert fr.parse_valid is True

    def test_parse_error_not_combined_with_regex_findings(self, tmp_path):
        """A syntactically broken file with a password-looking line → only PARSE_ERROR."""
        bad = tmp_path / "bad.py"
        bad.write_text("password = 'secret'\ndef broken(\n", encoding="utf-8")

        engine = AnalysisEngine()
        try:
            report = engine.run(target=tmp_path)
        finally:
            engine.close()

        fr = next(r for r in report.file_results if not r.skipped)
        assert fr.parse_valid is False
        assert len(fr.issues) == 1
        assert fr.issues[0]["id"] == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# Unit: policy evaluator sees parse_valid=False → gate 1 blocks
# ---------------------------------------------------------------------------

class TestParseErrorPolicy:
    def test_policy_gate1_fails_and_blocks(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        engine = AnalysisEngine()
        try:
            report = engine.run(target=tmp_path)
        finally:
            engine.close()

        fr = next(r for r in report.file_results if not r.skipped)
        assert fr.parse_valid is False

        code = bad.read_text(encoding="utf-8")
        env_contract = check_env_contract(tmp_path)

        outcomes, diff_patch, traces = process_findings_with_policy(
            code=code,
            file_path=bad,
            file=fr.file,
            issues=fr.issues,
            repo_path=tmp_path,
            parse_valid=fr.parse_valid,
            env_contract=env_contract,
            write=False,
        )

        assert len(traces) == 1
        trace = traces[0]

        # Gate 1 (parse_valid) must have failed
        gate1 = next(g for g in trace.gate_results if g.gate == "parse_valid")
        assert gate1.passed is False

        # Exactly one gate evaluated (early exit after gate 1)
        assert len(trace.gate_results) == 1

        assert trace.final_action == "block_with_reason"
        assert "parse" in trace.rationale.lower()

    def test_fix_outcome_is_refused(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        engine = AnalysisEngine()
        try:
            report = engine.run(target=tmp_path)
        finally:
            engine.close()

        fr = next(r for r in report.file_results if not r.skipped)
        code = bad.read_text(encoding="utf-8")

        outcomes, _, _ = process_findings_with_policy(
            code=code,
            file_path=bad,
            file=fr.file,
            issues=fr.issues,
            repo_path=tmp_path,
            parse_valid=fr.parse_valid,
            env_contract=False,
            write=False,
        )

        assert len(outcomes) == 1
        assert outcomes[0].state == "REFUSED"
        assert outcomes[0].reason == "policy_block"
        assert "parse" in outcomes[0].message.lower()

    def test_file_not_modified(self, tmp_path):
        bad = tmp_path / "bad.py"
        original = SYNTAX_ERROR_SRC
        bad.write_text(original, encoding="utf-8")

        engine = AnalysisEngine()
        try:
            report = engine.run(target=tmp_path)
        finally:
            engine.close()

        fr = next(r for r in report.file_results if not r.skipped)
        code = bad.read_text(encoding="utf-8")

        process_findings_with_policy(
            code=code,
            file_path=bad,
            file=fr.file,
            issues=fr.issues,
            repo_path=tmp_path,
            parse_valid=fr.parse_valid,
            env_contract=False,
            write=True,  # write=True but policy refuses → no write
        )

        assert bad.read_text(encoding="utf-8") == original
        assert not (tmp_path / "bad.py.bak").exists()


# ---------------------------------------------------------------------------
# CLI integration: scan command JSON output
# ---------------------------------------------------------------------------

class TestParseErrorCLI:
    def test_scan_produces_one_parse_error_finding(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        result = _scan(tmp_path)

        assert result.returncode == 1  # findings present

        data = json.loads(result.stdout)
        assert data["summary"]["total_findings"] == 1
        assert data["summary"]["safe_to_fix"] == 0
        assert data["summary"]["refused"] == 1

        finding = data["findings"][0]
        assert finding["rule_id"] == "PARSE_ERROR"
        assert finding["pattern_type"] == "parse_error"
        assert finding["safe_to_fix"] is False
        assert finding["refusal_reason"] == "policy_block"

    def test_scan_decision_trace_shows_gate1_failed(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        result = _scan(tmp_path)
        data = json.loads(result.stdout)
        finding = data["findings"][0]

        trace = finding["decision_trace"]
        assert trace is not None
        assert trace["final_action"] == "block_with_reason"

        gates = trace["gate_results"]
        assert len(gates) == 1  # early exit after gate 1
        assert gates[0]["gate"] == "parse_valid"
        assert gates[0]["passed"] is False

    def test_scan_rationale_is_clear(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        result = _scan(tmp_path)
        data = json.loads(result.stdout)
        finding = data["findings"][0]

        trace = finding["decision_trace"]
        assert "parse" in trace["rationale"].lower()

    def test_fix_does_not_modify_bad_file(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        result = _fix(tmp_path)

        # File must be untouched
        assert bad.read_text(encoding="utf-8") == SYNTAX_ERROR_SRC
        assert not (tmp_path / "bad.py.bak").exists()

    def test_clean_file_unaffected(self, tmp_path):
        (tmp_path / "clean.py").write_text("x = 10\n", encoding="utf-8")

        result = _scan(tmp_path)
        assert result.returncode == 0

        data = json.loads(result.stdout)
        assert data["summary"]["total_findings"] == 0

    def test_example_json_output_shape(self, tmp_path):
        """Document the exact JSON shape for a PARSE_ERROR finding."""
        bad = tmp_path / "bad.py"
        bad.write_text(SYNTAX_ERROR_SRC, encoding="utf-8")

        result = _scan(tmp_path)
        data = json.loads(result.stdout)
        finding = data["findings"][0]

        # Required fields
        assert "file" in finding
        assert "line" in finding
        assert "rule_id" in finding
        assert "pattern_type" in finding
        assert "safe_to_fix" in finding
        assert "refusal_reason" in finding
        assert "decision_trace" in finding
        assert "fingerprint" in finding

        # Semantics
        assert finding["rule_id"] == "PARSE_ERROR"
        assert finding["safe_to_fix"] is False
        assert finding["suggested_env_var"] is None
