"""
Tests for bench/scripts/precision_sample.py.

Covers:
- deterministic sampling (same seed → identical ordering)
- seed reproducibility (different seed → different ordering)
- duplicate prevention
- deterministic ordering before dedup (input-order independence)
- preview redaction (NEVER emits raw secrets)
- synthetic flag preservation
- strict CSV boolean parsing (Phase 1 hardening)
- malformed synthetic field exclusion (Phase 3 hardening)
"""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "bench" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ps():
    return _load("precision_sample", SCRIPTS_DIR / "precision_sample.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_ROWS = [
    {
        "repo": "flask",
        "file": f"src/file_{i}.py",
        "line": str(i),
        "rule_id": "SEC002",
        "matched_value": f"ghp_{'A' * 36}{i:04d}",
        "surrounding_context": f"context for row {i}",
        "synthetic": "false",
    }
    for i in range(50)
]

_SYNTHETIC_ROWS = [
    {
        "repo": "flask",
        "file": "tests/fixtures.py",
        "line": "10",
        "rule_id": "SEC002",
        "matched_value": "ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE0000",
        "surrounding_context": "# synthetic: true",
        "synthetic": "true",
    }
]


def _write_csv(tmp_path: Path, rows: list[dict], name: str = "findings.csv") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    if not rows:
        return p
    fieldnames = list(rows[0].keys())
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return p


