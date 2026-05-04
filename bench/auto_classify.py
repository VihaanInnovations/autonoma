#!/usr/bin/env python3
"""
Auto-classify every finding in bench/findings_full.csv using heuristic rules.

Rules applied in priority order:
  1. FP:FP_gha        — GitHub Actions variable reference
  2. FP:FP_dunder     — dunder assignment (__name__ = ...)
  3. FP:FP_test       — file is inside a test directory / file
  4. FP:FP_doc        — file is inside docs / examples / tutorials
  5. FP:FP_placeholder — value looks like a known placeholder or is too short (<=2 chars)
  6. FP:FP_pattern    — value is too short to be a real secret (<4 chars)
  7. TP               — long value (>12 chars) with high Shannon entropy (>3.5)
  8. REVIEW           — everything else

Writes:  bench/findings_classified.csv
Then runs bench/compute_precision.py on that file and prints the report.
"""
import csv
import math
import re
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).parent
INPUT_CSV = BENCH_DIR / "findings_full.csv"
OUTPUT_CSV = BENCH_DIR / "findings_classified.csv"

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


def classify(row: dict) -> str:
    file_path = _norm_path(row.get("file", ""))
    line_ctx = row.get("line_context", "")
    matched = row.get("matched_value", "")
    matched_lower = matched.lower().strip()

    # 1. FP:FP_gha — GitHub Actions secret references, not hardcoded values
    if "${{" in line_ctx or "secrets." in line_ctx or "github.token" in line_ctx:
        return "FP:FP_gha"

    # 2. FP:FP_dunder — module-level metadata like __author__ = "..."
    if re.search(r"__\w+__\s*=", line_ctx):
        return "FP:FP_dunder"

    # 3. FP:FP_test — inside test files
    if any(m in file_path for m in _TEST_PATH_MARKERS):
        return "FP:FP_test"

    # 4. FP:FP_doc — inside docs / examples
    if any(m in file_path for m in _DOC_PATH_MARKERS):
        return "FP:FP_doc"

    # 5. FP:FP_placeholder — known placeholder value or too short
    if len(matched_lower) <= 2:
        return "FP:FP_placeholder"
    if any(p in matched_lower for p in _PLACEHOLDER_SUBSTRINGS):
        return "FP:FP_placeholder"

    # 6. FP:FP_pattern — value is too short to carry a real secret
    if len(matched) < 4:
        return "FP:FP_pattern"

    # 7. TP — long value with high entropy
    if len(matched) > 12 and shannon_entropy(matched) > 3.5:
        return "TP"

    # 8. REVIEW — ambiguous, needs human judgement
    return "REVIEW"


def main():
    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} not found. Run measure_precision.py first.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    counts: dict = {}
    for row in rows:
        cls = classify(row)
        row["classification"] = cls
        counts[cls] = counts.get(cls, 0) + 1

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Classified {len(rows)} findings:", file=sys.stderr)
    for cls, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cls:<20} {count}", file=sys.stderr)
    print(f"Output: {OUTPUT_CSV}", file=sys.stderr)
    print(file=sys.stderr)

    result = subprocess.run(
        [sys.executable, str(BENCH_DIR / "compute_precision.py"), str(OUTPUT_CSV)],
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
