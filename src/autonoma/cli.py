"""CLI for Autonoma security scanner."""
import subprocess
import sys
from pathlib import Path

from colorama import just_fix_windows_console

# Fix Windows ANSI escape sequence leakage
just_fix_windows_console()

import click

from dataclasses import asdict as _dc_asdict

from . import __version__
from ._internal.heuristics import ALL_SUPPORTED_EXTENSIONS, DEFAULT_EXTENSIONS
from .engine import AnalysisEngine, DetectFinding, DetectReport, DetectSummary
from .history import HistoryEngine
from .fixer import fix_file_issues, process_findings_with_policy, FixOutcome, FIXED, REFUSED, SKIPPED, FAILED
from .audit import generate_audit_log
from .policy import check_env_contract
from .reporter import (
    report_text, report_json, report_fix_outcomes,
    report_history_text, report_history_json, report_detect_json,
    _utc_iso
)


@click.group()
@click.version_option(__version__, prog_name="Autonoma", message="%(prog)s %(version)s")
def cli():
    """Autonoma - code security scanner."""
    pass


def _run_analyze_pipeline(
    path, fmt="text", verbose=False, exclude=(), include_ext=(),
    auto_fix=False, dry_run=False, diff=False, ci=False, json_out=False,
    report_out=None, quiet=False, threads=1, detect_only=False, fix_mode=False,
    exclude_tests=True, exclude_docs=False,
):
    try:
        target = Path(path).resolve()

        if json_out:
            fmt = "json"

        if diff:
            dry_run = True
        if dry_run:
            auto_fix = True
            diff = True  # dry-run always shows a diff
        if detect_only:
            auto_fix = True
            dry_run = True  
            quiet = True    
            verbose = False 

        # Build allowed extensions set (start from full default set)
        allowed = set(DEFAULT_EXTENSIONS)
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
                exclude_tests=exclude_tests,
                exclude_docs=exclude_docs,
            )
        finally:
            engine.close()

        if fmt != "json" and not detect_only:
            report_text(report, verbose=verbose, quiet=quiet)

        # Auto-fix: batch per file
        all_outcomes = []
        all_diffs = []
        # Traces keyed by (file, line, rule_id) — computed once, reused by detect_only block.
        _all_traces: dict = {}
        if auto_fix and report.total_issues > 0:
            base_path = target.parent if target.is_file() else target
            _fix_env_contract = check_env_contract(base_path)
            _fix_finding_counter = 0

            for fr in sorted(report.file_results, key=lambda r: r.file):
                if fr.skipped or not fr.issues:
                    continue

                file_path = Path(fr.abs_path)

                try:
                    code = file_path.read_text(encoding="utf-8")
                except Exception as e:
                    try:
                        rel_file = str(file_path.relative_to(base_path))
                    except ValueError:
                        rel_file = str(file_path)
                    for issue in fr.issues:
                        all_outcomes.append(FixOutcome(
                            state=FAILED,
                            issue_id=issue.get("id", "?"),
                            file=rel_file,
                            line=issue.get("line"),
                            message=f"Cannot read file: {e}",
                        ))
                    continue

                counter_start = _fix_finding_counter
                _fix_finding_counter += len(fr.issues)

                outcomes, diff_patch, file_traces = process_findings_with_policy(
                    code=code,
                    file_path=file_path,
                    file=fr.file,
                    issues=fr.issues,
                    repo_path=base_path,
                    parse_valid=fr.parse_valid,
                    env_contract=_fix_env_contract,
                    write=not dry_run,
                    finding_counter_start=counter_start,
                    dry_run=dry_run,
                )
                for issue, trace in zip(fr.issues, file_traces):
                    _all_traces[(fr.file, issue.get("line"), issue.get("id", ""))] = trace
                all_outcomes.extend(outcomes)
                if diff_patch and diff:
                    all_diffs.append(diff_patch)

            if not json_out and not detect_only:
                report_fix_outcomes(all_outcomes, fmt=fmt, dry_run=dry_run, diff_patches=all_diffs if diff else None, quiet=quiet)
            
            # 4. Generate Audit Log File
            if report_out:
                out_p = Path(report_out).resolve()
                try:
                    written_files = generate_audit_log(all_outcomes, out_p)
                    if not json_out and not quiet:
                        for wf in written_files:
                            click.echo(f"\nAudit log written to: {wf}")
                except Exception as e:
                    click.secho(f"\nERROR: Failed to write audit log to {out_p}", fg="red", bold=True, err=True)
                    click.secho(f"Details: {e}", fg="red", err=True)
                    click.secho("CRITICAL: Remediation may have completed, but the audit report failed to save.", fg="yellow", bold=True, err=True)
                    sys.exit(1)

        # --- Detect Only Mode (outside report.total_issues loop) ---
        if detect_only:
            detect_findings = []
            for fr in sorted(report.file_results, key=lambda r: r.file):
                for issue in fr.issues:
                    # Find matching outcome
                    found_outcome = next((o for o in all_outcomes if o.file == fr.file and o.line == issue.get("line") and o.issue_id == issue.get("id")), None)
                    if not found_outcome:
                        continue

                    rule_id = issue.get("id", "")
                    pattern_type = issue.get("pattern_type", "unknown")
                    # Reuse trace computed in the auto_fix block above.
                    trace = _all_traces.get((fr.file, issue.get("line"), rule_id))

                    detect_findings.append(DetectFinding(
                        file=fr.file.replace("\\", "/"),
                        line=issue.get("line"),
                        col=issue.get("col_offset"),
                        pattern_type=pattern_type,
                        severity=issue.get("severity", "medium"),
                        safe_to_fix=(found_outcome.state == "FIXED"),
                        refusal_reason=found_outcome.reason if found_outcome.state == "REFUSED" else None,
                        suggested_env_var=found_outcome.env_var,
                        rule_id=rule_id,
                        fingerprint=found_outcome.fingerprint or "sha256:unknown",
                        provider=issue.get("provider"),
                        decision_trace=_dc_asdict(trace) if trace else None,
                    ))
            
            # --- Summary to stderr ---
            safe_count = sum(1 for f in detect_findings if f.safe_to_fix)
            refused_count = sum(1 for f in detect_findings if not f.safe_to_fix)
            
            detect_summary = DetectSummary(
                files_processed=report.files_scanned,
                total_findings=len(detect_findings),
                safe_to_fix=safe_count,
                refused=refused_count
            )
            
            detect_report = DetectReport(
                generated_at=_utc_iso(),
                summary=detect_summary,
                findings=detect_findings
            )
            report_detect_json(detect_report)
            
            click.echo("Autonoma detect-only summary", err=True)
            click.echo(
                f"files_processed={detect_summary.files_processed} "
                f"findings={detect_summary.total_findings} "
                f"safe_to_fix={detect_summary.safe_to_fix} "
                f"refused={detect_summary.refused}",
                err=True
            )
            
            # Exit code: 0 if no findings, 1 if findings present
            if len(detect_findings) > 0:
                sys.exit(1)
            else:
                sys.exit(0)

        if fmt == "json":
            report_json(report, fix_outcomes=all_outcomes if (auto_fix and report.total_issues > 0) else None, dry_run=dry_run)

        # Exit code
        if fix_mode:
            modified = any(o.state == FIXED for o in all_outcomes)
            sys.exit(1 if modified else 0)

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

        if report.total_issues > 0:
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(3)


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", help="Output format.")
@click.option("--verbose", is_flag=True, help="Show progress and debug info.")
@click.option("--exclude", multiple=True, help="Glob patterns to exclude (repeatable).")
@click.option("--include-ext", multiple=True, help="Extra extensions to scan, e.g. --include-ext .js --include-ext .ts")
@click.option("--auto-fix", is_flag=True, help="Auto-fix SEC001/SEC002 issues (deterministic, with .bak backup).")
@click.option("--dry-run", is_flag=True, help="Preview auto-fix patches without writing files.")
@click.option("--diff", is_flag=True, help="Preview auto-fix via git-style unified diff patch.")
@click.option("--ci", is_flag=True, help="Run in CI mode with specific exit codes (0=clean, 1=secrets, 2=fixable).")
@click.option("--json", "json_out", is_flag=True, help="Output a single machine-readable JSON payload.")
@click.option("--report-out", type=click.Path(), help="Path to write the remediation audit log (determines format by suffix .md/.json).")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.option("--threads", "-t", type=int, default=1, help="Number of concurrent threads to use for scanning.")
@click.option("--detect-only", is_flag=True, help="Run remediation analysis without modifying files. Outputs JSON findings.")
@click.option("--exclude-tests", is_flag=True, help="Skip test files (tests/, test_*, *_test.py, conftest.py, spec/, fixtures/, testdata/).")
@click.option("--exclude-docs", is_flag=True, help="Skip documentation files (docs/, examples/, tutorial/, documentation/).")
def analyze(path, fmt, verbose, exclude, include_ext, auto_fix, dry_run, diff, ci, json_out, report_out, quiet, threads, detect_only, exclude_tests, exclude_docs):
    """[LEGACY] Analyze path for secrets."""
    _run_analyze_pipeline(
        path=path, fmt=fmt, verbose=verbose,
        exclude=exclude, include_ext=include_ext, auto_fix=auto_fix,
        dry_run=dry_run, diff=diff, ci=ci, json_out=json_out,
        report_out=report_out, quiet=quiet, threads=threads, detect_only=detect_only,
        exclude_tests=exclude_tests, exclude_docs=exclude_docs,
    )


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--verbose", is_flag=True, help="Show progress info on stderr.")
@click.option("--exclude", multiple=True, help="Patterns to exclude.")
@click.option("--include-ext", multiple=True, help="Extra extensions to scan.")
@click.option("--threads", "-t", type=int, default=1, help="Concurrent threads.")
@click.option("--ci", is_flag=True, help="CI mode (0=none, 1=any, 2=fixable).")
@click.option("--include-tests", is_flag=True, help="Include test files in scan (excluded by default: tests/, test_*, *_test.py, conftest.py, spec/, fixtures/, testdata/).")
@click.option("--exclude-tests", is_flag=True, expose_value=False, hidden=True, help="Deprecated: test files are excluded by default. Use --include-tests to opt in.")
@click.option("--exclude-docs", is_flag=True, help="Skip documentation files (docs/, docs_src/, examples/, tutorial/, documentation/, README).")
@click.option("--include-docs", is_flag=True, expose_value=False, help="Include documentation files (default behavior).")
def scan(path, verbose, exclude, include_ext, threads, ci, include_tests, exclude_docs):
    """Scan for hardcoded secrets (non-mutating, JSON findings to stdout)."""
    _run_analyze_pipeline(
        path=path, detect_only=True,
        verbose=verbose, exclude=exclude, include_ext=include_ext, threads=threads, ci=ci,
        exclude_tests=not include_tests, exclude_docs=exclude_docs,
    )


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview fixes without writing files.")
@click.option("--diff", is_flag=True, help="Preview via unified diff.")
@click.option("--report-out", type=click.Path(), help="Path to write remediation audit log.")
@click.option("--json", "json_out", is_flag=True, help="Output machine-readable JSON.")
@click.option("--exclude", multiple=True, help="Exclude patterns.")
@click.option("--include-ext", multiple=True, help="Include extensions.")
@click.option("--threads", "-t", type=int, default=1, help="Number of threads.")
@click.option("--quiet", "-q", is_flag=True, help="Minimize console output.")
@click.option("--ci", is_flag=True, help="CI mode.")
@click.option("--include-tests", is_flag=True, help="Include test files in fix (excluded by default: tests/, test_*, *_test.py, conftest.py, spec/, fixtures/, testdata/).")
@click.option("--exclude-tests", is_flag=True, expose_value=False, hidden=True, help="Deprecated: test files are excluded by default. Use --include-tests to opt in.")
@click.option("--exclude-docs", is_flag=True, help="Skip documentation files (docs/, docs_src/, examples/, tutorial/, documentation/, README).")
@click.option("--include-docs", is_flag=True, expose_value=False, help="Include documentation files (default behavior).")
def fix(path, dry_run, diff, report_out, json_out, exclude, include_ext, threads, quiet, ci, include_tests, exclude_docs):
    """Automatically fix hardcoded secrets (mutating)."""
    _run_analyze_pipeline(
        path=path, auto_fix=True, dry_run=dry_run, diff=diff, report_out=report_out,
        json_out=json_out, exclude=exclude, include_ext=include_ext, threads=threads,
        quiet=quiet, ci=ci, detect_only=False, fix_mode=True,
        exclude_tests=not include_tests, exclude_docs=exclude_docs,
    )

