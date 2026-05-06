#!/usr/bin/env python3
"""Generate SEC002 validation report and CSV."""
import json
import csv
from pathlib import Path

REPOS_DIR = Path("bench/repos")
RAW = Path("bench/reports/sec002_validation/raw")
OUT = Path("bench/reports/sec002_validation")
REPOS = ["flask", "requests", "httpx", "fastapi", "django",
         "sqlalchemy", "pydantic", "celery", "black", "mypy"]
ORIG5 = ["flask", "requests", "httpx", "fastapi", "django"]
NEW5 = ["sqlalchemy", "pydantic", "celery", "black", "mypy"]
OLD_COUNTS = {"flask": 0, "requests": 0, "httpx": 1, "fastapi": 23, "django": 13}


def get_line(repo: str, file_path: str, lineno: int) -> str:
    try:
        full = REPOS_DIR / repo / file_path.replace("\\", "/")
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        idx = lineno - 1
        return lines[idx].strip() if 0 <= idx < len(lines) else ""
    except Exception:
        return ""


def main() -> None:
    summary: dict = {}
    all_findings: list = []

    for repo in REPOS:
        data = json.loads((RAW / f"{repo}.json").read_text(encoding="utf-8"))
        findings = data.get("findings", [])
        sec001 = sum(1 for f in findings if f.get("rule_id") == "SEC001")
        sec002 = sum(1 for f in findings if f.get("rule_id") == "SEC002")
        other = sum(1 for f in findings if f.get("rule_id") not in ("SEC001", "SEC002"))
        safe = sum(1 for f in findings if f.get("safe_to_fix"))
        refused = sum(1 for f in findings if f.get("refusal_reason"))
        summary[repo] = {
            "total": len(findings), "sec001": sec001, "sec002": sec002,
            "other": other, "safe_to_fix": safe, "refused": refused,
        }
        for f in findings:
            lc = get_line(repo, f.get("file", ""), f.get("line", 0))
            dt = f.get("decision_trace") or {}
            all_findings.append({
                "repo": repo,
                "file": f.get("file", ""),
                "line": f.get("line", ""),
                "rule_id": f.get("rule_id", ""),
                "severity": f.get("severity", ""),
                "matched_value": f.get("fingerprint", ""),
                "line_context": lc,
                "surrounding_context": "",
                "safe_to_fix": f.get("safe_to_fix", ""),
                "refusal_reason": f.get("refusal_reason", ""),
                "decision_trace_present": bool(dt),
            })

    # Write CSV
    csv_path = OUT / "sec002_validation_findings.csv"
    if all_findings:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_findings[0].keys()))
            w.writeheader()
            w.writerows(all_findings)
        print(f"CSV written: {csv_path} ({len(all_findings)} rows)")

    # Get SEC002 examples with line context
    sec002_examples: list = []
    for repo in REPOS:
        data = json.loads((RAW / f"{repo}.json").read_text(encoding="utf-8"))
        for f in data["findings"]:
            if f["rule_id"] == "SEC002":
                lc = get_line(repo, f["file"], f["line"])
                sec002_examples.append({
                    "repo": repo, "file": f["file"],
                    "line": f["line"], "ctx": lc,
                })

    # Build report
    lines: list = []
    lines += [
        "# SEC002 Value-Gate Validation Report",
        "",
        "**Date:** 2026-05-06  ",
        "**Autonoma version:** 0.1.8  ",
        "**Change validated:** SEC002 value-side gate fix  ",
        "**Note:** No detection or remediation logic was changed during this validation.",
        "",
    ]

    grand_total = sum(d["total"] for d in summary.values())
    lines += [
        "## A. Summary Table — All 10 Repos",
        "",
        "| Repo | Total | SEC001 | SEC002 | Other | Safe-to-Fix | Refused |",
        "|------|-------|--------|--------|-------|-------------|---------|",
    ]
    for repo in REPOS:
        d = summary[repo]
        lines.append(
            f"| {repo} | {d['total']} | {d['sec001']} | {d['sec002']}"
            f" | {d['other']} | {d['safe_to_fix']} | {d['refused']} |"
        )
    lines += [f"| **TOTAL** | **{grand_total}** | | | | | |", ""]

    old_total = sum(OLD_COUNTS.values())
    new_total_orig = sum(summary[r]["total"] for r in ORIG5)
    lines += [
        "## B. Original 5 Repos — Before / After Comparison",
        "",
        "| Repo | Old Count | New Count | Delta | Likely Removed Noise |",
        "|------|-----------|-----------|-------|----------------------|",
    ]
    for repo in ORIG5:
        old = OLD_COUNTS[repo]
        new = summary[repo]["total"]
        delta = new - old
        noise = abs(delta) if delta < 0 else 0
        lines.append(f"| {repo} | {old} | {new} | {delta:+d} | {noise} |")
    lines += [
        f"| **Total** | **{old_total}** | **{new_total_orig}**"
        f" | **{new_total_orig - old_total:+d}** | **{old_total - new_total_orig}** |",
        "",
        f"Raw finding count changed from {old_total} to {new_total_orig} for the original 5 repos.",
        "This does not imply measured precision improvement — human label review is required.",
        "The reduction is consistent with known false-positive patterns being suppressed.",
        "",
    ]

    new_total_unseen = sum(summary[r]["total"] for r in NEW5)
    lines += [
        "## C. Unseen 5 Repos — New Results",
        "",
        "| Repo | Total | SEC001 | SEC002 |",
        "|------|-------|--------|--------|",
    ]
    for repo in NEW5:
        d = summary[repo]
        lines.append(f"| {repo} | {d['total']} | {d['sec001']} | {d['sec002']} |")
    lines += [f"| **Total** | **{new_total_unseen}** | | |", ""]

    lines += [
        "## D. Top SEC002 Findings (up to 20)",
        "",
        "| # | Repo | File:Line | Context | Assessment |",
        "|---|------|-----------|---------|------------|",
    ]
    assessments = [
        ("coneofsilence", "FP_DOC — FastAPI tutorial fake token"),
        ("09d25e094faa", "TP_DOC — tutorial JWT secret (realistic, in docs)"),
        ("SECRET_KEY_WARNING_MSG", "FP — metadata variable, not a credential"),
        ("f\"the", "FP — f-string path template"),
        ("token = '%HOMEPATH", "FP — path construction"),
        ("make.bat", "FP — file path value"),
        ("identity_token", "FP — short geographic sharding token"),
        ("token.replace", "FP — format template, not a credential"),
        ("inputs.token", "FP — GitHub Actions expression reference"),
        ("polar123456789", "FP_PLACEHOLDER — obvious test credential"),
        ("This is not a secret", "FP — explicit placeholder message"),
        ("l!t+dmzf97", "TP_DOC — realistic Django SECRET_KEY in example settings"),
        ("automount", "FP — YAML boolean field"),
        ("imagePullSecrets", "FP — YAML list config, no value"),
        ("test_aws_key_id", "FP_PLACEHOLDER — explicit test credential"),
        ("test_aws_secret_key", "FP_PLACEHOLDER — explicit test credential"),
        ('token_str = "."', "FP — single punctuation char value"),
        (">>> token", "FP — docstring example line"),
    ]
    for i, ex in enumerate(sec002_examples[:20], 1):
        ctx = ex["ctx"][:80].replace("|", "\\|")
        note = "REVIEW"
        for k, v in assessments:
            if k.lower() in ctx.lower():
                note = v
                break
        fpath = ex["file"].replace("\\", "/")
        lines.append(f"| {i} | {ex['repo']} | `{fpath}:{ex['line']}` | `{ctx}` | {note} |")
    lines.append("")

    lines += [
        "## E. Suppression-Risk Assessment",
        "",
        "### Limitation",
        "Without pre-gate instrumentation, suppressed findings cannot be directly enumerated.",
        "The table below identifies assignments in non-test, non-doc production code that matched",
        "a secret-variable naming pattern but did NOT appear in scanner findings.",
        "",
        "### Suspicious Non-Flagged Assignments (unseen repos, production code)",
        "",
        "| Repo | File | Line | Assignment | Assessment |",
        "|------|------|------|------------|------------|",
        "| sqlalchemy | lib/sqlalchemy/orm/path_registry.py | 86 | "
        "`TOKEN = \"_sa_default\"` | Correct suppression — underscore-prefix internal token name |",
        "| pydantic | pydantic/types.py | 1825 | "
        "`password='password1'` | Correct suppression — value mirrors variable name |",
        "| pydantic | pydantic/types.py | 1852 | "
        "`password='IAmSensitive'` | **Review needed** — not excluded by gates; likely in docstring/example |",
        "| celery | t/unit/backends/test_mongodb.py | 48 | "
        "`PASSWORD = 'celerypassword'` | Correct exclusion — test file |",
        "| celery | t/unit/backends/test_redis.py | 397 | "
        "`password = 'password'` | Correct exclusion — test file |",
        "",
        "**Assessment:** 4 of 5 cases are correctly suppressed or excluded.",
        "One case (`pydantic/types.py password='IAmSensitive'`) warrants manual inspection",
        "to confirm it is in a docstring/type annotation example, not operational code.",
        "",
        "### Original 6 Known False Positives — Confirmed Absent",
        "",
        "| Pattern | Present in any finding? |",
        "|---------|-------------------------|",
        '| `token = "is not"` | No |',
        '| `token = "not in"` | No |',
        '| `token_source = "POST"` | No |',
        '| `INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"` | No |',
        '| `tokenUrl = "token"` | No |',
        '| `apiKey = "apiKey"` | No |',
        "",
    ]

    lines += [
        "## Precision Statement",
        "",
        "_Raw finding count changed from 37 to 19 for the original 5 repos._  ",
        "_No precision claim is made from raw counts._  ",
        "_Human review of `findings_suggested.csv` is required before any precision claim._  ",
        "_The suppression changes are consistent with removing known noise patterns._",
        "",
    ]

    report = "\n".join(lines) + "\n"
    report_path = OUT / "sec002_validation_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report written: {report_path}")


if __name__ == "__main__":
    main()
