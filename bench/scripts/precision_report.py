#!/usr/bin/env python3
"""
precision_report.py -- Compute precision metrics from labeled review output.

CRITICAL INVARIANTS
-------------------
1. Synthetic positive controls (synthetic == "true") are EXCLUDED from
   precision numerator AND denominator.  They contribute to recall
   measurement, not precision.

2. UNCERTAIN rows are excluded from the precision denominator and reported
   separately as uncertain_rate.

3. Precision = TP / (TP + FP)   over non-synthetic, non-uncertain rows only.

4. Wilson 95% score interval (no continuity correction) accompanies every
   precision number.

5. Rows with malformed synthetic fields are excluded from metrics and
   reported separately.  They never silently enter the precision denominator.

Synthetic field parsing
-----------------------
The synthetic column is authoritative.  Only "true" and "false"
(case-insensitive, whitespace-trimmed) are accepted.  Any other value —
including "yes", "1", "", or Python repr "False" — is rejected as malformed.
Malformed rows are excluded from all metrics and counted separately.

DO NOT silently coerce unknown values.  bool("False") == True is the exact
class of bug this strict parsing prevents.

Input CSV
---------
Output of precision_sample.py after human labeling.  Expected columns:
    finding_id, repo, file, line, rule_id, matched_preview,
    surrounding_context, synthetic, human_label, category,
    review_notes, reviewer, review_timestamp, labeling_pass_id

    Optional: re_review_label (enables intra-rater Cohen's kappa)

Labels accepted in human_label
-------------------------------
    TRUE_POSITIVE   -> TP
    FALSE_POSITIVE  -> FP (category read from `category` column)
    UNCERTAIN       -> excluded from precision, counted as uncertain

Unrecognised / blank labels are skipped and reported separately.

Usage
-----
    python bench/scripts/precision_report.py \\
        --input bench/precision/sample_2026_01_labeled.csv \\
        [--out bench/precision/report_2026_01.md]
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Wilson confidence interval
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% score interval (no continuity correction).

    Returns (lower, upper) as proportions in [0, 1].
    Returns (0.0, 1.0) when trials == 0.
    """
    if trials == 0:
        return 0.0, 1.0
    p_hat = successes / trials
    z2 = z * z
    denom = 1 + z2 / trials
    centre = (p_hat + z2 / (2 * trials)) / denom
    margin = (z / denom) * math.sqrt(p_hat * (1 - p_hat) / trials + z2 / (4 * trials ** 2))
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _pct(num: int, denom: int) -> str:
    if denom == 0:
        return "n/a"
    return f"{num / denom:.1%}"


def _wilson_str(lo: float, hi: float) -> str:
    return f"[{lo:.1%}, {hi:.1%}]"


# ---------------------------------------------------------------------------
# Label parsing
# ---------------------------------------------------------------------------

_TP_LABELS = {"TRUE_POSITIVE", "TP"}
_FP_LABELS = {"FALSE_POSITIVE", "FP"}
_UNCERTAIN_LABELS = {"UNCERTAIN"}
_SKIP_LABELS = {"", "UNKNOWN", "REVIEW"}


def parse_human_label(raw: str) -> str | None:
    """Return 'TP', 'FP', 'UNCERTAIN', or None (skip)."""
    s = raw.strip().upper()
    if s in _TP_LABELS:
        return "TP"
    if s in _FP_LABELS:
        return "FP"
    if s in _UNCERTAIN_LABELS:
        return "UNCERTAIN"
    if s in _SKIP_LABELS:
        return None
    # Legacy: FP_* prefixed labels
    if s.startswith("FP_") or s.startswith("FP:"):
        return "FP"
    if s.startswith("TP_"):
        return "TP"
    return None


# ---------------------------------------------------------------------------
# Strict synthetic field parsing
# ---------------------------------------------------------------------------

def parse_synthetic_strict(raw: str) -> tuple[bool | None, str | None]:
    """Parse the synthetic CSV column with strict boolean semantics.

    Returns (value, error_message).

    Accepted (case-insensitive, whitespace-trimmed):
        "true"   -> (True,  None)
        "false"  -> (False, None)

    Rejected (anything else):
        "yes", "1", "no", "0", "", Python repr "False" -> (None, <message>)

    DO NOT use Python's bool() or truthiness — bool("False") == True is the
    exact bug this function prevents.
    """
    normalised = raw.strip().lower()
    if normalised == "true":
        return True, None
    if normalised == "false":
        return False, None
    return None, (
        f"synthetic field has unrecognised value {raw!r} "
        f"(accepted: 'true' or 'false', case-insensitive)"
    )


