#!/usr/bin/env python3
"""
Compute precision from human-reviewed findings.

Precision is computed from human_label/classification only.
suggested_label is advisory and ignored.

Label column priority:
  1. human_label   — authoritative (filled by human reviewer)
  2. classification — backward compat with pre-suggest_labels.py CSVs
  suggested_label is NEVER used for precision.

Accepted human labels:
  TP_REAL, TP_TEST          → true positive
  FP_DOC, FP_PLACEHOLDER,
  FP_PATTERN, FP_NONSECRET,
  FP_GHA, FP_DUNDER,
  FP_TEST                   → false positive
  UNKNOWN, REVIEW           → skipped (not counted)

Legacy labels (backward compat):
  TP                        → true positive
  FP, FP:<category>         → false positive

Reads:   positional arg or bench/findings_sample.csv
Writes:  bench/precision_report.md
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

BENCH_DIR = Path(__file__).parent
INPUT_CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else BENCH_DIR / "findings_sample.csv"
OUTPUT_MD = BENCH_DIR / "precision_report.md"

_TP_LABELS = {"TP_REAL", "TP_TEST", "TP"}
_SKIP_LABELS = {"UNKNOWN", "REVIEW", ""}

# FP labels (canonical + legacy prefix)
def _is_fp_label(s: str) -> tuple[bool, str]:
    """Return (is_fp, category). category is empty string for non-FP."""
    upper = s.upper()
    if upper.startswith("FP_") or upper == "FP_NONSECRET":
        return True, s
    if upper == "FP":
        return True, "uncategorized"
    if upper.startswith("FP:"):
        return True, s[3:].strip() or "uncategorized"
    return False, ""


def resolve_label(row: dict) -> str:
    """Return the effective label for a row, ignoring suggested_label."""
    human = row.get("human_label", "").strip()
    if human:
        return human
    return row.get("classification", "").strip()


def parse_label(raw: str) -> tuple[bool | None, bool | None, str]:
    """
    Return (is_tp, is_fp, fp_category).
    Returns (None, None, '') for skipped/unrecognised rows.
    """
    s = raw.strip()
    if not s or s.upper() in _SKIP_LABELS:
        return None, None, ""
    if s.upper() in _TP_LABELS:
        return True, False, ""
    is_fp, cat = _is_fp_label(s)
    if is_fp:
        return False, True, cat
    return None, None, ""


def precision(tp: int, fp: int) -> str:
    total = tp + fp
    if total == 0:
        return "n/a"
    return f"{tp / total:.1%}"


def main() -> None:
    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} not found.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    overall_tp = overall_fp = 0
    by_rule: dict = defaultdict(lambda: {"tp": 0, "fp": 0})
    by_repo: dict = defaultdict(lambda: {"tp": 0, "fp": 0})
    fp_categories: dict = defaultdict(int)
    skipped = unrecognised = 0

    for r in rows:
        label = resolve_label(r)
        is_tp, is_fp, fp_cat = parse_label(label)
        if is_tp is None:
            if label == "":
                skipped += 1
            else:
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

    classified = overall_tp + overall_fp

    lines: list[str] = []
    lines.append("# Precision Report")
    lines.append("")
    lines.append(
        "_Precision is computed from human_label/classification only. "
        "suggested_label is advisory and ignored._"
    )
    lines.append("")
    lines.append(f"**Classified:** {classified}  ")
    if skipped:
        lines.append(f"**Unclassified (skipped):** {skipped}  ")
    if unrecognised:
        lines.append(f"**Unrecognised labels (skipped):** {unrecognised}  ")
    lines.append(f"**True Positives:** {overall_tp}  ")
    lines.append(f"**False Positives:** {overall_fp}  ")
    lines.append(f"**Overall Precision:** {precision(overall_tp, overall_fp)}")
    lines.append("")

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

    lines.append("## FP Category Breakdown")
    lines.append("")
    lines.append(
        "_Canonical FP labels: `FP_GHA`, `FP_DUNDER`, `FP_TEST`, `FP_DOC`, "
        "`FP_PLACEHOLDER`, `FP_PATTERN`, `FP_NONSECRET`._"
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
