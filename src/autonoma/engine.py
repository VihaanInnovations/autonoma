"""
Autonoma — Analysis Engine

Runs scans. Finds files, passes them to the scanner, 
collects results. No state kept between runs.
"""
import ast
import os
import fnmatch
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple, Literal

from .scanner import Scanner
from .config import ConfigManager
from ._internal.heuristics import DEFAULT_EXTENSIONS, ALL_SUPPORTED_EXTENSIONS, _file_ext
from ._internal.merge_utils import make_issue_key
from . import __version__


# Directories to always skip
SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', '.pytest_cache',
    'venv', '.venv', 'dist', 'build', '.tox', '.mypy_cache',
    '.eggs',
}


Severity = Literal["low", "medium", "high"]
PatternType = Literal["password", "passwd", "api_key", "token", "generic_secret", "unknown", "parse_error"]


@dataclass(frozen=True)
class DetectFinding:
    """A finding from the remediation analysis pipeline (detect-only mode)."""
    file: str
    line: int
    col: int
    pattern_type: PatternType
    severity: Severity
    safe_to_fix: bool
    refusal_reason: Optional[str]
    suggested_env_var: Optional[str]
    rule_id: str
    fingerprint: str
    provider: Optional[str] = None
    decision_trace: Optional[dict] = None


@dataclass(frozen=True)
class DetectSummary:
    """Summary stats for detect-only mode."""
    files_processed: int
    total_findings: int
    safe_to_fix: int
    refused: int


@dataclass(frozen=True)
class DetectReport:
    """Complete report for detect-only mode."""
    schema_version: str = "1.0"
    tool_name: str = "autonoma"
    tool_version: str = __version__
    generated_at: str = ""  # Populated at runtime
    mode: str = "detect-only"
    summary: Optional[DetectSummary] = None
    findings: List[DetectFinding] = field(default_factory=list)


