#!/usr/bin/env python3
"""
Compute precision from bench/findings_sample.csv where the 'classification' column is filled.

Classification values accepted:
  TP              — true positive
  FP              — false positive (no category)
  FP:<category>   — false positive with category label
                    e.g. FP:FP_gha, FP:FP_dunder, FP:FP_test,
                         FP:FP_doc, FP:FP_placeholder, FP:FP_pattern

Writes:  bench/precision_report.md
Prints:  same content to stdout
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

BENCH_DIR = Path(__file__).parent
INPUT_CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else BENCH_DIR / "findings_sample.csv"
OUTPUT_MD = BENCH_DIR / "precision_report.md"


def parse_classification(raw: str):
    """
    Return (is_tp, is_fp, fp_category).
    Unrecognised values are skipped (returns None, None, None).
    """
    s = raw.strip().upper()
    if s == "TP":
        return True, False, None
    if s.startswith("FP"):
        remainder = raw.strip()[2:]  # keep original case for category
        if remainder.startswith(":"):
            category = remainder[1:].strip() or "uncategorized"
        else:
            category = "uncategorized"
        return False, True, category
    return None, None, None


def precision(tp: int, fp: int) -> str:
    total = tp + fp
    if total == 0:
        return "n/a"
    return f"{tp / total:.1%}"


def main():
    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} not found. Run sample_findings.py first.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    classified_rows = [r for r in rows if r.get("classification", "").strip()]
    skipped = len(rows) - len(classified_rows)

    if not classified_rows:
        print(
            "ERROR: No rows have a 'classification' value. "
            "Fill the classification column in findings_sample.csv first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Accumulators
    overall_tp = overall_fp = 0
    by_rule: dict = defaultdict(lambda: {"tp": 0, "fp": 0})
    by_repo: dict = defaultdict(lambda: {"tp": 0, "fp": 0})
    fp_categories: dict = defaultdict(int)
    unrecognised = 0

    for r in classified_rows:
        is_tp, is_fp, fp_cat = parse_classification(r["classification"])
        if is_tp is None:
            unrecognised += 1
            continue
        rule_id = r.get("rule_id", "unknown")
        repo = r.get("repo", "unknown")
        if is_tp:
            overall_tp += 1
            by_rule[rule_id]["tp"] += 1
            by_repo[repo]["tp"] += 1
        else:
            overall_fp += 1
            by_rule[rule_id]["fp"] += 1
            by_repo[repo]["fp"] += 1
            fp_categories[fp_cat] += 1

    lines = []
    lines.append("# Precision Report")
    lines.append("")
    lines.append(f"**Classified:** {overall_tp + overall_fp}  ")
    if skipped:
        lines.append(f"**Unclassified (skipped):** {skipped}  ")
    if unrecognised:
        lines.append(f"**Unrecognised labels (skipped):** {unrecognised}  ")
    lines.append(f"**True Positives:** {overall_tp}  ")
    lines.append(f"**False Positives:** {overall_fp}  ")
    lines.append(f"**Overall Precision:** {precision(overall_tp, overall_fp)}")
    lines.append("")

    # By rule_id
    lines.append("## Precision by Rule ID")
    lines.append("")
    lines.append("| Rule ID | TP | FP | Total | Precision |")
    lines.append("|---------|----|----|-------|-----------|")
    for rule_id in sorted(by_rule):
        d = by_rule[rule_id]
        lines.append(
            f"| {rule_id} | {d['tp']} | {d['fp']} "
            f"| {d['tp'] + d['fp']} | {precision(d['tp'], d['fp'])} |"
        )
    lines.append("")

    # By repo
    lines.append("## Precision by Repo")
    lines.append("")
    lines.append("| Repo | TP | FP | Total | Precision |")
    lines.append("|------|----|----|-------|-----------|")
    for repo in sorted(by_repo):
        d = by_repo[repo]
        lines.append(
            f"| {repo} | {d['tp']} | {d['fp']} "
            f"| {d['tp'] + d['fp']} | {precision(d['tp'], d['fp'])} |"
        )
    lines.append("")

    # FP category breakdown
    lines.append("## FP Category Breakdown")
    lines.append("")
    lines.append(
        "_Categorise FPs as `FP:<category>` in the classification column. "
        "Known categories: `FP_gha`, `FP_dunder`, `FP_test`, `FP_doc`, "
        "`FP_placeholder`, `FP_pattern`._"
    )
    lines.append("")
    if fp_categories:
        lines.append("| Category | Count | % of FPs |")
        lines.append("|----------|-------|----------|")
        for cat, count in sorted(fp_categories.items(), key=lambda x: -x[1]):
            pct = f"{count / overall_fp:.1%}" if overall_fp else "n/a"
            lines.append(f"| {cat} | {count} | {pct} |")
    else:
        lines.append("_No categorised FPs yet._")
    lines.append("")

    report = "\n".join(lines) + "\n"

    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written to: {OUTPUT_MD}", file=sys.stderr)


if __name__ == "__main__":
    main()
