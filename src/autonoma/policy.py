"""
Autonoma — Policy Layer v1.5

Separates detection from decision from execution.
Each finding is evaluated through an explicit gate sequence and receives
a structured DecisionTrace documenting inputs, gate results, and final action.

Scope: SEC001 and SEC002 only.
Does not modify files; produces decision records only.

Policy version: 2026-04-22.1
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import __version__

POLICY_VERSION = "2026-04-22.1"

# Minimum confidence for SEC001 to qualify for preview_then_apply.
# 0.90–0.94 is the near-threshold review band: routes to preview_only.
# SEC002 is capped at preview_only regardless of confidence.
SEC001_CONFIDENCE_THRESHOLD = 0.94

# Gate names (stable identifiers — do not rename without versioning policy)
GATE_PARSE_VALID = "parse_valid"
GATE_CATEGORY_POLICY = "category_policy"
GATE_CONFIDENCE_THRESHOLD = "confidence_threshold"
GATE_ENV_CONTRACT_PRESENT = "env_contract_present"
GATE_SINGLE_LITERAL_REPLACEMENT = "single_literal_replacement"
GATE_OVERRIDE_VALID = "override_valid"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class OverrideToken:
    """Represents a human-approved override token. Stubbed in v1."""
    present: bool = False
    id: Optional[str] = None
    actor: Optional[str] = None
    expires_at: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class PolicyInputs:
    """Normalised inputs fed into the policy evaluator for a single finding."""
    file: str
    line: int
    rule_id: str           # "SEC001" | "SEC002"
    pattern: str           # pattern_type e.g. "password", "api_key", "token"
    confidence: float      # 0.0–1.0, derived from heuristic signal strength
    parse_valid: bool      # True if file was successfully parsed before reaching this finding
    env_contract_exists: bool  # True if .env.example / .env / .env.sample found in repo
    file_type: str         # file extension e.g. ".py"
    single_literal_replacement: bool = True  # True if fix replaces exactly one simple string literal
    override_token: OverrideToken = field(default_factory=OverrideToken)
    interactive_ci: bool = False  # True when running in an interactive CI environment


@dataclass
class GateResult:
    """Result of a single policy gate evaluation."""
    gate: str
    passed: bool
    evidence: str
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class DecisionAudit:
    """Audit metadata attached to every decision trace."""
    policy_version: str
    engine_version: str
    evaluated_at: str   # UTC ISO-8601


@dataclass
class DecisionTrace:
    """
    Complete, structured record of the policy decision for one finding.

    final_action values:
      "preview_then_apply"  — safe to auto-fix (maps to fixer FIXED path)
      "preview_only"        — show finding but do not auto-apply
      "block_with_reason"   — no fix; caller must address the stated blocker
    """
    finding_id: str
    rule_id: str
    inputs: PolicyInputs
    gate_results: List[GateResult]
    final_action: str
    rationale: str
    smallest_unblocking_action: Optional[str]
    audit: DecisionAudit


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

# Maximum number of directory levels start may sit below the git root.
# Prevents home-directory or system-wide git repos from being treated as
# the project root when scanning temp directories or deep system paths.
_MAX_GIT_ROOT_DEPTH = 3


def _find_project_root(start: Path) -> Path:
    """Return the git root if start is inside a repo and close to it.

    Falls back to start on any failure: git not installed, non-zero exit,
    the returned root not being a genuine ancestor of start, or start
    being more than _MAX_GIT_ROOT_DEPTH levels below the root (which
    indicates an unrelated system-level repo such as a home directory).
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            root = Path(result.stdout.strip())
            try:
                rel = start.resolve().relative_to(root.resolve())
                if len(rel.parts) <= _MAX_GIT_ROOT_DEPTH:
                    return root
            except ValueError:
                pass
    except Exception:
        pass
    return start


def check_env_contract(repo_path: Path) -> bool:
    """Return True if an env contract file exists within the project root.

    Search boundary: only the project root directory itself (not parent dirs).
    Project root is determined by git rev-parse --show-toplevel, falling back
    to repo_path. This prevents false positives from .env files outside the project.
    """
    if not repo_path or not repo_path.exists():
        return False
    try:
        candidates = ('.env', '.env.example', '.env.sample', '.env.local')
        search = repo_path if repo_path.is_dir() else repo_path.parent
        project_root = _find_project_root(search)
        # Only check within the project root — never above it
        for name in candidates:
            if (project_root / name).exists():
                return True
    except Exception:
        pass
    return False


