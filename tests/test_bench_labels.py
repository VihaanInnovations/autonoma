"""
Tests for benchmark label integrity.

Verifies that compute_precision.py:
- never uses suggested_label as ground truth
- uses human_label for precision
- skips UNKNOWN and REVIEW rows
- never treats TP_CANDIDATE as a true positive
"""
import csv
import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BENCH_DIR = Path(__file__).parent.parent / "bench"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def compute():
    return _load_module("compute_precision", BENCH_DIR / "compute_precision.py")


@pytest.fixture()
def suggest():
    return _load_module("suggest_labels", BENCH_DIR / "suggest_labels.py")


def _write_csv(tmp_path: Path, rows: list[dict], filename: str = "findings.csv") -> Path:
    if not rows:
        raise ValueError("rows must not be empty")
    fieldnames = list(rows[0].keys())
    p = tmp_path / filename
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return p


# ---------------------------------------------------------------------------
# Test: suggested_label is ignored by compute_precision — never treated as TP
# ---------------------------------------------------------------------------

def test_suggested_label_ignored(tmp_path, compute, monkeypatch):
    """Rows with only suggested_label=TP_CANDIDATE and no human_label are skipped."""
    rows = [
        {
            "repo": "testrepo", "file": "a.py", "line": "1",
            "rule_id": "SEC002", "severity": "high",
            "matched_value": "SomeHighEntropyValue1234",
            "line_context": "api_key = 'SomeHighEntropyValue1234'",
            "suggested_label": "TP_CANDIDATE",
            "suggestion_confidence": "low",
            "suggestion_reason": "high_entropy_candidate",
            "human_label": "",
            "review_notes": "",
            "reviewer": "",
        }
    ]
    csv_path = _write_csv(tmp_path, rows)
    monkeypatch.setattr(sys, "argv", ["compute_precision.py", str(csv_path)])

    # Reload module so argv takes effect
    mod = _load_module("compute_precision", BENCH_DIR / "compute_precision.py")

    captured = io.StringIO()
    with patch("builtins.print", lambda *a, **kw: captured.write(" ".join(str(x) for x in a) + "\n")):
        try:
            mod.main()
        except SystemExit:
            pass

    output = captured.getvalue()
    assert "True Positives: 0" in output or "True Positives:** 0" in output
    assert "TP_CANDIDATE" not in output or "ignored" in output.lower()


# ---------------------------------------------------------------------------
# Test: human_label drives precision
# ---------------------------------------------------------------------------

def test_human_label_used_for_precision(tmp_path, monkeypatch):
    """TP_REAL and FP_DOC in human_label produce correct TP/FP counts."""
    rows = [
        {
            "repo": "r", "file": "main.py", "line": "1",
            "rule_id": "SEC001", "severity": "high",
            "matched_value": "hunter2",
            "line_context": "password = 'hunter2'",
            "suggested_label": "REVIEW",
            "suggestion_confidence": "low",
            "suggestion_reason": "needs_human_review",
            "human_label": "TP_REAL",
            "review_notes": "",
            "reviewer": "alice",
        },
        {
            "repo": "r", "file": "docs/example.py", "line": "5",
            "rule_id": "SEC001", "severity": "high",
            "matched_value": "examplepass",
            "line_context": "password = 'examplepass'",
            "suggested_label": "FP_DOC",
            "suggestion_confidence": "medium",
            "suggestion_reason": "docs_path_marker",
            "human_label": "FP_DOC",
            "review_notes": "",
            "reviewer": "alice",
        },
    ]
    csv_path = _write_csv(tmp_path, rows)
    monkeypatch.setattr(sys, "argv", ["compute_precision.py", str(csv_path)])

    mod = _load_module("compute_precision", BENCH_DIR / "compute_precision.py")

    captured = io.StringIO()
    with patch("builtins.print", lambda *a, **kw: captured.write(" ".join(str(x) for x in a) + "\n")):
        try:
            mod.main()
        except SystemExit:
            pass

    output = captured.getvalue()
    assert "True Positives:** 1" in output or "True Positives: 1" in output
    assert "False Positives:** 1" in output or "False Positives: 1" in output
    assert "50.0%" in output


