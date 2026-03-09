"""
Autonoma -- Metrics Dashboard

Runs Autonoma against every test repo and records structured metrics.
Outputs a table suitable for CI logs and reporting.

Measured per repo:
  repo, py_files, loc, runtime_s, findings, fixed, refused, skipped, failed,
  crash, traceback, files_modified, deterministic

Usage:
  python tests/test_metrics.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Re-use generators from existing test suites
sys.path.insert(0, str(Path(__file__).parent))
from test_acceptance import generate_repo
from test_repo_categories import (
    CATEGORY_A_GENERATORS,
    gen_seeded_benchmark,
    gen_ugly_repo,
)

AUTONOMA_CMD = [sys.executable, "-m", "autonoma"]
TIMEOUT = 120
DETERMINISM_RUNS = 3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RepoMetrics:
    repo: str = ""
    category: str = ""
    py_files: int = 0
    loc: int = 0
    runtime_s: float = 0.0
    peak_mem_mb: float = 0.0
    findings: int = 0
    fixed: int = 0
    refused: int = 0
    skipped: int = 0
    failed: int = 0
    crash: bool = False
    traceback: bool = False
    files_modified: int = 0
    deterministic: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def count_repo(repo_dir: Path) -> Tuple[int, int]:
    """Count .py files and total LOC."""
    py_files = 0
    loc = 0
    for root, _, filenames in os.walk(repo_dir):
        for f in filenames:
            if f.endswith(".py"):
                py_files += 1
                try:
                    loc += (Path(root) / f).read_text(encoding="utf-8").count("\n") + 1
                except Exception:
                    pass
    return py_files, loc


def run_autonoma(repo_dir: Path, args: List[str] = None) -> Tuple[int, str, float]:
    """Run autonoma, return (exit_code, combined_output, elapsed)."""
    cmd = AUTONOMA_CMD + ["analyze", str(repo_dir)] + (args or [])
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT,
        )
        elapsed = time.perf_counter() - start
        return result.returncode, result.stdout, elapsed
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT", time.perf_counter() - start


def run_with_memory(repo_dir: Path, args: List[str] = None) -> Tuple[int, str, float, float]:
    """Run autonoma and try to capture peak memory via a wrapper."""
    # Use a small Python wrapper to measure peak RSS
    wrapper = (
        "import sys, subprocess, os; "
        "try:\n"
        "  import resource\n"
        "  r = subprocess.run(sys.argv[1:], capture_output=True, text=True, timeout=120)\n"
        "  mem = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024\n"
        "  print(f'__MEM__:{mem:.1f}')\n"
        "  print(r.stdout)\n"
        "  sys.exit(r.returncode)\n"
        "except ImportError:\n"
        "  r = subprocess.run(sys.argv[1:], capture_output=True, text=True, timeout=120)\n"
        "  print(r.stdout)\n"
        "  sys.exit(r.returncode)\n"
    )
    # Fallback: just run normally and skip memory measurement on Windows
    code, output, elapsed = run_autonoma(repo_dir, args)
    return code, output, elapsed, 0.0


def parse_json_output(output: str) -> Optional[dict]:
    """Parse JSON output, handling concatenated JSON blocks."""
    depth = 0
    start = 0
    blocks = []
    for i, ch in enumerate(output):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blocks.append(output[start:i+1])

    for block in blocks:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    return None


def parse_fix_results(output: str) -> Optional[dict]:
    """Extract fix_results from potentially concatenated JSON output."""
    depth = 0
    start = 0
    blocks = []
    for i, ch in enumerate(output):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blocks.append(output[start:i+1])

    for block in blocks:
        try:
            parsed = json.loads(block)
            if "fix_results" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def compute_file_hashes(repo_dir: Path) -> Dict[str, str]:
    import hashlib
    hashes = {}
    for root, _, filenames in os.walk(repo_dir):
        for f in filenames:
            if f.endswith(".py"):
                fp = Path(root) / f
                hashes[str(fp.relative_to(repo_dir))] = (
                    hashlib.sha256(fp.read_bytes()).hexdigest()
                )
    return hashes


# ---------------------------------------------------------------------------
# Measure a single repo
# ---------------------------------------------------------------------------

def measure_repo(repo_dir: Path, name: str, category: str) -> RepoMetrics:
    """Full measurement of one repo."""
    m = RepoMetrics(repo=name, category=category)

    # Count
    m.py_files, m.loc = count_repo(repo_dir)

    # --- Scan ---
    code, output, elapsed = run_autonoma(repo_dir, ["--format", "json"])
    m.runtime_s = round(elapsed, 3)
    m.crash = code != 0 and code != 1
    m.traceback = "Traceback" in output

    scan_data = parse_json_output(output)
    if scan_data:
        m.findings = scan_data.get("summary", {}).get("total_issues", 0)

    # --- Auto-fix (on a copy) ---
    fix_dir = repo_dir.parent / f"{repo_dir.name}__fix"
    if fix_dir.exists():
        shutil.rmtree(fix_dir)
    shutil.copytree(repo_dir, fix_dir)

    pre_hashes = compute_file_hashes(fix_dir)
    code_f, output_f, _ = run_autonoma(fix_dir, ["--auto-fix", "--format", "json"])

    if "Traceback" in output_f:
        m.traceback = True

    fix_data = parse_fix_results(output_f)
    if fix_data:
        results = fix_data.get("fix_results", [])
        for fr in results:
            state = fr.get("state", "")
            if state == "FIXED":
                m.fixed += 1
            elif state == "REFUSED":
                m.refused += 1
            elif state == "SKIPPED":
                m.skipped += 1
            elif state == "FAILED":
                m.failed += 1

    # Files modified
    post_hashes = compute_file_hashes(fix_dir)
    m.files_modified = sum(
        1 for k in pre_hashes
        if pre_hashes.get(k) != post_hashes.get(k)
    )

    shutil.rmtree(fix_dir, ignore_errors=True)

    # --- Determinism ---
    outputs = []
    for _ in range(DETERMINISM_RUNS):
        _, out, _ = run_autonoma(repo_dir, ["--format", "json"])
        # Strip timestamp for comparison
        d = parse_json_output(out)
        if d:
            d.pop("timestamp", None)
            outputs.append(json.dumps(d, sort_keys=True))
        else:
            outputs.append(out)

    m.deterministic = len(set(outputs)) == 1

    return m


# ---------------------------------------------------------------------------
# Table formatter
# ---------------------------------------------------------------------------

def format_table(metrics: List[RepoMetrics]) -> str:
    """Format metrics as an aligned ASCII table."""
    headers = [
        "repo", "cat", "py_files", "loc", "runtime_s",
        "findings", "fixed", "refused", "skipped", "failed",
        "crash", "traceback", "modified", "deterministic",
    ]

    rows = []
    for m in metrics:
        rows.append([
            m.repo,
            m.category,
            str(m.py_files),
            str(m.loc),
            f"{m.runtime_s:.3f}",
            str(m.findings),
            str(m.fixed),
            str(m.refused),
            str(m.skipped),
            str(m.failed),
            "YES" if m.crash else "no",
            "YES" if m.traceback else "no",
            str(m.files_modified),
            "yes" if m.deterministic else "NO",
        ])

    # Compute column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = []
    lines.append(fmt_row(headers))
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(fmt_row(row))

    return "\n".join(lines)


def format_json_report(metrics: List[RepoMetrics]) -> str:
    """Format metrics as JSON for CI consumption."""
    entries = []
    for m in metrics:
        entries.append({
            "repo": m.repo,
            "category": m.category,
            "py_files": m.py_files,
            "loc": m.loc,
            "runtime_s": m.runtime_s,
            "findings": m.findings,
            "fixed": m.fixed,
            "refused": m.refused,
            "skipped": m.skipped,
            "failed": m.failed,
            "crash": m.crash,
            "traceback": m.traceback,
            "files_modified": m.files_modified,
            "deterministic": m.deterministic,
        })

    all_pass = all(
        not m.crash and not m.traceback and m.deterministic
        for m in metrics
    )

    return json.dumps({
        "schema_version": "1.0",
        "all_pass": all_pass,
        "repos_tested": len(metrics),
        "results": entries,
    }, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import random
    random.seed(42)

    print("=" * 80)
    print("Autonoma Metrics Dashboard")
    print("=" * 80)

    all_metrics: List[RepoMetrics] = []

    with tempfile.TemporaryDirectory(prefix="autonoma_metrics_") as tmp_path:
        tmppath = Path(tmp_path)

        # --- Category A: Clean repos ---
        print("\n[A] Generating clean repos...")
        for name, gen_fn in CATEGORY_A_GENERATORS.items():
            repo_dir = tmppath / "a" / name
            repo_dir.mkdir(parents=True)
            gen_fn(repo_dir)
            print(f"  Measuring: {name}...", end=" ", flush=True)
            m = measure_repo(repo_dir, name, "A-clean")
            all_metrics.append(m)
            print(f"done ({m.runtime_s:.3f}s, {m.findings} findings)")

        # --- Category B: Seeded benchmark ---
        print("\n[B] Generating seeded benchmark...")
        bench_dir = tmppath / "b" / "benchmark"
        bench_dir.mkdir(parents=True)
        gen_seeded_benchmark(bench_dir)
        print("  Measuring: benchmark...", end=" ", flush=True)
        m = measure_repo(bench_dir, "seeded_benchmark", "B-seeded")
        all_metrics.append(m)
        print(f"done ({m.runtime_s:.3f}s, {m.findings} findings)")

        # --- Category C: Ugly repos ---
        print("\n[C] Generating ugly repo...")
        ugly_dir = tmppath / "c" / "ugly"
        ugly_dir.mkdir(parents=True)
        gen_ugly_repo(ugly_dir)
        print("  Measuring: ugly...", end=" ", flush=True)
        m = measure_repo(ugly_dir, "ugly_adversarial", "C-ugly")
        all_metrics.append(m)
        print(f"done ({m.runtime_s:.3f}s, {m.findings} findings)")

        # --- Synthetic scale repos ---
        print("\n[S] Generating synthetic scale repos...")
        for label, target_loc, secrets in [("synth_3k", 3000, 10), ("synth_10k", 10000, 30)]:
            repo_dir = tmppath / "s" / label / "repo"
            meta = generate_repo(repo_dir, target_loc, inject_secrets=secrets,
                                 inject_safe=5, inject_unsupported=3)
            print(f"  Measuring: {label} ({meta['total_files']} files, ~{meta['total_loc']} LOC)...",
                  end=" ", flush=True)
            m = measure_repo(repo_dir, label, "S-scale")
            all_metrics.append(m)
            print(f"done ({m.runtime_s:.3f}s, {m.findings} findings)")

    # --- Output ---
    print(f"\n{'='*80}")
    print("METRICS TABLE")
    print(f"{'='*80}\n")
    print(format_table(all_metrics))

    # Summary
    total_crash = sum(1 for m in all_metrics if m.crash)
    total_tb = sum(1 for m in all_metrics if m.traceback)
    total_nondet = sum(1 for m in all_metrics if not m.deterministic)

    print(f"\n{'='*80}")
    print(f"Repos tested:    {len(all_metrics)}")
    print(f"Crashes:         {total_crash}")
    print(f"Tracebacks:      {total_tb}")
    print(f"Non-deterministic: {total_nondet}")

    all_pass = total_crash == 0 and total_tb == 0 and total_nondet == 0
    if all_pass:
        print("STATUS:          ALL PASS")
    else:
        print("STATUS:          FAILURES DETECTED")
    print(f"{'='*80}")

    # Write JSON report
    report_path = Path(__file__).parent / "metrics_report.json"
    report_path.write_text(format_json_report(all_metrics), encoding="utf-8")
    print(f"\nJSON report written to: {report_path}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
