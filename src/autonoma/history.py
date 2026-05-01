"""
Autonoma — History Engine

Orchestrates git history scanning.
Pulls commits from `git.py` and feeds added lines into `Scanner`.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
import fnmatch
import concurrent.futures

from .scanner import Scanner
from .config import ConfigManager
from ._internal.heuristics import DEFAULT_EXTENSIONS
from ._internal.git import parse_git_log_p, GitCommit


@dataclass
class HistoryFinding:
    """A single secret found in a historical commit."""
    commit_hash: str
    author_date: str
    commit_message: str
    file: str
    line_number: int
    rule_id: str
    severity: str
    message: str


@dataclass
class HistoryReport:
    """Complete history analysis report."""
    commits_scanned: int = 0
    total_findings: int = 0
    findings: List[HistoryFinding] = field(default_factory=list)


class HistoryEngine:
    """
    Orchestrates the git history scan pipeline.

    Usage:
        engine = HistoryEngine()
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
    ) -> HistoryReport:
        """
        Run history analysis on a git repository.
        """
        target = target.resolve()
        exclude_patterns = exclude_patterns or []
        
        # Gather ignore patterns from .autonomaignore
        ignore_file = target / ".autonomaignore"
        if ignore_file.exists() and ignore_file.is_file():
            try:
                for line in ignore_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        exclude_patterns.append(line)
            except Exception:
                pass
        
        # Resolve config
        user_config = self._config.resolve_config(str(target))
        disabled_rules = set(user_config.get("disabled_rules", []))
        
        report = HistoryReport()
        
        # Iterate over all commits that added text to allowed extensions
        commit_stream = parse_git_log_p(target, self._extensions)
        
        # We don't deduplicate by issue key here, because the identical secret 
        # might be added in multiple commits (e.g. reverted and re-added).
        # We want to show the full trail.
        
        def _scan_wrapper(file_diff) -> List[HistoryFinding]:
            return self._process_diff(file_diff, commit.hash, commit.author_date, commit.message, exclude_patterns, disabled_rules)
            
        for commit in commit_stream:
            report.commits_scanned += 1
            
            if threads > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
                    diff_findings_lists = list(executor.map(_scan_wrapper, commit.file_diffs))
            else:
                diff_findings_lists = [_scan_wrapper(fd) for fd in commit.file_diffs]
                
            for findings in diff_findings_lists:
                if findings:
                    report.findings.extend(findings)
                    report.total_findings += len(findings)

        return report

    def _process_diff(
        self, 
        file_diff, 
        commit_hash: str, 
        author_date: str, 
        commit_message: str, 
        exclude_patterns: List[str], 
        disabled_rules: Set[str]
    ) -> List[HistoryFinding]:
        """Thread-safe worker function to process a single Git Diff file."""
        findings = []
        
        # Check exclude patterns
        try:
            fp = Path(file_diff.file_path)
            rel_str = fp.as_posix()
            if any(
                fnmatch.fnmatch(rel_str, p) or 
                fnmatch.fnmatch(rel_str.split('/')[0], p) or
                fnmatch.fnmatch(fp.name, p)
                for p in exclude_patterns
            ):
                return findings
        except ValueError:
            pass

        for added_line in file_diff.added_lines:
            # Trailing newline needed for regex matching algorithms
            content = added_line.content + "\n"
            
            issues = self._scanner.scan(
                content=content,
                file_path=file_diff.file_path,  # Extension is what matters here
                disabled_rules=disabled_rules
            )
            
            for issue in issues:
                findings.append(HistoryFinding(
                    commit_hash=commit_hash,
                    author_date=author_date,
                    commit_message=commit_message,
                    file=file_diff.file_path,
                    line_number=added_line.line_number,
                    rule_id=issue.get("id", "?"),
                    severity=issue.get("severity", "?"),
                    message=issue.get("message", "")
                ))
        return findings
        
        return report

    def close(self):
        self._scanner.close()
