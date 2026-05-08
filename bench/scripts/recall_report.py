"""
Recall calculator for Autonoma synthetic positive controls.

Computes recall by matching seed_log entries against Autonoma findings using
fingerprints as the identity signal. Fingerprints are ``sha256:<first 16 hex
chars of SHA-256(utf-8(secret_value))>``, matching the algorithm in
``autonoma.audit.generate_fingerprint``. No raw matched values are used or
required.

Three-way diagnostic:

  - MATCHED            : expected fingerprint found at the expected path
  - PATH_MISMATCH      : expected fingerprint found in findings, but at a
                         different path than recorded in seed_log (benchmark
                         bug, not a detector miss — fix normalization first)
  - VALUE_NOT_FOUND    : expected fingerprint does not appear anywhere in
                         findings (genuine detector miss)

Reports overall, per-family, and per-format recall with Wilson 95% score
intervals. Emits a per-finding diagnostic CSV for triage.

Usage:
    python recall_report.py \\
        --seed-log bench/positive_controls/generated/flask.seed_log.json \\
        --findings bench/positive_controls/generated/flask.findings.json \\
        --diagnostic-out bench/positive_controls/generated/flask.diagnostic.csv

Multiple repos:
    python recall_report.py \\
        --seed-log flask.seed_log.json --findings flask.findings.json \\
        --seed-log httpx.seed_log.json --findings httpx.findings.json \\
        --seed-log requests.seed_log.json --findings requests.findings.json \\
        --diagnostic-out combined.diagnostic.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Fingerprint (matches autonoma.audit.generate_fingerprint exactly)
# ---------------------------------------------------------------------------

def compute_fingerprint(secret_value: str) -> str:
    """Return sha256:<first 16 hex chars of SHA-256(utf-8(secret_value))>.

    Identical algorithm to ``autonoma.audit.generate_fingerprint``.
    Empty-string special-case matches the empty-string SHA-256 digest prefix.
    """
    if not secret_value:
        return "sha256:e3b0c44298fc1c149afbf4c8"
    return "sha256:" + hashlib.sha256(secret_value.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

PATH_KEYS = ("file", "path", "file_path", "filename", "filepath", "location")


def normalize_path(p: str, repo_root: str | None = None) -> str:
    """Return a canonical, case-preserving, forward-slash relative path.

    Strips any leading repo_root if present (covers detectors that emit
    absolute paths). Normalizes backslashes to forward slashes. Does NOT
    lowercase — file systems vary, and accidental case folding hides bugs.
    """
    if not p:
        return ""
    s = str(p).replace("\\", "/")

    while s.startswith("./"):
        s = s[2:]

    if repo_root:
        root = str(repo_root).replace("\\", "/").rstrip("/")
        if s.startswith(root + "/"):
            s = s[len(root) + 1:]
        elif s == root:
            s = ""

    while "//" in s:
        s = s.replace("//", "/")

    return s


# ---------------------------------------------------------------------------
# Findings extraction — fingerprint-based, no raw values
# ---------------------------------------------------------------------------

def extract_findings_by_fingerprint(
    findings_doc: dict,
    repo_root_hint: str | None = None,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (path_to_fingerprints, fingerprint_to_paths).

    path_to_fingerprints  : normalized_path → set of fingerprints found there
    fingerprint_to_paths  : fingerprint → set of normalized paths where it appears

    Tolerates several findings schema variants. Emits a warning if no
    fingerprints are present (Autonoma findings should always carry them).
    """
    if isinstance(findings_doc, list):
        raw = findings_doc
    else:
        raw = findings_doc.get("findings") or findings_doc.get("results") or []

    path_to_fps: dict[str, set[str]] = defaultdict(set)
    fp_to_paths: dict[str, set[str]] = defaultdict(set)
    fp_count = 0

    for item in raw:
        if not isinstance(item, dict):
            continue

        path = None
        for k in PATH_KEYS:
            v = item.get(k)
            if v:
                path = normalize_path(v, repo_root_hint)
                break

        fp = item.get("fingerprint")
        if fp:
            fp_count += 1
            if path:
                path_to_fps[path].add(fp)
                fp_to_paths[fp].add(path)

    if raw and fp_count == 0:
        print(
            "WARNING: findings contain no 'fingerprint' fields. "
            "All controls will be classified VALUE_NOT_FOUND. "
            "Ensure Autonoma was run in detect-only mode (scan command).",
            file=sys.stderr,
        )

    return dict(path_to_fps), dict(fp_to_paths)


