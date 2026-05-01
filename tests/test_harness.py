"""
Autonoma -- Minimum Test Harness

Point this at any repo path (or git URL) and get structured evidence.

For each repo it:
  1. Clones/copies into a temp directory
  2. Runs autonoma scan, captures stdout/stderr
  3. Records runtime, exit code, findings
  4. Runs autofix on a temp copy
  5. Runs compileall on the fixed copy
  6. Checks determinism (re-run)
  7. Outputs JSON result (and optionally appends to CSV)

Usage:
  # Single local repo
  python tests/test_harness.py ./my-project

  # Multiple repos
  python tests/test_harness.py ./repo1 ./repo2 /path/to/repo3

  # Git URL
  python tests/test_harness.py https://github.com/user/repo.git

  # With CSV output
  python tests/test_harness.py ./my-project --csv results.csv

  # With auto-fix testing
  python tests/test_harness.py ./my-project --fix

  # Full battery (fix + determinism + compileall)
  python tests/test_harness.py ./my-project --full

  # JSON output to file
  python tests/test_harness.py ./my-project -o report.json
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


AUTONOMA = [sys.executable, "-m", "autonoma"]
TIMEOUT = 120


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_autonoma(target: str, args: List[str] = None) -> Tuple[int, str, str, float]:
    """Run autonoma, return (exit_code, stdout, stderr, elapsed)."""
    cmd = AUTONOMA + ["analyze", target] + (args or [])
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        elapsed = time.perf_counter() - t0
        return r.returncode, r.stdout, r.stderr, elapsed
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT", time.perf_counter() - t0
    except Exception as e:
        return -1, "", str(e), time.perf_counter() - t0


def count_py(repo: Path) -> Tuple[int, int]:
    """Count .py files and LOC."""
    files = 0
    loc = 0
    for root, _, names in os.walk(repo):
        for n in names:
            if n.endswith(".py"):
                files += 1
                try:
                    loc += (Path(root) / n).read_text(encoding="utf-8", errors="replace").count("\n") + 1
                except Exception:
                    pass
    return files, loc


def file_hashes(repo: Path) -> Dict[str, str]:
    """SHA256 of every .py file."""
    h = {}
    for root, _, names in os.walk(repo):
        for n in names:
            if n.endswith(".py"):
                fp = Path(root) / n
                h[str(fp.relative_to(repo))] = hashlib.sha256(fp.read_bytes()).hexdigest()
    return h


def parse_json_block(text: str) -> Optional[dict]:
    """Extract first valid JSON object from text."""
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    continue
    return None


def parse_fix_results(text: str) -> Optional[dict]:
    """Extract JSON block containing fix_results."""
    depth = 0
    start = 0
    blocks = []
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blocks.append(text[start:i + 1])
    for b in blocks:
        try:
            d = json.loads(b)
            if "fix_results" in d:
                return d
        except json.JSONDecodeError:
            continue
    return None


# ---------------------------------------------------------------------------
# Core: test one repo
# ---------------------------------------------------------------------------

def test_repo(source: str, run_fix: bool = False, run_full: bool = False) -> dict:
    """
    Run the full harness on one repo.
    Returns a structured result dict.
    """
    result = {
        "repo": os.path.basename(source.rstrip("/\\")),
        "source": source,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "py_files": 0,
        "loc": 0,
        "runtime_seconds": 0.0,
        "exit_code": 0,
        "findings": 0,
        "fixed": 0,
        "refused": 0,
        "skipped": 0,
        "failed_fixes": 0,
        "files_modified": 0,
        "compileall_passed": None,
        "crashed": False,
        "traceback": False,
        "deterministic": None,
        "stdout_excerpt": "",
        "stderr_excerpt": "",
    }

    with tempfile.TemporaryDirectory(prefix="autonoma_harness_") as tmp_path:
        tmp = Path(tmp_path)

        # ------- Step 1: Clone / copy -------
        source_path = Path(source)
        if source.startswith("http://") or source.startswith("https://") or source.endswith(".git"):
            # Git clone
            repo_dir = tmp / "repo"
            clone = subprocess.run(
                ["git", "clone", "--depth", "1", source, str(repo_dir)],
                capture_output=True, text=True, timeout=60,
            )
            if clone.returncode != 0:
                result["crashed"] = True
                result["stderr_excerpt"] = clone.stderr[:500]
                return result
        elif source_path.is_dir():
            repo_dir = tmp / "repo"
            shutil.copytree(source_path, repo_dir, dirs_exist_ok=True)
        elif source_path.is_file():
            repo_dir = tmp / "repo"
            repo_dir.mkdir()
            shutil.copy2(source_path, repo_dir / source_path.name)
        else:
            result["crashed"] = True
            result["stderr_excerpt"] = f"Source not found: {source}"
            return result

        # ------- Step 2: Count -------
        result["py_files"], result["loc"] = count_py(repo_dir)

        # ------- Step 3: Scan -------
        code, stdout, stderr, elapsed = run_autonoma(str(repo_dir), ["--format", "json"])
        result["exit_code"] = code
        result["runtime_seconds"] = round(elapsed, 3)
        result["crashed"] = code not in (0, 1) or "Traceback" in stdout or "Traceback" in stderr
        result["traceback"] = "Traceback" in stdout or "Traceback" in stderr
        result["stdout_excerpt"] = stdout[:500] if len(stdout) > 500 else stdout
        result["stderr_excerpt"] = stderr[:500] if len(stderr) > 500 else stderr

        scan = parse_json_block(stdout)
        if scan:
            result["findings"] = scan.get("summary", {}).get("total_issues", 0)

        # ------- Step 4: Auto-fix (optional) -------
        if run_fix or run_full:
            fix_dir = tmp / "repo_fix"
            shutil.copytree(repo_dir, fix_dir)

            pre_h = file_hashes(fix_dir)
            code_f, stdout_f, stderr_f, _ = run_autonoma(str(fix_dir), ["--auto-fix", "--format", "json"])

            if "Traceback" in stdout_f or "Traceback" in stderr_f:
                result["traceback"] = True

            fix_data = parse_fix_results(stdout_f)
            if fix_data:
                for fr in fix_data.get("fix_results", []):
                    st = fr.get("state", "")
                    if st == "FIXED":
                        result["fixed"] += 1
                    elif st == "REFUSED":
                        result["refused"] += 1
                    elif st == "SKIPPED":
                        result["skipped"] += 1
                    elif st == "FAILED":
                        result["failed_fixes"] += 1

            post_h = file_hashes(fix_dir)
            result["files_modified"] = sum(
                1 for k in pre_h if pre_h.get(k) != post_h.get(k)
            )

            # ------- Step 5: compileall -------
            comp = subprocess.run(
                [sys.executable, "-m", "compileall", "-q", str(fix_dir)],
                capture_output=True, text=True, timeout=30,
            )
            result["compileall_passed"] = comp.returncode == 0

            shutil.rmtree(fix_dir, ignore_errors=True)

        # ------- Step 6: Determinism (optional) -------
        if run_full:
            outputs = []
            for _ in range(3):
                _, out, _, _ = run_autonoma(str(repo_dir), ["--format", "json"])
                d = parse_json_block(out)
                if d:
                    d.pop("timestamp", None)
                    outputs.append(json.dumps(d, sort_keys=True))
                else:
                    outputs.append(out)
            result["deterministic"] = len(set(outputs)) == 1

    # Clean up excerpts for JSON
    result["stdout_excerpt"] = result["stdout_excerpt"].replace("\r\n", "\n").strip()
    result["stderr_excerpt"] = result["stderr_excerpt"].replace("\r\n", "\n").strip()

    return result


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "repo", "timestamp", "py_files", "loc", "runtime_seconds", "exit_code",
    "findings", "fixed", "refused", "skipped", "failed_fixes", "files_modified",
    "compileall_passed", "crashed", "traceback", "deterministic",
]


def append_csv(filepath: str, results: List[dict]):
    """Append results to a CSV file (create if missing)."""
    write_header = not Path(filepath).exists()
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Autonoma Test Harness -- structured evidence for any repo",
    )
    parser.add_argument("repos", nargs="+", help="Repo paths or git URLs to test")
    parser.add_argument("--fix", action="store_true", help="Run auto-fix + compileall")
    parser.add_argument("--full", action="store_true",
                        help="Full battery: fix + compileall + determinism check")
    parser.add_argument("--csv", metavar="FILE", help="Append results to CSV file")
    parser.add_argument("-o", "--output", metavar="FILE", help="Write JSON report to file")
    parser.add_argument("--quiet", action="store_true", help="Only output JSON, no progress")
    args = parser.parse_args()

    all_results = []

    for source in args.repos:
        if not args.quiet:
            print(f"Testing: {source} ...", end=" ", flush=True)

        r = test_repo(source, run_fix=args.fix, run_full=args.full)
        all_results.append(r)

        if not args.quiet:
            status = "CRASH" if r["crashed"] else "OK"
            print(f"{status} | {r['py_files']} files | {r['loc']} LOC | "
                  f"{r['runtime_seconds']}s | {r['findings']} findings", end="")
            if args.fix or args.full:
                print(f" | {r['fixed']} fixed | {r['refused']} refused | "
                      f"compileall={'PASS' if r['compileall_passed'] else 'FAIL'}", end="")
            if args.full:
                det = "yes" if r["deterministic"] else "NO"
                print(f" | deterministic={det}", end="")
            print()

    # JSON output
    report = {
        "harness_version": "1.0",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos_tested": len(all_results),
        "all_pass": all(not r["crashed"] and not r["traceback"] for r in all_results),
        "results": all_results,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not args.quiet:
            print(f"\nJSON report: {args.output}")
    else:
        # Print JSON to stdout
        print(json.dumps(report, indent=2))

    # CSV
    if args.csv:
        append_csv(args.csv, all_results)
        if not args.quiet:
            print(f"CSV appended: {args.csv}")

    # Exit code
    sys.exit(0 if report["all_pass"] else 1)


if __name__ == "__main__":
    main()
