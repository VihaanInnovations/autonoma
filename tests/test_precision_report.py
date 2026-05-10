"""
Tests for bench/scripts/precision_report.py.

Covers:
- synthetic controls excluded from precision denominator (MANDATORY)
- UNCERTAIN rows excluded from precision denominator
- Wilson interval output stable
- FP category aggregation correct
- Cohen's kappa (intra-rater) when re_review_label column present
- strict CSV boolean parsing (Phase 1 hardening)
- malformed synthetic field exclusion from metrics (Phase 3 hardening)
"""

import csv
import importlib.util
import math
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "bench" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pr():
    return _load("precision_report", SCRIPTS_DIR / "precision_report.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(
    human_label: str = "TRUE_POSITIVE",
    category: str = "",
    synthetic: str = "false",
    review_notes: str = "",
    repo: str = "flask",
    rule_id: str = "SEC002",
    re_review_label: str = "",
) -> dict:
    return {
        "finding_id": "F000000000001",
        "repo": repo,
        "file": "src/auth.py",
        "line": "42",
        "rule_id": rule_id,
        "matched_preview": "ghp_abcd...0123",
        "surrounding_context": "",
        "synthetic": synthetic,
        "human_label": human_label,
        "category": category,
        "review_notes": review_notes,
        "reviewer": "vithushan",
        "review_timestamp": "2026-05-10T00:00:00Z",
        "labeling_pass_id": "SEC002-precision-2026-01",
        "re_review_label": re_review_label,
    }


