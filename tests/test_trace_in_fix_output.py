"""
Verify that decision_trace is present in fix JSON output and is consistent
with the trace produced by scan for the same finding.

Tests:
  - fix --json includes decision_trace per fix_result entry
  - scan and fix produce equivalent traces for the same finding
  - final_action in trace matches the actual fix outcome
  - refused findings carry the trace explaining why
  - dry-run (--dry-run --json) also includes traces
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def _env():
    e = os.environ.copy()
    e["PYTHONPATH"] = "src"
    return e


def _scan(path, extra=None):
    cmd = [sys.executable, "-m", "autonoma.cli", "scan", str(path)] + (extra or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=_env())


def _fix(path, extra=None):
    cmd = [sys.executable, "-m", "autonoma.cli", "fix", "--json", str(path)] + (extra or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=_env())


def _strip_volatile(trace: dict) -> dict:
    """Remove wall-clock timestamp and finding_id label before comparing."""
    t = dict(trace)
    t.pop("finding_id", None)
    if t.get("audit"):
        t["audit"] = dict(t["audit"])
        t["audit"].pop("evaluated_at", None)
    return t


# ---------------------------------------------------------------------------
# Presence: fix JSON contains decision_trace
# ---------------------------------------------------------------------------

class TestTraceInFixOutput:
    def test_fix_json_has_decision_trace(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        result = _fix(tmp_path)
        data = json.loads(result.stdout)

        assert "fix_results" in data
        entry = data["fix_results"][0]
        assert "decision_trace" in entry, "decision_trace missing from fix_results entry"

    def test_fix_json_trace_has_required_fields(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        result = _fix(tmp_path)
        data = json.loads(result.stdout)
        trace = data["fix_results"][0]["decision_trace"]

        assert "rule_id" in trace
        assert "final_action" in trace
        assert "gate_results" in trace
        assert "inputs" in trace
        assert "rationale" in trace
        assert "audit" in trace

    def test_refused_fix_has_trace(self, tmp_path):
        """SEC002 without .env.example is refused; trace must explain why."""
        src = tmp_path / "config.py"
        src.write_text("api_key = 'sk-live-abcdef1234'\n")
        # No .env.example → block_with_reason

        result = _fix(tmp_path)
        data = json.loads(result.stdout)

        refused = [e for e in data["fix_results"] if e["state"] == "REFUSED"]
        assert refused, "expected at least one REFUSED entry"

        trace = refused[0]["decision_trace"]
        assert trace["final_action"] == "block_with_reason"
        env_gate = next(
            (g for g in trace["gate_results"] if g["gate"] == "env_contract_present"),
            None,
        )
        assert env_gate is not None
        assert env_gate["passed"] is False

    def test_dry_run_also_has_trace(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        result = _fix(tmp_path, extra=["--dry-run"])
        data = json.loads(result.stdout)

        assert data.get("dry_run") is True
        entry = data["fix_results"][0]
        assert "decision_trace" in entry


# ---------------------------------------------------------------------------
# Consistency: scan trace == fix trace for the same finding
# ---------------------------------------------------------------------------

class TestScanFixTraceConsistency:
    def test_final_action_matches_between_scan_and_fix(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        scan_result = _scan(tmp_path)
        scan_data = json.loads(scan_result.stdout)
        scan_trace = scan_data["findings"][0]["decision_trace"]

        fix_result = _fix(tmp_path)
        fix_data = json.loads(fix_result.stdout)
        fix_trace = fix_data["fix_results"][0]["decision_trace"]

        assert scan_trace["final_action"] == fix_trace["final_action"]

    def test_gate_results_match_between_scan_and_fix(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        # Run scan first, then fix on a fresh copy (fix modifies the file)
        scan_result = _scan(tmp_path)
        scan_data = json.loads(scan_result.stdout)
        scan_trace = _strip_volatile(scan_data["findings"][0]["decision_trace"])

        # Re-create file for fix pass (scan didn't modify it, but be explicit)
        src.write_text("password = 'supersecret'\n")

        fix_result = _fix(tmp_path)
        fix_data = json.loads(fix_result.stdout)
        fix_trace = _strip_volatile(fix_data["fix_results"][0]["decision_trace"])

        assert scan_trace["gate_results"] == fix_trace["gate_results"]

    def test_policy_inputs_match_between_scan_and_fix(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        scan_result = _scan(tmp_path)
        scan_data = json.loads(scan_result.stdout)
        scan_inputs = scan_data["findings"][0]["decision_trace"]["inputs"]

        src.write_text("password = 'supersecret'\n")

        fix_result = _fix(tmp_path)
        fix_data = json.loads(fix_result.stdout)
        fix_inputs = fix_data["fix_results"][0]["decision_trace"]["inputs"]

        # All policy-meaningful inputs must be identical
        for key in ("rule_id", "line", "pattern", "confidence",
                    "parse_valid", "env_contract_exists", "file_type", "interactive_ci"):
            assert scan_inputs[key] == fix_inputs[key], (
                f"inputs[{key!r}] differs: scan={scan_inputs[key]!r} fix={fix_inputs[key]!r}"
            )

    def test_refused_trace_consistent_across_scan_and_fix(self, tmp_path):
        """SEC002 refused in both scan and fix with matching trace structure."""
        src = tmp_path / "config.py"
        src.write_text("api_key = 'sk-live-abcdef1234'\n")

        scan_result = _scan(tmp_path)
        scan_data = json.loads(scan_result.stdout)
        scan_trace = scan_data["findings"][0]["decision_trace"]

        fix_result = _fix(tmp_path)
        fix_data = json.loads(fix_result.stdout)
        fix_trace = fix_data["fix_results"][0]["decision_trace"]

        assert scan_trace["final_action"] == fix_trace["final_action"] == "block_with_reason"
        assert scan_trace["rationale"] == fix_trace["rationale"]


# ---------------------------------------------------------------------------
# final_action ↔ outcome alignment
# ---------------------------------------------------------------------------

class TestFinalActionMatchesOutcome:
    def test_preview_then_apply_means_fixed(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        fix_result = _fix(tmp_path)
        data = json.loads(fix_result.stdout)
        entry = data["fix_results"][0]

        assert entry["decision_trace"]["final_action"] == "preview_then_apply"
        assert entry["state"] == "FIXED"

    def test_block_with_reason_means_refused(self, tmp_path):
        src = tmp_path / "config.py"
        src.write_text("api_key = 'sk-live-abcdef1234'\n")

        fix_result = _fix(tmp_path)
        data = json.loads(fix_result.stdout)
        entry = data["fix_results"][0]

        assert entry["decision_trace"]["final_action"] == "block_with_reason"
        assert entry["state"] == "REFUSED"

    def test_parse_error_is_refused_with_trace(self, tmp_path):
        src = tmp_path / "bad.py"
        src.write_text("def broken(\n    x = 'oops'\n")

        fix_result = _fix(tmp_path)
        data = json.loads(fix_result.stdout)
        entry = data["fix_results"][0]

        assert entry["state"] == "REFUSED"
        trace = entry["decision_trace"]
        assert trace["final_action"] == "block_with_reason"
        gate1 = trace["gate_results"][0]
        assert gate1["gate"] == "parse_valid"
        assert gate1["passed"] is False


# ---------------------------------------------------------------------------
# interactive_ci presence in scan and fix trace outputs
# ---------------------------------------------------------------------------

class TestInteractiveCiInTraceOutput:
    """Verify interactive_ci appears in decision_trace.inputs for both scan and fix."""

    def test_scan_trace_inputs_include_interactive_ci(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        result = _scan(tmp_path)
        data = json.loads(result.stdout)
        inputs = data["findings"][0]["decision_trace"]["inputs"]
        assert "interactive_ci" in inputs

    def test_fix_trace_inputs_include_interactive_ci(self, tmp_path):
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        result = _fix(tmp_path)
        data = json.loads(result.stdout)
        inputs = data["fix_results"][0]["decision_trace"]["inputs"]
        assert "interactive_ci" in inputs

    def test_scan_and_fix_agree_on_interactive_ci(self, tmp_path):
        """interactive_ci value must be identical between scan and fix traces."""
        src = tmp_path / "settings.py"
        src.write_text("password = 'supersecret'\n")
        (tmp_path / ".env.example").write_text("PASSWORD=\n")

        scan_result = _scan(tmp_path)
        scan_data = json.loads(scan_result.stdout)
        scan_ic = scan_data["findings"][0]["decision_trace"]["inputs"]["interactive_ci"]

        src.write_text("password = 'supersecret'\n")

        fix_result = _fix(tmp_path)
        fix_data = json.loads(fix_result.stdout)
        fix_ic = fix_data["fix_results"][0]["decision_trace"]["inputs"]["interactive_ci"]

        assert scan_ic == fix_ic