# ---------------------------------------------------------------------------
# Cohen's kappa (intra-rater)
# ---------------------------------------------------------------------------

def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """Compute Cohen's kappa between two label sequences of equal length.

    Returns None when the sequences are empty or when expected agreement is 1.
    """
    n = len(labels_a)
    if n == 0 or n != len(labels_b):
        return None

    agree = sum(a == b for a, b in zip(labels_a, labels_b))
    p_o = agree / n

    all_labels = set(labels_a) | set(labels_b)
    p_e = sum(
        (labels_a.count(lbl) / n) * (labels_b.count(lbl) / n)
        for lbl in all_labels
    )
    if p_e >= 1.0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_metrics(rows: list[dict]) -> dict:
    """Return a dict of all precision metrics.

    Keys:
        total_rows            int -- all rows read
        malformed_rows        int -- rows excluded due to malformed synthetic field
        synthetic_excluded    int -- rows excluded as synthetic controls
        total_non_synthetic   int -- rows available for precision (excl. synthetic + malformed)
        tp                    int
        fp                    int
        uncertain             int
        unrecognised          int
        precision             float | None
        wilson_lo             float | None
        wilson_hi             float | None
        uncertain_rate        float | None
        preliminary           bool   -- True when n < 30
        by_repo               dict[str, dict]
        by_rule               dict[str, dict]
        fp_categories         dict[str, int]
        tp_criteria           dict[str, int]
        kappa                 float | None
        malformed_warnings    list[str]
    """
    total_rows = len(rows)
    malformed_rows = 0
    synthetic_excluded = 0
    tp = fp = uncertain = unrecognised = 0
    by_repo: dict = defaultdict(lambda: {"tp": 0, "fp": 0, "uncertain": 0})
    by_rule: dict = defaultdict(lambda: {"tp": 0, "fp": 0, "uncertain": 0})
    fp_categories: dict[str, int] = defaultdict(int)
    tp_criteria: dict[str, int] = defaultdict(int)
    malformed_warnings: list[str] = []

    # For optional kappa
    first_pass_labels: list[str] = []
    re_review_labels: list[str] = []

    for row in rows:
        raw_synthetic = str(row.get("synthetic", "") or "")
        synthetic_val, synthetic_err = parse_synthetic_strict(raw_synthetic)

        if synthetic_err is not None:
            malformed_rows += 1
            loc = (
                f"{row.get('repo', '?')}:"
                f"{row.get('file', '?')}:"
                f"{row.get('line', '?')}"
            )
            malformed_warnings.append(f"[{loc}] {synthetic_err}")
            continue

        if synthetic_val is True:
            synthetic_excluded += 1
            continue

        raw_label = row.get("human_label", "").strip()
        parsed = parse_human_label(raw_label)

        if parsed is None:
            unrecognised += 1
            continue

        repo = row.get("repo", "unknown")
        rule_id = row.get("rule_id", "unknown")
        category = row.get("category", "").strip()

        if parsed == "TP":
            tp += 1
            by_repo[repo]["tp"] += 1
            by_rule[rule_id]["tp"] += 1
            if category:
                tp_criteria[category] += 1
        elif parsed == "FP":
            fp += 1
            by_repo[repo]["fp"] += 1
            by_rule[rule_id]["fp"] += 1
            cat = category if category else "uncategorised"
            fp_categories[cat] += 1
        elif parsed == "UNCERTAIN":
            uncertain += 1
            by_repo[repo]["uncertain"] += 1
            by_rule[rule_id]["uncertain"] += 1

        # Collect labels for kappa if re_review_label column exists
        re_review_raw = row.get("re_review_label", "").strip()
        if re_review_raw:
            first_pass_labels.append(parsed or "SKIP")
            re_review_parsed = parse_human_label(re_review_raw)
            re_review_labels.append(re_review_parsed or "SKIP")

    n_precision = tp + fp
    total_non_synthetic = total_rows - synthetic_excluded - malformed_rows

    precision_val: float | None = None
    wilson_lo: float | None = None
    wilson_hi: float | None = None
    if n_precision > 0:
        precision_val = tp / n_precision
        wilson_lo, wilson_hi = wilson_interval(tp, n_precision)

    uncertain_rate: float | None = None
    if (tp + fp + uncertain) > 0:
        uncertain_rate = uncertain / (tp + fp + uncertain)

    kappa: float | None = None
    if first_pass_labels and re_review_labels:
        kappa = cohen_kappa(first_pass_labels, re_review_labels)

    return {
        "total_rows": total_rows,
        "malformed_rows": malformed_rows,
        "synthetic_excluded": synthetic_excluded,
        "total_non_synthetic": total_non_synthetic,
        "tp": tp,
        "fp": fp,
        "uncertain": uncertain,
        "unrecognised": unrecognised,
        "precision": precision_val,
        "wilson_lo": wilson_lo,
        "wilson_hi": wilson_hi,
        "uncertain_rate": uncertain_rate,
        "preliminary": n_precision < 30,
        "by_repo": dict(by_repo),
        "by_rule": dict(by_rule),
        "fp_categories": dict(fp_categories),
        "tp_criteria": dict(tp_criteria),
        "kappa": kappa,
        "malformed_warnings": malformed_warnings,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _prec_str(val: float | None, lo: float | None, hi: float | None) -> str:
    if val is None:
        return "n/a"
    s = f"{val:.1%}"
    if lo is not None and hi is not None:
        s += f"  (Wilson 95% CI: [{lo:.1%}, {hi:.1%}])"
    return s


def render_report(m: dict) -> str:
    lines: list[str] = []

    lines.append("# Precision Report")
    lines.append("")
    lines.append(
        "_Precision is computed from `human_label` only. "
        "Synthetic positive controls are excluded from precision. "
        "`suggested_label` is never used._"
    )
    lines.append("")

    if m["preliminary"]:
        lines.append(
            "> **PRELIMINARY** — sample size n = "
            f"{m['tp'] + m['fp']} (< 30). "
            "Treat as indicative only."
        )
        lines.append("")

    if m["malformed_rows"]:
        lines.append(
            f"> **WARNING** — {m['malformed_rows']} row(s) excluded due to "
            "malformed `synthetic` field (unrecognised value; expected 'true' "
            "or 'false'). These rows are not counted in any metric."
        )
        lines.append("")

    # Counts
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Total rows read | {m['total_rows']} |")
    if m["malformed_rows"]:
        lines.append(f"| Malformed synthetic field (excluded) | {m['malformed_rows']} |")
    lines.append(f"| Synthetic controls excluded | {m['synthetic_excluded']} |")
    lines.append(f"| Rows available for precision | {m['total_non_synthetic']} |")
    lines.append(f"| True Positives (TP) | {m['tp']} |")
    lines.append(f"| False Positives (FP) | {m['fp']} |")
    lines.append(f"| UNCERTAIN (excluded from precision) | {m['uncertain']} |")
    if m["unrecognised"]:
        lines.append(f"| Unrecognised / blank labels (skipped) | {m['unrecognised']} |")
    lines.append("")

    # Precision
    lines.append("## Precision")
    lines.append("")
    n = m["tp"] + m["fp"]
    prec_str = _prec_str(m["precision"], m["wilson_lo"], m["wilson_hi"])
    lines.append(f"**Strict precision (n = {n}):** {prec_str}")
    lines.append("")
    if m["uncertain_rate"] is not None:
        lines.append(
            f"**Uncertain rate:** {m['uncertain_rate']:.1%}  "
            f"({m['uncertain']} UNCERTAIN out of "
            f"{m['tp'] + m['fp'] + m['uncertain']} non-synthetic rows)"
        )
        lines.append("")

    if m["kappa"] is not None:
        lines.append(
            f"**Intra-rater Cohen's kappa:** {m['kappa']:.3f}  "
            "_(measures labeling consistency, not freedom from systematic bias)_"
        )
        lines.append("")

    # By rule
    if m["by_rule"]:
        lines.append("## Precision by Rule ID")
        lines.append("")
        lines.append("| Rule ID | TP | FP | n | Precision | Wilson 95% CI |")
        lines.append("|---------|----|----|---|-----------|----------------|")
        for rule_id in sorted(m["by_rule"]):
            d = m["by_rule"][rule_id]
            rn = d["tp"] + d["fp"]
            rp = d["tp"] / rn if rn else None
            rlo, rhi = wilson_interval(d["tp"], rn) if rn else (None, None)
            prec_cell = f"{rp:.1%}" if rp is not None else "n/a"
            ci_cell = _wilson_str(rlo, rhi) if rlo is not None else "n/a"
            lines.append(
                f"| {rule_id} | {d['tp']} | {d['fp']} | {rn} "
                f"| {prec_cell} | {ci_cell} |"
            )
        lines.append("")

    # By repo
    if m["by_repo"]:
        lines.append("## Precision by Repo")
        lines.append("")
        lines.append("| Repo | TP | FP | n | Precision | Wilson 95% CI |")
        lines.append("|------|----|----|---|-----------|----------------|")
        for repo in sorted(m["by_repo"]):
            d = m["by_repo"][repo]
            rn = d["tp"] + d["fp"]
            rp = d["tp"] / rn if rn else None
            rlo, rhi = wilson_interval(d["tp"], rn) if rn else (None, None)
            prec_cell = f"{rp:.1%}" if rp is not None else "n/a"
            ci_cell = _wilson_str(rlo, rhi) if rlo is not None else "n/a"
            lines.append(
                f"| {repo} | {d['tp']} | {d['fp']} | {rn} "
                f"| {prec_cell} | {ci_cell} |"
            )
        lines.append("")

    # FP categories
    lines.append("## FP Category Breakdown")
    lines.append("")
    lines.append(
        "_Taxonomy: categories A–H (A=concept labels, B=protocol constants, "
        "C=natural language, D=schema labels, E=framework constants, "
        "F=mirror values, G=public test credentials, H=synthetic test artifacts) "
        "plus R (redaction markers)._"
    )
    lines.append("")
    if m["fp_categories"]:
        total_fp = m["fp"]
        lines.append("| Category | Count | % of FPs |")
        lines.append("|----------|-------|----------|")
        for cat, count in sorted(m["fp_categories"].items(), key=lambda x: -x[1]):
            pct = f"{count / total_fp:.1%}" if total_fp else "n/a"
            lines.append(f"| {cat} | {count} | {pct} |")
    else:
        lines.append("_No categorised FPs._")
    lines.append("")

    # TP criteria
    if m["tp_criteria"]:
        lines.append("## TP Criteria Breakdown")
        lines.append("")
        lines.append(
            "_Criteria: 1=known credential format, "
            "2=high-entropy credential-shaped value, "
            "3=synthetic positive control (should be 0 after synthetic exclusion)._"
        )
        lines.append("")
        lines.append("| Criterion | Count |")
        lines.append("|-----------|-------|")
        for crit, count in sorted(m["tp_criteria"].items()):
            lines.append(f"| {crit} | {count} |")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute precision metrics from a labeled review CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input", "-i",
        required=True,
        metavar="CSV",
        help="Labeled review CSV (output of precision_sample.py after labeling).",
    )
    p.add_argument(
        "--out", "-o",
        default=None,
        metavar="FILE",
        help="Output Markdown report path (default: stdout).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: {input_path} not found.", file=sys.stderr)
        return 1

    with open(input_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("ERROR: input CSV is empty.", file=sys.stderr)
        return 1

    metrics = compute_metrics(rows)

    # Emit warnings for malformed rows
    if metrics["malformed_warnings"]:
        print(
            f"warning: {metrics['malformed_rows']} malformed synthetic field(s):",
            file=sys.stderr,
        )
        for w in metrics["malformed_warnings"][:20]:
            print(f"  {w}", file=sys.stderr)
        if len(metrics["malformed_warnings"]) > 20:
            print(
                f"  ... and {len(metrics['malformed_warnings']) - 20} more (suppressed)",
                file=sys.stderr,
            )

    report = render_report(metrics)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Report written to {out_path}", file=sys.stderr)
    else:
        print(report)

    # Print key numbers to stderr for quick inspection
    n = metrics["tp"] + metrics["fp"]
    prec = metrics["precision"]
    prec_str = f"{prec:.1%}" if prec is not None else "n/a"
    lo = metrics["wilson_lo"]
    hi = metrics["wilson_hi"]
    ci_str = (
        f"[{lo:.1%}, {hi:.1%}]"
        if lo is not None and hi is not None
        else "n/a"
    )
    print(
        f"Precision: {prec_str}  Wilson 95%: {ci_str}  "
        f"n={n}  synthetic_excluded={metrics['synthetic_excluded']}  "
        f"malformed={metrics['malformed_rows']}  "
        f"uncertain={metrics['uncertain']}",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
