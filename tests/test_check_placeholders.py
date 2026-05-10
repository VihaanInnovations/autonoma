"""
Tests for bench/scripts/check_placeholders.py.

Covers:
- detects _(placeholder)_ in scope docs (find_placeholders, status-unaware)
- passes when docs have no placeholders
- reports offending files and line numbers
- handles multiple files
- handles empty directories gracefully
- status-aware enforcement: draft => skip, frozen => enforce
- missing or invalid status => fail
- parse_doc_status unit tests
- integration: actual scope docs are draft, so CI passes
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "bench" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cp():
    return _load("check_placeholders", SCRIPTS_DIR / "check_placeholders.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _frozen(content: str) -> str:
    """Prepend 'Status: frozen' so CLI tests get a valid frozen doc."""
    return f"Status: frozen\n\n{content}"


def _draft(content: str) -> str:
    """Prepend 'Status: draft' so CLI tests get a valid draft doc."""
    return f"Status: draft\n\n{content}"


# ---------------------------------------------------------------------------
# Core detection — find_placeholders() is status-unaware (raw text search)
# ---------------------------------------------------------------------------

def test_placeholder_detected(tmp_path, cp):
    doc = _write_md(tmp_path, "scope.md", "**Commit SHA:** _(placeholder)_\n")
    result = cp.find_placeholders(doc)
    assert len(result) == 1
    lineno, line_text = result[0]
    assert lineno == 1
    assert "_(placeholder)_" in line_text


def test_no_placeholder_clean(tmp_path, cp):
    doc = _write_md(tmp_path, "scope.md", "**Commit SHA:** abc123def456\n")
    result = cp.find_placeholders(doc)
    assert result == []


def test_multiple_placeholders_in_one_file(tmp_path, cp):
    content = (
        "**SHA:** _(placeholder)_\n"
        "Normal line\n"
        "**Version:** _(placeholder)_\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 2
    assert result[0][0] == 1
    assert result[1][0] == 3


def test_placeholder_line_number_correct(tmp_path, cp):
    content = "line 1\nline 2\n_(placeholder)_\nline 4\n"
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 1
    assert result[0][0] == 3


# ---------------------------------------------------------------------------
# parse_doc_status — unit tests
# ---------------------------------------------------------------------------

def test_parse_status_draft(cp):
    status, err = cp.parse_doc_status("Status: draft\n\nSome content.\n")
    assert status == "draft"
    assert err is None


def test_parse_status_frozen(cp):
    status, err = cp.parse_doc_status("Status: frozen\n\nSome content.\n")
    assert status == "frozen"
    assert err is None


def test_parse_status_case_insensitive(cp):
    for raw in ("Status: Draft\n", "STATUS: FROZEN\n", "status: frozen\n"):
        status, err = cp.parse_doc_status(raw)
        assert err is None, f"Should accept {raw!r}"
        assert status in ("draft", "frozen")


def test_parse_status_missing_returns_error(cp):
    status, err = cp.parse_doc_status("**SHA:** _(placeholder)_\nNo status line.\n")
    assert status is None
    assert err is not None
    assert "missing" in err.lower() or "Status" in err


def test_parse_status_invalid_value_returns_error(cp):
    status, err = cp.parse_doc_status("Status: pending\n\nContent.\n")
    assert status is None
    assert err is not None
    assert "pending" in err or "unrecognised" in err.lower()


def test_parse_status_bold_markdown_ignored(cp):
    """**Status:** bold lines must not be parsed as the document status."""
    text = "**Status:** Pre-pass (scope registered)\nSome body.\n"
    status, err = cp.parse_doc_status(text)
    assert status is None
    assert err is not None  # no bare Status: line → missing error


def test_parse_status_bold_ignored_bare_wins(cp):
    """When both a bold **Status:** and a bare Status: line exist, bare line wins."""
    text = (
        "**Status:** Active\n"
        "Status: frozen\n"
        "Content.\n"
    )
    status, err = cp.parse_doc_status(text)
    assert status == "frozen"
    assert err is None


def test_parse_status_whitespace_trimmed(cp):
    status, err = cp.parse_doc_status("  Status:  draft  \n")
    assert status == "draft"
    assert err is None


def test_parse_status_html_comment_skipped(cp):
    """Status: inside an HTML comment block must be ignored; bare field wins."""
    text = (
        "<!--\n"
        "Status: draft  = work in progress\n"
        "Status: frozen = published artifact\n"
        "-->\n"
        "\n"
        "Status: draft\n"
    )
    status, err = cp.parse_doc_status(text)
    assert status == "draft"
    assert err is None


def test_parse_status_html_comment_single_line_skipped(cp):
    """Single-line HTML comment (<!-- ... -->) must be skipped."""
    text = "<!-- Status: frozen -->\nStatus: draft\n"
    status, err = cp.parse_doc_status(text)
    assert status == "draft"
    assert err is None


def test_parse_status_html_comment_only_missing(cp):
    """Doc with Status: only inside an HTML comment must report 'missing'."""
    text = "<!--\nStatus: draft\n-->\nNo bare status line here.\n"
    status, err = cp.parse_doc_status(text)
    assert status is None
    assert err is not None
    assert "missing" in err.lower() or "Status" in err


# ---------------------------------------------------------------------------
# CLI exit codes — status-aware behavior
# ---------------------------------------------------------------------------

def test_draft_doc_with_placeholders_passes(tmp_path, cp):
    """Draft docs with placeholder markers must pass (exit 0)."""
    _write_md(tmp_path, "scope.md",
              _draft("**SHA:** _(placeholder)_\n"))
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 0, "Draft docs with placeholders must not fail"


def test_frozen_doc_with_placeholders_fails(tmp_path, cp):
    """Frozen docs with placeholder markers must fail (exit 1)."""
    _write_md(tmp_path, "scope.md",
              _frozen("**SHA:** _(placeholder)_\n"))
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Frozen docs with placeholders must fail"


def test_frozen_doc_without_placeholders_passes(tmp_path, cp):
    """Frozen docs with all fields filled must pass (exit 0)."""
    _write_md(tmp_path, "scope.md",
              _frozen("**SHA:** abc123def456\n"))
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 0, "Frozen docs with no placeholders must pass"


def test_missing_status_fails(tmp_path, cp):
    """Docs without a Status field must fail (exit 1)."""
    _write_md(tmp_path, "scope.md", "**SHA:** abc123def456\n")
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Missing Status field must fail"


def test_invalid_status_fails(tmp_path, cp):
    """Docs with an unrecognised status value must fail (exit 1)."""
    _write_md(tmp_path, "scope.md", "Status: pending\n\n**SHA:** abc123\n")
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Invalid status must fail"


# ---------------------------------------------------------------------------
# CLI exit codes — pre-existing tests updated with Status: frozen
# ---------------------------------------------------------------------------

def test_cli_returns_1_when_placeholder_found(tmp_path, cp):
    _write_md(tmp_path, "scope.md",
              _frozen("**SHA:** _(placeholder)_\n"))
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1


def test_cli_returns_0_when_clean(tmp_path, cp):
    _write_md(tmp_path, "scope.md",
              _frozen("**SHA:** abc123def456\n"))
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 0


def test_cli_directory_scans_md_files(tmp_path, cp):
    sub = tmp_path / "scope"
    sub.mkdir()
    _write_md(sub, "a.md", _frozen("**SHA:** abc123\n"))
    _write_md(sub, "b.md", _frozen("**SHA:** _(placeholder)_\n"))
    rc = cp.main([str(sub)])
    assert rc == 1


def test_cli_directory_clean(tmp_path, cp):
    sub = tmp_path / "scope"
    sub.mkdir()
    _write_md(sub, "a.md", _frozen("**SHA:** abc123\n"))
    _write_md(sub, "b.md", _frozen("**Version:** 1.1\n"))
    rc = cp.main([str(sub)])
    assert rc == 0


def test_cli_multiple_files(tmp_path, cp):
    clean = _write_md(tmp_path, "clean.md", _frozen("**SHA:** abc123\n"))
    dirty = _write_md(tmp_path, "dirty.md", _frozen("**SHA:** _(placeholder)_\n"))
    rc = cp.main([str(clean), str(dirty)])
    assert rc == 1


def test_cli_nonexistent_path_exits_nonzero(tmp_path, cp, monkeypatch):
    with pytest.raises(SystemExit) as exc_info:
        cp.main([str(tmp_path / "does_not_exist.md")])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Mixed directory: draft files skip, frozen files enforce
# ---------------------------------------------------------------------------

def test_mixed_draft_frozen_directory(tmp_path, cp):
    """Draft files with placeholders must be skipped; only frozen files enforced."""
    sub = tmp_path / "scope"
    sub.mkdir()
    _write_md(sub, "draft.md", _draft("**SHA:** _(placeholder)_\n"))
    _write_md(sub, "frozen_clean.md", _frozen("**SHA:** abc123\n"))
    rc = cp.main([str(sub)])
    assert rc == 0, "Draft file with placeholder must not cause failure"


def test_mixed_draft_frozen_frozen_fails(tmp_path, cp):
    """A frozen file with placeholders fails even when draft files are present."""
    sub = tmp_path / "scope"
    sub.mkdir()
    _write_md(sub, "draft.md", _draft("**SHA:** _(placeholder)_\n"))
    _write_md(sub, "frozen.md", _frozen("**SHA:** _(placeholder)_\n"))
    rc = cp.main([str(sub)])
    assert rc == 1, "Frozen file with placeholder must fail"


# ---------------------------------------------------------------------------
# Variant marker forms — only exact string is matched
# ---------------------------------------------------------------------------

def test_partial_marker_not_matched(tmp_path, cp):
    """Only the exact string _(placeholder)_ must trigger; partial matches don't."""
    doc = _write_md(tmp_path, "scope.md", "placeholder text here\n")
    result = cp.find_placeholders(doc)
    assert result == [], "Partial 'placeholder' text must not trigger the check"


