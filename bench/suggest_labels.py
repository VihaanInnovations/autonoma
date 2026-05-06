#!/usr/bin/env python3
"""
Generate heuristic label suggestions for findings in bench/findings_full.csv.

This script produces SUGGESTIONS ONLY. It is not authoritative.
Human reviewers must fill the human_label column in findings_suggested.csv
before running compute_precision.py.

Do NOT pipe this output directly into compute_precision.py.

Workflow:
  python bench/measure_precision.py
  python bench/suggest_labels.py
  # open findings_suggested.csv, fill human_label for each row
  python bench/compute_precision.py bench/findings_suggested.csv

Reads:   bench/findings_full.csv
Writes:  bench/findings_suggested.csv
"""
import csv
import math
import re
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).parent
INPUT_CSV = BENCH_DIR / "findings_full.csv"
OUTPUT_CSV = BENCH_DIR / "findings_suggested.csv"

_PLACEHOLDER_SUBSTRINGS = [
    "test", "dummy", "placeholder", "example", "sample", "fake", "mock",
    "changeme", "replace", "your-key", "your-secret", "secret123",
    "password123", "postgres", "mysql", "redis", "none", "null",
    "undefined", "dev", "todo", "fixme", "xxx",
]

_TEST_PATH_MARKERS = [
    "tests/", "test_", "_test.py", "conftest", "testdata", "fixtures", "spec/",
]

_DOC_PATH_MARKERS = [
    "docs/", "examples/", "tutorial/", "documentation/", "README",
]


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _norm_path(p: str) -> str:
    return p.replace("\\", "/")


def suggest(row: dict) -> tuple[str, str, str]:
    """Return (suggested_label, suggestion_confidence, suggestion_reason)."""
    file_path = _norm_path(row.get("file", ""))
    line_ctx = row.get("line_context", "")
    matched = row.get("matched_value", "")
    matched_lower = matched.lower().strip()

    # 1. GitHub Actions secret reference — not a hardcoded value
    if "${{" in line_ctx or "secrets." in line_ctx or "github.token" in line_ctx:
        return "FP_GHA", "high", "github_actions_reference"

    # 2. Dunder assignment — module-level metadata like __author__ = "..."
    if re.search(r"__\w+__\s*=", line_ctx):
        return "FP_DUNDER", "high", "dunder_assignment"

    # 3. Test file path
    if any(m in file_path for m in _TEST_PATH_MARKERS):
        return "FP_TEST", "medium", "test_path_marker"

    # 4. Docs / examples path
    if any(m in file_path for m in _DOC_PATH_MARKERS):
        return "FP_DOC", "medium", "docs_path_marker"

    # 5. Known placeholder substring or very short value
    if len(matched_lower) <= 2:
        return "FP_PLACEHOLDER", "high", "placeholder_substring"
    if any(p in matched_lower for p in _PLACEHOLDER_SUBSTRINGS):
        return "FP_PLACEHOLDER", "high", "placeholder_substring"

    # 6. Value too short to carry a real secret
    if len(matched) < 4:
        return "FP_PATTERN", "high", "too_short_pattern"

    # 7. Long value with high entropy — candidate only, not ground truth
    if len(matched) > 12 and shannon_entropy(matched) > 3.5:
        return "TP_CANDIDATE", "low", "high_entropy_candidate"

    # 8. Ambiguous — requires human judgement
    return "REVIEW", "low", "needs_human_review"


def main() -> None:
    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} not found. Run measure_precision.py first.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        source_fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    # Preserve source columns except old 'classification' (heuristic artifact).
    # Add structured suggestion columns + empty human review columns.
    base_cols = [c for c in source_fieldnames if c != "classification"]
    out_fieldnames = base_cols + [
        "suggested_label",
        "suggestion_confidence",
        "suggestion_reason",
        "human_label",
        "review_notes",
        "reviewer",
    ]

    counts: dict = {}
    out_rows = []
    for row in rows:
        label, confidence, reason = suggest(row)
        out_row = {c: row.get(c, "") for c in base_cols}
        out_row["suggested_label"] = label
        out_row["suggestion_confidence"] = confidence
        out_row["suggestion_reason"] = reason
        out_row["human_label"] = ""
        out_row["review_notes"] = ""
        out_row["reviewer"] = ""
        out_rows.append(out_row)
        counts[label] = counts.get(label, 0) + 1

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Suggested labels for {len(out_rows)} findings:", file=sys.stderr)
    for label, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {label:<20} {count}", file=sys.stderr)
    print(f"Output: {OUTPUT_CSV}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Next step: open findings_suggested.csv and fill the human_label column.", file=sys.stderr)
    print("Then run: python bench/compute_precision.py bench/findings_suggested.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