def _write_csv(tmp_path: Path, rows: list[dict], name: str = "labeled.csv") -> Path:
    p = tmp_path / name
    fieldnames = list(rows[0].keys()) if rows else ["human_label"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return p


# ---------------------------------------------------------------------------
# MANDATORY: synthetic controls excluded from precision
# ---------------------------------------------------------------------------

def test_synthetic_controls_excluded_from_precision(pr):
    """Synthetic positive controls must not appear in precision numerator or denominator.

    This test is a hard benchmark-integrity requirement.  Synthetic controls
    inflate precision artificially because the benchmark itself seeded them;
    excluding them is mandatory per Governance v1.1 Section 2.2.

    Only the synthetic CSV column is authoritative (strict parsing).
    """
    rows = [
        # 1 real TP
        _row("TRUE_POSITIVE", synthetic="false"),
        # 1 real FP
        _row("FALSE_POSITIVE", category="A", synthetic="false"),
        # 2 synthetic TPs — excluded via synthetic column only
        _row("TRUE_POSITIVE", synthetic="true"),
        _row("TRUE_POSITIVE", synthetic="TRUE"),  # case-insensitive
    ]
    m = pr.compute_metrics(rows)

    assert m["synthetic_excluded"] == 2, (
        f"Expected 2 synthetic rows excluded, got {m['synthetic_excluded']}"
    )
    assert m["tp"] == 1, f"Expected 1 TP (synthetic rows excluded), got {m['tp']}"
    assert m["fp"] == 1, f"Expected 1 FP, got {m['fp']}"
    # precision = 1 / (1+1) = 0.5
    assert m["precision"] == pytest.approx(0.5, abs=1e-6), (
        f"Expected precision=0.5, got {m['precision']}"
    )


def test_review_notes_synthetic_tag_not_authoritative(pr):
    """review_notes 'synthetic: true' is documentation only; synthetic column is authoritative.

    A row with synthetic='false' and review_notes containing 'synthetic: true'
    must NOT be excluded — the column wins.
    """
    rows = [
        _row("TRUE_POSITIVE", synthetic="true"),   # excluded via column
        _row("TRUE_POSITIVE", review_notes="synthetic: true", synthetic="false"),  # NOT excluded
        _row("TRUE_POSITIVE", synthetic="false"),  # not excluded
    ]
    m = pr.compute_metrics(rows)
    assert m["synthetic_excluded"] == 1, (
        "Only synthetic='true' row should be excluded; review_notes is not authoritative"
    )
    assert m["tp"] == 2


def test_all_synthetic_yields_no_precision(pr):
    rows = [_row("TRUE_POSITIVE", synthetic="true") for _ in range(5)]
    m = pr.compute_metrics(rows)
    assert m["precision"] is None
    assert m["synthetic_excluded"] == 5
    assert m["tp"] == 0
    assert m["fp"] == 0


# ---------------------------------------------------------------------------
# UNCERTAIN excluded from precision denominator
# ---------------------------------------------------------------------------

def test_uncertain_excluded_from_precision_denominator(pr):
    rows = [
        _row("TRUE_POSITIVE"),
        _row("FALSE_POSITIVE", category="B"),
        _row("UNCERTAIN"),
        _row("UNCERTAIN"),
    ]
    m = pr.compute_metrics(rows)
    # precision denominator = TP + FP = 2, not 4
    assert m["tp"] == 1
    assert m["fp"] == 1
    assert m["uncertain"] == 2
    assert m["precision"] == pytest.approx(0.5, abs=1e-6)


def test_uncertain_rate_correct(pr):
    rows = [
        _row("TRUE_POSITIVE"),
        _row("FALSE_POSITIVE", category="C"),
        _row("UNCERTAIN"),
    ]
    m = pr.compute_metrics(rows)
    # uncertain_rate = 1 / (1+1+1) = 1/3
    assert m["uncertain_rate"] == pytest.approx(1 / 3, abs=1e-6)


def test_zero_uncertain_rate(pr):
    rows = [_row("TRUE_POSITIVE"), _row("FALSE_POSITIVE", category="D")]
    m = pr.compute_metrics(rows)
    assert m["uncertain"] == 0
    assert m["uncertain_rate"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Wilson interval
# ---------------------------------------------------------------------------

def test_wilson_interval_bounds(pr):
    lo, hi = pr.wilson_interval(8, 10)
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_interval_zero_trials(pr):
    lo, hi = pr.wilson_interval(0, 0)
    assert lo == 0.0
    assert hi == 1.0


def test_wilson_interval_perfect_precision(pr):
    lo, hi = pr.wilson_interval(50, 50)
    assert lo > 0.85  # Lower bound well above 0 for n=50 perfect precision
    assert hi == pytest.approx(1.0, abs=1e-6)


def test_wilson_interval_in_report_metrics(pr):
    rows = [_row("TRUE_POSITIVE")] * 9 + [_row("FALSE_POSITIVE", category="A")]
    m = pr.compute_metrics(rows)
    assert m["wilson_lo"] is not None
    assert m["wilson_hi"] is not None
    assert 0.0 <= m["wilson_lo"] <= m["wilson_hi"] <= 1.0
    assert m["wilson_lo"] < m["precision"] < m["wilson_hi"]


def test_wilson_interval_stable_across_calls(pr):
    """Wilson interval must be deterministic (no randomness)."""
    lo1, hi1 = pr.wilson_interval(30, 40)
    lo2, hi2 = pr.wilson_interval(30, 40)
    assert lo1 == lo2
    assert hi1 == hi2


def test_preliminary_flag_n_less_than_30(pr):
    rows = [_row("TRUE_POSITIVE")] * 5 + [_row("FALSE_POSITIVE", category="B")] * 5
    m = pr.compute_metrics(rows)
    assert m["preliminary"] is True


def test_not_preliminary_n_ge_30(pr):
    rows = [_row("TRUE_POSITIVE")] * 25 + [_row("FALSE_POSITIVE", category="B")] * 5
    m = pr.compute_metrics(rows)
    assert m["preliminary"] is False


# ---------------------------------------------------------------------------
# FP category aggregation
# ---------------------------------------------------------------------------

def test_fp_category_counts_correct(pr):
    rows = [
        _row("FALSE_POSITIVE", category="A"),
        _row("FALSE_POSITIVE", category="A"),
        _row("FALSE_POSITIVE", category="B"),
        _row("FALSE_POSITIVE", category="H"),
        _row("TRUE_POSITIVE"),
    ]
    m = pr.compute_metrics(rows)
    assert m["fp_categories"]["A"] == 2
    assert m["fp_categories"]["B"] == 1
    assert m["fp_categories"]["H"] == 1


def test_fp_category_r_counted(pr):
    rows = [_row("FALSE_POSITIVE", category="R")]
    m = pr.compute_metrics(rows)
    assert m["fp_categories"]["R"] == 1


def test_fp_category_h_counted(pr):
    rows = [_row("FALSE_POSITIVE", category="H")]
    m = pr.compute_metrics(rows)
    assert m["fp_categories"]["H"] == 1


def test_fp_category_all_categories(pr):
    categories = list("ABCDEFGHR")
    rows = [_row("FALSE_POSITIVE", category=c) for c in categories]
    m = pr.compute_metrics(rows)
    for c in categories:
        assert m["fp_categories"][c] == 1, f"Category {c} not counted"


def test_fp_uncategorised_labelled(pr):
    rows = [_row("FALSE_POSITIVE", category="")]
    m = pr.compute_metrics(rows)
    assert m["fp"] == 1
    # Uncategorised FPs should still be counted under some key
    assert sum(m["fp_categories"].values()) == 1


# ---------------------------------------------------------------------------
# TP criteria breakdown
# ---------------------------------------------------------------------------

def test_tp_criteria_breakdown(pr):
    rows = [
        _row("TRUE_POSITIVE", category="1"),
        _row("TRUE_POSITIVE", category="1"),
        _row("TRUE_POSITIVE", category="2"),
    ]
    m = pr.compute_metrics(rows)
    assert m["tp_criteria"]["1"] == 2
    assert m["tp_criteria"]["2"] == 1


# ---------------------------------------------------------------------------
# Cohen's kappa (optional)
# ---------------------------------------------------------------------------

def test_kappa_perfect_agreement(pr):
    rows = [
        _row("TRUE_POSITIVE", re_review_label="TRUE_POSITIVE"),
        _row("FALSE_POSITIVE", category="A", re_review_label="FALSE_POSITIVE"),
        _row("FALSE_POSITIVE", category="B", re_review_label="FALSE_POSITIVE"),
    ]
    m = pr.compute_metrics(rows)
    assert m["kappa"] == pytest.approx(1.0, abs=0.01)


def test_kappa_absent_without_re_review_column(pr):
    rows = [_row("TRUE_POSITIVE"), _row("FALSE_POSITIVE", category="C")]
    m = pr.compute_metrics(rows)
    assert m["kappa"] is None


def test_kappa_range(pr):
    rows = [
        _row("TRUE_POSITIVE", re_review_label="FALSE_POSITIVE"),
        _row("FALSE_POSITIVE", category="A", re_review_label="TRUE_POSITIVE"),
        _row("TRUE_POSITIVE", re_review_label="TRUE_POSITIVE"),
    ]
    m = pr.compute_metrics(rows)
    assert m["kappa"] is not None
    assert -1.0 <= m["kappa"] <= 1.0


# ---------------------------------------------------------------------------
# Per-repo and per-rule breakdowns
# ---------------------------------------------------------------------------

def test_per_repo_breakdown(pr):
    rows = [
        _row("TRUE_POSITIVE", repo="flask"),
        _row("FALSE_POSITIVE", category="A", repo="flask"),
        _row("TRUE_POSITIVE", repo="django"),
    ]
    m = pr.compute_metrics(rows)
    assert m["by_repo"]["flask"]["tp"] == 1
    assert m["by_repo"]["flask"]["fp"] == 1
    assert m["by_repo"]["django"]["tp"] == 1
    assert m["by_repo"]["django"]["fp"] == 0


def test_per_rule_breakdown(pr):
    rows = [
        _row("TRUE_POSITIVE", rule_id="SEC001"),
        _row("FALSE_POSITIVE", category="B", rule_id="SEC002"),
    ]
    m = pr.compute_metrics(rows)
    assert m["by_rule"]["SEC001"]["tp"] == 1
    assert m["by_rule"]["SEC002"]["fp"] == 1


# ---------------------------------------------------------------------------
# Report rendering (smoke test)
# ---------------------------------------------------------------------------

def test_render_report_contains_key_sections(pr):
    rows = [
        _row("TRUE_POSITIVE"),
        _row("FALSE_POSITIVE", category="A"),
        _row("UNCERTAIN"),
        _row("TRUE_POSITIVE", synthetic="true"),
    ]
    m = pr.compute_metrics(rows)
    report = pr.render_report(m)
    assert "# Precision Report" in report
    assert "Strict precision" in report
    assert "Uncertain rate" in report or "uncertain" in report.lower()
    assert "FP Category" in report


def test_render_report_marks_preliminary(pr):
    rows = [_row("TRUE_POSITIVE")] * 3 + [_row("FALSE_POSITIVE", category="C")]
    m = pr.compute_metrics(rows)
    assert m["preliminary"]
    report = pr.render_report(m)
    assert "PRELIMINARY" in report


def test_render_report_no_synthetic_in_denominator_message(pr):
    rows = [
        _row("TRUE_POSITIVE"),
        _row("TRUE_POSITIVE", synthetic="true"),
    ]
    m = pr.compute_metrics(rows)
    report = pr.render_report(m)
    assert "synthetic" in report.lower()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_cli_runs_without_error(tmp_path, pr):
    rows = [
        _row("TRUE_POSITIVE"),
        _row("FALSE_POSITIVE", category="B"),
        _row("UNCERTAIN"),
    ]
    csv_path = _write_csv(tmp_path, rows)
    out_path = tmp_path / "report.md"
    rc = pr.main(["--input", str(csv_path), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "# Precision Report" in content


def test_cli_missing_input_returns_error(tmp_path, pr):
    rc = pr.main(["--input", str(tmp_path / "nonexistent.csv")])
    assert rc != 0


# ---------------------------------------------------------------------------
# PHASE 1: Strict CSV boolean parsing in precision_report
# ---------------------------------------------------------------------------

def test_report_strict_bool_true_lowercase(pr):
    val, err = pr.parse_synthetic_strict("true")
    assert val is True
    assert err is None


def test_report_strict_bool_false_lowercase(pr):
    val, err = pr.parse_synthetic_strict("false")
    assert val is False
    assert err is None


def test_report_strict_bool_False_mixed_case(pr):
    """'False' (Python bool repr) must map to False, not be treated as truthy.

    This covers the bool('False') == True bug that strict parsing prevents.
    """
    val, err = pr.parse_synthetic_strict("False")
    assert val is False, (
        "Strict parsing: 'False'.lower() == 'false' -> False (not Python truthiness True)"
    )
    assert err is None


def test_report_strict_bool_TRUE_uppercase(pr):
    val, err = pr.parse_synthetic_strict("TRUE")
    assert val is True
    assert err is None


def test_report_strict_bool_yes_malformed(pr):
    val, err = pr.parse_synthetic_strict("yes")
    assert val is None
    assert err is not None


def test_report_strict_bool_empty_malformed(pr):
    val, err = pr.parse_synthetic_strict("")
    assert val is None
    assert err is not None


def test_report_strict_bool_one_malformed(pr):
    val, err = pr.parse_synthetic_strict("1")
    assert val is None
    assert err is not None


def test_report_strict_bool_whitespace_trimmed(pr):
    val, err = pr.parse_synthetic_strict("  false  ")
    assert val is False
    assert err is None


# ---------------------------------------------------------------------------
# PHASE 3: Malformed synthetic field handling in precision_report
# ---------------------------------------------------------------------------

def test_malformed_synthetic_excluded_from_metrics(pr):
    """Rows with malformed synthetic field must be excluded from ALL metrics."""
    rows = [
        _row("TRUE_POSITIVE", synthetic="false"),   # valid, counts as TP
        _row("TRUE_POSITIVE", synthetic="true"),    # valid, synthetic excluded
        _row("TRUE_POSITIVE", synthetic="yes"),     # malformed, excluded
        _row("FALSE_POSITIVE", category="A", synthetic=""),  # malformed, excluded
    ]
    m = pr.compute_metrics(rows)
    assert m["malformed_rows"] == 2, (
        f"Expected 2 malformed rows, got {m['malformed_rows']}"
    )
    assert m["synthetic_excluded"] == 1
    assert m["tp"] == 1
    assert m["fp"] == 0


def test_malformed_count_in_metrics(pr):
    rows = [
        _row("TRUE_POSITIVE", synthetic="yes"),    # malformed
        _row("FALSE_POSITIVE", category="B", synthetic="no"),  # malformed
        _row("TRUE_POSITIVE", synthetic="false"),  # valid
    ]
    m = pr.compute_metrics(rows)
    assert m["malformed_rows"] == 2
    assert "malformed_rows" in m


def test_malformed_rows_not_in_precision_denominator(pr):
    """Malformed rows must not inflate or deflate the precision denominator."""
    rows = [
        _row("TRUE_POSITIVE", synthetic="false"),
        _row("FALSE_POSITIVE", category="A", synthetic="false"),
        _row("TRUE_POSITIVE", synthetic="1"),  # malformed — must not enter denominator
    ]
    m = pr.compute_metrics(rows)
    assert m["malformed_rows"] == 1
    # precision denominator = 1 TP + 1 FP = 2 (malformed row not counted)
    assert m["tp"] == 1
    assert m["fp"] == 1
    assert m["precision"] == pytest.approx(0.5, abs=1e-6)


def test_all_malformed_yields_no_precision(pr):
    rows = [
        _row("TRUE_POSITIVE", synthetic="yes"),
        _row("FALSE_POSITIVE", category="A", synthetic=""),
    ]
    m = pr.compute_metrics(rows)
    assert m["malformed_rows"] == 2
    assert m["tp"] == 0
    assert m["fp"] == 0
    assert m["precision"] is None


def test_malformed_warning_text_in_metrics(pr):
    rows = [_row("TRUE_POSITIVE", synthetic="badvalue")]
    m = pr.compute_metrics(rows)
    assert m["malformed_warnings"]
    assert any("badvalue" in w for w in m["malformed_warnings"])


def test_render_report_shows_malformed_warning(pr):
    rows = [
        _row("TRUE_POSITIVE", synthetic="false"),
        _row("TRUE_POSITIVE", synthetic="yes"),  # malformed
    ]
    m = pr.compute_metrics(rows)
    report = pr.render_report(m)
    assert "malformed" in report.lower() or "WARNING" in report


# ---------------------------------------------------------------------------
# PHASE 2 hardening: missing column and JSON null synthetic handling
# ---------------------------------------------------------------------------

def test_missing_synthetic_column_malformed_in_report(pr):
    """Row without synthetic column must be excluded as malformed in precision_report."""
    row_without_key = {
        "finding_id": "F999",
        "repo": "flask",
        "file": "src/no_synth.py",
        "line": "99",
        "rule_id": "SEC002",
        "matched_preview": "ghp_abcd...0123",
        "surrounding_context": "",
        # "synthetic" key deliberately absent
        "human_label": "TRUE_POSITIVE",
        "category": "",
        "review_notes": "",
        "reviewer": "v",
        "review_timestamp": "",
        "labeling_pass_id": "",
    }
    m = pr.compute_metrics([row_without_key, _row("FALSE_POSITIVE", category="A")])
    assert m["malformed_rows"] == 1, (
        "Row with missing synthetic column must be counted as malformed"
    )
    assert m["tp"] == 0
    assert m["fp"] == 1


def test_json_null_synthetic_malformed_in_report(pr):
    """Row with synthetic=None (JSON null equivalent) must be malformed in precision_report."""
    row_with_none = dict(_row("TRUE_POSITIVE"), synthetic=None)
    m = pr.compute_metrics([row_with_none, _row("FALSE_POSITIVE", category="B")])
    assert m["malformed_rows"] == 1, (
        "synthetic=None (JSON null) must be counted as malformed"
    )
    assert m["tp"] == 0
    assert m["fp"] == 1


# ---------------------------------------------------------------------------
# UNCERTAIN exclusion — explicit denominator check
# ---------------------------------------------------------------------------

def test_uncertain_not_in_precision_denominator_explicit(pr):
    """UNCERTAIN rows must not appear in TP+FP denominator, only in uncertain_rate."""
    rows = [
        _row("TRUE_POSITIVE"),
        _row("FALSE_POSITIVE", category="C"),
        _row("UNCERTAIN"),
        _row("UNCERTAIN"),
        _row("UNCERTAIN"),
    ]
    m = pr.compute_metrics(rows)
    denominator = m["tp"] + m["fp"]
    assert denominator == 2, (
        f"Precision denominator must be TP+FP only (got {denominator}), "
        "UNCERTAIN must not enter denominator"
    )
    assert m["uncertain"] == 3
    assert m["uncertain_rate"] == pytest.approx(3 / (1 + 1 + 3), abs=1e-6)
    assert m["precision"] == pytest.approx(0.5, abs=1e-6)