def default_confidence(rule_id: str, pattern_type: str) -> float:
    """
    Return an implicit confidence score for a finding.

    Values are derived from how specific the detection heuristics are.
    SEC001 (password) patterns are highly specific and score above the 0.92 threshold.
    SEC002 patterns are somewhat noisier and score below it, but SEC002 has no
    auto-apply path in policy v1 regardless of confidence.
    """
    if rule_id == "SEC001":
        if pattern_type == "passwd":
            return 0.93   # abbreviated form (passwd/pwd) — slightly less specific, still above threshold
        return 0.95   # full 'password' keyword — highly specific
    if rule_id == "SEC002":
        if pattern_type == "api_key":
            return 0.88
        return 0.87   # token/secret patterns can match broader variable names
    return 0.80


def _smallest_unblocking_action(inputs: PolicyInputs) -> Optional[str]:
    """Return the minimal deterministic step that would unblock remediation."""
    if not inputs.parse_valid:
        return "Fix syntax errors so Autonoma can parse the file safely."
    if not inputs.env_contract_exists:
        if inputs.rule_id == "SEC002":
            return (
                "Define the API key destination in .env.example: "
                "add an entry with the variable name, scope, and load path."
            )
        return "Declare the env variable destination in .env.example (e.g., PASSWORD=)."
    if inputs.rule_id == "SEC001" and not inputs.single_literal_replacement:
        return (
            "Refactor the assignment to a single string literal so Autonoma can safely rewrite it."
        )
    if inputs.rule_id == "SEC001" and 0.90 <= inputs.confidence < SEC001_CONFIDENCE_THRESHOLD:
        if inputs.interactive_ci:
            return "Request reviewer override token to proceed with auto-apply."
        return "Keep preview_only or raise confidence via stronger signal before enabling auto-apply."
    if inputs.confidence < SEC001_CONFIDENCE_THRESHOLD:
        return (
            "Review finding manually, or lower the confidence threshold "
            "via a configurable policy layer in a future release."
        )
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Policy evaluator
# ---------------------------------------------------------------------------

