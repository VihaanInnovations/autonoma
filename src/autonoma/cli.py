"""
Autonoma — CLI

Single-process, daemon-free security scanner.
"""
import sys
from pathlib import Path

import click

from . import __version__
from ._internal.heuristics import ALL_SUPPORTED_EXTENSIONS
from .engine import AnalysisEngine
from .history import HistoryEngine
from .fixer import fix_file_issues, FixOutcome, FIXED, REFUSED, SKIPPED, FAILED
from .reporter import report_text, report_json, report_fix_outcomes, report_history_text, report_history_json


@click.group()
@click.version_option(__version__, prog_name="Autonoma", message="%(prog)s %(version)s")
def cli():
    """Autonoma — Deterministic code security scanner."""
    pass


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", help="Output format.")
@click.option("--fail-on-findings", is_flag=True, help="Exit 1 if any issues are found.")
@click.option("--verbose", is_flag=True, help="Show progress and debug info.")
@click.option("--exclude", multiple=True, help="Glob patterns to exclude (repeatable).")
@click.option("--include-ext", multiple=True, help="Extra extensions to scan, e.g. --include-ext .js --include-ext .ts")
@click.option("--auto-fix", is_flag=True, help="Auto-fix SEC001/SEC002 issues (deterministic, with .bak backup).")
@click.option("--dry-run", is_flag=True, help="Preview auto-fix patches without writing files.")
@click.option("--diff", is_flag=True, help="Preview auto-fix via git-style unified diff patch.")
@click.option("--ci", is_flag=True, help="Run in CI mode with specific exit codes (0=clean, 1=secrets, 2=fixable).")
@click.option("--json", is_flag=True, help="Output a single machine-readable JSON payload.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.option("--threads", "-t", type=int, default=1, help="Number of concurrent threads to use for scanning.")
def analyze(path, fmt, fail_on_findings, verbose, exclude, include_ext, auto_fix, dry_run, diff, ci, json, quiet, threads):
    """Analyze a file or directory for security issues."""
    try:
        target = Path(path).resolve()

        if json:
            fmt = "json"

        # --diff implies --dry-run
        if diff:
            dry_run = True

        # --dry-run implies --auto-fix
        if dry_run:
            auto_fix = True

        # Build allowed extensions set
        allowed = {".py"}
        for ext in include_ext:
            ext = ext if ext.startswith(".") else f".{ext}"
            if ext in ALL_SUPPORTED_EXTENSIONS:
                allowed.add(ext)
            else:
                click.echo(f"Warning: '{ext}' not supported. Supported: {sorted(ALL_SUPPORTED_EXTENSIONS)}", err=True)

        engine = AnalysisEngine(allowed_extensions=allowed)

        try:
            report = engine.run(
                target=target,
                exclude_patterns=list(exclude),
                verbose=verbose,
                threads=threads,
            )
        finally:
            engine.close()

        # Output text scan results immediately (JSON is deferred)
        if fmt != "json":
            report_text(report, verbose=verbose, quiet=quiet)

        # Auto-fix: batch per file
        all_outcomes = []
        all_diffs = []
        if auto_fix and report.total_issues > 0:
            base_path = target.parent if target.is_file() else target

            for fr in sorted(report.file_results, key=lambda r: r.file):
                if fr.skipped or not fr.issues:
                    continue

                file_path = Path(fr.abs_path)

                try:
                    code = file_path.read_text(encoding="utf-8")
                except Exception as e:
                    for issue in fr.issues:
                        all_outcomes.append(FixOutcome(
                            state=FAILED,
                            issue_id=issue.get("id", "?"),
                            file=fr.file,
                            line=issue.get("line"),
                            message=f"Cannot read file: {e}",
                        ))
                    continue

                # One call per file — batched internally
                # dry_run → write=False (preview only)
                outcomes, diff_patch = fix_file_issues(
                    code=code,
                    file_path=file_path,
                    issues=fr.issues,
                    repo_path=base_path,
                    write=not dry_run,
                )
                all_outcomes.extend(outcomes)
                if diff_patch and diff:
                    all_diffs.append(diff_patch)

            report_fix_outcomes(all_outcomes, fmt=fmt, dry_run=dry_run, diff_patches=all_diffs if diff else None, quiet=quiet)

        if fmt == "json":
            report_json(report, fix_outcomes=all_outcomes if (auto_fix and report.total_issues > 0) else None, dry_run=dry_run)

        # Exit code
        if ci:
            fixable_count = sum(
                1 for i in report.all_issues
                if str(i.get("severity", "")).lower() == "high" and i.get("id") in ("SEC001", "SEC002")
            )
            if report.total_issues == 0:
                sys.exit(0)
            elif fixable_count > 0:
                sys.exit(2)
            else:
                sys.exit(1)
        
        if fail_on_findings and report.total_issues > 0:
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(3)

@cli.command(name="history-scan")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--fail-on-findings", is_flag=True, help="Exit 1 if any issues are found in history.")
@click.option("--verbose", is_flag=True, help="Show progress and debug info.")
@click.option("--exclude", multiple=True, help="Glob patterns to exclude (repeatable).")
@click.option("--include-ext", multiple=True, help="Extra extensions to scan, e.g. --include-ext .js --include-ext .ts")
@click.option("--json", is_flag=True, help="Output a single machine-readable JSON payload.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.option("--threads", "-t", type=int, default=1, help="Number of concurrent threads to use for scanning.")
def history_scan(path, fail_on_findings, verbose, exclude, include_ext, json, quiet, threads):
    """Scan git history for secrets that were added and removed."""
    try:
        target = Path(path).resolve()

        # Build allowed extensions set
        allowed = {".py"}
        for ext in include_ext:
            ext = ext if ext.startswith(".") else f".{ext}"
            if ext in ALL_SUPPORTED_EXTENSIONS:
                allowed.add(ext)
            else:
                click.echo(f"Warning: '{ext}' not supported.", err=True)

        engine = HistoryEngine(allowed_extensions=allowed)

        try:
            report = engine.run(
                target=target,
                exclude_patterns=list(exclude),
                verbose=verbose,
                threads=threads,
            )
        finally:
            engine.close()

        # Output results
        report_history_text(report)

        # Exit code
        if fail_on_findings and report.total_findings > 0:
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(3)


def main():
    cli()


if __name__ == "__main__":
    main()
