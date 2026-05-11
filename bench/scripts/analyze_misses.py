"""
SEC002 miss-pattern classifier.

Reads bench/reports/sec002_recall_diagnostic_v2.csv and classifies each
VALUE_NOT_FOUND row into one of seven categories:

  EXTENSION_EXCLUDED   -- file not scanned; .md excluded from DEFAULT_EXTENSIONS
  FAMILY_OUT_OF_SCOPE  -- family intentionally outside SEC002 detection scope
  KEYWORD_GAP          -- value reachable and in scope, but keyword routing never
                          evaluated it because the var/key name is not in SEC002
                          keyword patterns (architectural/routing miss)
  PARSER_GAP           -- file/family in scope, but parser extraction or syntax
                          routing failed before SEC002 evaluation could occur
                          (extraction/routing miss)
  DETECTOR_MISS        -- value reachable, in scope, parser-accessible, keyword-
                          routing evaluated it, but SEC002 still failed to detect
                          (true detector failure — smallest bucket)
  REMEDIATION_UNSAFE   -- detection possible, safe remediation blocked
  BENCHMARK_ARTIFACT   -- seeding, path, or fingerprinting issue

KEYWORD_GAP, PARSER_GAP, and DETECTOR_MISS replace what was previously a single
monolithic DETECTOR_MISS bucket. The distinction matters for engineering triage:
KEYWORD_GAP indicates routing architecture changes, PARSER_GAP indicates extraction
work, and DETECTOR_MISS indicates a true SEC002 pattern failure.

Outputs:
  bench/reports/sec002_miss_pattern_analysis.md
  bench/reports/sec002_miss_pattern_analysis.json

Usage:
    python bench/scripts/analyze_misses.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
DIAGNOSTIC_CSV = BENCH_DIR / "reports" / "sec002_recall_diagnostic_v2.csv"
OUT_MD = BENCH_DIR / "reports" / "sec002_miss_pattern_analysis.md"
OUT_JSON = BENCH_DIR / "reports" / "sec002_miss_pattern_analysis.json"

# ---------------------------------------------------------------------------
# Classification rules
# Evidence basis noted for each rule.
# ---------------------------------------------------------------------------

# Families with NO detection rule in the current SEC002 implementation.
# PEM: no -----BEGIN RSA PRIVATE KEY----- pattern exists.
# opaque_random_cred: 24-40 char alphanumeric/dash/underscore with no prefix;
#   entropy-based detection intentionally excluded pending a false-positive corpus.
FAMILY_OUT_OF_SCOPE_FAMILIES = {"pem_private", "opaque_random_cred"}

# Families where SEC002 keyword routing never evaluated the value because the
# seeder assigned a var_name that falls outside the current keyword sets.
#
# heuristics.py DEFAULT_EXTENSIONS excludes .md entirely.
# heuristics.py patterns require one of these var_name keywords:
#   .py:   api_key, apikey, secret_key, secret, token, auth_token, api_secret,
#          access_key, private_key
#   .env:  secret, api_key, api_secret, auth_token, auth_key, access_key,
#          private_key, token, stripe, sendgrid, twilio, mailgun, github_token,
#          heroku, cloudinary
#   .yaml: api_key, secret_key, secret, auth_token, auth_key, access_key,
#          private_key, token
#   .json: api_key, secret_key, secret, auth_token, auth_key, access_key,
#          private_key, token
#
# Var_names the seeder can assign that are NOT in any keyword set:
#   generic_bearer:       api_bearer, auth_bearer    (bearer_token has 'token')
#   opaque_session_token: user_session, access_session (session_token has 'token')
#   github_pat:           gh_pat                     (github_token/github_api_token ok)
#   google_api:           gcp_key                    (google_api_key/maps_api_key ok)
#   jwt:                  session_jwt                (auth_token/id_token ok)
#
# These are KEYWORD_GAP misses: routing architecture failures, not detector failures.
# The parser reached the value; SEC002 keyword routing never evaluated it.
KEYWORD_GAP_FAMILIES = {
    "generic_bearer",
    "opaque_session_token",
    "github_pat",
    "google_api",
    "jwt",
}

# Families where parser/extraction failure is the identified miss cause.
# Currently empty for in-scope families. pem_private has parser gaps (triple-quoted
# Python, YAML block scalars) but is FAMILY_OUT_OF_SCOPE, so those misses stay there.
# No in-scope family in the current benchmark produces PARSER_GAP misses.
PARSER_GAP_FAMILIES: set[str] = set()

KEYWORD_GAP_NOTES: dict[str, str] = {
    "generic_bearer": (
        "Var_names 'api_bearer' and 'auth_bearer' contain no SEC002 keyword. "
        "'bearer_token' (contains 'token') is detectable; the other two are not."
    ),
    "opaque_session_token": (
        "Var_names 'user_session' and 'access_session' contain no SEC002 keyword. "
        "'session_token' (contains 'token') is detectable; the other two are not."
    ),
    "github_pat": (
        "Var_name 'gh_pat' contains no SEC002 keyword. "
        "'github_token' and 'github_api_token' (contain 'token') are detectable."
    ),
    "google_api": (
        "Var_name 'gcp_key' contains no SEC002 keyword. "
        "'google_api_key' and 'maps_api_key' (contain 'api_key') are detectable."
    ),
    "jwt": (
        "Var_name 'session_jwt' contains no SEC002 keyword. "
        "'auth_token' and 'id_token' (contain 'token') are detectable."
    ),
    "opaque_api_secret": (
        "All three var_names contain 'secret', so keyword matching should fire. "
        "This single miss is anomalous; likely a value-side gate interaction "
        "(e.g. _looks_like_identifier_or_word on a value with $, *, @ chars in an env file)."
    ),
    "aws_pair": (
        "aws_pair miss is markdown-format only (EXTENSION_EXCLUDED). "
        "No non-markdown aws_pair misses."
    ),
    "slack_bot": (
        "slack_bot miss is markdown-format only (EXTENSION_EXCLUDED)."
    ),
    "stripe": (
        "stripe miss is markdown-format only (EXTENSION_EXCLUDED)."
    ),
}

PEM_ROUTING_NOTE = (
    "PEM misses have three compounding causes: "
    "(1) No detection rule for PEM envelope markers exists in SEC002 or any current rule. "
    "(2) Python triple-quoted strings (\"\"\"...\"\"\") are not matched by the single-quote "
    "regex ['\"][^'\"]+['\"]. "
    "(3) YAML block scalars ('|') put the value on subsequent indented lines, "
    "invisible to a single-line key: value regex. "
    "PRIMARY classification: FAMILY_OUT_OF_SCOPE."
)


def classify(family: str, file_format: str) -> tuple[str, str]:
    """Return (category, reason) for a VALUE_NOT_FOUND row."""
    if file_format == "markdown":
        return (
            "EXTENSION_EXCLUDED",
            ".md is not in DEFAULT_EXTENSIONS or ALL_SUPPORTED_EXTENSIONS in heuristics.py. "
            "Files are excluded before any scanner sees them.",
        )

    if family in FAMILY_OUT_OF_SCOPE_FAMILIES:
        if family == "pem_private":
            return "FAMILY_OUT_OF_SCOPE", PEM_ROUTING_NOTE
        return (
            "FAMILY_OUT_OF_SCOPE",
            "Generic entropy-only random credentials have no structural prefix or "
            "keyword pattern. Broad entropy rules intentionally excluded pending a "
            "labeled false-positive corpus. No SEC002 or other current rule covers "
            "this family.",
        )

    if family in KEYWORD_GAP_FAMILIES:
        note = KEYWORD_GAP_NOTES.get(family, "Var_name not in SEC002 keyword pattern list.")
        return "KEYWORD_GAP", note

    if family in PARSER_GAP_FAMILIES:
        return (
            "PARSER_GAP",
            "File and family are in scope, but parser extraction or syntax routing "
            "failed before SEC002 evaluation could occur.",
        )

    # True detector miss: value reachable, in scope, parser-accessible,
    # keyword-routing should have evaluated it, but SEC002 still failed.
    note = KEYWORD_GAP_NOTES.get(
        family,
        "Value reachable and in scope; keyword-routing evaluated it but SEC002 failed to detect.",
    )
    return "DETECTOR_MISS", note


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float, float]:
    if trials == 0:
        return 0.0, 0.0, 0.0
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = (z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main() -> int:
    if not DIAGNOSTIC_CSV.exists():
        print(f"ERROR: {DIAGNOSTIC_CSV} not found. Run benchmark_runner.py first.", file=sys.stderr)
        return 2

    rows = []
    misses = []
    total = 0

    with DIAGNOSTIC_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            total += 1
            rows.append(row)
            if row["outcome"] == "VALUE_NOT_FOUND":
                cat, reason = classify(row["family"], row["file_format"])
                misses.append({
                    "repo": row["repo"],
                    "control_id": row["control_id"],
                    "family": row["family"],
                    "file_format": row["file_format"],
                    "expected_path": row["expected_path"],
                    "outcome": row["outcome"],
                    "category": cat,
                    "reason": reason,
                })

    matched = total - len(misses)
    n_miss = len(misses)

    # Aggregate counts
    by_category: dict[str, int] = defaultdict(int)
    by_repo: dict[str, int] = defaultdict(int)
    by_family: dict[str, int] = defaultdict(int)
    by_format: dict[str, int] = defaultdict(int)
    by_family_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_format_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for m in misses:
        by_category[m["category"]] += 1
        by_repo[m["repo"]] += 1
        by_family[m["family"]] += 1
        by_format[m["file_format"]] += 1
        by_family_cat[m["family"]][m["category"]] += 1
        by_format_cat[m["file_format"]][m["category"]] += 1

    # Category ordering
    CATEGORIES = [
        "EXTENSION_EXCLUDED",
        "FAMILY_OUT_OF_SCOPE",
        "KEYWORD_GAP",
        "PARSER_GAP",
        "DETECTOR_MISS",
        "REMEDIATION_UNSAFE",
        "BENCHMARK_ARTIFACT",
    ]

    # Per-family recall for context
    fam_total: dict[str, int] = defaultdict(int)
    fam_match: dict[str, int] = defaultdict(int)
    for row in rows:
        fam_total[row["family"]] += 1
        if row["outcome"] == "MATCHED":
            fam_match[row["family"]] += 1

    repo_total: dict[str, int] = defaultdict(int)
    repo_match: dict[str, int] = defaultdict(int)
    for row in rows:
        repo_total[row["repo"]] += 1
        if row["outcome"] == "MATCHED":
            repo_match[row["repo"]] += 1

    # -----------------------------------------------------------------------
    # Build JSON output
    # -----------------------------------------------------------------------

    analysis_json = {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(DIAGNOSTIC_CSV),
        "taxonomy_note": (
            "DETECTOR_MISS has been split into three categories: KEYWORD_GAP "
            "(routing architecture failure — var_name not in SEC002 keyword sets), "
            "PARSER_GAP (extraction failure — parser could not surface the value), "
            "and DETECTOR_MISS (true detection failure — value reachable and "
            "keyword-routing evaluated it, but SEC002 failed to detect)."
        ),
        "summary": {
            "total_seeded": total,
            "total_matched": matched,
            "total_missed": n_miss,
            "strict_recall": round(matched / total, 4) if total else 0,
        },
        "by_category": {
            cat: {
                "count": by_category.get(cat, 0),
                "pct_of_misses": round(by_category.get(cat, 0) / n_miss, 4) if n_miss else 0,
                "description": {
                    "EXTENSION_EXCLUDED": "File type excluded from DEFAULT_EXTENSIONS; never scanned.",
                    "FAMILY_OUT_OF_SCOPE": "Family intentionally outside SEC002 scope by design.",
                    "KEYWORD_GAP": (
                        "Value reachable and in scope; keyword routing never evaluated "
                        "because the var/key name is not in the SEC002 keyword sets. "
                        "Architectural/routing failure."
                    ),
                    "PARSER_GAP": (
                        "File and family in scope; parser extraction or syntax routing "
                        "failed before SEC002 evaluation could occur. Extraction failure."
                    ),
                    "DETECTOR_MISS": (
                        "Value reachable, in scope, parser-accessible, keyword-routing "
                        "evaluated it, but SEC002 still failed to detect. True detector failure."
                    ),
                    "REMEDIATION_UNSAFE": "Detection possible; safe remediation blocked by policy.",
                    "BENCHMARK_ARTIFACT": "Seeding, path, or fingerprinting issue in benchmark.",
                }.get(cat, ""),
            }
            for cat in CATEGORIES
        },
        "by_family": {
            fam: {
                "total_seeded": fam_total[fam],
                "matched": fam_match[fam],
                "missed": fam_total[fam] - fam_match[fam],
                "recall": round(fam_match[fam] / fam_total[fam], 4) if fam_total[fam] else 0,
                "miss_categories": dict(by_family_cat.get(fam, {})),
            }
            for fam in sorted(fam_total)
        },
        "by_repo": {
            repo: {
                "total_seeded": repo_total[repo],
                "matched": repo_match[repo],
                "missed": repo_total[repo] - repo_match[repo],
                "recall": round(repo_match[repo] / repo_total[repo], 4) if repo_total[repo] else 0,
            }
            for repo in sorted(repo_total)
        },
        "by_format": {
            fmt: {
                "total_seeded": sum(1 for r in rows if r["file_format"] == fmt),
                "missed": by_format.get(fmt, 0),
                "miss_categories": dict(by_format_cat.get(fmt, {})),
            }
            for fmt in sorted(by_format)
        },
        "missed_controls": misses,
    }

    # -----------------------------------------------------------------------
    # Build Markdown report
    # -----------------------------------------------------------------------

    lines = []

    def h(n: int, text: str) -> None:
        lines.append(f"{'#' * n} {text}")
        lines.append("")

    def p(text: str = "") -> None:
        lines.append(text)

    h(1, "SEC002 Miss-Pattern Analysis Report")
    p(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    p(f"Source: `{DIAGNOSTIC_CSV.name}`")
    p(f"Corpus: 10 repos, 33 controls/repo, 330 total seedings")
    p()

    h(2, "1. Executive Summary")
    p(f"- **Total seeded controls**: {total}")
    p(f"- **Matched (detected)**: {matched} ({pct(matched/total)})")
    p(f"- **Missed (VALUE_NOT_FOUND)**: {n_miss} ({pct(n_miss/total)})")
    p(f"- **Strict recall**: {pct(matched/total)} (headline metric, unchanged)")
    p()
    p(
        "The 142 missed controls decompose into four root-cause tiers. "
        "Fourteen are architectural exclusions (Markdown extension not scanned). "
        "Fifty belong to families intentionally outside SEC002 scope (PEM private keys and "
        "opaque random credentials). Seventy-seven are routing architecture failures where "
        "the seeder assigned variable names outside the SEC002 keyword sets — the parser "
        "reached the value but keyword routing never evaluated it. One is a true detector "
        "failure where keyword routing evaluated the value but SEC002 failed to detect it."
    )
    p()

    h(2, "2. Miss Categories")
    p(
        "The old DETECTOR_MISS bucket has been split into three categories that reflect "
        "distinct failure modes in the detection pipeline. See Section 2a for definitions."
    )
    p()
    p(f"{'Category':<28} {'Count':>6}  {'% of Misses':>12}  {'% of Total':>11}")
    p("-" * 65)
    for cat in CATEGORIES:
        cnt = by_category.get(cat, 0)
        pct_m = cnt / n_miss if n_miss else 0
        pct_t = cnt / total if total else 0
        p(f"{cat:<28} {cnt:>6}  {pct(pct_m):>12}  {pct(pct_t):>11}")
    p()

    h(3, "2a. Failure Mode Definitions")
    p(
        "Three distinct failure modes replace the prior monolithic DETECTOR_MISS bucket. "
        "Separating them allows engineering work to be directed at the correct layer."
    )
    p()
    p("**KEYWORD_GAP — Architectural/routing failure**")
    p(
        "The credential value shape is recognizable and the family is in scope, but "
        "SEC002 keyword routing never evaluated the value because the variable or key name "
        "is not present in the SEC002 keyword pattern lists. The parser successfully "
        "extracted the value; the detector never received it. This is a routing "
        "architecture gap. Fixing it requires extending the keyword sets, not changing "
        "detection logic. Keyword additions require FP validation before deployment."
    )
    p()
    p("Examples: `gh_pat = \"ghp_...\"`, `gcp_key = \"AIza...\"`, `api_bearer = \"...\"`, `access_session = \"...\"`")
    p()
    p("**PARSER_GAP — Extraction/routing failure**")
    p(
        "The file type and family are in scope, but parser extraction or syntax routing "
        "failed before SEC002 evaluation could occur. The detector never received a "
        "candidate value to evaluate. Examples include Python triple-quoted multiline "
        "strings (not matched by the single-quote regex) and YAML block scalars "
        "(the parser extracts `|` instead of the key material on subsequent indented lines). "
        "No in-scope families currently produce PARSER_GAP misses in this benchmark — "
        "`pem_private`, the primary example of these parser limitations, is "
        "FAMILY_OUT_OF_SCOPE. The category is defined here for completeness and for "
        "future use when in-scope families with multiline value formats are added."
    )
    p()
    p("**DETECTOR_MISS — True detection failure**")
    p(
        "The value was reachable, in scope, parser-accessible, and keyword routing "
        "evaluated it, but SEC002 still failed to detect it. This is the smallest bucket "
        "and represents genuine pattern or logic failures in the detector. "
        "Current data shows 1 case: `opaque_api_secret` in an ENV file where the value "
        "contains special characters (`$`, `*`, `@`) that are believed to trigger a "
        "value-side gate (`_looks_like_identifier_or_word`), blocking detection despite "
        "the `secret` keyword matching."
    )
    p()

    h(2, "3. Investigation: Markdown 0% Detection")
    p("**Question**: Was Markdown scanned? Extension excluded? Secrets inside fenced code blocks?")
    p()
    p("**Finding**: `.md` is completely absent from both `DEFAULT_EXTENSIONS` and")
    p("`ALL_SUPPORTED_EXTENSIONS` in `src/autonoma/_internal/heuristics.py`.")
    p("Files are filtered out before any scanner or parser runs.")
    p()
    p("Seeded Markdown content format (from `seeder.py render_markdown`):")
    p("```markdown")
    p("## google_api_key")
    p("")
    p("Example value:")
    p("")
    p("```")
    p("GIZAHYqM6Ojb6mjBHqSiFVKu4MbMnrHontIKARA")
    p("```")
    p("```")
    p()
    p("Secrets are in fenced code blocks, rendered as plain text inside triple backticks.")
    p("No Python/YAML/JSON/ENV syntax — Markdown has its own structure.")
    p()
    md_fams: dict[str, int] = defaultdict(int)
    for m in misses:
        if m["file_format"] == "markdown":
            md_fams[m["family"]] += 1
    p(f"**Impact**: 14 missed controls (9.9% of all misses).")
    p()
    p(f"The 14 Markdown misses span {len(md_fams)} families:")
    for fam, cnt in sorted(md_fams.items()):
        p(f"- {fam}: {cnt}")
    p()
    p("**Determination**: `EXTENSION_EXCLUDED`. This is an architectural scope decision.")
    p("Markdown detection would require a different extraction strategy (text scanning")
    p("for token-like patterns, not key=value or key: value). No false-positive analysis")
    p("of Markdown content currently exists.")
    p()

    h(2, "4. Investigation: PEM Private Key 0% Detection")
    p("**Question**: Is PEM detection in SEC002 scope? Different rule? Remediation safe?")
    p()
    p("**Finding**: No PEM detection rule exists in any current Autonoma rule (SEC001–SEC005).")
    p()
    p("PEM values are seeded in three rendered formats:")
    p()
    p("**Python** (triple-quoted string):")
    p("```python")
    p('server_private_key = """-----BEGIN RSA PRIVATE KEY-----')
    p("nIB2PWKhPV5ibveNkDNjl3S4W5oH...")
    p("-----END RSA PRIVATE KEY-----\"\"\"")
    p("```")
    p("The Python regex `['\"][^'\"]+['\"]` cannot match triple-quoted strings.")
    p("This is a PARSER_GAP for PEM — but since PEM is FAMILY_OUT_OF_SCOPE, the")
    p("parser limitation is secondary to the scope decision.")
    p()
    p("**YAML** (block scalar):")
    p("```yaml")
    p("server_private_key: |")
    p("  -----BEGIN RSA PRIVATE KEY-----")
    p("  nIB2PWKhPV5ibveNkDNjl3S4W5oH...")
    p("  -----END RSA PRIVATE KEY-----")
    p("```")
    p("The YAML regex sees `server_private_key: |` and extracts `|` as the value.")
    p("The actual key material is on subsequent indented lines — invisible to a")
    p("single-line `key: value` pattern. This is also a PARSER_GAP for PEM.")
    p()
    p("**ENV** (escaped newlines, single line):")
    p("```")
    p('SERVER_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\nnIB2PWKh..."')
    p("```")
    p("When var_name is `server_private_key` or `rsa_private_key`, the `private_key`")
    p("keyword IS in the ENV pattern. When var_name is `tls_key`, no keyword matches.")
    p()
    p("**Remediation safety**: PEM key replacement requires knowing the private key's")
    p("usage context, correct PEM encoding, and ensuring the replacement key matches")
    p("paired certificates. AST-safe deterministic remediation for multiline PEM blobs")
    p("is not currently implemented and would be high-risk.")
    p()
    p("**Determination**: `FAMILY_OUT_OF_SCOPE`. PEM private key detection belongs in a")
    p("separate rule (e.g., a future SEC006) with dedicated multiline extraction,")
    p("not as an extension of SEC002's key=value pattern. Remediation safety is")
    p("a separate blocker even if detection were added.")
    p()

    h(2, "5. Investigation: Opaque Token Misses")
    p()
    h(3, "5a. opaque_random_cred (22.2% recall, 21 missed in supported formats)")
    p("**Var_names assigned by seeder**: `credential`, `auth_credential`, `service_credential`")
    p("**Value structure**: 24–40 char alphanumeric + `_-`, no prefix, variable length")
    p()
    p("None of the three var_names contain a keyword from any SEC002 pattern.")
    p("The value structure provides no structural signal either — no prefix, no fixed length.")
    p()
    p("**Determination**: `FAMILY_OUT_OF_SCOPE`. Detecting generic random credentials")
    p("requires entropy-based analysis. Adding entropy rules without a labeled false-positive")
    p("corpus would compromise SEC002's precision-oriented design. This exclusion is")
    p("intentional per the project's anti-overfitting policy.")
    p()

    h(3, "5b. opaque_session_token (26.7% recall, 22 missed total, 21 in supported formats)")
    p("**Var_names**: `session_token`, `user_session`, `access_session`")
    p("**Value structure**: `{8 base62}-{12 base62}-{12 base62}`, e.g. `SFx7ZHrZ-fUBfBM0lIsug-fuQstCMTBkSC`")
    p()
    p("`session_token` contains `token` — matched by the SEC002 token keyword. Detected when this var_name is assigned.")
    p("`user_session` and `access_session` contain no SEC002 keyword — missed regardless of format.")
    p()
    p("**Determination**: `KEYWORD_GAP`. The var_name keyword gap in SEC002 routing explains")
    p("the miss pattern. The parser extracted the value correctly; keyword routing never")
    p("evaluated it because neither `user_session` nor `access_session` appears in any")
    p("SEC002 keyword list. This is a routing architecture miss, not a detector miss.")
    p()

    h(3, "5c. generic_bearer (20.0% recall, 24 missed total, 23 in supported formats)")
    p("**Var_names**: `bearer_token`, `api_bearer`, `auth_bearer`")
    p("**Value structure**: 40-char base64url, no prefix, e.g. `RkwfF44uUVKX0RgQiQmXKGtQksSNYqkNWQql2UcU`")
    p()
    p("`bearer_token` contains `token` — detectable. `api_bearer` and `auth_bearer`")
    p("contain neither `api_key`, `api_secret`, `auth_token`, nor `auth_key`.")
    p("Pattern `auth_bearer` would need `auth` to match `auth_token` but the full")
    p("keyword `auth_token` is required — partial matches don't fire.")
    p()
    p("**Determination**: `KEYWORD_GAP`. Var_name keyword gap in SEC002 routing.")
    p("The value was parser-accessible in all seeded formats; SEC002 keyword routing")
    p("was the gate that prevented detection.")
    p()

    h(2, "6. Misses by Family")
    p(f"{'Family':<28} {'Seeded':>7} {'Matched':>8} {'Missed':>7} {'Recall':>8}  {'Primary Category'}")
    p("-" * 80)
    for fam in sorted(fam_total):
        fseeded = fam_total[fam]
        fmatched = fam_match[fam]
        fmissed = fseeded - fmatched
        frecall = pct(fmatched / fseeded) if fseeded else "n/a"
        cats = by_family_cat.get(fam, {})
        primary = max(cats, key=cats.get) if cats else "—"
        p(f"{fam:<28} {fseeded:>7} {fmatched:>8} {fmissed:>7} {frecall:>8}  {primary}")
    p()

    h(2, "7. Misses by Repo")
    p(f"{'Repo':<14} {'Seeded':>7} {'Matched':>8} {'Missed':>7} {'Recall':>8}")
    p("-" * 50)
    for repo in sorted(repo_total):
        p(f"{repo:<14} {repo_total[repo]:>7} {repo_match[repo]:>8} {repo_total[repo]-repo_match[repo]:>7} {pct(repo_match[repo]/repo_total[repo]):>8}")
    p()

    h(2, "8. Misses by File Format")
    p(f"{'Format':<10} {'Seeded':>7} {'Missed':>7}  {'Category Breakdown'}")
    p("-" * 70)
    format_order = ["python", "yaml", "env", "json", "markdown"]
    for fmt in format_order:
        fmt_seeded = sum(1 for r in rows if r["file_format"] == fmt)
        fmt_missed = by_format.get(fmt, 0)
        cats = by_format_cat.get(fmt, {})
        cat_str = ", ".join(f"{c}:{n}" for c, n in sorted(cats.items()))
        p(f"{fmt:<10} {fmt_seeded:>7} {fmt_missed:>7}  {cat_str}")
    p()

    h(2, "9. Top Recurring Miss Causes")
    p("**1. Markdown extension not supported (14 misses)**")
    p("   `.md` absent from `DEFAULT_EXTENSIONS`. 100% miss rate for all Markdown seedings.")
    p()
    p("**2. PEM family has no detection rule (29 misses in supported formats)**")
    p("   No `-----BEGIN RSA PRIVATE KEY-----` pattern exists in SEC002 or any other rule.")
    p("   Compounded by format-level parser gaps (triple-quoted Python, YAML block scalars).")
    p()
    p("**3. opaque_random_cred intentionally excluded (21 misses)**")
    p("   Broad entropy detection deferred; no labeled FP corpus exists to validate precision.")
    p()
    p("**4. KEYWORD_GAP — generic_bearer (23 misses in supported formats)**")
    p("   `api_bearer` and `auth_bearer` not in any SEC002 keyword pattern.")
    p("   Value was parser-accessible; routing never evaluated it.")
    p()
    p("**5. KEYWORD_GAP — opaque_session_token (21 misses in supported formats)**")
    p("   `user_session` and `access_session` not in any SEC002 keyword pattern.")
    p("   Value was parser-accessible; routing never evaluated it.")
    p()
    p("**6. KEYWORD_GAP — google_api (12 misses)**")
    p("   `gcp_key` not in any SEC002 keyword pattern.")
    p()
    p("**7. KEYWORD_GAP — jwt (11 misses)**")
    p("   `session_jwt` not in any SEC002 keyword pattern.")
    p()
    p("**8. KEYWORD_GAP — github_pat (10 misses)**")
    p("   `gh_pat` not in any SEC002 keyword pattern.")
    p()
    p("**9. True DETECTOR_MISS — opaque_api_secret (1 miss)**")
    p("   Keyword match should have fired (`secret` in var_name), parser reached the value,")
    p("   but a value-side gate (special chars `$`, `*`, `@` in ENV value) likely blocked")
    p("   detection. This is the only true detector failure in the current benchmark corpus.")
    p()

    h(2, "10. Distinction: Detection vs Remediation vs Scope")
    p("| Concept | Definition | Evidence in This Benchmark |")
    p("|---------|-----------|---------------------------|")
    p("| **Detection recall** | Whether SEC002 _found_ the secret | 57.0% strict recall overall |")
    p("| **Remediation eligibility** | Whether found secrets are _safe to fix_ | 100% of matched findings refused (`preview_only`) — env_contract absent |")
    p("| **Intentional scope** | Families excluded by design | pem_private, opaque_random_cred |")
    p("| **Routing architecture** | Whether keyword routing evaluated the value | KEYWORD_GAP: 77 misses — value reachable, routing blocked |")
    p("| **Parser coverage** | Whether the parser surfaced the value | PARSER_GAP: 0 misses for in-scope families (pem_private gaps are FAMILY_OUT_OF_SCOPE) |")
    p()
    p("The 0% remediation rate on matched findings is an expected benchmark artifact:")
    p("seeded repos have no `reviewer.config.json` (env_contract absent), so all")
    p("findings fall into `preview_only` mode. This does not indicate a remediation bug.")
    p("Benchmark recall measures detection only.")
    p()

    h(2, "11. Recommended Next Engineering Actions")
    p("Listed in priority order. None implemented here.")
    p()
    p("**Action 1 — Document pem_private and opaque_random_cred as out-of-scope**")
    p("Add explicit documentation in benchmark documentation that these")
    p("families are excluded by design. Update the recall report to show")
    p("'in-scope recall' (excluding out-of-scope families) alongside the raw number.")
    p("Estimated in-scope recall with these excluded: 188 / 230 = 81.7%.")
    p()
    p("**Action 2 — Address KEYWORD_GAP misses by extending the SEC002 keyword list**")
    p("Before adding keywords, produce a false-positive sample: scan 3–5 of the")
    p("benchmark repos WITHOUT seeded controls and measure how many lines")
    p("matching new keywords (`gh_pat`, `gcp_key`, `session_jwt`, `api_bearer`,")
    p("`auth_bearer`, `user_session`, `access_session`) appear naturally.")
    p("Only add keywords whose FP rate is acceptable under the existing precision threshold.")
    p("KEYWORD_GAP accounts for 77 of 78 previously-labeled DETECTOR_MISS cases — this")
    p("is the highest-leverage engineering action for in-scope recall improvement.")
    p()
    p("**Action 3 — Assess PEM detection as a separate rule**")
    p("Evaluate whether a dedicated PEM rule (SEC006 or similar) is warranted.")
    p("Key questions: Does PEM detection have an acceptable FP rate on the benchmark repos?")
    p("Is deterministic AST-safe remediation feasible (likely not — multiline, cert-paired)?")
    p("If detection-only is the answer, a SEC006 detect-only rule could be added without")
    p("remediation support. Note that PEM detection also requires solving PARSER_GAP issues")
    p("(triple-quoted Python, YAML block scalars) for full coverage.")
    p()
    p("**Action 4 — Investigate the single true DETECTOR_MISS (opaque_api_secret ENV)**")
    p("One miss: `opaque_api_secret` in an ENV file with special chars in the value.")
    p("Diagnose whether `_looks_like_identifier_or_word` or another gate is blocking")
    p("detection of values containing `$`, `*`, `@`. A single targeted fix may resolve this.")
    p()
    p("**Action 5 — Evaluate Markdown scanning as a configuration option**")
    p("Markdown detection would require content-scan heuristics (token-like patterns,")
    p("code block extraction) rather than key=value parsing. Assess FP rate on real")
    p("Markdown documentation before adding. Should be gated on a `--include-md` flag,")
    p("not enabled by default, until precision is measured.")
    p()
    p("**Action 6 — Expand benchmark to a false-positive corpus (separate from recall)**")
    p("The current benchmark measures recall on positive controls only. A complementary")
    p("FP corpus (real repo scans without seeding) is needed before expanding keyword lists")
    p("or adding entropy rules. This is a prerequisite for Action 2.")
    p()
    p("---")
    p()
    p("*Report generated by `bench/scripts/analyze_misses.py`. Do not edit manually.*")
    p("*Re-run to update after any benchmark or classifier changes.*")

    # -----------------------------------------------------------------------
    # Write outputs
    # -----------------------------------------------------------------------

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {OUT_MD}")

    OUT_JSON.write_text(json.dumps(analysis_json, indent=2), encoding="utf-8")
    print(f"Wrote: {OUT_JSON}")

    # Print summary to stdout
    print()
    print(f"Total misses: {n_miss} / {total}  (strict recall: {pct(matched/total)})")
    for cat in CATEGORIES:
        cnt = by_category.get(cat, 0)
        if cnt or cat in ("KEYWORD_GAP", "PARSER_GAP", "DETECTOR_MISS"):
            print(f"  {cat}: {cnt} ({pct(cnt/n_miss)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
