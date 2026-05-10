"""
CSV round-trip integrity tests for precision benchmark label fields.

Proves that reviewer-filled fields (human_label, category, review_notes,
surrounding_context) survive a CSV write/read cycle even when they contain
embedded commas, double quotes, or newlines.

These tests guard against silent data corruption in the precision pipeline:
    precision_sample.py writes output CSV
    → human reviewer fills in labels (in a spreadsheet or text editor)
    → precision_report.py reads labeled CSV
    → compute_metrics() produces precision numbers

If quoting is broken, a review_note like 'looks real, no test indicators'
could silently split into two cells, corrupting the label read by
compute_metrics().
"""

from __future__ import annotations

import csv
import importlib.util
import io
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


@pytest.fixture(scope="module")
def pr():
    return _load("precision_report", SCRIPTS_DIR / "precision_report.py")


# ---------------------------------------------------------------------------
# Helper: in-memory CSV round-trip
# ---------------------------------------------------------------------------

def _roundtrip(rows: list[dict]) -> list[dict]:
    """Write rows to an in-memory CSV buffer and read them back."""
    if not rows:
        return []
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return list(csv.DictReader(buf))


def _make_labeled_row(
    human_label: str = "TRUE_POSITIVE",
    category: str = "1",
    review_notes: str = "",
    surrounding_context: str = "",
    synthetic: str = "false",
) -> dict:
    return {
        "finding_id": "Fabcdef123456",
        "repo": "flask",
        "file": "src/auth.py",
        "line": "42",
        "rule_id": "SEC002",
        "matched_preview": "ghp_abcd...0123",
        "surrounding_context": surrounding_context,
        "synthetic": synthetic,
        "human_label": human_label,
        "category": category,
        "review_notes": review_notes,
        "reviewer": "vithushan",
        "review_timestamp": "2026-05-10T12:00:00Z",
        "labeling_pass_id": "SEC002-precision-2026-01",
    }


# ---------------------------------------------------------------------------
# review_notes with embedded commas
# ---------------------------------------------------------------------------

def test_roundtrip_review_notes_comma(pr):
    """review_notes with embedded commas must survive CSV write/read."""
    notes = "looks legit, high entropy, matches GitHub PAT format"
    rt = _roundtrip([_make_labeled_row(review_notes=notes)])
    assert len(rt) == 1
    assert rt[0]["review_notes"] == notes
    assert rt[0]["human_label"] == "TRUE_POSITIVE"


def test_roundtrip_review_notes_multiple_commas_metrics_correct(pr):
    """Commas in review_notes must not corrupt human_label parsed by compute_metrics."""
    rows = [
        _make_labeled_row(human_label="TRUE_POSITIVE",
                          review_notes="format match, prod file, no test context"),
        _make_labeled_row(human_label="FALSE_POSITIVE", category="H",
                          review_notes="test fixture, category H, no live indicators",
                          synthetic="false"),
    ]
    rt = _roundtrip(rows)
    m = pr.compute_metrics(rt)
    assert m["tp"] == 1
    assert m["fp"] == 1
    assert m["precision"] == pytest.approx(0.5, abs=1e-6)
    assert m["fp_categories"].get("H", 0) == 1


# ---------------------------------------------------------------------------
# review_notes with embedded double quotes
# ---------------------------------------------------------------------------

def test_roundtrip_review_notes_double_quotes(pr):
    """review_notes with embedded double quotes must survive CSV write/read."""
    notes = 'matched "ghp_" prefix exactly — high confidence'
    rt = _roundtrip([_make_labeled_row(review_notes=notes)])
    assert len(rt) == 1
    assert rt[0]["review_notes"] == notes


def test_roundtrip_category_with_quotes_label_preserved(pr):
    """Category field must be preserved exactly when review_notes contains quotes."""
    row = _make_labeled_row(
        human_label="FALSE_POSITIVE",
        category="A",
        review_notes='key name is "token" — concept label, not a real secret',
    )
    rt = _roundtrip([row])
    assert rt[0]["human_label"] == "FALSE_POSITIVE"
    assert rt[0]["category"] == "A"


# ---------------------------------------------------------------------------
# surrounding_context with embedded newlines
# ---------------------------------------------------------------------------

