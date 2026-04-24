"""
Tests for the policy layer v1 (src/autonoma/policy.py).

Gate sequence under test:
  1. parse_valid
  2. category_policy
  3. confidence_threshold
  4. env_contract_present
  5. override_valid (stub)
"""
import json
import os
import subprocess
import sys
import textwrap
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from autonoma.policy import (
    GATE_CATEGORY_POLICY,
    GATE_CONFIDENCE_THRESHOLD,
    GATE_ENV_CONTRACT_PRESENT,
    GATE_OVERRIDE_VALID,
    GATE_PARSE_VALID,
    GATE_SINGLE_LITERAL_REPLACEMENT,
    SEC001_CONFIDENCE_THRESHOLD,
    PolicyInputs,
    OverrideToken,
    evaluate_finding_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inputs(
    rule_id="SEC001",
    pattern="password",
    confidence=0.95,
    parse_valid=True,
    env_contract_exists=True,
    file_type=".py",
    single_literal_replacement=True,
    override_token=None,
    interactive_ci=False,
) -> PolicyInputs:
    return PolicyInputs(
        file="app/config.py",
        line=10,
        rule_id=rule_id,
        pattern=pattern,
        confidence=confidence,
        parse_valid=parse_valid,
        env_contract_exists=env_contract_exists,
        file_type=file_type,
        single_literal_replacement=single_literal_replacement,
        override_token=override_token or OverrideToken(),
        interactive_ci=interactive_ci,
    )


def _gate_passed(trace, gate_name: str) -> bool:
    for g in trace.gate_results:
        if g.gate == gate_name:
            return g.passed
    raise KeyError(f"gate not found: {gate_name}")


# ---------------------------------------------------------------------------
# Action routing
# ---------------------------------------------------------------------------

class TestFinalAction:
    def test_sec001_above_threshold_with_env_contract(self):
        trace = evaluate_finding_policy("F-001", _inputs(
            rule_id="SEC001", confidence=0.95, env_contract_exists=True
        ))
        assert trace.final_action == "preview_then_apply"

    def test_sec001_below_threshold(self):
        trace = evaluate_finding_policy("F-002", _inputs(
            rule_id="SEC001", confidence=0.85, env_contract_exists=True
        ))
        assert trace.final_action == "preview_only"

    def test_sec001_at_exact_threshold(self):
        trace = evaluate_finding_policy("F-003", _inputs(
            rule_id="SEC001", confidence=SEC001_CONFIDENCE_THRESHOLD, env_contract_exists=True
        ))
        assert trace.final_action == "preview_then_apply"

    def test_sec001_missing_env_contract(self):
        # No env contract: cannot derive a safe destination, so preview_only (not block).
        # Policy v1 intent: block_with_reason is reserved for SEC002+no_env and parse failures.
        # SEC001+no_env still gets preview_only (finding is visible, just not auto-applicable).
        trace = evaluate_finding_policy("F-004", _inputs(
            rule_id="SEC001", confidence=0.95, env_contract_exists=False
        ))
        assert trace.final_action == "preview_only"

    def test_sec002_missing_env_contract(self):
        trace = evaluate_finding_policy("F-005", _inputs(
            rule_id="SEC002", pattern="api_key", confidence=0.88, env_contract_exists=False
        ))
        assert trace.final_action == "block_with_reason"

    def test_sec002_with_env_contract(self):
        trace = evaluate_finding_policy("F-006", _inputs(
            rule_id="SEC002", pattern="api_key", confidence=0.88, env_contract_exists=True
        ))
        assert trace.final_action == "preview_only"

    def test_parse_invalid(self):
        trace = evaluate_finding_policy("F-007", _inputs(parse_valid=False))
        assert trace.final_action == "block_with_reason"

    def test_unknown_rule_id(self):
        # Rules outside SEC001/SEC002 get preview_only (not blocked, not auto-applied)
        trace = evaluate_finding_policy("F-008", _inputs(
            rule_id="SEC099", confidence=0.99, env_contract_exists=True
        ))
        assert trace.final_action == "preview_only"

    def test_sec001_at_0p93_with_env_and_slr_is_preview_only(self):
        # 0.93 is in the near-threshold review band (0.90–0.94) → preview_only
        trace = evaluate_finding_policy("F-009", _inputs(
            rule_id="SEC001", confidence=0.93,
            env_contract_exists=True, single_literal_replacement=True,
        ))
        assert trace.final_action == "preview_only"

    def test_sec001_at_0p94_with_env_and_slr_is_preview_then_apply(self):
        # 0.94 meets threshold + all gates pass → preview_then_apply
        trace = evaluate_finding_policy("F-010", _inputs(
            rule_id="SEC001", confidence=0.94,
            env_contract_exists=True, single_literal_replacement=True,
        ))
        assert trace.final_action == "preview_then_apply"

    def test_sec001_at_0p94_single_literal_false_is_preview_only(self):
        # confidence meets threshold but single_literal_replacement=False → preview_only
        trace = evaluate_finding_policy("F-011", _inputs(
            rule_id="SEC001", confidence=0.94,
            env_contract_exists=True, single_literal_replacement=False,
        ))
        assert trace.final_action == "preview_only"


# ---------------------------------------------------------------------------
# Gate results
# ---------------------------------------------------------------------------

class TestGateResults:
    EXPECTED_ORDER = [
        GATE_PARSE_VALID,
        GATE_CATEGORY_POLICY,
        GATE_CONFIDENCE_THRESHOLD,
        GATE_ENV_CONTRACT_PRESENT,
        GATE_SINGLE_LITERAL_REPLACEMENT,
        GATE_OVERRIDE_VALID,
    ]

    def test_gate_order_is_stable(self):
        trace = evaluate_finding_policy("G-001", _inputs())
        names = [g.gate for g in trace.gate_results]
        assert names == self.EXPECTED_ORDER

    def test_parse_invalid_stops_after_gate_1(self):
        trace = evaluate_finding_policy("G-002", _inputs(parse_valid=False))
        assert len(trace.gate_results) == 1
        assert trace.gate_results[0].gate == GATE_PARSE_VALID
        assert not trace.gate_results[0].passed

    def test_parse_valid_gate_passes(self):
        trace = evaluate_finding_policy("G-003", _inputs(parse_valid=True))
        assert _gate_passed(trace, GATE_PARSE_VALID)

    def test_confidence_gate_reflects_actual(self):
        trace = evaluate_finding_policy("G-004", _inputs(rule_id="SEC001", confidence=0.85))
        for g in trace.gate_results:
            if g.gate == GATE_CONFIDENCE_THRESHOLD:
                assert g.actual == "0.85"
                assert not g.passed
                break
        else:
            pytest.fail("confidence gate not found")

    def test_confidence_gate_passes_above_threshold(self):
        trace = evaluate_finding_policy("G-005", _inputs(rule_id="SEC001", confidence=0.95))
        assert _gate_passed(trace, GATE_CONFIDENCE_THRESHOLD)

    def test_env_gate_passes_when_present(self):
        trace = evaluate_finding_policy("G-006", _inputs(env_contract_exists=True))
        assert _gate_passed(trace, GATE_ENV_CONTRACT_PRESENT)

    def test_env_gate_fails_when_absent(self):
        trace = evaluate_finding_policy("G-007", _inputs(env_contract_exists=False))
        assert not _gate_passed(trace, GATE_ENV_CONTRACT_PRESENT)

    def test_override_gate_always_false_in_v1(self):
        trace = evaluate_finding_policy("G-008", _inputs())
        assert not _gate_passed(trace, GATE_OVERRIDE_VALID)

    def test_all_six_gates_present_for_normal_finding(self):
        trace = evaluate_finding_policy("G-009", _inputs())
        assert len(trace.gate_results) == 6


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

class TestRationale:
    def test_rationale_nonempty_preview_then_apply(self):
        trace = evaluate_finding_policy("R-001", _inputs(rule_id="SEC001", confidence=0.95))
        assert trace.rationale and len(trace.rationale) > 10

    def test_rationale_nonempty_preview_only(self):
        trace = evaluate_finding_policy("R-002", _inputs(rule_id="SEC002", env_contract_exists=True))
        assert trace.rationale and len(trace.rationale) > 10

    def test_rationale_nonempty_block(self):
        trace = evaluate_finding_policy("R-003", _inputs(rule_id="SEC002", env_contract_exists=False))
        assert trace.rationale and len(trace.rationale) > 10

    def test_rationale_nonempty_parse_invalid(self):
        trace = evaluate_finding_policy("R-004", _inputs(parse_valid=False))
        assert trace.rationale and len(trace.rationale) > 10

    def test_rationale_below_threshold_mentions_confidence(self):
        trace = evaluate_finding_policy("R-005", _inputs(rule_id="SEC001", confidence=0.80))
        assert "0.80" in trace.rationale or "confidence" in trace.rationale.lower()

    def test_rationale_review_band_is_specific(self):
        # 0.93 is in the review band → rationale must mention the band
        trace = evaluate_finding_policy("R-006", _inputs(
            rule_id="SEC001", confidence=0.93,
            env_contract_exists=True, single_literal_replacement=True,
        ))
        assert trace.final_action == "preview_only"
        assert "0.93" in trace.rationale
        assert "0.94" in trace.rationale

    def test_rationale_single_literal_false_is_specific(self):
        # single_literal_replacement=False at threshold → rationale must mention it
        trace = evaluate_finding_policy("R-007", _inputs(
            rule_id="SEC001", confidence=0.94,
            env_contract_exists=True, single_literal_replacement=False,
        ))
        assert trace.final_action == "preview_only"
        assert "literal" in trace.rationale.lower() or "complex" in trace.rationale.lower()


# ---------------------------------------------------------------------------
# Smallest unblocking action
# ---------------------------------------------------------------------------

class TestSmallestUnblockingAction:
    def test_present_when_parse_invalid(self):
        trace = evaluate_finding_policy("U-001", _inputs(parse_valid=False))
        assert trace.smallest_unblocking_action is not None
        assert "syntax" in trace.smallest_unblocking_action.lower() or "parse" in trace.smallest_unblocking_action.lower()

    def test_present_when_sec002_no_env(self):
        trace = evaluate_finding_policy("U-002", _inputs(rule_id="SEC002", env_contract_exists=False))
        assert trace.smallest_unblocking_action is not None
        assert ".env" in trace.smallest_unblocking_action

    def test_present_when_sec001_no_env(self):
        trace = evaluate_finding_policy("U-003", _inputs(rule_id="SEC001", confidence=0.95, env_contract_exists=False))
        assert trace.smallest_unblocking_action is not None

    def test_none_when_preview_then_apply(self):
        trace = evaluate_finding_policy("U-004", _inputs(rule_id="SEC001", confidence=0.95, env_contract_exists=True))
        assert trace.final_action == "preview_then_apply"
        assert trace.smallest_unblocking_action is None

    def test_present_when_below_confidence_threshold(self):
        trace = evaluate_finding_policy("U-005", _inputs(rule_id="SEC001", confidence=0.80, env_contract_exists=True))
        assert trace.smallest_unblocking_action is not None
        assert "threshold" in trace.smallest_unblocking_action.lower() or "review" in trace.smallest_unblocking_action.lower()

    def test_sec001_near_threshold_interactive_ci_true(self):
        inputs = PolicyInputs(
            file="app/config.py", line=10, rule_id="SEC001", pattern="password",
            confidence=0.92, parse_valid=True, env_contract_exists=True,
            file_type=".py", single_literal_replacement=True,
            interactive_ci=True,
        )
        trace = evaluate_finding_policy("U-006", inputs)
        assert trace.final_action == "preview_only"
        assert trace.inputs.interactive_ci is True
        assert trace.smallest_unblocking_action == "Request reviewer override token to proceed with auto-apply."

    def test_sec001_near_threshold_interactive_ci_false(self):
        inputs = PolicyInputs(
            file="app/config.py", line=10, rule_id="SEC001", pattern="password",
            confidence=0.92, parse_valid=True, env_contract_exists=True,
            file_type=".py", single_literal_replacement=True,
            interactive_ci=False,
        )
        trace = evaluate_finding_policy("U-007", inputs)
        assert trace.final_action == "preview_only"
        assert trace.inputs.interactive_ci is False
        assert trace.smallest_unblocking_action == "Keep preview_only or raise confidence via stronger signal before enabling auto-apply."


# ---------------------------------------------------------------------------
# Audit metadata
# ---------------------------------------------------------------------------

class TestAuditMetadata:
    def test_policy_version_present(self):
        trace = evaluate_finding_policy("A-001", _inputs())
        assert trace.audit.policy_version == "2026-04-22.1"

    def test_engine_version_present(self):
        trace = evaluate_finding_policy("A-002", _inputs())
        assert trace.audit.engine_version  # non-empty

    def test_evaluated_at_is_utc_iso(self):
        trace = evaluate_finding_policy("A-003", _inputs())
        ts = trace.audit.evaluated_at
        assert "T" in ts and ts.endswith("Z")

    def test_finding_id_preserved(self):
        trace = evaluate_finding_policy("UNIQUE-ID-42", _inputs())
        assert trace.finding_id == "UNIQUE-ID-42"

    def test_rule_id_preserved(self):
        trace = evaluate_finding_policy("A-004", _inputs(rule_id="SEC002"))
        assert trace.rule_id == "SEC002"


# ---------------------------------------------------------------------------
# asdict / JSON serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_asdict_produces_dict(self):
        trace = evaluate_finding_policy("S-001", _inputs())
        d = asdict(trace)
        assert isinstance(d, dict)
        assert "gate_results" in d
        assert "final_action" in d
        assert "audit" in d

    def test_gate_results_is_list_of_dicts(self):
        trace = evaluate_finding_policy("S-002", _inputs())
        d = asdict(trace)
        assert isinstance(d["gate_results"], list)
        assert all(isinstance(g, dict) for g in d["gate_results"])

    def test_json_roundtrip(self):
        trace = evaluate_finding_policy("S-003", _inputs())
        raw = json.dumps(asdict(trace))
        loaded = json.loads(raw)
        assert loaded["final_action"] in ("preview_then_apply", "preview_only", "block_with_reason")
        assert len(loaded["gate_results"]) > 0

    def test_inputs_included_in_asdict(self):
        trace = evaluate_finding_policy("S-004", _inputs(rule_id="SEC001", confidence=0.95))
        d = asdict(trace)
        assert d["inputs"]["rule_id"] == "SEC001"
        assert d["inputs"]["confidence"] == 0.95
        assert "interactive_ci" in d["inputs"]


# ---------------------------------------------------------------------------
# interactive_ci: recorded in inputs, never a gate, only wording differs
# ---------------------------------------------------------------------------

class TestInteractiveCiInTrace:
    """Verify interactive_ci is an input/context field only.

    Rules enforced:
    - Both interactive_ci values produce final_action=preview_only for 0.90–0.94.
    - smallest_unblocking_action wording differs between the two values.
    - DecisionTrace.inputs includes interactive_ci with the correct value.
    - interactive_ci never appears as a gate name.
    """

    @pytest.mark.parametrize("confidence", [0.90, 0.91, 0.92, 0.93])
    def test_final_action_preview_only_interactive_ci_false(self, confidence):
        trace = evaluate_finding_policy(
            f"IC-F-{int(confidence * 100)}",
            _inputs(
                rule_id="SEC001", confidence=confidence,
                env_contract_exists=True, single_literal_replacement=True,
                interactive_ci=False,
            ),
        )
        assert trace.final_action == "preview_only"

    @pytest.mark.parametrize("confidence", [0.90, 0.91, 0.92, 0.93])
    def test_final_action_preview_only_interactive_ci_true(self, confidence):
        trace = evaluate_finding_policy(
            f"IC-T-{int(confidence * 100)}",
            _inputs(
                rule_id="SEC001", confidence=confidence,
                env_contract_exists=True, single_literal_replacement=True,
                interactive_ci=True,
            ),
        )
        assert trace.final_action == "preview_only"

    def test_smallest_unblocking_action_differs_by_interactive_ci(self):
        base = dict(
            rule_id="SEC001", confidence=0.91,
            env_contract_exists=True, single_literal_replacement=True,
        )
        trace_f = evaluate_finding_policy("IC-diff-F", _inputs(**base, interactive_ci=False))
        trace_t = evaluate_finding_policy("IC-diff-T", _inputs(**base, interactive_ci=True))
        assert trace_f.smallest_unblocking_action != trace_t.smallest_unblocking_action

    def test_inputs_dict_includes_interactive_ci_false(self):
        trace = evaluate_finding_policy("IC-ser-F", _inputs(interactive_ci=False))
        d = asdict(trace)
        assert "interactive_ci" in d["inputs"]
        assert d["inputs"]["interactive_ci"] is False

    def test_inputs_dict_includes_interactive_ci_true(self):
        trace = evaluate_finding_policy(
            "IC-ser-T",
            _inputs(
                rule_id="SEC001", confidence=0.92,
                env_contract_exists=True, single_literal_replacement=True,
                interactive_ci=True,
            ),
        )
        d = asdict(trace)
        assert "interactive_ci" in d["inputs"]
        assert d["inputs"]["interactive_ci"] is True

    def test_interactive_ci_not_a_gate(self):
        """interactive_ci must never appear as a gate name in gate_results."""
        for ic in (False, True):
            trace = evaluate_finding_policy(
                f"IC-gate-{'T' if ic else 'F'}",
                _inputs(
                    rule_id="SEC001", confidence=0.92,
                    env_contract_exists=True, single_literal_replacement=True,
                    interactive_ci=ic,
                ),
            )
            gate_names = [g.gate for g in trace.gate_results]
            assert "interactive_ci" not in gate_names


# ---------------------------------------------------------------------------
# Integration: real scan JSON output contains decision_trace fields
# ---------------------------------------------------------------------------

AUTONOMA = [sys.executable, "-m", "autonoma"]


def _git_init(path: Path) -> None:
    """Initialize a minimal git repo so git rev-parse --show-toplevel works."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)


@pytest.fixture()
def sec001_project(tmp_path):
    _git_init(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.py").write_text("password = 'supersecret'\n")
    (tmp_path / ".env.example").write_text("PASSWORD=\n")
    return tmp_path


@pytest.fixture()
def sec002_project(tmp_path):
    _git_init(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "api.py").write_text("api_key = 'sk-live-abc123xyz456'\n")
    (tmp_path / ".env.example").write_text("API_KEY=\n")
    return tmp_path


def _run_scan(cwd: Path) -> dict:
    result = subprocess.run(
        AUTONOMA + ["scan", str(cwd / "src")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent / "src")},
    )
    return json.loads(result.stdout)


class TestIntegration:
    def test_sec001_finding_has_decision_trace(self, sec001_project):
        report = _run_scan(sec001_project)
        findings = report.get("findings", [])
        assert findings, "Expected at least one finding"
        sec001_findings = [f for f in findings if f.get("rule_id") == "SEC001"]
        assert sec001_findings, "Expected a SEC001 finding"
        trace = sec001_findings[0].get("decision_trace")
        assert trace is not None, "decision_trace missing from SEC001 finding"
        assert "final_action" in trace
        assert "gate_results" in trace
        assert "rationale" in trace
        assert "audit" in trace

    def test_sec001_full_trace_action(self, sec001_project):
        report = _run_scan(sec001_project)
        findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC001"]
        trace = findings[0]["decision_trace"]
        # With env contract present and default confidence above threshold: preview_then_apply
        assert trace["final_action"] == "preview_then_apply"

    def test_sec001_trace_has_six_gates(self, sec001_project):
        report = _run_scan(sec001_project)
        findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC001"]
        trace = findings[0]["decision_trace"]
        assert len(trace["gate_results"]) == 6

    def test_sec002_finding_has_decision_trace(self, sec002_project):
        report = _run_scan(sec002_project)
        findings = report.get("findings", [])
        sec002_findings = [f for f in findings if f.get("rule_id") == "SEC002"]
        assert sec002_findings, "Expected a SEC002 finding"
        trace = sec002_findings[0].get("decision_trace")
        assert trace is not None, "decision_trace missing from SEC002 finding"
        assert trace["final_action"] == "preview_only"  # env contract present → preview_only

    def test_sec002_no_env_contract_block(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "api.py").write_text("api_key = 'sk-live-abc123xyz456'\n")
        # No .env.example → expect block_with_reason for SEC002
        report = _run_scan(tmp_path)
        sec002_findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC002"]
        if sec002_findings:
            trace = sec002_findings[0].get("decision_trace")
            assert trace is not None
            assert trace["final_action"] == "block_with_reason"

    def test_report_schema_includes_decision_trace_key(self, sec001_project):
        """decision_trace key exists on finding objects (None or dict)."""
        report = _run_scan(sec001_project)
        for finding in report.get("findings", []):
            assert "decision_trace" in finding

    def test_decision_trace_inputs_includes_interactive_ci(self, sec001_project):
        """decision_trace.inputs must contain interactive_ci in scan output."""
        report = _run_scan(sec001_project)
        findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC001"]
        assert findings
        inputs = findings[0]["decision_trace"]["inputs"]
        assert "interactive_ci" in inputs


# ---------------------------------------------------------------------------
# Policy as single decision source: scan and fix must agree
# ---------------------------------------------------------------------------

def _run_fix(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        AUTONOMA + ["fix", str(cwd / "src"), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent / "src")},
    )


class TestSingleDecisionSource:
    def test_preview_only_fix_does_not_modify_file(self, sec002_project):
        """SEC002 with env contract → scan says preview_only → fix dry-run shows REFUSED."""
        report = _run_scan(sec002_project)
        sec002_findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC002"]
        assert sec002_findings
        assert sec002_findings[0]["decision_trace"]["final_action"] == "preview_only"

        fix_result = _run_fix(sec002_project)
        fix_data = json.loads(fix_result.stdout)
        fix_results = fix_data.get("fix_results", [])
        sec002_results = [o for o in fix_results if o.get("issue_id") == "SEC002"]
        # preview_only → policy blocks the fix → REFUSED
        assert sec002_results, "Expected at least one SEC002 fix_result"
        assert all(o["state"] == "REFUSED" for o in sec002_results), (
            f"Expected all REFUSED, got {[o['state'] for o in sec002_results]}"
        )

    def test_preview_then_apply_fix_modifies_file(self, sec001_project):
        """SEC001 above threshold + env contract → scan says preview_then_apply → fix applies."""
        report = _run_scan(sec001_project)
        sec001_findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC001"]
        assert sec001_findings
        assert sec001_findings[0]["decision_trace"]["final_action"] == "preview_then_apply"

        fix_result = _run_fix(sec001_project)
        fix_data = json.loads(fix_result.stdout)
        fix_results = fix_data.get("fix_results", [])
        sec001_results = [o for o in fix_results if o.get("issue_id") == "SEC001"]
        # preview_then_apply → fix proceeds (dry-run shows FIXED outcome)
        assert sec001_results, "Expected at least one SEC001 fix_result"
        assert all(o["state"] == "FIXED" for o in sec001_results), (
            f"Expected all FIXED, got {[o['state'] for o in sec001_results]}"
        )

    def test_scan_and_fix_decisions_match(self, sec001_project):
        """The final_action from scan matches what fix actually does."""
        scan_report = _run_scan(sec001_project)
        fix_result = _run_fix(sec001_project)
        fix_data = json.loads(fix_result.stdout)

        for finding in scan_report.get("findings", []):
            trace = finding.get("decision_trace", {})
            action = trace.get("final_action")
            rule_id = finding.get("rule_id")

            matching = [o for o in fix_data.get("fix_results", [])
                        if o.get("issue_id") == rule_id and o.get("line") == finding.get("line")]
            if not matching:
                continue

            if action == "preview_then_apply":
                assert matching[0]["state"] == "FIXED", (
                    f"scan said preview_then_apply but fix returned {matching[0]['state']}"
                )
            elif action in ("preview_only", "block_with_reason"):
                assert matching[0]["state"] == "REFUSED", (
                    f"scan said {action} but fix returned {matching[0]['state']}"
                )

    def test_scan_fix_consistency_regardless_of_env_contract(self, tmp_path):
        """Whatever scan decides, fix must agree — tests the single-decision-source property."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("password = 'supersecret'\n")

        report = _run_scan(tmp_path)
        sec001_findings = [f for f in report.get("findings", []) if f.get("rule_id") == "SEC001"]
        if not sec001_findings:
            pytest.skip("No SEC001 finding detected")

        action = sec001_findings[0]["decision_trace"]["final_action"]

        fix_result = _run_fix(tmp_path)
        fix_data = json.loads(fix_result.stdout)
        fix_results = fix_data.get("fix_results", [])
        sec001_results = [o for o in fix_results if o.get("issue_id") == "SEC001"]
        if not sec001_results:
            pytest.skip("No SEC001 fix_result")

        if action == "preview_then_apply":
            assert sec001_results[0]["state"] == "FIXED", (
                f"scan said preview_then_apply but fix returned {sec001_results[0]['state']}"
            )
        else:
            assert sec001_results[0]["state"] == "REFUSED", (
                f"scan said {action} but fix returned {sec001_results[0]['state']}"
            )


# ---------------------------------------------------------------------------
# check_env_contract() search boundary tests
# ---------------------------------------------------------------------------

class TestCheckEnvContract:
    """Verify that check_env_contract() only detects files within the project root."""

    def test_env_example_in_project_root_returns_true(self, tmp_path):
        (tmp_path / ".env.example").write_text("SECRET_KEY=\n")
        from autonoma.policy import check_env_contract
        assert check_env_contract(tmp_path) is True

    def test_no_env_file_returns_false(self, tmp_path):
        from autonoma.policy import check_env_contract
        assert check_env_contract(tmp_path) is False

    def test_env_file_in_parent_outside_project_not_detected(self, tmp_path):
        # Place .env.example in the parent, NOT in the project subdirectory.
        (tmp_path / ".env.example").write_text("SECRET_KEY=\n")
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        from autonoma.policy import check_env_contract
        # project_dir has no git root (no .git), so _find_project_root returns project_dir.
        # The parent's .env.example must NOT be found.
        assert check_env_contract(project_dir) is False

    def test_nested_project_with_own_env_contract(self, tmp_path):
        project_dir = tmp_path / "nested" / "project"
        project_dir.mkdir(parents=True)
        (project_dir / ".env.sample").write_text("DB_URL=\n")
        from autonoma.policy import check_env_contract
        assert check_env_contract(project_dir) is True

    def test_dot_env_file_also_detected(self, tmp_path):
        (tmp_path / ".env").write_text("SECRET=value\n")
        from autonoma.policy import check_env_contract
        assert check_env_contract(tmp_path) is True

    def test_nonexistent_path_returns_false(self, tmp_path):
        from autonoma.policy import check_env_contract
        assert check_env_contract(tmp_path / "does_not_exist") is False