def test_exact_marker_in_inline_context(tmp_path, cp):
    doc = _write_md(
        tmp_path, "scope.md",
        "**Commit SHA:** _(placeholder — fill before freezing)_\n"
    )
    result = cp.find_placeholders(doc)
    assert result == [], (
        "Longer placeholder annotation must not match exact _(placeholder)_ sentinel"
    )


# ---------------------------------------------------------------------------
# Explanatory instruction text vs. actual placeholder fields
# ---------------------------------------------------------------------------

def test_checker_ignores_non_sentinel_instruction_text(tmp_path, cp):
    """Instruction text describing placeholders without the sentinel must not trigger."""
    doc = _write_md(
        tmp_path, "scope.md",
        "## Instructions\n"
        "Fill all placeholder fields before freezing.\n"
        "**Commit SHA:** abc123def456\n",
    )
    result = cp.find_placeholders(doc)
    assert result == [], (
        "Instruction text without _(placeholder)_ must not trigger the checker"
    )


def test_checker_catches_actual_placeholder_field(tmp_path, cp):
    """Real unfilled placeholder fields (_(placeholder)_) must be detected."""
    doc = _write_md(
        tmp_path, "scope.md",
        "## Metadata\n"
        "**Commit SHA:** _(placeholder)_\n"
        "Fill all placeholder fields before freezing.\n",
    )
    result = cp.find_placeholders(doc)
    assert len(result) == 1, "Exactly one unfilled field must be found"
    assert "Commit SHA" in result[0][1]