def test_roundtrip_surrounding_context_newline(pr):
    """surrounding_context with embedded newlines must survive CSV write/read."""
    context = "api_key = 'ghp_abcd'\nother_config = 'something'\n# end of block"
    rt = _roundtrip([_make_labeled_row(surrounding_context=context)])
    assert len(rt) == 1
    assert rt[0]["surrounding_context"] == context


def test_roundtrip_metrics_unaffected_by_newlines_in_context(pr):
    """Newlines in surrounding_context must not corrupt human_label in compute_metrics."""
    rows = [
        _make_labeled_row(
            human_label="TRUE_POSITIVE",
            surrounding_context="api_key = 'ghp_'\nreturn api_key",
        ),
        _make_labeled_row(
            human_label="FALSE_POSITIVE",
            category="B",
            surrounding_context="scheme = 'Bearer'\nheader = scheme",
        ),
    ]
    rt = _roundtrip(rows)
    m = pr.compute_metrics(rt)
    assert m["tp"] == 1
    assert m["fp"] == 1
    assert m["precision"] == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# Label and category fields preserved exactly through round-trip
# ---------------------------------------------------------------------------

def test_roundtrip_all_fp_categories_preserved(pr):
    """All FP category labels (A–H, R) must survive CSV round-trip unchanged."""
    categories = list("ABCDEFGHR")
    rows = [
        _make_labeled_row(human_label="FALSE_POSITIVE", category=c,
                          review_notes=f"category {c} example")
        for c in categories
    ]
    rt = _roundtrip(rows)
    assert len(rt) == len(categories)
    recovered_cats = [r["category"] for r in rt]
    assert recovered_cats == categories, (
        f"Category labels changed during CSV round-trip: {recovered_cats}"
    )


def test_roundtrip_labeling_pass_id_preserved(pr):
    """labeling_pass_id must survive round-trip unchanged."""
    pass_id = "SEC002-precision-2026-01"
    rt = _roundtrip([_make_labeled_row()])
    assert rt[0]["labeling_pass_id"] == pass_id


def test_roundtrip_synthetic_flag_preserved_true(pr):
    """synthetic='true' must survive CSV round-trip and be excluded from precision."""
    row = _make_labeled_row(human_label="TRUE_POSITIVE", synthetic="true")
    rt = _roundtrip([row])
    assert rt[0]["synthetic"] == "true"
    m = pr.compute_metrics(rt)
    assert m["synthetic_excluded"] == 1
    assert m["tp"] == 0
    assert m["precision"] is None


def test_roundtrip_synthetic_flag_preserved_false(pr):
    """synthetic='false' must survive CSV round-trip and be included in precision."""
    row = _make_labeled_row(human_label="TRUE_POSITIVE", synthetic="false")
    rt = _roundtrip([row])
    assert rt[0]["synthetic"] == "false"
    m = pr.compute_metrics(rt)
    assert m["tp"] == 1


# ---------------------------------------------------------------------------
# Full pipeline round-trip via precision_sample write_csv + DictReader
# ---------------------------------------------------------------------------

def test_write_csv_roundtrip_via_script(tmp_path, ps, pr):
    """precision_sample.write_csv() output must be readable by precision_report DictReader."""
    import csv as _csv

    output_rows = [
        {
            "finding_id": "F001",
            "repo": "flask",
            "file": "src/auth.py",
            "line": "42",
            "rule_id": "SEC002",
            "matched_preview": "ghp_abcd...0123",
            "surrounding_context": "token = 'ghp_...'\nreturn token",
            "synthetic": "false",
            "human_label": "",
            "category": "",
            "review_notes": "",
            "reviewer": "",
            "review_timestamp": "",
            "labeling_pass_id": "",
        }
    ]

    out_path = tmp_path / "sample.csv"
    ps.write_csv(output_rows, out_path)

    with open(out_path, newline="", encoding="utf-8") as f:
        read_back = list(_csv.DictReader(f))

    assert len(read_back) == 1
    assert read_back[0]["surrounding_context"] == output_rows[0]["surrounding_context"]
    assert read_back[0]["synthetic"] == "false"
    assert read_back[0]["matched_preview"] == "ghp_abcd...0123"