@dataclass
class FileResult:
    """Result for a single file."""
    file: str          # relative path
    abs_path: str      # absolute path
    issues: List[Dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None
    parse_valid: bool = True  # False when the file failed AST parse (SyntaxError)


@dataclass
class AnalysisReport:
    """Complete analysis report."""
    files_scanned: int = 0
    files_skipped: int = 0
    total_issues: int = 0
    high_count: int = 0
    file_results: List[FileResult] = field(default_factory=list)

    @property
    def all_issues(self) -> List[Dict[str, Any]]:
        """All issues across all files, sorted deterministically."""
        issues = []
        for fr in sorted(self.file_results, key=lambda r: r.file):
            for issue in sorted(fr.issues, key=lambda i: (i.get("line", 0), i.get("id", ""))):
                enriched = dict(issue)
                enriched["file"] = fr.file
                issues.append(enriched)
        return issues


class AnalysisEngine:
    """
    Runs the scan. Call run() with a path, get a report back.

    Usage:
        engine = AnalysisEngine()
        report = engine.run(Path("."))
    """

    def __init__(self, allowed_extensions: Optional[Set[str]] = None):
        self._extensions = allowed_extensions or DEFAULT_EXTENSIONS
        self._scanner = Scanner(allowed_extensions=self._extensions)
        self._config = ConfigManager()

    # Path substrings that identify test files
    _TEST_PATH_MARKERS = ("tests/", "test_", "_test.py", "conftest.py", "spec/", "fixtures/", "testdata/")
    # Path substrings that identify documentation files
    _DOCS_PATH_MARKERS = ("docs/", "docs_src/", "examples/", "tutorial/", "documentation/", "readme")

    def run(
        self,
        target: Path,
        exclude_patterns: Optional[List[str]] = None,
        verbose: bool = False,
        threads: int = 1,
        exclude_tests: bool = True,
        exclude_docs: bool = False,
    ) -> AnalysisReport:
        """
        Run analysis on a file or directory.

        Returns:
            AnalysisReport with deterministic ordering.
        """
        target = target.resolve()
        base_path = target.parent if target.is_file() else target
        exclude_patterns = list(exclude_patterns or [])

        # Resolve config
        user_config = self._config.resolve_config(str(base_path))
        disabled_rules = set(user_config.get("disabled_rules", []))

        # Gather ignore patterns from .autonomaignore
        ignore_file = base_path / ".autonomaignore"
        if ignore_file.exists() and ignore_file.is_file():
            try:
                for line in ignore_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        exclude_patterns.append(line)
            except Exception:
                pass

        # Gather files
        files = self._gather_files(target, exclude_patterns, exclude_tests=exclude_tests, exclude_docs=exclude_docs)

        # Sort for deterministic ordering
        files.sort()

        report = AnalysisReport()

        def _scan_wrapper(file_path: Path) -> FileResult:
            return self._process_file(file_path, base_path, disabled_rules)

        if threads > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
                # executor.map guarantees results are yielded in exactly the same order
                # as the input `files` iterable, preserving our strict deterministic sorting.
                results = list(executor.map(_scan_wrapper, files))
        else:
            results = [_scan_wrapper(f) for f in files]

        for file_res in results:
            if file_res.skipped:
                report.files_skipped += 1
            else:
                report.files_scanned += 1
                report.total_issues += len(file_res.issues)
                report.high_count += sum(
                    1 for i in file_res.issues
                    if str(i.get("severity", "")).lower() == "high"
                )
            report.file_results.append(file_res)

        return report

    def _process_file(self, file_path: Path, base_path: Path, disabled_rules: Set[str]) -> FileResult:
        """Thread-safe worker function to scan a single file."""
        rel_path = str(file_path.relative_to(base_path))

        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            return FileResult(
                file=rel_path,
                abs_path=str(file_path),
                skipped=True,
                skip_reason=str(e),
            )

        # For Python files, detect parse failures before running the scanner.
        # A SyntaxError makes structural rewriting unsafe, so we emit one
        # synthetic PARSE_ERROR finding and skip further analysis of this file.
        if file_path.suffix == ".py":
            try:
                ast.parse(content)
            except SyntaxError as e:
                synthetic_issue = {
                    "id": "PARSE_ERROR",
                    "line": e.lineno or 1,
                    "col_offset": max(0, (e.offset or 1) - 1),
                    "end_col_offset": None,
                    "message": (
                        "File contains a syntax error; "
                        "safe structural rewrite cannot be proven."
                    ),
                    "type": "security",
                    "severity": "high",
                    "source": "parse_error",
                    "pattern_type": "parse_error",
                    "truncated_secret": None,
                    "provider": None,
                    "fingerprint": "sha256:parse_error",
                }
                return FileResult(
                    file=rel_path,
                    abs_path=str(file_path),
                    issues=[synthetic_issue],
                    parse_valid=False,
                )

        issues = self._scanner.scan(content, str(file_path), disabled_rules)

        # Deduplicate issues by (id, line) and overlapping spans
        # Group issues by (rule_id, line)
        groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for issue in issues:
            key = (issue.get("id", "unknown"), issue.get("line", 0))
            if key not in groups:
                groups[key] = []
            groups[key].append(issue)

        unique_issues = []
        for (rule_id, line), group in groups.items():
            # Sort by col_offset to make merging easier
            group.sort(key=lambda i: i.get("col_offset", -1))
            
            merged_in_group = []
            for issue in group:
                if not merged_in_group:
                    merged_in_group.append(issue)
                    continue
                
                prev = merged_in_group[-1]
                
                # Check for overlap
                # Span 1: [start1, end1], Span 2: [start2, end2]
                start1 = prev.get("col_offset", -1)
                end1 = prev.get("end_col_offset") or (start1 + 1)
                
                start2 = issue.get("col_offset", -1)
                end2 = issue.get("end_col_offset") or (start2 + 1)
                
                # If they overlap, keep one (prefer AST if available, or just the first)
                if max(start1, start2) < min(end1, end2):
                    # Overlap detected! 
                    # Prefer the one with a more descriptive message or specifically from AST
                    if issue.get("source") == "ast_engine_native" and prev.get("source") != "ast_engine_native":
                        merged_in_group[-1] = issue
                    continue
                else:
                    merged_in_group.append(issue)
            
            unique_issues.extend(merged_in_group)

        # Sort issues deterministically: by line, then rule_id
        unique_issues.sort(key=lambda i: (i.get("line", 0), i.get("id", "")))

        return FileResult(
            file=rel_path,
            abs_path=str(file_path),
            issues=unique_issues,
        )

    def _gather_files(
        self,
        target: Path,
        exclude_patterns: List[str],
        exclude_tests: bool = True,
        exclude_docs: bool = False,
    ) -> List[Path]:
        """Gather files to analyze, respecting skip dirs and exclude patterns."""
        if target.is_file():
            if _file_ext(str(target)) in self._extensions:
                rel_str = target.name
                if exclude_tests and any(m in rel_str for m in self._TEST_PATH_MARKERS):
                    return []
                if exclude_docs and any(m in rel_str for m in self._DOCS_PATH_MARKERS):
                    return []
                return [target]
            return []

        files = []
        for root, dirs, filenames in os.walk(target):
            # Remove skip directories in-place
            dirs[:] = [
                d for d in dirs
                if d not in SKIP_DIRS and not any(
                    fnmatch.fnmatch(d, p) or fnmatch.fnmatch(d + '/', p)
                    for p in exclude_patterns
                )
            ]

            for filename in filenames:
                file_path = Path(root) / filename
                if _file_ext(str(file_path)) not in self._extensions:
                    continue

                # Check exclude patterns against relative path
                try:
                    rel = file_path.relative_to(target)
                    rel_str = rel.as_posix()
                    if any(
                        fnmatch.fnmatch(rel_str, p) or
                        fnmatch.fnmatch(rel_str.split('/')[0], p) or
                        fnmatch.fnmatch(file_path.name, p)
                        for p in exclude_patterns
                    ):
                        continue

                    # FIX 3: Skip test files if requested
                    if exclude_tests and any(m in rel_str for m in self._TEST_PATH_MARKERS):
                        continue

                    # FIX 4: Skip doc files if requested
                    if exclude_docs and any(m in rel_str for m in self._DOCS_PATH_MARKERS):
                        continue
                except ValueError:
                    pass

                files.append(file_path)

        return files

    def close(self):
        self._scanner.close()