def test_checker_instruction_text_with_sentinel_in_backticks_ignored(tmp_path, cp):
    """Instruction text using the sentinel inside backticks must NOT trigger the checker.

    Inline code spans are ignored by the scanner, so documentation examples
    that reference _(placeholder)_ inside backticks are safe.
    """
    doc = _write_md(
        tmp_path, "scope.md",
        "Fill `_(placeholder)_` fields before freezing.\n",
    )
    result = cp.find_placeholders(doc)
    assert result == [], (
        "Sentinel inside backticks is inline code and must be ignored"
    )


def test_checker_bare_sentinel_in_prose_triggers(tmp_path, cp):
    """Bare _(placeholder)_ in prose (outside any code context) must trigger."""
    doc = _write_md(
        tmp_path, "scope.md",
        "Fill _(placeholder)_ fields before freezing.\n",
    )
    result = cp.find_placeholders(doc)
    assert len(result) == 1, (
        "Bare sentinel in prose must still trigger the checker"
    )


# ---------------------------------------------------------------------------
# Code-context awareness — fenced code blocks (find_placeholders unit tests)
# ---------------------------------------------------------------------------

def test_fenced_block_placeholder_ignored(tmp_path, cp):
    """Placeholder inside a fenced code block must not be reported."""
    content = (
        "Normal prose.\n"
        "```\n"
        "api_key = _(placeholder)_\n"
        "```\n"
        "More prose.\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert result == [], "Placeholder inside ``` fence must be ignored"


def test_fenced_block_with_language_specifier_ignored(tmp_path, cp):
    """Fenced block with language tag (e.g. ```python) must also be ignored."""
    content = (
        "```python\n"
        "SECRET = '_(placeholder)_'\n"
        "```\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert result == [], "Placeholder in ```python fence must be ignored"


def test_fenced_block_fence_delimiter_not_reported(tmp_path, cp):
    """The ``` fence delimiter line itself must not count as a hit."""
    content = "```\n_(placeholder)_ is here\n```\n"
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert result == [], "Lines inside or on fence delimiters must not be reported"


def test_placeholder_outside_fence_still_detected(tmp_path, cp):
    """Placeholder in prose surrounding a fenced block must still be detected."""
    content = (
        "**SHA:** _(placeholder)_\n"
        "```\n"
        "safe_example = 'not flagged'\n"
        "```\n"
        "**Version:** 1.0\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 1
    assert result[0][0] == 1  # line 1


