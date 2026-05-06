#!/usr/bin/env python3
"""
Benchmark: verify SEC001/SEC002 positive and negative controls.

Reads EXPECT annotations from bench/positive_controls/*.py,
runs Autonoma scan, and checks every expected detection and suppression.

Exit codes:
  0  all controls behaved as expected
  1  one or more positives missed OR one or more negatives fired
  2  scan or parse failure
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).parent
CONTROLS_DIR = BENCH_DIR / "positive_controls"
CONTROL_FILES = sorted(CONTROLS_DIR.glob("*.py"))

_EXPECT_RE = re.compile(r"#\s*EXPECT:\s*(\S+)")


def parse_expectations(filepath: Path) -> dict:
    """Return {line_number: expected_tag} from EXPECT annotations on code lines.

    Pure comment lines (stripped line starts with '#') are skipped so that
    header comments explaining the annotation format are not mistaken for
    actual expectations.
    """
    expectations: dict = {}
    for i, line in enumerate(filepath.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        m = _EXPECT_RE.search(line)
        if m:
            tag = m.group(1).upper()
            if tag in ("SEC001", "SEC002", "SUPPRESS"):
                expectations[i] = tag
    return expectations


def run_scan() -> list:
    """Run autonoma scan on positive_controls/ and return findings list."""
    result = subprocess.run(
        [sys.executable, "-m", "autonoma", "scan", str(CONTROLS_DIR)],
        capture_output=True, text=True,
        cwd=str(BENCH_DIR.parent),
    )
    try:
        data = json.loads(result.stdout)
        return data.get("findings", [])
    except Exception as e:
        print(f"ERROR: could not parse scan output: {e}", file=sys.stderr)
        print(result.stdout[:500], file=sys.stderr)
        sys.exit(2)


def main() -> None:
    # Build expectations: {(filename, line): tag}
    all_expectations: dict = {}
    for filepath in CONTROL_FILES:
        for line, tag in parse_expectations(filepath).items():
            all_expectations[(filepath.name, line)] = tag

    # Run scan
    findings = run_scan()

    # Index findings: {(filename, line): rule_id}
    found: dict = {}
    for f in findings:
        fname = Path(f["file"]).name
        found[(fname, f["line"])] = f["rule_id"]

    # Evaluate
    detected: list = []
    missed: list = []
    suppressed_ok: list = []
    false_fired: list = []

    for (fname, line), tag in sorted(all_expectations.items()):
        actual = found.get((fname, line))
        if tag == "SUPPRESS":
            if actual is None:
                suppressed_ok.append((fname, line))
            else:
                false_fired.append((fname, line, actual))
        else:
            if actual is not None:
                extra = f" (expected {tag})" if actual != tag else ""
                detected.append((fname, line, actual, extra))
            else:
                missed.append((fname, line, tag))

    # Report
    sep = "=" * 62
    print(sep)
    print("Autonoma Positive Control Benchmark")
    print(sep)
    total_pos = len(detected) + len(missed)
    total_neg = len(suppressed_ok) + len(false_fired)
    print(f"\nExpected positives : {total_pos}")
    print(f"Detected           : {len(detected)}")
    print(f"Missed             : {len(missed)}")
    print(f"\nExpected negatives : {total_neg}")
    print(f"Correctly suppressed: {len(suppressed_ok)}")
    print(f"False detections   : {len(false_fired)}")

    if detected:
        print("\n[PASS] Detected positives:")
        for fname, line, rule, extra in detected:
            print(f"  {fname}:{line}  [{rule}]{extra}")

    if missed:
        print("\n[FAIL] Missed positives:")
        for fname, line, tag in missed:
            print(f"  {fname}:{line}  [expected {tag}]")

    if suppressed_ok:
        print("\n[PASS] Correctly suppressed negatives:")
        for fname, line in suppressed_ok:
            print(f"  {fname}:{line}")

    if false_fired:
        print("\n[FAIL] False detections on negatives:")
        for fname, line, rule in false_fired:
            print(f"  {fname}:{line}  [{rule}]")

    failures = len(missed) + len(false_fired)
    print()
    if failures:
        print(f"FAILED — {failures} control(s) did not behave as expected.")
        sys.exit(1)
    else:
        print("PASSED — all controls behaved as expected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