# ---------------------------------------------------------------------------
# Test: UNKNOWN and REVIEW rows are skipped
# ---------------------------------------------------------------------------

def test_unknown_and_review_skipped(tmp_path, monkeypatch):
    """Rows with UNKNOWN or REVIEW human_label are not counted as TP or FP."""
    rows = [
        {
            "repo": "r", "file": "a.py", "line": "1",
            "rule_id": "SEC002", "severity": "high",
            "matched_value": "abc123",
            "line_context": "key = 'abc123'",
            "suggested_label": "REVIEW",
            "suggestion_confidence": "low",
            "suggestion_reason": "needs_human_review",
            "human_label": "UNKNOWN",
            "review_notes": "",
            "reviewer": "",
        },
        {
            "repo": "r", "file": "b.py", "line": "2",
            "rule_id": "SEC002", "severity": "high",
            "matched_value": "xyz987",
            "line_context": "token = 'xyz987'",
            "suggested_label": "TP_CANDIDATE",
            "suggestion_confidence": "low",
            "suggestion_reason": "high_entropy_candidate",
            "human_label": "REVIEW",
            "review_notes": "needs more context",
            "reviewer": "",
        },
    ]
    csv_path = _write_csv(tmp_path, rows)
    monkeypatch.setattr(sys, "argv", ["compute_precision.py", str(csv_path)])

    mod = _load_module("compute_precision", BENCH_DIR / "compute_precision.py")

    captured = io.StringIO()
    with patch("builtins.print", lambda *a, **kw: captured.write(" ".join(str(x) for x in a) + "\n")):
        try:
            mod.main()
        except SystemExit:
            pass

    output = captured.getvalue()
    assert "True Positives:** 0" in output or "True Positives: 0" in output
    assert "False Positives:** 0" in output or "False Positives: 0" in output
    assert "Classified:** 0" in output or "Classified: 0" in output


# ---------------------------------------------------------------------------
# Test: TP_CANDIDATE is never treated as TP
# ---------------------------------------------------------------------------

def test_tp_candidate_never_tp(compute):
    """parse_label must return not-TP for TP_CANDIDATE."""
    is_tp, is_fp, _ = compute.parse_label("TP_CANDIDATE")
    assert is_tp is None, "TP_CANDIDATE must not be counted as a true positive"
    assert is_fp is None, "TP_CANDIDATE must be skipped entirely"


# ---------------------------------------------------------------------------
# Test: suggest_labels output never writes to findings_classified.csv
# ---------------------------------------------------------------------------

def test_suggest_labels_output_path(suggest):
    """suggest_labels must write to findings_suggested.csv, not findings_classified.csv."""
    assert suggest.OUTPUT_CSV.name == "findings_suggested.csv"
    assert suggest.INPUT_CSV.name == "findings_full.csv"


# ---------------------------------------------------------------------------
# Test: suggest labels heuristics return structured results
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row,expected_label", [
    (
        {"file": "a.py", "line_context": "${{ secrets.API_KEY }}", "matched_value": "somevalue"},
        "FP_GHA",
    ),
    (
        {"file": "a.py", "line_context": "__author__ = 'alice'", "matched_value": "alice"},
        "FP_DUNDER",
    ),
    (
        {"file": "tests/test_auth.py", "line_context": "password = 'test'", "matched_value": "test"},
        "FP_TEST",
    ),
    (
        {"file": "docs/tutorial.py", "line_context": "api_key = 'example'", "matched_value": "example"},
        "FP_DOC",
    ),
    (
        {"file": "a.py", "line_context": "key = 'placeholder'", "matched_value": "placeholder"},
        "FP_PLACEHOLDER",
    ),
    (
        {"file": "a.py", "line_context": "key = 'ab'", "matched_value": "ab"},
        "FP_PLACEHOLDER",
    ),
    (
        {"file": "a.py", "line_context": "key = 'abc'", "matched_value": "abc"},
        "FP_PATTERN",
    ),
])
def test_suggest_heuristics(suggest, row, expected_label):
    label, confidence, reason = suggest.suggest(row)
    assert label == expected_label, f"Expected {expected_label}, got {label} for row {row}"
    assert confidence in {"high", "medium", "low"}
    assert reason