@cli.command(name="history-scan")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--verbose", is_flag=True, help="Show progress and debug info.")
@click.option("--exclude", multiple=True, help="Glob patterns to exclude (repeatable).")
@click.option("--include-ext", multiple=True, help="Extra extensions to scan, e.g. --include-ext .js --include-ext .ts")
@click.option("--json", is_flag=True, help="Output a single machine-readable JSON payload.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.option("--threads", "-t", type=int, default=1, help="Number of concurrent threads to use for scanning.")
def history_scan(path, verbose, exclude, include_ext, json, quiet, threads):
    """Scan git history for secrets that were added and removed."""
    try:
        target = Path(path).resolve()

        # Build allowed extensions set (start from full default set)
        allowed = set(DEFAULT_EXTENSIONS)
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
        if report.total_findings > 0:
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(3)



@cli.command(name="pre-commit")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--auto-fix", is_flag=True, help="Auto-fix SEC001/SEC002 and re-stage fixed files.")
@click.option("--include-ext", multiple=True, help="Extra extensions to scan, e.g. --include-ext .js")
@click.option("--exclude", multiple=True, help="Glob patterns to exclude (repeatable).")
@click.option("--verbose", is_flag=True, help="Show progress and debug info.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.option("--json", "json_out", is_flag=True, help="Output a single machine-readable JSON payload.")
def pre_commit_cmd(files, auto_fix, include_ext, exclude, verbose, quiet, json_out):
    """Run Autonoma as a pre-commit hook (scans only staged files)."""
    try:
        if not files:
            sys.exit(0)

        # Build allowed extensions set (start from full default set)
        allowed = set(DEFAULT_EXTENSIONS)
        for ext in include_ext:
            ext = ext if ext.startswith(".") else f".{ext}"
            if ext in ALL_SUPPORTED_EXTENSIONS:
                allowed.add(ext)
            else:
                click.echo(f"Warning: '{ext}' not supported. Supported: {sorted(ALL_SUPPORTED_EXTENSIONS)}", err=True)

        # Filter to only files with allowed extensions
        targets = []
        for f in files:
            p = Path(f).resolve()
            if p.suffix in allowed:
                targets.append(p)

        if not targets:
            sys.exit(0)

        engine = AnalysisEngine(allowed_extensions=allowed)
        blocked = False
        total_issues = 0

        try:
            for file_path in sorted(targets):
                report = engine.run(
                    target=file_path,
                    exclude_patterns=list(exclude),
                    verbose=verbose,
                    threads=1,
                )

                if report.total_issues == 0:
                    continue

                total_issues += report.total_issues

                if auto_fix:
                    base_path = file_path.parent
                    _pc_env_contract = check_env_contract(base_path)
                    _pc_counter = 0

                    for fr in report.file_results:
                        if fr.skipped or not fr.issues:
                            continue

                        try:
                            code = Path(fr.abs_path).read_text(encoding="utf-8")
                        except Exception as e:
                            if not quiet:
                                click.echo(f"Cannot read {fr.file}: {e}", err=True)
                            blocked = True
                            continue

                        counter_start = _pc_counter
                        _pc_counter += len(fr.issues)

                        outcomes, diff_patch, _ = process_findings_with_policy(
                            code=code,
                            file_path=Path(fr.abs_path),
                            file=fr.file,
                            issues=fr.issues,
                            repo_path=base_path,
                            parse_valid=fr.parse_valid,
                            env_contract=_pc_env_contract,
                            write=True,
                            finding_counter_start=counter_start,
                        )

                        file_blocked = False
                        for outcome in outcomes:
                            if outcome.state == REFUSED:
                                file_blocked = True
                                if not quiet:
                                    click.echo(
                                        f"REFUSED: {outcome.issue_id} in {outcome.file} "
                                        f"line {outcome.line} — {outcome.message}",
                                        err=True,
                                    )
                            elif outcome.state == FAILED:
                                file_blocked = True
                                if not quiet:
                                    click.echo(
                                        f"FAILED: {outcome.issue_id} in {outcome.file} "
                                        f"line {outcome.line} — {outcome.message}",
                                        err=True,
                                    )

                        if file_blocked:
                            blocked = True
                        else:
                            # All issues fixed — re-stage the file
                            any_fixed = any(o.state == FIXED for o in outcomes)
                            if any_fixed:
                                add_result = subprocess.run(
                                    ["git", "add", str(file_path)],
                                    capture_output=True,
                                )
                                if add_result.returncode != 0:
                                    blocked = True
                                    click.echo(
                                        f"ERROR: git add failed for {file_path.name} "
                                        f"(exit {add_result.returncode}) — "
                                        f"file was fixed on disk but is not staged.",
                                        err=True,
                                    )
                                elif not quiet:
                                    click.echo(f"Fixed and re-staged: {file_path.name}")
                else:
                    # No auto-fix: any issue blocks the commit
                    blocked = True
            if json_out:
                report_json(report, out=sys.stdout)
            else:
                report_text(report, verbose=verbose, quiet=quiet)
        finally:
            engine.close()

        if blocked:
            if not quiet and total_issues > 0:
                click.echo(
                    f"\nAutonoma: {total_issues} issue(s) found. Commit blocked.",
                    err=True,
                )
            sys.exit(1)

        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()
