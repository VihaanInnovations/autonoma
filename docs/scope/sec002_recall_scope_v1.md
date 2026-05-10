# SEC002 Recall Benchmark Scope — v1

<!--
Status: draft  = work in progress, placeholder enforcement disabled
Status: frozen = published artifact, placeholder enforcement enabled
-->

Status: frozen

**Benchmark ID:** SEC002-recall-v1
**Governance Version:** 1.1
**Detector Commit SHA:** 3d0620ac12082489f09548a3c2334877371334bd
**Scope Registration Date:** 2026-05-10
**Status:** Active

## Reproducibility Metadata

**Python implementation:** CPython
**Python version:** Python 3.11.0

Fill all placeholder fields above before freezing.  Python version is required
because it affects RNG behaviour and string-handling edge cases.

---

## Rule Scope

**Rule covered:** SEC002 — hardcoded API keys and tokens.

SEC001, SEC003, SEC004, SEC005 are out of scope for this benchmark run.

---

## Repo Scope

Ten real-world Python repositories cloned from public GitHub at pinned SHAs:

| Repo | Commit SHA |
|------|------------|
| flask | 7374c85ddefc3f4b177a698ab9f0cbb6a5c0b392 |
| httpx | b5addb64f0161ff6bfe94c124ef76f6a1fba5254 |
| requests | 04d750509b90da728e53aee8d7516426e5a1a293 |


Seeded copies are local-only. Public remotes are removed before seeding.

---

## Syntactic Context Scope

Included:
- Simple string literal assignments (`key = "value"`)
- Dict literals (`{"key": "value"}`)
- Function call keyword arguments (`client(api_key="value")`)
- Environment variable look-ups where the default is hardcoded

Excluded (intentional):
- f-strings (remediation-unsafe; detection possible but excluded from auto-fix scope)
- String concatenations
- Computed or dynamic values
- Values inside comments or docstrings (not executable assignments)

---

## File Extension Scope

Included:
- `.py` (Python source)
- `.cfg`, `.ini`, `.toml`, `.yaml`, `.yml`, `.env`, `.json` (config files)

Excluded:
- `.md`, `.rst`, `.txt` (documentation, not executable)
- Binary files
- Files in `.git/`

---

## Exclusion Scope

The following contexts are intentionally excluded from the strict recall
denominator:

- Seeded controls placed in excluded file extensions (by design)
- Seeded controls placed inside comments (not in executable assignments)

No post-execution exclusions are applied. All seeded controls remain in the
denominator regardless of file extension, parser coverage, or scope
interpretation.

---

## Synthetic Control Parameters

- Generator script: `bench/positive_controls/generator.py`
- Seeder script: `bench/positive_controls/seeder.py`
- Generator seed: 42
- Per-family count: 3
- Seeder RNG seeds:
  - Flask: 7
  - HTTPX: 8
  - Requests: 9
- Total seeded controls: 99
- Families:
  - stripe
  - github_pat
  - aws_pair
  - google_api
  - slack_bot
  - jwt
  - pem_private
  - generic_bearer
  - opaque_api_secret
  - opaque_random_cred
  - opaque_session_token

---

## Frozen Artifact References

| Artifact | Location |
|----------|----------|
| Seed logs | `bench/positive_controls/generated/*.seed_log.json` |
| Findings JSON | `bench/positive_controls/generated/*.findings.json` |
| Redacted manifest | `bench/positive_controls/generated/controls.redacted.json` |
| Recall report | `bench/reports/recall_report_v1.md` _(generated)_ |
| Diagnostic CSV | `bench/positive_controls/generated/combined.diagnostic.csv` _(generated)_ |

The private manifest (`controls.private.json`) is not committed.

---

## Remediation Boundary

This benchmark measures detection recall only.  Remediation eligibility
(safe-to-fix vs. refused) is recorded in findings output but does not affect
the recall denominator.
