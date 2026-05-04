#!/usr/bin/env python3
"""
Produce bench/findings_sample.csv: stratified random sample of 20 findings per repo,
balanced across rule_id types within each repo.

Reads:  bench/findings_full.csv
Writes: bench/findings_sample.csv  (same columns)
"""
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

BENCH_DIR = Path(__file__).parent
INPUT_CSV = BENCH_DIR / "findings_full.csv"
OUTPUT_CSV = BENCH_DIR / "findings_sample.csv"

SAMPLE_PER_REPO = 20


def stratified_sample(rows: list, n: int) -> list:
    """
    Return up to n rows sampled proportionally across rule_id strata.
    Fills any deficit left by small strata from the remaining pool.
    """
    by_rule = defaultdict(list)
    for row in rows:
        by_rule[row["rule_id"]].append(row)

    rule_ids = sorted(by_rule)
    n_rules = len(rule_ids)
    if n_rules == 0:
        return []

    base = n // n_rules
    extra = n % n_rules

    selected = []
    for i, rule_id in enumerate(rule_ids):
        quota = base + (1 if i < extra else 0)
        pool = by_rule[rule_id]
        take = min(quota, len(pool))
        selected.extend(random.sample(pool, take))

    # Top-up from unselected rows if we're still short
    selected_ids = {id(r) for r in selected}
    remaining = [r for r in rows if id(r) not in selected_ids]
    deficit = n - len(selected)
    if deficit > 0 and remaining:
        selected.extend(random.sample(remaining, min(deficit, len(remaining))))

    # Trim if somehow over (shouldn't normally happen)
    if len(selected) > n:
        selected = random.sample(selected, n)

    return selected


def main():
    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} not found. Run measure_precision.py first.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        all_rows = list(reader)

    if not all_rows:
        print("ERROR: findings_full.csv is empty.", file=sys.stderr)
        sys.exit(1)

    by_repo = defaultdict(list)
    for row in all_rows:
        by_repo[row["repo"]].append(row)

    sampled = []
    for repo in sorted(by_repo):
        repo_rows = by_repo[repo]
        repo_sample = stratified_sample(repo_rows, SAMPLE_PER_REPO)
        sampled.extend(repo_sample)
        print(
            f"  {repo}: sampled {len(repo_sample)} / {len(repo_rows)}",
            file=sys.stderr,
        )

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sampled)

    print(f"\nTotal sampled: {len(sampled)}", file=sys.stderr)
    print(f"Output: {OUTPUT_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
