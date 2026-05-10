#!/usr/bin/env python3
"""
check_placeholders.py -- Fail if *frozen* scope docs contain unfilled placeholder markers.

A placeholder marker is any occurrence of the literal string:
    _(placeholder)_

Status-aware enforcement
------------------------
Each scope document must carry a bare 'Status:' line (not inside markdown
bold **...**):

    Status: draft    -- placeholders allowed; enforcement is skipped
    Status: frozen   -- placeholders forbidden; enforcement is applied

A missing or unrecognised status value is always treated as an error (exit 1).

Code-context awareness
----------------------
The scanner ignores placeholders that appear inside code contexts:

  - Fenced code blocks  (lines whose stripped form starts with ```)
  - Inline code spans   (text wrapped in single backticks: `...`)

Placeholders in prose, metadata fields, and table cells are still flagged.

This script is intended as a pre-commit check or CI validation step.

Usage
-----
    # Check default scope dir (docs/scope/)
    python bench/scripts/check_placeholders.py

    # Check specific files
    python bench/scripts/check_placeholders.py docs/scope/sec002_recall_scope_v1.md

    # Check a directory
    python bench/scripts/check_placeholders.py docs/scope/

Exits
-----
    0  -- all frozen docs are clean; draft docs were skipped
    1  -- placeholder found in frozen doc, or status missing/invalid
    2  -- usage / filesystem error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLACEHOLDER_MARKER = "_(placeholder)_"
STATUS_VALID = frozenset({"draft", "frozen"})

# Matches a single-backtick inline code span on one line.
# Removes the entire span so its interior is not scanned for placeholders.
_INLINE_CODE_RE = re.compile(r'`[^`\n]*`')

# Default target when no paths are supplied
_DEFAULT_SCOPE_DIR = Path(__file__).parent.parent.parent / "docs" / "scope"


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------

def _scan_for_placeholders(text: str) -> list[tuple[int, str]]:
    """Scan document text for placeholder markers, skipping code contexts.

    Ignored contexts:
    - Fenced code blocks: a line whose stripped form starts with ``` toggles
      the fenced-block state.  All lines inside the fence are skipped.
      The fence delimiter line itself is also skipped.
    - Inline code spans: single-backtick spans (`...`) are stripped from each
      line before the marker search so that examples in documentation prose
      do not trigger false positives.

    Returns list of (1-based line number, original line text) for each hit.
    """
    hits: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Fence toggle: a line starting with ``` opens or closes a code block.
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue  # fence delimiter line is not scanned
        if in_fence:
            continue
        # Strip inline code spans before checking for the marker.
        check_line = _INLINE_CODE_RE.sub("", line)
        if PLACEHOLDER_MARKER in check_line:
            hits.append((lineno, line.rstrip()))
    return hits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_doc_status(text: str) -> tuple[str | None, str | None]:
    """Return (status, error_message) parsed from document text.

    Looks for the first bare 'Status: <value>' line, skipping:
    - HTML comment blocks (<!-- ... -->) — used for inline documentation
    - Markdown bold lines (**Status:** ...) — human-readable metadata block

    Valid values: 'draft', 'frozen' (case-insensitive).

    Returns:
        (value, None)   -- status successfully parsed
        (None, message) -- status missing or unrecognised
    """
    in_html_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        # Skip HTML comment blocks.  Both single-line (<!-- ... -->) and
        # multi-line (<!-- \n ... \n -->) forms are handled.
        if not in_html_comment and "<!--" in stripped:
            in_html_comment = True
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            continue
        lower = stripped.lower()
        if lower.startswith("status:") and not stripped.startswith("**"):
            raw_value = stripped[7:].strip()
            value = raw_value.lower()
            if value in STATUS_VALID:
                return value, None
            return None, (
                f"unrecognised status {raw_value!r} "
                f"(expected 'draft' or 'frozen')"
            )
    return None, (
        "missing 'Status:' field "
        "(add a bare line 'Status: draft' or 'Status: frozen' to the document)"
    )


def find_placeholders(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line_text) for lines containing the marker.

    Skips fenced code blocks and inline code spans.
    Performs scanning regardless of document status — status-aware enforcement
    is handled by main().  Call this directly when you want to inspect
    placeholder presence independent of status.
    """
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return hits
    return _scan_for_placeholders(text)


def collect_files(targets: list[Path]) -> list[Path]:
    """Expand directories to markdown files; return files directly."""
    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            files.extend(sorted(target.rglob("*.md")))
        elif target.is_file():
            files.append(target)
        else:
            print(f"ERROR: path does not exist: {target}", file=sys.stderr)
            sys.exit(2)
    return files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            f"Fail if frozen scope docs contain {PLACEHOLDER_MARKER!r} markers."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help=(
            "Files or directories to check.  "
            f"Defaults to {_DEFAULT_SCOPE_DIR} if not supplied."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    raw_targets = [Path(p) for p in args.paths] if args.paths else [_DEFAULT_SCOPE_DIR]

    if not raw_targets:
        print("No targets specified.", file=sys.stderr)
        return 2

    files = collect_files(raw_targets)
    if not files:
        print("No markdown files found in the specified targets.", file=sys.stderr)
        return 0

    found_any = False
    skipped_draft = 0
    enforced = 0

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            found_any = True
            continue

        status, status_err = parse_doc_status(text)

        if status_err is not None:
            found_any = True
            print(f"STATUS ERROR: {path}")
            print(f"  {status_err}")
            continue

        if status == "draft":
            skipped_draft += 1
            continue

        # status == "frozen": enforce placeholder check (code-context-aware)
        enforced += 1
        hits = _scan_for_placeholders(text)

        if hits:
            found_any = True
            print(f"PLACEHOLDER found: {path}")
            for lineno, line_text in hits:
                print(f"  line {lineno}: {line_text}")

    if found_any:
        print(
            f"\nFAIL: unfilled placeholder markers ({PLACEHOLDER_MARKER!r}) "
            "found in frozen doc(s), or status field missing/invalid. "
            "Fill all placeholders before freezing.",
            file=sys.stderr,
        )
        return 1

    parts = [f"{enforced} frozen file(s) checked clean"]
    if skipped_draft:
        parts.append(f"{skipped_draft} draft file(s) skipped")
    print(f"OK: {', '.join(parts)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
