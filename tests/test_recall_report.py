"""
Tests for bench/scripts/recall_report.py — fingerprint-based recall matching.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Make bench/scripts importable without installing it as a package.
sys.path.insert(0, str(Path(__file__).parent.parent / "bench" / "scripts"))

from recall_report import (
    compute_fingerprint,
    diagnose,
    extract_findings_by_fingerprint,
    normalize_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp(value: str) -> str:
    """Reference fingerprint computation for test assertions."""
    if not value:
        return "sha256:e3b0c44298fc1c149afbf4c8"
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _seed_log(locations: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "rng_seed": 42,
        "manifest_seed": 1,
        "target_repo": "/tmp/repo",
        "seeded_at": "2026-01-01T00:00:00+00:00",
        "locations": locations,
    }


def _loc(
    control_id: str,
    family: str,
    file_path: str,
    expected_value: str,
    file_format: str = "python",
) -> dict:
    return {
        "control_id": control_id,
        "family": family,
        "file_path": file_path,
        "file_format": file_format,
        "var_name": "api_key",
        "expected_value": expected_value,
    }


def _findings(items: list[dict]) -> dict:
    return {"findings": items}


def _finding(file: str, fingerprint: str) -> dict:
    return {"file": file, "line": 1, "fingerprint": fingerprint, "rule_id": "SEC002"}


# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------

def test_compute_fingerprint_matches_reference():
    for value in ["sk_live_abc123", "AXIA1234567890ABCDEF", "some-token", ""]:
        assert compute_fingerprint(value) == _fp(value)


def test_compute_fingerprint_format():
    fp = compute_fingerprint("hello")
    assert fp.startswith("sha256:")
    hex_part = fp[len("sha256:"):]
    assert len(hex_part) == 24
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_compute_fingerprint_empty():
    # Empty string special-case matches SHA-256 of empty string prefix.
    assert compute_fingerprint("") == "sha256:e3b0c44298fc1c149afbf4c8"


def test_compute_fingerprint_deterministic():
    assert compute_fingerprint("abc") == compute_fingerprint("abc")


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------

def test_normalize_path_forward_slashes():
    assert normalize_path("a/b/c.py") == "a/b/c.py"


def test_normalize_path_windows_backslashes():
    assert normalize_path(".github\\workflows\\deploy.py") == ".github/workflows/deploy.py"


def test_normalize_path_strips_leading_dotslash():
    assert normalize_path("./config/secrets.py") == "config/secrets.py"


def test_normalize_path_strips_repo_root():
    assert normalize_path("/repo/src/settings.py", repo_root="/repo") == "src/settings.py"


def test_normalize_path_collapses_double_slashes():
    assert normalize_path("a//b//c.py") == "a/b/c.py"


# ---------------------------------------------------------------------------
# extract_findings_by_fingerprint
# ---------------------------------------------------------------------------

def test_extract_basic():
    fp_val = _fp("secret123")
    doc = _findings([_finding("config/settings.py", fp_val)])
    path_to_fps, fp_to_paths = extract_findings_by_fingerprint(doc)
    assert fp_val in path_to_fps.get("config/settings.py", set())
    assert "config/settings.py" in fp_to_paths.get(fp_val, set())


def test_extract_normalizes_backslash_paths():
    fp_val = _fp("secret123")
    doc = _findings([{"file": ".github\\workflows\\ci.py", "fingerprint": fp_val}])
    path_to_fps, fp_to_paths = extract_findings_by_fingerprint(doc)
    assert ".github/workflows/ci.py" in path_to_fps
    assert fp_val in path_to_fps[".github/workflows/ci.py"]


def test_extract_multiple_fps_at_same_path():
    fp1, fp2 = _fp("val1"), _fp("val2")
    doc = _findings([
        _finding("config/a.py", fp1),
        _finding("config/a.py", fp2),
    ])
    path_to_fps, _ = extract_findings_by_fingerprint(doc)
    assert {fp1, fp2} == path_to_fps["config/a.py"]


def test_extract_empty_findings():
    path_to_fps, fp_to_paths = extract_findings_by_fingerprint({"findings": []})
    assert path_to_fps == {}
    assert fp_to_paths == {}


# ---------------------------------------------------------------------------
# diagnose — MATCHED
# ---------------------------------------------------------------------------

def test_diagnose_matched():
    value = "stk_live_abc123XYZ890"
    fp = _fp(value)
    log = _seed_log([_loc("stripe_000", "stripe", "config/secrets.py", value)])
    doc = _findings([_finding("config/secrets.py", fp)])
    outcomes = diagnose(log, doc, "myrepo")
    assert len(outcomes) == 1
    assert outcomes[0].outcome == "MATCHED"
    assert outcomes[0].control_id == "stripe_000"


def test_diagnose_matched_backslash_path_in_seed_log():
    """Seed log path with backslashes should match a finding with forward slashes."""
    value = "ght_abc123XYZ890abcdef"
    fp = _fp(value)
    log = _seed_log([_loc("github_000", "github_pat", "tests\\fixtures\\cfg.py", value)])
    doc = _findings([_finding("tests/fixtures/cfg.py", fp)])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "MATCHED"


# ---------------------------------------------------------------------------
# diagnose — PATH_MISMATCH
# ---------------------------------------------------------------------------

def test_diagnose_path_mismatch():
    """Fingerprint present in findings but at a different path."""
    value = "GIZAabcdef1234567890QWERTY12345"
    fp = _fp(value)
    log = _seed_log([_loc("google_000", "google_api", "config/creds.py", value)])
    # Finding is at a different path
    doc = _findings([_finding("deploy/config.yaml", fp)])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "PATH_MISMATCH"
    assert "deploy/config.yaml" in outcomes[0].detail


def test_diagnose_path_mismatch_not_matched():
    """PATH_MISMATCH must not be reported as MATCHED."""
    value = "xotb-111111111111-222222222222-AbCdEfGhIjKlMnOpQrSt"
    fp = _fp(value)
    log = _seed_log([_loc("slack_000", "slack_bot", "scripts/notify.py", value)])
    doc = _findings([_finding("examples/notify.py", fp)])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "PATH_MISMATCH"


# ---------------------------------------------------------------------------
# diagnose — VALUE_NOT_FOUND
# ---------------------------------------------------------------------------

def test_diagnose_value_not_found():
    log = _seed_log([_loc("stripe_001", "stripe", "config/secrets.py", "stk_live_notpresent")])
    doc = _findings([_finding("config/secrets.py", _fp("completely_different_value"))])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "VALUE_NOT_FOUND"


def test_diagnose_value_not_found_empty_findings():
    log = _seed_log([_loc("stripe_002", "stripe", "config/secrets.py", "stk_live_abc")])
    outcomes = diagnose(log, {"findings": []}, "myrepo")
    assert outcomes[0].outcome == "VALUE_NOT_FOUND"


# ---------------------------------------------------------------------------
# diagnose — aws_pair (two-component fingerprints)
# ---------------------------------------------------------------------------

def test_diagnose_aws_pair_access_key_matched():
    """A hit on the access-key component fingerprint counts as MATCHED."""
    access = "AXIA1234567890ABCDEF"
    secret = "abcdefghijklmnopqrstuvwxyz012345678901234"
    combined = f"{access}|{secret}"
    fp_access = _fp(access)
    log = _seed_log([_loc("aws_000", "aws_pair", "config/aws.env", combined, "env")])
    doc = _findings([_finding("config/aws.env", fp_access)])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "MATCHED"


def test_diagnose_aws_pair_secret_key_matched():
    """A hit on the secret-key component fingerprint counts as MATCHED."""
    access = "AXIA1234567890ABCDEF"
    secret = "abcdefghijklmnopqrstuvwxyz012345678901234"
    combined = f"{access}|{secret}"
    fp_secret = _fp(secret)
    log = _seed_log([_loc("aws_001", "aws_pair", "config/aws.env", combined, "env")])
    doc = _findings([_finding("config/aws.env", fp_secret)])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "MATCHED"


def test_diagnose_aws_pair_both_components_matched():
    """Both access and secret fingerprints at the same path → MATCHED."""
    access = "AXIA1234567890ABCDEF"
    secret = "abcdefghijklmnopqrstuvwxyz012345678901234"
    combined = f"{access}|{secret}"
    log = _seed_log([_loc("aws_002", "aws_pair", "config/aws.env", combined, "env")])
    doc = _findings([
        _finding("config/aws.env", _fp(access)),
        _finding("config/aws.env", _fp(secret)),
    ])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "MATCHED"


def test_diagnose_aws_pair_path_mismatch():
    """aws_pair component fingerprint found but at wrong path → PATH_MISMATCH."""
    access = "AXIA1234567890ABCDEF"
    secret = "abcdefghijklmnopqrstuvwxyz012345678901234"
    combined = f"{access}|{secret}"
    log = _seed_log([_loc("aws_003", "aws_pair", "config/aws.env", combined, "env")])
    doc = _findings([_finding("deploy/aws.env", _fp(access))])
    outcomes = diagnose(log, doc, "myrepo")
    assert outcomes[0].outcome == "PATH_MISMATCH"


def test_diagnose_aws_pair_not_found():
    access = "AXIA1234567890ABCDEF"
    secret = "abcdefghijklmnopqrstuvwxyz012345678901234"
    combined = f"{access}|{secret}"
    log = _seed_log([_loc("aws_004", "aws_pair", "config/aws.env", combined, "env")])
    outcomes = diagnose(log, {"findings": []}, "myrepo")
    assert outcomes[0].outcome == "VALUE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Regression: detect-only JSON paths must use forward slashes
# ---------------------------------------------------------------------------

def _env():
    e = os.environ.copy()
    e["PYTHONPATH"] = "src"
    return e


def test_detect_only_json_paths_use_forward_slashes(tmp_path):
    """Detect-only scan output must emit forward-slash paths even on Windows."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    secret_file = subdir / "settings.py"
    secret_file.write_text("password = 'supersecret'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PASSWORD=\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "autonoma.cli", "scan", str(tmp_path)],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(Path(__file__).parent.parent),
    )

    data = json.loads(result.stdout)
    for finding in data.get("findings", []):
        assert "\\" not in finding["file"], (
            f"Finding path contains backslash: {finding['file']!r}"
        )
