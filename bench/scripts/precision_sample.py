#!/usr/bin/env python3
"""
precision_sample.py -- Generate a deterministic review sample from SEC002 findings.

Inputs
------
One or more findings files (CSV or JSON), an RNG seed, a target sample size,
and optional repo filters.  Outputs a review-ready CSV and an optional JSONL
manifest.

Input formats accepted
----------------------
CSV (like bench/findings_full.csv):
    repo, file, line, rule_id, [severity], [matched_value],
    [line_context], [surrounding_context], [classification], [synthetic]

JSON (autonoma scan output or enriched variant):
    {"findings": [{...}, ...]}   -- single-repo wrapper
    [{...}, ...]                 -- flat list
    Each object may carry: repo, file, line, rule_id, matched_value,
    surrounding_context, fingerprint, synthetic, provider, ...

Output CSV fields
-----------------
finding_id, repo, file, line, rule_id, matched_preview, surrounding_context,
synthetic, human_label, category, review_notes, reviewer, review_timestamp,
labeling_pass_id

Determinism guarantees
----------------------
1. Input rows are sorted by (repo, file, line, rule_id) before deduplication so
   "first occurrence wins" is stable regardless of input ordering.
2. Deduplication removes exact-key duplicates after sorting.
3. Shuffling uses random.Random(seed) so same seed => identical sample order.

Synthetic field parsing
-----------------------
The synthetic CSV column is authoritative.  Only the literal strings "true" and
"false" (case-insensitive, whitespace-trimmed) are accepted.

Any other value — including "yes", "1", "", or Python repr "False" — is
rejected as malformed.  Malformed rows are excluded from the sample and a
warning is emitted per row.  The malformed count is printed in the summary.

DO NOT silently coerce unknown values.

Redaction
---------
Raw matched values are NEVER written to the output CSV.  The matched_preview
field preserves enough structure to orient the reviewer (provider prefix + first
few chars + ellipsis + last few chars) while hiding the interior.

Examples:
    ghp_abcdefghijklmnopqrstuvwxyz0123  -->  ghp_abcd...0123
    sk_live_51ABCDEFGHIJKLMNOPQRSTU     -->  sk_live_51AB...RSTU
    AKIAIOSFODNN7EXAMPLE                -->  AKIA...MPLE
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Known provider prefixes (longest first so greediest match wins)
# ---------------------------------------------------------------------------

_KNOWN_PREFIXES: list[str] = [
    "github_pat_",
    "sk_live_",
    "sk_test_",
    "pk_live_",
    "pk_test_",
    "whsec_",
    "rk_live_",
    "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
    "xoxb-", "xoxp-", "xoxa-", "xoxr-",
    "AIza",
    "AKIA", "ASIA",
    "Bearer ",
]

_REDACTION_ELLIPSIS = "..."
_PREVIEW_HEAD = 4  # chars to keep after prefix (or from start if no prefix)
_PREVIEW_TAIL = 4  # chars to keep at end


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

OUTPUT_FIELDNAMES = [
    "finding_id",
    "repo",
    "file",
    "line",
    "rule_id",
    "matched_preview",
    "surrounding_context",
    "synthetic",
    "human_label",
    "category",
    "review_notes",
    "reviewer",
    "review_timestamp",
    "labeling_pass_id",
]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def redact_preview(value: str) -> str:
    """Return a structure-preserving but interior-redacted preview.

    Keeps any known provider prefix intact, then shows the first
    _PREVIEW_HEAD and last _PREVIEW_TAIL characters of the remaining
    content separated by an ellipsis.  Very short values are fully masked.
    """
    if not value:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""

    prefix = ""
    body = stripped
    for pfx in _KNOWN_PREFIXES:
        if stripped.startswith(pfx):
            prefix = pfx
            body = stripped[len(pfx):]
            break

    min_len = _PREVIEW_HEAD + _PREVIEW_TAIL + len(_REDACTION_ELLIPSIS)
    if len(body) <= min_len:
        return prefix + "*" * max(3, len(body))

    return prefix + body[:_PREVIEW_HEAD] + _REDACTION_ELLIPSIS + body[-_PREVIEW_TAIL:]


# ---------------------------------------------------------------------------
# Finding identity
# ---------------------------------------------------------------------------

def make_finding_id(repo: str, file: str, line: int | str, rule_id: str) -> str:
    """Stable sha256-based ID for (repo, file, line, rule_id)."""
    key = f"{repo}|{file}|{line}|{rule_id}"
    return "F" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def finding_dedup_key(row: dict) -> tuple:
    return (
        row.get("repo", ""),
        row.get("file", ""),
        str(row.get("line", "")),
        row.get("rule_id", ""),
    )


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
        "yes", "1", "no", "0", "", "False", "TRUE " -> (None, <message>)

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
# Input loading
# ---------------------------------------------------------------------------

def _load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("findings", "results", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


def load_findings(paths: list[Path]) -> list[dict]:
    """Load findings from one or more CSV or JSON files."""
    all_rows: list[dict] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            rows = _load_csv(path)
        elif suffix in (".json", ".jsonl"):
            rows = _load_json(path)
        else:
            print(f"warning: unrecognised extension {path.suffix!r}, trying JSON",
                  file=sys.stderr)
            rows = _load_json(path)

        # Attach repo name from filename if not present in rows
        repo_from_name = path.stem.split(".")[0]
        for r in rows:
            if not r.get("repo"):
                r["repo"] = repo_from_name

        all_rows.extend(rows)

    return all_rows


# ---------------------------------------------------------------------------
# Normalisation → canonical Finding dict
# ---------------------------------------------------------------------------

def normalise(row: dict) -> dict:
    """Return a canonical finding dict from a raw CSV or JSON row.

    The returned dict always has a 'malformed' key (bool) and a
    'malformed_reason' key (str).  Malformed rows must be filtered out
    before sampling.

    The synthetic field uses strict parsing — only "true" / "false"
    (case-insensitive, trimmed) are accepted.  Any other value, including
    "yes", "1", or empty string, marks the row malformed.
    """
    # Convert to string without losing Python bool False via truthiness coercion.
    # JSON booleans load as Python True/False; str(False) -> "False" -> accepted.
    raw_val = row.get("synthetic")
    if isinstance(raw_val, bool):
        raw_synthetic = "true" if raw_val else "false"
    elif raw_val is None:
        raw_synthetic = ""
    else:
        raw_synthetic = str(raw_val)
    synthetic_val, synthetic_err = parse_synthetic_strict(raw_synthetic)

    malformed = synthetic_err is not None
    malformed_reason = synthetic_err or ""

    return {
        "repo": str(row.get("repo", "") or ""),
        "file": str(row.get("file", "") or row.get("path", "") or ""),
        "line": str(row.get("line", "") or ""),
        "rule_id": str(row.get("rule_id", "") or ""),
        "matched_value": str(row.get("matched_value", "") or row.get("value", "") or ""),
        "surrounding_context": str(
            row.get("surrounding_context", "")
            or row.get("line_context", "")
            or ""
        ),
        "synthetic": synthetic_val if not malformed else False,
        "malformed": malformed,
        "malformed_reason": malformed_reason,
    }


# ---------------------------------------------------------------------------
# Deduplication (with deterministic sort before dedup)
# ---------------------------------------------------------------------------

def deduplicate(rows: list[dict]) -> list[dict]:
    """Remove duplicate findings, keeping first occurrence per identity key.

    Sorts by (repo, file, line, rule_id) BEFORE deduplication so that
    "first occurrence wins" is stable regardless of input file ordering.
    """
    sorted_rows = sorted(rows, key=lambda r: (
        r.get("repo", ""),
        r.get("file", ""),
        str(r.get("line", "")),
        r.get("rule_id", ""),
        r.get("matched_value", ""),  # tiebreaker: deterministic winner for same-key rows
    ))
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in sorted_rows:
        key = finding_dedup_key(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def sample_findings(
    rows: list[dict],
    seed: int,
    size: int,
    repos: list[str] | None = None,
) -> list[dict]:
    """Return a deterministic sample of up to `size` findings.

    Same seed => identical ordering.  Different seed => different ordering.
    """
    filtered = rows
    if repos:
        repo_set = {r.lower() for r in repos}
        filtered = [r for r in rows if r.get("repo", "").lower() in repo_set]

    rng = random.Random(seed)
    shuffled = list(filtered)
    rng.shuffle(shuffled)
    return shuffled[:size]


# ---------------------------------------------------------------------------
# Output conversion
# ---------------------------------------------------------------------------

def to_output_row(row: dict) -> dict:
    """Convert a canonical finding dict to an output CSV row."""
    repo = row["repo"]
    file_ = row["file"]
    line = row["line"]
    rule_id = row["rule_id"]
    matched_value = row["matched_value"]

    return {
        "finding_id": make_finding_id(repo, file_, line, rule_id),
        "repo": repo,
        "file": file_,
        "line": line,
        "rule_id": rule_id,
        "matched_preview": redact_preview(matched_value),
        "surrounding_context": row["surrounding_context"],
        "synthetic": "true" if row["synthetic"] else "false",
        # Reviewer-filled columns — empty placeholders
        "human_label": "",
        "category": "",
        "review_notes": "",
        "reviewer": "",
        "review_timestamp": "",
        "labeling_pass_id": "",
    }


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate a deterministic precision-review sample.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input", "-i",
        nargs="+",
        required=True,
        metavar="FILE",
        help="One or more findings files (CSV or JSON).",
    )
    p.add_argument(
        "--seed", "-s",
        type=int,
        required=True,
        help="RNG seed for deterministic sampling.",
    )
    p.add_argument(
        "--size", "-n",
        type=int,
        required=True,
        help="Target sample size.",
    )
    p.add_argument(
        "--repo",
        nargs="*",
        metavar="REPO",
        help="Restrict to these repos (case-insensitive).",
    )
    p.add_argument(
        "--out", "-o",
        default=None,
        metavar="FILE",
        help="Output CSV path (default: stdout).",
    )
    p.add_argument(
        "--jsonl",
        default=None,
        metavar="FILE",
        help="Also write a JSONL manifest.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_paths = [Path(p) for p in args.input]
    for p in input_paths:
        if not p.exists():
            print(f"ERROR: input file not found: {p}", file=sys.stderr)
            return 1

    raw = load_findings(input_paths)
    if not raw:
        print("ERROR: no findings loaded from inputs.", file=sys.stderr)
        return 1

    normalised = [normalise(r) for r in raw]

    # Warn about and exclude malformed rows
    malformed_rows = [r for r in normalised if r["malformed"]]
    clean_rows = [r for r in normalised if not r["malformed"]]

    if malformed_rows:
        print(
            f"warning: {len(malformed_rows)} row(s) excluded due to malformed "
            f"synthetic field:",
            file=sys.stderr,
        )
        for r in malformed_rows[:20]:  # cap log output
            loc = f"{r['repo']}:{r['file']}:{r['line']}"
            print(f"  [{loc}] {r['malformed_reason']}", file=sys.stderr)
        if len(malformed_rows) > 20:
            print(
                f"  ... and {len(malformed_rows) - 20} more (suppressed)",
                file=sys.stderr,
            )

    if not clean_rows:
        print("ERROR: no valid findings remain after excluding malformed rows.",
              file=sys.stderr)
        return 1

    unique = deduplicate(clean_rows)
    sampled = sample_findings(unique, args.seed, args.size, args.repo)
    output_rows = [to_output_row(r) for r in sampled]

    if args.out:
        out_path = Path(args.out)
        write_csv(output_rows, out_path)
        print(f"Wrote {len(output_rows)} rows to {out_path}", file=sys.stderr)
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(output_rows)

    if args.jsonl:
        jsonl_path = Path(args.jsonl)
        write_jsonl(output_rows, jsonl_path)
        print(f"Wrote JSONL manifest to {jsonl_path}", file=sys.stderr)

    # Summary
    synthetic_count = sum(1 for r in output_rows if r["synthetic"] == "true")
    real_count = len(output_rows) - synthetic_count
    print(
        f"Sample: {len(output_rows)} total "
        f"({real_count} real-world, {synthetic_count} synthetic controls)",
        file=sys.stderr,
    )
    if malformed_rows:
        print(
            f"Malformed rows excluded from sample: {len(malformed_rows)}",
            file=sys.stderr,
        )
    if args.size > len(unique):
        print(
            f"warning: requested {args.size} but only {len(unique)} unique findings "
            f"available after deduplication.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