def test_placeholder_after_fence_closes_detected(tmp_path, cp):
    """Placeholders after a fence closes must be detected normally."""
    content = (
        "```\n"
        "safe = _(placeholder)_\n"
        "```\n"
        "**SHA:** _(placeholder)_\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 1
    assert result[0][0] == 4  # only the prose line after the fence


def test_multiple_fences_all_ignored(tmp_path, cp):
    """Multiple fenced blocks in one doc — all placeholders inside ignored."""
    content = (
        "Intro.\n"
        "```\n"
        "x = _(placeholder)_\n"
        "```\n"
        "Middle.\n"
        "```yaml\n"
        "key: _(placeholder)_\n"
        "```\n"
        "End.\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert result == [], "All fenced-block placeholders must be ignored"


# ---------------------------------------------------------------------------
# Code-context awareness — inline code spans (find_placeholders unit tests)
# ---------------------------------------------------------------------------

def test_inline_code_placeholder_ignored(tmp_path, cp):
    """Placeholder inside a backtick inline code span must not be reported."""
    content = "See the `_(placeholder)_` pattern for field values.\n"
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert result == [], "Placeholder inside backticks must be ignored"


def test_inline_code_does_not_suppress_prose_placeholder(tmp_path, cp):
    """Inline code elsewhere on a line must not suppress a bare prose placeholder."""
    content = "Use `some_func()` to set _(placeholder)_ here.\n"
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 1, "Bare placeholder must be found even when inline code present"


def test_metadata_field_placeholder_detected(tmp_path, cp):
    """Placeholder in a metadata field line (prose, not code) must be detected."""
    content = "**Detector Commit SHA:** _(placeholder)_\n"
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 1


def test_table_placeholder_detected(tmp_path, cp):
    """Placeholder in a table cell must be detected."""
    content = (
        "| Repo | Commit SHA |\n"
        "|------|------------|\n"
        "| flask | _(placeholder)_ |\n"
    )
    doc = _write_md(tmp_path, "scope.md", content)
    result = cp.find_placeholders(doc)
    assert len(result) == 1
    assert result[0][0] == 3


# ---------------------------------------------------------------------------
# CLI: code-context-aware enforcement for frozen docs
# ---------------------------------------------------------------------------

def test_frozen_fenced_block_passes(tmp_path, cp):
    """Frozen doc with placeholder inside a fenced block must pass (exit 0)."""
    content = _frozen(
        "**SHA:** abc123\n"
        "```\n"
        "example = _(placeholder)_\n"
        "```\n"
    )
    _write_md(tmp_path, "scope.md", content)
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 0, "Placeholder inside fenced block must not fail frozen doc"


def test_frozen_inline_code_passes(tmp_path, cp):
    """Frozen doc with placeholder inside inline code must pass (exit 0)."""
    content = _frozen(
        "**SHA:** abc123\n"
        "See `_(placeholder)_` for the field format.\n"
    )
    _write_md(tmp_path, "scope.md", content)
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 0, "Placeholder inside inline backticks must not fail frozen doc"


def test_frozen_prose_placeholder_fails(tmp_path, cp):
    """Frozen doc with a bare prose placeholder must fail (exit 1)."""
    content = _frozen("Set the value to _(placeholder)_ before publishing.\n")
    _write_md(tmp_path, "scope.md", content)
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Bare prose placeholder must fail frozen doc"


def test_frozen_metadata_placeholder_fails(tmp_path, cp):
    """Frozen doc with a metadata field placeholder must fail (exit 1)."""
    content = _frozen("**Detector Commit SHA:** _(placeholder)_\n")
    _write_md(tmp_path, "scope.md", content)
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Metadata placeholder must fail frozen doc"


def test_frozen_table_placeholder_fails(tmp_path, cp):
    """Frozen doc with a table cell placeholder must fail (exit 1)."""
    content = _frozen(
        "| Repo | Commit SHA |\n"
        "|------|------------|\n"
        "| flask | _(placeholder)_ |\n"
    )
    _write_md(tmp_path, "scope.md", content)
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Table cell placeholder must fail frozen doc"


# ---------------------------------------------------------------------------
# Unknown status (regression)
# ---------------------------------------------------------------------------

def test_unknown_status_typo_fails(tmp_path, cp):
    """A typo in the status value (e.g. 'drafr') must fail with STATUS ERROR."""
    _write_md(tmp_path, "scope.md", "Status: drafr\n\n**SHA:** abc123\n")
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1, "Typo in status value must fail (STATUS ERROR, not pass)"


def test_unknown_status_arbitrary_word_fails(tmp_path, cp):
    """Any unrecognised status word must fail."""
    _write_md(tmp_path, "scope.md", "Status: pending\n\n**SHA:** abc123\n")
    rc = cp.main([str(tmp_path / "scope.md")])
    assert rc == 1


# ---------------------------------------------------------------------------
# Scope docs integration
# ---------------------------------------------------------------------------

def test_actual_scope_docs_have_placeholders(cp):
    """The real scope docs contain unfilled _(placeholder)_ markers.

    This test uses find_placeholders() directly (status-unaware) to prove
    the placeholder markers are present.  The docs are currently 'draft'
    status, so main() correctly skips enforcement for them.
    """
    scope_dir = Path(__file__).parent.parent / "docs" / "scope"
    if not scope_dir.exists():
        pytest.skip("docs/scope/ does not exist")

    scope_files = list(scope_dir.glob("*.md"))
    if not scope_files:
        pytest.skip("No .md files in docs/scope/")

    all_hits = {}
    for f in scope_files:
        hits = cp.find_placeholders(f)
        if hits:
            all_hits[f.name] = hits

    assert all_hits, (
        "Expected docs/scope/*.md to contain _(placeholder)_ markers "
        "(they are scaffolding docs with fields to be filled at benchmark freeze)."
    )


def test_scope_docs_draft_ci_passes(cp):
    """Current scope docs are 'Status: draft' — CI placeholder check must pass (exit 0).

    This proves the CI gate is green for the current pre-pass state and will
    only fail once a doc is frozen with unfilled placeholders.
    """
    scope_dir = Path(__file__).parent.parent / "docs" / "scope"
    if not scope_dir.exists():
        pytest.skip("docs/scope/ does not exist")

    rc = cp.main([str(scope_dir)])
    assert rc == 0, (
        "Scope docs with 'Status: draft' must not fail the placeholder checker. "
        "CI should be green until docs are frozen with unfilled placeholders."
    )
