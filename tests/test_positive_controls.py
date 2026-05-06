"""
Pytest wrapper for the positive control benchmark.

Verifies that bench/check_positive_controls.py exits 0 (all controls pass).
Also contains direct unit-level checks using HeuristicsEngine so failures
produce clear per-control assertions rather than a single subprocess failure.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from autonoma._internal.heuristics import HeuristicsEngine

CONTROLS_DIR = Path(__file__).parent.parent / "bench" / "positive_controls"
_EXPECT_RE = re.compile(r"#\s*EXPECT:\s*(\S+)")


def _parse_controls(filename: str) -> list:
    """Return list of (line_number, code_fragment, expected_tag).

    Skips pure-comment lines so header annotations are not treated as expectations.
    """
    path = CONTROLS_DIR / filename
    controls = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        m = _EXPECT_RE.search(line)
        if m:
            tag = m.group(1).upper()
            if tag in ("SEC001", "SEC002", "SUPPRESS"):
                controls.append((i, line.split("#")[0].strip(), tag))
    return controls


def _scan_file(filename: str) -> dict:
    """Scan a control file and return {line: rule_id} for all findings."""
    engine = HeuristicsEngine()
    path = CONTROLS_DIR / filename
    content = path.read_text(encoding="utf-8")
    result = engine.analyze(content, str(path))
    return {f["line"]: f["id"] for f in result.issues}


# ---------------------------------------------------------------------------
# SEC001 positive controls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lineno,code,tag", _parse_controls("sec001_passwords.py"))
def test_sec001_control(lineno, code, tag):
    findings = _scan_file("sec001_passwords.py")
    if tag == "SUPPRESS":
        assert lineno not in findings, (
            f"Line {lineno} should be suppressed but fired {findings[lineno]!r}: {code!r}"
        )
    else:
        assert lineno in findings, (
            f"Line {lineno} was not detected (expected {tag}): {code!r}"
        )
        assert findings[lineno] == tag, (
            f"Line {lineno} fired {findings[lineno]!r} instead of {tag!r}: {code!r}"
        )


# ---------------------------------------------------------------------------
# SEC002 positive and negative controls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lineno,code,tag", _parse_controls("sec002_tokens.py"))
def test_sec002_control(lineno, code, tag):
    findings = _scan_file("sec002_tokens.py")
    if tag == "SUPPRESS":
        assert lineno not in findings, (
            f"Line {lineno} should be suppressed but fired {findings[lineno]!r}: {code!r}"
        )
    else:
        assert lineno in findings, (
            f"Line {lineno} was not detected (expected {tag}): {code!r}"
        )
        assert findings[lineno] == tag, (
            f"Line {lineno} fired {findings[lineno]!r} instead of {tag!r}: {code!r}"
        )


# ---------------------------------------------------------------------------
# Integration: full benchmark script exits 0
# ---------------------------------------------------------------------------

def test_check_positive_controls_script_passes():
    """The benchmark script must exit 0 when all controls pass."""
    result = subprocess.run(
        [sys.executable, "bench/check_positive_controls.py"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0, (
        f"check_positive_controls.py exited {result.returncode}:\n{result.stdout}"
    )