def _run_sample(ps, tmp_path, rows, seed=42, size=20, repos=None, expect_rc=0):
    """Helper: write rows to CSV, run sample, return output rows."""
    csv_path = _write_csv(tmp_path, rows)
    out_path = tmp_path / "out.csv"
    argv = [
        "--input", str(csv_path),
        "--seed", str(seed),
        "--size", str(size),
        "--out", str(out_path),
    ]
    if repos:
        argv += ["--repo"] + repos
    rc = ps.main(argv)
    assert rc == expect_rc, f"main() returned {rc}, expected {expect_rc}"
    if rc != 0:
        return []
    with open(out_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Deterministic sampling
# ---------------------------------------------------------------------------

def test_same_seed_identical_ordering(tmp_path, ps):
    rows_a = _run_sample(ps, tmp_path / "a", _SAMPLE_ROWS, seed=7, size=30)
    rows_b = _run_sample(ps, tmp_path / "b", _SAMPLE_ROWS, seed=7, size=30)
    ids_a = [r["finding_id"] for r in rows_a]
    ids_b = [r["finding_id"] for r in rows_b]
    assert ids_a == ids_b, "Same seed must produce identical ordering"


def test_different_seed_different_ordering(tmp_path, ps):
    rows_a = _run_sample(ps, tmp_path / "a", _SAMPLE_ROWS, seed=1, size=30)
    rows_b = _run_sample(ps, tmp_path / "b", _SAMPLE_ROWS, seed=2, size=30)
    ids_a = [r["finding_id"] for r in rows_a]
    ids_b = [r["finding_id"] for r in rows_b]
    assert ids_a != ids_b, "Different seeds should produce different orderings"


def test_sample_size_respected(tmp_path, ps):
    rows = _run_sample(ps, tmp_path, _SAMPLE_ROWS, seed=42, size=15)
    assert len(rows) == 15


def test_sample_size_capped_at_available(tmp_path, ps):
    rows = _run_sample(ps, tmp_path, _SAMPLE_ROWS[:5], seed=42, size=100)
    assert len(rows) == 5, "Cannot sample more than available unique findings"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_duplicate_prevention(tmp_path, ps):
    dup = _SAMPLE_ROWS[:5] * 4  # 20 rows, only 5 unique
    rows = _run_sample(ps, tmp_path, dup, seed=42, size=100)
    assert len(rows) == 5, "Duplicates must be removed before sampling"
    ids = [r["finding_id"] for r in rows]
    assert len(ids) == len(set(ids)), "Each output row must have a unique finding_id"


def test_dedup_preserves_first_occurrence(tmp_path, ps):
    base = {
        "repo": "flask",
        "file": "src/auth.py",
        "line": "42",
        "rule_id": "SEC002",
        "matched_value": "ghp_FIRST" + "A" * 32,
        "surrounding_context": "first",
        "synthetic": "false",
    }
    duplicate = dict(base, matched_value="ghp_SECOND" + "B" * 32, surrounding_context="second")
    rows = _run_sample(ps, tmp_path, [base, duplicate], seed=42, size=10)
    assert len(rows) == 1
    assert rows[0]["surrounding_context"] == "first"


# ---------------------------------------------------------------------------
# PHASE 2: Deterministic ordering before dedup
# ---------------------------------------------------------------------------

def test_dedup_independent_of_input_order(tmp_path, ps):
    """Same rows in different input orders must produce identical sampled output.

    This test verifies that rows are sorted by stable keys BEFORE deduplication,
    so 'first occurrence wins' is deterministic regardless of load order.
    """
    base_rows = [
        {
            "repo": "flask",
            "file": f"src/f{i}.py",
            "line": str(i * 10),
            "rule_id": "SEC002",
            "matched_value": f"ghp_{'B' * 36}{i:04d}",
            "surrounding_context": f"ctx {i}",
            "synthetic": "false",
        }
        for i in range(10)
    ]
    # Provide first ordering
    rows_fwd = _run_sample(ps, tmp_path / "fwd", base_rows, seed=5, size=10)
    # Provide same rows in reverse order
    rows_rev = _run_sample(ps, tmp_path / "rev", list(reversed(base_rows)), seed=5, size=10)

    ids_fwd = [r["finding_id"] for r in rows_fwd]
    ids_rev = [r["finding_id"] for r in rows_rev]
    assert ids_fwd == ids_rev, (
        "Sampling must be independent of input row order. "
        f"fwd={ids_fwd}, rev={ids_rev}"
    )


def test_dedup_with_duplicates_input_order_independent(tmp_path, ps):
    """When duplicates exist, result must not depend on which duplicate comes first.

    The sort key includes matched_value as a tiebreaker so that rows with the
    same (repo, file, line, rule_id) but different content resolve deterministically.
    The lexicographically smaller matched_value wins.
    """
    row_a = {
        "repo": "flask",
        "file": "src/x.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_AAAA" + "A" * 32,  # lex-smaller -> always wins
        "surrounding_context": "version A",
        "synthetic": "false",
    }
    row_b = dict(row_a, matched_value="ghp_BBBB" + "B" * 32, surrounding_context="version B")

    out_ab = _run_sample(ps, tmp_path / "ab", [row_a, row_b], seed=42, size=10)
    out_ba = _run_sample(ps, tmp_path / "ba", [row_b, row_a], seed=42, size=10)

    assert len(out_ab) == 1
    assert len(out_ba) == 1
    # Both must resolve to the same finding
    assert out_ab[0]["finding_id"] == out_ba[0]["finding_id"]
    # Content must also be identical (matched_value tiebreaker makes it deterministic)
    assert out_ab[0]["surrounding_context"] == out_ba[0]["surrounding_context"], (
        "Dedup must produce identical content regardless of input order; "
        "matched_value tiebreaker selects the lex-smaller value's row."
    )


# ---------------------------------------------------------------------------
# PHASE 1: Strict CSV boolean parsing
# ---------------------------------------------------------------------------

def test_strict_bool_true_lowercase(ps):
    val, err = ps.parse_synthetic_strict("true")
    assert val is True
    assert err is None


def test_strict_bool_false_lowercase(ps):
    val, err = ps.parse_synthetic_strict("false")
    assert val is False
    assert err is None


def test_strict_bool_TRUE_uppercase(ps):
    """'TRUE' must be accepted (case-insensitive)."""
    val, err = ps.parse_synthetic_strict("TRUE")
    assert val is True
    assert err is None


def test_strict_bool_False_mixed_case(ps):
    """'False' (Python repr) must map to False — NOT silently treated as True.

    Python's bool('False') == True is the truthiness bug this prevents.
    Strict case-insensitive comparison: 'False'.lower() == 'false' -> False.
    """
    val, err = ps.parse_synthetic_strict("False")
    assert val is False, (
        "Strict parsing must handle 'False' as false, not as Python truthiness True"
    )
    assert err is None


def test_strict_bool_yes_is_malformed(ps):
    """'yes' must be rejected — not silently coerced to True."""
    val, err = ps.parse_synthetic_strict("yes")
    assert val is None
    assert err is not None


def test_strict_bool_empty_is_malformed(ps):
    """Empty string must be rejected — not silently coerced to False."""
    val, err = ps.parse_synthetic_strict("")
    assert val is None
    assert err is not None


def test_strict_bool_one_is_malformed(ps):
    """'1' must be rejected — not silently coerced to True."""
    val, err = ps.parse_synthetic_strict("1")
    assert val is None
    assert err is not None


def test_strict_bool_zero_is_malformed(ps):
    val, err = ps.parse_synthetic_strict("0")
    assert val is None
    assert err is not None


def test_strict_bool_whitespace_trimmed(ps):
    """Leading/trailing whitespace must be trimmed before comparison."""
    val, err = ps.parse_synthetic_strict("  true  ")
    assert val is True
    assert err is None


def test_strict_bool_arbitrary_string_malformed(ps):
    val, err = ps.parse_synthetic_strict("maybe")
    assert val is None
    assert err is not None


# ---------------------------------------------------------------------------
# PHASE 2 hardening: missing column and JSON null synthetic handling
# ---------------------------------------------------------------------------

def test_missing_synthetic_column_malformed(ps):
    """Row without a synthetic key (column absent from CSV) must be malformed."""
    row = {
        "repo": "flask",
        "file": "src/auth.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_" + "X" * 36,
        "surrounding_context": "",
        # "synthetic" key deliberately absent
    }
    result = ps.normalise(row)
    assert result["malformed"] is True, (
        "Missing synthetic column must be treated as malformed"
    )
    assert result["malformed_reason"] != ""


def test_json_null_synthetic_malformed(ps):
    """JSON synthetic: null (Python None) must be treated as malformed."""
    row = {
        "repo": "flask",
        "file": "src/auth.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_" + "X" * 36,
        "surrounding_context": "",
        "synthetic": None,  # JSON null -> Python None
    }
    result = ps.normalise(row)
    assert result["malformed"] is True, (
        "JSON null synthetic must be treated as malformed"
    )


def test_missing_synthetic_column_excluded_from_sample(tmp_path, ps):
    """CSV without a synthetic column must cause all rows to be excluded (non-zero exit)."""
    import csv as _csv
    csv_path = tmp_path / "no_synthetic_col.csv"
    fieldnames = ["repo", "file", "line", "rule_id", "matched_value", "surrounding_context"]
    rows = [
        {"repo": "flask", "file": "src/auth.py", "line": "1",
         "rule_id": "SEC002", "matched_value": "ghp_" + "X" * 36,
         "surrounding_context": ""},
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    out_path = tmp_path / "out.csv"
    rc = ps.main(["--input", str(csv_path), "--seed", "42", "--size", "10",
                  "--out", str(out_path)])
    assert rc != 0, "All rows malformed (no synthetic column) must return non-zero"


# ---------------------------------------------------------------------------
# PHASE 3: Malformed synthetic field exclusion
# ---------------------------------------------------------------------------

def test_malformed_synthetic_row_excluded(tmp_path, ps):
    """A row with an unrecognised synthetic field must be excluded from the sample."""
    bad_row = {
        "repo": "flask",
        "file": "src/auth.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_" + "X" * 36,
        "surrounding_context": "",
        "synthetic": "yes",  # not 'true' or 'false' -> malformed
    }
    good_row = dict(bad_row, file="src/good.py", line="2", synthetic="false")
    rows = _run_sample(ps, tmp_path, [bad_row, good_row], seed=42, size=10)
    # Only the good row should appear
    assert len(rows) == 1
    assert rows[0]["file"] == "src/good.py"


def test_malformed_empty_synthetic_excluded(tmp_path, ps):
    """Empty synthetic field is malformed and must be excluded."""
    bad_row = {
        "repo": "flask",
        "file": "src/empty_synth.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_" + "E" * 36,
        "surrounding_context": "",
        "synthetic": "",  # malformed
    }
    good_row = dict(bad_row, file="src/good.py", line="2", synthetic="false")
    rows = _run_sample(ps, tmp_path, [bad_row, good_row], seed=42, size=10)
    assert len(rows) == 1
    assert rows[0]["file"] == "src/good.py"


def test_all_malformed_returns_error(tmp_path, ps):
    """If every row is malformed, main() must return non-zero."""
    bad_rows = [
        {
            "repo": "flask",
            "file": f"src/bad_{i}.py",
            "line": str(i),
            "rule_id": "SEC002",
            "matched_value": "ghp_" + "X" * 36,
            "surrounding_context": "",
            "synthetic": "yes",
        }
        for i in range(3)
    ]
    _run_sample(ps, tmp_path, bad_rows, seed=42, size=10, expect_rc=1)


def test_malformed_does_not_enter_precision_denominator(ps):
    """Normalised malformed rows must be flagged; not silently included."""
    row = {
        "repo": "flask",
        "file": "src/x.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_" + "X" * 36,
        "surrounding_context": "",
        "synthetic": "yes",
    }
    result = ps.normalise(row)
    assert result["malformed"] is True
    assert result["malformed_reason"] != ""


# ---------------------------------------------------------------------------
# Preview redaction
# ---------------------------------------------------------------------------

def test_no_raw_secrets_in_output(tmp_path, ps):
    secret_rows = [
        dict(r, matched_value=f"sk_live_51{'X' * 30}{i}")
        for i, r in enumerate(_SAMPLE_ROWS[:10])
    ]
    output_rows = _run_sample(ps, tmp_path, secret_rows, seed=42, size=10)
    for row in output_rows:
        preview = row["matched_preview"]
        assert "sk_live_51" + "X" * 30 not in preview, (
            f"Raw secret must not appear in output: {preview}"
        )
        assert "..." in preview or "*" in preview, (
            f"Preview must redact interior: {preview}"
        )


def test_redaction_preserves_prefix_github(ps):
    preview = ps.redact_preview("ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert preview.startswith("ghp_"), f"GitHub prefix must be preserved: {preview}"
    assert "..." in preview, f"Ellipsis must appear in preview: {preview}"
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in preview


def test_redaction_preserves_prefix_stripe(ps):
    preview = ps.redact_preview("stk_live_51ABCDEFGHIJKLMNOPQRSTUVWXYZabcde")
    assert preview.startswith("stk_"), f"Stripe alias prefix preview must preserve leading marker: {preview}"
    assert "..." in preview
    assert preview.endswith("bcde")
    assert "live_51ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in preview


def test_redaction_short_value(ps):
    preview = ps.redact_preview("abc")
    assert "abc" not in preview or "*" in preview or "..." in preview


def test_redaction_empty_value(ps):
    assert ps.redact_preview("") == ""


# ---------------------------------------------------------------------------
# Synthetic flag preservation
# ---------------------------------------------------------------------------

def test_synthetic_flag_preserved_true(tmp_path, ps):
    rows = _run_sample(ps, tmp_path, _SYNTHETIC_ROWS, seed=42, size=10)
    assert len(rows) == 1
    assert rows[0]["synthetic"] == "true"


def test_synthetic_flag_preserved_false(tmp_path, ps):
    rows = _run_sample(ps, tmp_path, _SAMPLE_ROWS[:5], seed=42, size=5)
    for row in rows:
        assert row["synthetic"] == "false"


def test_empty_synthetic_field_is_malformed_not_false(tmp_path, ps):
    """Regression: empty synthetic field must be malformed, NOT silently treated as false.

    The review_notes fallback is removed; only the synthetic column is authoritative.
    """
    row = {
        "repo": "flask",
        "file": "tests/control.py",
        "line": "1",
        "rule_id": "SEC002",
        "matched_value": "ghp_FAKE" + "A" * 32,
        "surrounding_context": "",
        "synthetic": "",  # malformed — NOT a fallback signal
    }
    # Malformed row excluded → output is empty → rc=1
    _run_sample(ps, tmp_path, [row], seed=42, size=10, expect_rc=1)


# ---------------------------------------------------------------------------
# Output schema completeness
# ---------------------------------------------------------------------------

def test_output_has_all_required_fields(tmp_path, ps):
    rows = _run_sample(ps, tmp_path, _SAMPLE_ROWS[:5], seed=42, size=5)
    required = {
        "finding_id", "repo", "file", "line", "rule_id",
        "matched_preview", "surrounding_context", "synthetic",
        "human_label", "category", "review_notes",
        "reviewer", "review_timestamp", "labeling_pass_id",
    }
    actual_fields = set(rows[0].keys())
    assert required.issubset(actual_fields), (
        f"Missing fields: {required - actual_fields}"
    )


def test_reviewer_fields_are_empty_placeholders(tmp_path, ps):
    rows = _run_sample(ps, tmp_path, _SAMPLE_ROWS[:3], seed=42, size=3)
    for row in rows:
        assert row["human_label"] == "", "human_label must be empty before review"
        assert row["reviewer"] == "", "reviewer must be empty before review"
        assert row["review_timestamp"] == ""


# ---------------------------------------------------------------------------
# JSON input support
# ---------------------------------------------------------------------------

def test_json_input_format_string_false(tmp_path, ps):
    """JSON with string 'false' for synthetic must be accepted."""
    json_data = {
        "findings": [
            {
                "repo": "httpx",
                "file": "tests/auth.py",
                "line": 5,
                "rule_id": "SEC002",
                "matched_value": "ghp_JSONINPUTTEST" + "A" * 23,
                "surrounding_context": "test context",
                "synthetic": "false",
            }
        ]
    }
    json_path = tmp_path / "findings.json"
    json_path.write_text(json.dumps(json_data), encoding="utf-8")
    out_path = tmp_path / "out.csv"
    rc = ps.main([
        "--input", str(json_path),
        "--seed", "42",
        "--size", "10",
        "--out", str(out_path),
    ])
    assert rc == 0
    with open(out_path, newline="", encoding="utf-8") as f:
        output_rows = list(csv.DictReader(f))
    assert len(output_rows) == 1
    assert output_rows[0]["repo"] == "httpx"
    assert output_rows[0]["synthetic"] == "false"


def test_json_input_format_bool_false(tmp_path, ps):
    """JSON native boolean false must be handled without truthiness coercion bug."""
    json_data = {
        "findings": [
            {
                "repo": "httpx",
                "file": "tests/auth.py",
                "line": 5,
                "rule_id": "SEC002",
                "matched_value": "ghp_BOOLTEST" + "A" * 29,
                "surrounding_context": "test context",
                "synthetic": False,  # Python bool, from JSON false
            }
        ]
    }
    json_path = tmp_path / "findings_bool.json"
    json_path.write_text(json.dumps(json_data), encoding="utf-8")
    out_path = tmp_path / "out.csv"
    rc = ps.main([
        "--input", str(json_path),
        "--seed", "42",
        "--size", "10",
        "--out", str(out_path),
    ])
    assert rc == 0
    with open(out_path, newline="", encoding="utf-8") as f:
        output_rows = list(csv.DictReader(f))
    assert len(output_rows) == 1
    assert output_rows[0]["synthetic"] == "false"


# ---------------------------------------------------------------------------
# Repo filter
# ---------------------------------------------------------------------------

def test_repo_filter(tmp_path, ps):
    mixed = _SAMPLE_ROWS[:3] + [
        dict(_SAMPLE_ROWS[0], repo="django", file="views.py", line="99")
    ]
    rows = _run_sample(ps, tmp_path, mixed, seed=42, size=100, repos=["flask"])
    repos_in_output = {r["repo"] for r in rows}
    assert repos_in_output == {"flask"}, f"Expected only flask, got {repos_in_output}"
