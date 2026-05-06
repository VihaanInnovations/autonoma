#!/usr/bin/env python3
"""
Run autonoma scan on each repo in bench/repos/ and write bench/findings_full.csv.

Columns:
  repo, file, line, rule_id, severity, matched_value,
  line_context, surrounding_context, classification
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).parent
REPOS_DIR = BENCH_DIR / "repos"
OUTPUT_CSV = BENCH_DIR / "findings_full.csv"

FIELDNAMES = [
    "repo",
    "file",
    "line",
    "rule_id",
    "severity",
    "matched_value",
    "line_context",
    "surrounding_context",
    "suggested_label",
    "suggestion_confidence",
    "suggestion_reason",
    "human_label",
    "review_notes",
    "reviewer",
]

CONTEXT_RADIUS = 3


def extract_matched_value(line: str) -> str:
    """Extract the secret value from a line by parsing the RHS of = or :."""
    stripped = line.strip()
    # Quoted value after = or :
    m = re.search(r'[:=]\s*["\']([^"\']{1,200})["\']', stripped)
    if m:
        return m.group(1)
    # Unquoted value after = (env-style: KEY=VALUE)
    m = re.search(r'=\s*(\S{1,200})', stripped)
    if m:
        val = m.group(1)
        # Drop inline comment suffix
        val = re.split(r'\s+[#//]', val)[0]
        return val
    return stripped[:200]


def get_contexts(lines: list, line_no: int):
    """Return (line_context, surrounding_context) for 1-indexed line_no."""
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return "", ""
    line_ctx = lines[idx].rstrip("\n")
    start = max(0, idx - CONTEXT_RADIUS)
    end = min(len(lines), idx + CONTEXT_RADIUS + 1)
    surrounding = "\n".join(l.rstrip("\n") for l in lines[start:end])
    return line_ctx, surrounding


def scan_repo(repo_path: Path) -> list:
    """Run `autonoma scan <repo>` and return the findings list."""
    result = subprocess.run(
        ["autonoma", "scan", str(repo_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = result.stdout.strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        print(f"  WARNING: JSON parse error for {repo_path.name}: {exc}", file=sys.stderr)
        return []
    return data.get("findings", [])


def main():
    if not REPOS_DIR.exists():
        print(f"ERROR: {REPOS_DIR} does not exist.", file=sys.stderr)
        print("Populate bench/repos/ with the canonical repos before running.", file=sys.stderr)
        sys.exit(1)

    repos = sorted(d for d in REPOS_DIR.iterdir() if d.is_dir())
    if not repos:
        print(f"ERROR: No subdirectories found in {REPOS_DIR}.", file=sys.stderr)
        sys.exit(1)

    total = 0

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
        writer.writeheader()

        for repo_dir in repos:
            repo_name = repo_dir.name
            print(f"Scanning {repo_name} ...", file=sys.stderr)

            findings = scan_repo(repo_dir)
            print(f"  {len(findings)} findings", file=sys.stderr)

            for finding in findings:
                file_rel = finding.get("file", "")
                line_no = finding.get("line") or 0
                rule_id = finding.get("rule_id", "")
                severity = finding.get("severity", "")

                line_ctx = ""
                surrounding_ctx = ""
                matched_val = ""

                file_abs = repo_dir / file_rel
                try:
                    with open(file_abs, encoding="utf-8", errors="replace") as src:
                        source_lines = src.readlines()
                    line_ctx, surrounding_ctx = get_contexts(source_lines, line_no)
                    matched_val = extract_matched_value(line_ctx)
                except OSError:
                    pass

                writer.writerow({
                    "repo": repo_name,
                    "file": file_rel,
                    "line": line_no,
                    "rule_id": rule_id,
                    "severity": severity,
                    "matched_value": matched_val,
                    "line_context": line_ctx,
                    "surrounding_context": surrounding_ctx,
                    "suggested_label": "",
                    "suggestion_confidence": "",
                    "suggestion_reason": "",
                    "human_label": "",
                    "review_notes": "",
                    "reviewer": "",
                })
                total += 1

    print(f"\nTotal findings written: {total}", file=sys.stderr)
    print(f"Output: {OUTPUT_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