def evaluate_finding_policy(finding_id: str, inputs: PolicyInputs) -> DecisionTrace:
    """
    Evaluate policy gates for a single finding and return a full DecisionTrace.

    Gate sequence (in order):
      1. parse_valid                — can the file be safely rewritten?
      2. category_policy            — is this rule in the supported remediation scope?
      3. confidence_threshold       — is signal strength above the auto-apply bar?
      4. env_contract_present       — is there a safe destination for the secret?
      5. single_literal_replacement — is the fix a single deterministic literal rewrite?
      6. override_valid             — is there a valid human-approved override? (stubbed v1)

    SEC001 confidence bands:
      confidence >= 0.94            → eligible for preview_then_apply (all other gates must pass)
      0.90 <= confidence < 0.94     → preview_only (near-threshold review band)
      confidence < 0.90             → preview_only

    final_action mapping:
      parse invalid                                                  → block_with_reason
      SEC002 + no env contract                                       → block_with_reason
      SEC001 + confidence >= 0.94 + env + single_literal_replacement → preview_then_apply
      all other combinations                                         → preview_only
    """
    audit = DecisionAudit(
        policy_version=POLICY_VERSION,
        engine_version=__version__,
        evaluated_at=_utc_now(),
    )
    gates: List[GateResult] = []

    # ── Gate 1: parse_valid ──────────────────────────────────────────────
    g_parse = inputs.parse_valid
    gates.append(GateResult(
        gate=GATE_PARSE_VALID,
        passed=g_parse,
        evidence=(
            "File was successfully parsed prior to reaching this finding."
            if g_parse else
            "File could not be parsed by the AST engine."
        ),
    ))
    if not g_parse:
        return DecisionTrace(
            finding_id=finding_id,
            rule_id=inputs.rule_id,
            inputs=inputs,
            gate_results=gates,
            final_action="block_with_reason",
            rationale="Parse failed, so safe structural rewrite cannot be proven.",
            smallest_unblocking_action=_smallest_unblocking_action(inputs),
            audit=audit,
        )

    # ── Gate 2: category_policy ──────────────────────────────────────────
    is_sec001 = inputs.rule_id == "SEC001"
    is_sec002 = inputs.rule_id == "SEC002"
    g_cat = is_sec001 or is_sec002
    gates.append(GateResult(
        gate=GATE_CATEGORY_POLICY,
        passed=g_cat,
        evidence=(
            f"{inputs.rule_id}: qualifies for deterministic env replacement."
            if is_sec001 else
            f"{inputs.rule_id}: in scope for detection and preview; not auto-applied in policy v1."
            if is_sec002 else
            f"{inputs.rule_id}: outside remediation scope."
        ),
    ))

    # ── Gate 3: confidence_threshold ─────────────────────────────────────
    threshold = SEC001_CONFIDENCE_THRESHOLD if is_sec001 else 0.0
    g_conf = inputs.confidence >= threshold
    gates.append(GateResult(
        gate=GATE_CONFIDENCE_THRESHOLD,
        passed=g_conf,
        evidence=(
            f"confidence {inputs.confidence:.2f} "
            f"{'≥' if g_conf else '<'} threshold {threshold:.2f}"
        ),
        expected=f">={threshold:.2f}",
        actual=f"{inputs.confidence:.2f}",
    ))

    # ── Gate 4: env_contract_present ─────────────────────────────────────
    g_env = inputs.env_contract_exists
    gates.append(GateResult(
        gate=GATE_ENV_CONTRACT_PRESENT,
        passed=g_env,
        evidence=(
            "Env contract file (.env.example or equivalent) found in repo."
            if g_env else
            "No env contract file found; cannot derive safe destination variable."
        ),
    ))

    # ── Gate 5: single_literal_replacement ───────────────────────────────
    g_slr = inputs.single_literal_replacement
    gates.append(GateResult(
        gate=GATE_SINGLE_LITERAL_REPLACEMENT,
        passed=g_slr,
        evidence=(
            "Fix replaces exactly one simple string literal (deterministic rewrite)."
            if g_slr else
            "Fix involves a complex expression (f-string, concatenation, or multi-step); "
            "single literal replacement not guaranteed."
        ),
    ))

    # ── Gate 6: override_valid (stub) ────────────────────────────────────
    g_override = inputs.override_token.present
    gates.append(GateResult(
        gate=GATE_OVERRIDE_VALID,
        passed=g_override,
        evidence="No override token present. Override evaluation stubbed in policy v1.",
    ))

    # ── Final action ─────────────────────────────────────────────────────
    if is_sec002 and not g_env:
        return DecisionTrace(
            finding_id=finding_id,
            rule_id=inputs.rule_id,
            inputs=inputs,
            gate_results=gates,
            final_action="block_with_reason",
            rationale=(
                "Secret detected, but no safe destination contract exists for remediation."
            ),
            smallest_unblocking_action=_smallest_unblocking_action(inputs),
            audit=audit,
        )

    if is_sec001 and g_conf and g_env and g_slr:
        return DecisionTrace(
            finding_id=finding_id,
            rule_id=inputs.rule_id,
            inputs=inputs,
            gate_results=gates,
            final_action="preview_then_apply",
            rationale=(
                "High-confidence SEC001 with deterministic env replacement, "
                "single literal rewrite, and valid destination contract."
            ),
            smallest_unblocking_action=None,
            audit=audit,
        )

    # preview_only — determine rationale from which gate limited the action
    if is_sec002 and g_env:
        rationale = (
            "SEC002 findings qualify for preview only, not auto-apply, in policy v1."
        )
    elif not g_conf:
        if inputs.confidence >= 0.90:
            rationale = (
                f"Confidence {inputs.confidence:.2f} is in the near-threshold review band "
                f"(0.90\u2013{threshold:.2f}); auto-apply requires confidence \u2265 {threshold:.2f}."
            )
        else:
            rationale = (
                f"Confidence {inputs.confidence:.2f} is below the {threshold:.2f} "
                f"auto-apply threshold; review manually or adjust threshold in a future "
                f"configurable policy layer."
            )
    elif not g_env:
        rationale = (
            "Env contract absent; finding is visible but cannot be automatically remediated."
        )
    elif not g_slr:
        rationale = (
            "SEC001 requires a single literal replacement for auto-apply; "
            "this finding involves a complex expression and cannot be deterministically rewritten."
        )
    else:
        rationale = (
            f"{inputs.rule_id} does not satisfy all conditions for auto-apply "
            f"in policy v1."
        )

    return DecisionTrace(
        finding_id=finding_id,
        rule_id=inputs.rule_id,
        inputs=inputs,
        gate_results=gates,
        final_action="preview_only",
        rationale=rationale,
        smallest_unblocking_action=_smallest_unblocking_action(inputs),
        audit=audit,
    )