# ---------------------------------------------------------------------------
# Wilson score interval (95% by default)
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float, float]:
    """Return (point_estimate, lower, upper) as proportions in [0, 1].

    Z = 1.96 for 95% confidence. No continuity correction.
    """
    if trials == 0:
        return (0.0, 0.0, 0.0)
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = (z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def fmt_recall_line(label: str, hits: int, total: int, width: int = 24) -> str:
    p, lo, hi = wilson_interval(hits, total)
    return (
        f"{label:<{width}} {hits:>3}/{total:<3}  "
        f"{fmt_pct(p)}  [Wilson 95%: {fmt_pct(lo)} – {fmt_pct(hi)}]"
    )


# ---------------------------------------------------------------------------
# Diagnostic core
# ---------------------------------------------------------------------------

@dataclass
class LocationOutcome:
    repo: str
    control_id: str
    family: str
    file_format: str
    expected_path: str
    expected_value: str   # truncated preview only — not the full raw secret
    outcome: str          # MATCHED | PATH_MISMATCH | VALUE_NOT_FOUND
    detail: str


def diagnose(
    seed_log: dict,
    findings_doc: dict,
    repo_label: str,
    repo_root_hint: str | None = None,
) -> list[LocationOutcome]:
    path_to_fps, fp_to_paths = extract_findings_by_fingerprint(findings_doc, repo_root_hint)
    outcomes: list[LocationOutcome] = []

    for loc in seed_log["locations"]:
        expected_path_norm = normalize_path(loc["file_path"], repo_root_hint)
        expected_value = loc["expected_value"]

        # For aws_pair, expected_value is "ACCESS|SECRET" — compute fingerprints
        # for both components and treat a hit on either as a detection.
        if loc["family"] == "aws_pair" and "|" in expected_value:
            components = expected_value.split("|", 1)
        else:
            components = [expected_value]

        expected_fps = {compute_fingerprint(c) for c in components}

        # MATCHED: at least one expected fingerprint appears at the expected path.
        fps_at_expected_path = path_to_fps.get(expected_path_norm, set())
        path_hit = bool(expected_fps & fps_at_expected_path)

        # PATH_MISMATCH: at least one expected fingerprint appears, but elsewhere.
        fp_hit_anywhere = any(fp in fp_to_paths for fp in expected_fps)

        if path_hit:
            outcome = "MATCHED"
            detail = ""
        elif fp_hit_anywhere:
            outcome = "PATH_MISMATCH"
            actual_paths: set[str] = set()
            for fp in expected_fps:
                actual_paths |= fp_to_paths.get(fp, set())
            shown = ", ".join(sorted(actual_paths)[:3])
            detail = (
                f"fingerprint present in findings but not at expected path; "
                f"found at: {shown}"
            )
        else:
            outcome = "VALUE_NOT_FOUND"
            detail = "fingerprint absent from findings (true detector miss)"

        value_preview = expected_value[:60] + ("…" if len(expected_value) > 60 else "")

        outcomes.append(
            LocationOutcome(
                repo=repo_label,
                control_id=loc["control_id"],
                family=loc["family"],
                file_format=loc["file_format"],
                expected_path=expected_path_norm,
                expected_value=value_preview,
                outcome=outcome,
                detail=detail,
            )
        )
    return outcomes


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(outcomes: list[LocationOutcome]) -> None:
    total = len(outcomes)
    if total == 0:
        print("No outcomes to report.")
        return

    matched = [o for o in outcomes if o.outcome == "MATCHED"]
    path_mismatch = [o for o in outcomes if o.outcome == "PATH_MISMATCH"]
    value_missing = [o for o in outcomes if o.outcome == "VALUE_NOT_FOUND"]

    print("=" * 78)
    print("AUTONOMA RECALL REPORT")
    print("=" * 78)
    print()
    print(f"Total seeded controls: {total}")
    print(f"  MATCHED         : {len(matched):>3}  (fingerprint detected at expected path)")
    print(f"  PATH_MISMATCH   : {len(path_mismatch):>3}  (fingerprint found, path wrong — INVESTIGATE)")
    print(f"  VALUE_NOT_FOUND : {len(value_missing):>3}  (true detector misses)")
    print()

    print("-" * 78)
    print("STRICT RECALL  (MATCHED / total)")
    print("-" * 78)
    print(fmt_recall_line("OVERALL", len(matched), total))
    print()

    if path_mismatch:
        generous_hits = len(matched) + len(path_mismatch)
        print("-" * 78)
        print("GENEROUS RECALL  (treating PATH_MISMATCH as detected)")
        print("-" * 78)
        print(fmt_recall_line("OVERALL (generous)", generous_hits, total))
        print()
        print("If GENEROUS recall is materially higher than STRICT, your matcher")
        print("or detector has a path-normalization bug. Fix that before publishing.")
        print()

    fam_total: dict[str, int] = defaultdict(int)
    fam_match: dict[str, int] = defaultdict(int)
    for o in outcomes:
        fam_total[o.family] += 1
        if o.outcome == "MATCHED":
            fam_match[o.family] += 1

    print("-" * 78)
    print("BY FAMILY  (strict recall)")
    print("-" * 78)
    for fam in sorted(fam_total):
        print(fmt_recall_line(fam, fam_match[fam], fam_total[fam]))
    print()

    fmt_total: dict[str, int] = defaultdict(int)
    fmt_match: dict[str, int] = defaultdict(int)
    for o in outcomes:
        fmt_total[o.file_format] += 1
        if o.outcome == "MATCHED":
            fmt_match[o.file_format] += 1

    print("-" * 78)
    print("BY FORMAT  (strict recall)")
    print("-" * 78)
    for fmt in sorted(fmt_total):
        print(fmt_recall_line(fmt, fmt_match[fmt], fmt_total[fmt]))
    print()

    repo_total: dict[str, int] = defaultdict(int)
    repo_match: dict[str, int] = defaultdict(int)
    for o in outcomes:
        repo_total[o.repo] += 1
        if o.outcome == "MATCHED":
            repo_match[o.repo] += 1

    if len(repo_total) > 1:
        print("-" * 78)
        print("BY REPO  (strict recall)")
        print("-" * 78)
        for repo in sorted(repo_total):
            print(fmt_recall_line(repo, repo_match[repo], repo_total[repo]))
        print()

    if path_mismatch:
        print("-" * 78)
        print(f"PATH_MISMATCH details  ({len(path_mismatch)} cases — fix these first)")
        print("-" * 78)
        for o in path_mismatch[:25]:
            print(f"  {o.repo:<10} {o.control_id:<28} {o.file_format:<10} {o.expected_path}")
        if len(path_mismatch) > 25:
            print(f"  ... and {len(path_mismatch) - 25} more (see CSV)")
        print()

    if value_missing:
        print("-" * 78)
        print(f"VALUE_NOT_FOUND details  ({len(value_missing)} cases — true detector misses)")
        print("-" * 78)
        by_fam: dict[str, list[LocationOutcome]] = defaultdict(list)
        for o in value_missing:
            by_fam[o.family].append(o)
        for fam in sorted(by_fam):
            print(f"  [{fam}] ({len(by_fam[fam])})")
            for o in by_fam[fam][:5]:
                print(f"    {o.repo:<10} {o.control_id:<28} {o.file_format:<10} {o.expected_path}")
            if len(by_fam[fam]) > 5:
                print(f"    ... and {len(by_fam[fam]) - 5} more (see CSV)")
        print()

    print("=" * 78)


def write_diagnostic_csv(outcomes: list[LocationOutcome], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "repo",
                "control_id",
                "family",
                "file_format",
                "expected_path",
                "expected_value_preview",
                "outcome",
                "detail",
            ]
        )
        for o in outcomes:
            w.writerow(
                [
                    o.repo,
                    o.control_id,
                    o.family,
                    o.file_format,
                    o.expected_path,
                    o.expected_value,
                    o.outcome,
                    o.detail,
                ]
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def derive_repo_label(seed_log_path: Path) -> str:
    name = seed_log_path.name
    for suffix in (".seed_log.json", ".seedlog.json", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def main() -> int:
    p = argparse.ArgumentParser(description="Compute Autonoma recall against seeded controls.")
    p.add_argument("--seed-log", type=Path, action="append", required=True, help="Seed log JSON (repeatable)")
    p.add_argument("--findings", type=Path, action="append", required=True, help="Findings JSON (repeatable, paired with --seed-log in order)")
    p.add_argument("--diagnostic-out", type=Path, default=None, help="Optional CSV with per-finding diagnostics")
    p.add_argument("--repo-root-hint", type=str, default=None, help="Strip this prefix from finding paths before comparison")
    args = p.parse_args()

    if len(args.seed_log) != len(args.findings):
        print("Number of --seed-log and --findings arguments must match.", file=sys.stderr)
        return 2

    all_outcomes: list[LocationOutcome] = []
    for seed_log_path, findings_path in zip(args.seed_log, args.findings):
        try:
            seed_log = json.loads(seed_log_path.read_text())
            findings_doc = json.loads(findings_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"Failed to read {seed_log_path} / {findings_path}: {e}", file=sys.stderr)
            return 2

        repo_label = derive_repo_label(seed_log_path)
        outcomes = diagnose(seed_log, findings_doc, repo_label, args.repo_root_hint)
        all_outcomes.extend(outcomes)

    print_report(all_outcomes)

    if args.diagnostic_out:
        write_diagnostic_csv(all_outcomes, args.diagnostic_out)
        print(f"Diagnostic CSV written to: {args.diagnostic_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
