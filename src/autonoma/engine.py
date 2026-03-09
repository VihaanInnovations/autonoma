"""
Autonoma — Analysis Engine

Orchestrates: gather files → scan each → collect results.
Stateless, single-pass, deterministic.
"""
import os
import fnmatch
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple

from .scanner import Scanner
from .config import ConfigManager
from ._internal.heuristics import DEFAULT_EXTENSIONS, ALL_SUPPORTED_EXTENSIONS
from ._internal.merge_utils import make_issue_key


# Directories to always skip
SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', '.pytest_cache',
    'venv', '.venv', 'dist', 'build', '.tox', '.mypy_cache',
    '.eggs',
}


@dataclass
class FileResult:
    """Result for a single file."""
    file: str          # relative path
    abs_path: str      # absolute path
    issues: List[Dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None


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
    Orchestrates the full scan pipeline.

    Usage:
        engine = AnalysisEngine()
        report = engine.run(Path("."))
    """

    def __init__(self, allowed_extensions: Optional[Set[str]] = None):
        self._extensions = allowed_extensions or DEFAULT_EXTENSIONS
        self._scanner = Scanner(allowed_extensions=self._extensions)
        self._config = ConfigManager()

    def run(
        self,
        target: Path,
        exclude_patterns: Optional[List[str]] = None,
        verbose: bool = False,
        threads: int = 1,
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
        files = self._gather_files(target, exclude_patterns)

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

        issues = self._scanner.scan(content, str(file_path), disabled_rules)

        seen = set()
        unique_issues = []
        for issue in issues:
            key = make_issue_key(issue)
            if key not in seen:
                seen.add(key)
                unique_issues.append(issue)

        # Sort issues deterministically: by line, then rule_id
        unique_issues.sort(key=lambda i: (i.get("line", 0), i.get("id", "")))

        return FileResult(
            file=rel_path,
            abs_path=str(file_path),
            issues=unique_issues,
        )

    def _gather_files(self, target: Path, exclude_patterns: List[str]) -> List[Path]:
        """Gather files to analyze, respecting skip dirs and exclude patterns."""
        if target.is_file():
            if target.suffix in self._extensions:
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
                if file_path.suffix not in self._extensions:
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
                except ValueError:
                    pass

                files.append(file_path)

        return files

    def close(self):
        self._scanner.close()
