#!/usr/bin/env python3
"""
Autonoma Community Edition - CLI
Simplified command-line interface for local code analysis.
"""
import sys
import os
import asyncio
import json
import click
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from daemon.queues.analysis_queue import AnalysisQueue
from daemon.analysis.fix_engine import FixEngine


@click.group()
def cli():
    """Autonoma Community Edition - Code Security Analyzer"""
    pass


@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--project-id', default='cli-run', help='Project identifier')
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help='Output format')
@click.option('--fail-on-high', is_flag=True, help='Exit with error if high severity issues found')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
@click.option('--auto-fix', is_flag=True, help='Enable auto-fix for detected issues')
def analyze(path, project_id, format, fail_on_high, verbose, auto_fix):
    """Run analysis on a file or directory."""
    try:
        asyncio.run(_run_analysis(path, project_id, format, fail_on_high, verbose, auto_fix))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


async def _run_analysis(path_str: str, project_id: str, fmt: str, fail_on_high: bool, 
                        verbose: bool, auto_fix: bool = False):
    target_path = Path(path_str).resolve()
    base_path = target_path.parent if target_path.is_file() else target_path
    
    queue = AnalysisQueue()
    files_to_analyze = []

    if target_path.is_file():
        files_to_analyze.append(target_path)
    else:
        for root, dirs, files in os.walk(target_path):
            # Skip common non-code directories
            for skip in ['.git', '__pycache__', 'node_modules', '.pytest_cache', 'venv']:
                if skip in dirs:
                    dirs.remove(skip)
            
            for file in files:
                if file.endswith(('.py', '.js', '.ts')):
                    files_to_analyze.append(Path(root) / file)

    if verbose:
        click.echo(f"Analyzing {len(files_to_analyze)} file(s)...")

    all_issues = []

    for file_path in files_to_analyze:
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            if verbose:
                click.echo(f"  Skipping {file_path}: {e}")
            continue

        if verbose:
            click.echo(f"  Scanning {file_path.relative_to(base_path)}...")

        task = {
            "file_path": str(file_path),
            "content": content,
            "project_id": project_id,
            "user_config": {}
        }
        
        issues = await queue.run_analysis(task)
        if verbose:
            click.echo(f"[DEBUG] Found {len(issues)} issues in {file_path}")
            for i in issues:
                click.echo(f"  [DEBUG] Issue: {i.get('id')} ({i.get('severity')}) - {i.get('message')}")
        
        for issue in issues:
            issue['file'] = str(file_path.relative_to(base_path))
            all_issues.append(issue)
            
            if verbose and fmt == 'text':
                severity = issue.get('severity', 'UNKNOWN')
                rule_id = issue.get('id', 'UNKNOWN')
                line = issue.get('line', '?')
                msg = issue.get('message', issue.get('description', ''))
                click.echo(f"    [{severity}] {rule_id} (line {line}): {msg}")

    # Output results
    if fmt == 'json':
        click.echo(json.dumps(all_issues, indent=2))
    else:
        click.echo(f"\n=== Analysis Complete ===")
        click.echo(f"Files scanned: {len(files_to_analyze)}")
        click.echo(f"Issues found: {len(all_issues)}")
        
        high_count = sum(1 for i in all_issues if i.get('severity') == 'HIGH')
        if high_count > 0:
            click.echo(f"HIGH severity: {high_count}")

    # Auto-fix
    if auto_fix and all_issues:
        click.echo("\n=== Auto-Fix ===")
        engine = FixEngine()
        for issue in all_issues:
            severity = issue.get('severity')
            click.echo(f"[DEBUG] Processing {issue.get('id')} with severity {severity}")
            
            if str(severity).upper() == 'HIGH':
                file_path = base_path / issue.get('file')
                code = file_path.read_text(encoding='utf-8')
                click.echo(f"[DEBUG] Generating fix for {issue.get('id')} in {file_path}")
                
                try:
                    fixed = await engine.generate_fix(code, issue)
                    if fixed and fixed != code:
                        file_path.write_text(fixed, encoding='utf-8')
                        click.echo(f"  Fixed: {issue.get('file')}")
                    else:
                        click.echo(f"[DEBUG] Fix generation returned same code or None")
                except Exception as e:
                    click.echo(f"[DEBUG] Fix generation failed: {e}")

    # Exit code
    if fail_on_high and high_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    cli()
