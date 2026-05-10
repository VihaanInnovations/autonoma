# Precision Annotation Guidelines

**Annotation Guidelines Version:** 0.2
**Effective Date:** 2026-05-09
**Governance Version:** 1.1
**Maintainer:** Vithushan / Vihaan Innovations

This document operates under Benchmark Governance v1.1 and is binding for any
precision labeling pass conducted under that governance version. The
guidelines version in effect for a labeling pass must be recorded in the
pass's scope registration per Governance v1.1 Section 3.1.

---

## Purpose

These guidelines define how findings are labeled during precision evaluation
of SEC002.

The goal is to measure SEC002's false-positive behavior on real-world
findings. Labels are used for evaluation only; they do not directly change
detector behavior.

Operational usefulness and remediation appropriateness are out of scope for
this version of the guidelines and will be addressed in a separate
remediation-evaluation document if needed.

---

## Label Categories

Three labels exist. Use exactly one per row.

### TRUE_POSITIVE

A finding is labeled `TRUE_POSITIVE` if it meets at least one of the
following criteria. Record which criterion in the `category` field.

#### Criterion 1 — Known credential format match

The value matches a documented credential prefix or structure:

- real provider prefixes (`sk_live_`, `sk_test_`, `whsec_`, `ghp_`, `gho_`,
  `github_pat_`, `AKIA`, `ASIA`, `AIza`, `xoxb-`, `xoxp-`),
- three-segment HS256/RS256 JWTs where the first segment decodes to valid
  JSON header,
- PEM envelopes (`-----BEGIN ... PRIVATE KEY-----`),
- documented bearer-token formats from major providers.

Example:

```
STRIPE_SECRET = "sk_live_51ABCDEF..."
```

#### Criterion 2 — High-entropy credential-shaped value

All of the following must hold:

- value is ≥16 characters,
- value contains mixed character classes (letters + digits, or letters +
  digits + symbols),
- Shannon entropy ≥3.5 bits/char,
- value is assigned to a variable, key, header, or environment variable
  whose name suggests a credential (`api_key`, `token`, `secret`,
  `password`, `authorization`, or close variants).

Example:

```
authorization = "Bearer eyJhbGciOi..."
```

#### Criterion 3 — Synthetic positive control

A seeded benchmark control intentionally inserted for recall evaluation.

Required tag in `review_notes`: `synthetic: true`.

Example (inert payload, real prefix):

```
# Synthetic positive control
TEST_GITHUB_PAT = "ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE0000"
```

**Synthetic controls are excluded from precision calculation** (see Precision
Calculation section below). They are labeled `TRUE_POSITIVE` for completeness
of the labeled corpus but contribute to recall, not precision.

---

### FALSE_POSITIVE

A finding is labeled `FALSE_POSITIVE` if it does not meet any TRUE_POSITIVE
criterion. Record exactly one category code per row in the `category` field.

#### Category A — Concept Labels

The value names the concept itself rather than containing a credential.

Examples:

```
token = "token"
api_key = "apiKey"
secret = "secret"
```

Counter-example (would be TRUE_POSITIVE):

```
api_key = "ghp_abcd1234..."
```

#### Category B — Protocol / HTTP Constants

Protocol-level constants or auth scheme names without credential material.

Examples:

```
method = "POST"
scheme = "Bearer"
auth_type = "Basic"
content_type = "application/json"
```

Counter-example (would be TRUE_POSITIVE):

```
authorization = "Bearer eyJhbGciOi..."
```

#### Category C — Natural-Language Fragments

Ordinary language accidentally matching heuristic patterns.

Examples:

```
token = "is not"
message = "not available"
note = "access denied"
```

Counter-example (would be TRUE_POSITIVE):

```
session_token = "a92f4c81..."
```

#### Category D — Schema Labels / Field Names

Identifiers describing database or schema structure rather than storing
secrets.

Examples:

```
column = "_password_reset_token"
field = "api_key"
attribute = "secret_name"
```

Counter-example (would be TRUE_POSITIVE):

```
api_key = "AIza..."
```

#### Category E — Framework Constants / Enum Values

Static framework values or enum-like constants without credential semantics.

Examples:

```
AUTH_MODE = "TOKEN"
STATE = "AUTHORIZED"
ROLE = "ADMIN"
```

Counter-example (would be TRUE_POSITIVE):

```
ACCESS_TOKEN = "ghp_abcd..."
```

#### Category F — Mirror Values

The value is a substring, exact match, or trivial case/punctuation
transformation of the variable name or key.

Required tag in `review_notes`: `mirror: true`.

Examples:

```
password = "password"
api_key = "API_KEY"
token = "your-token-here"
```

Counter-example (would be TRUE_POSITIVE):

```
api_key = "ghp_abcd1234..."
```

#### Category G — Public Test Credentials

Public-by-design credentials that providers explicitly publish for testing
purposes (Stripe published test keys, AWS canary keys, GitHub example tokens
from public docs).

Required tag in `review_notes`: `public_test_credential: true`.

Examples:

```
STRIPE_TEST_KEY = "sk_test_..."  # provider-published test key
AWS_CANARY = "AKIAIOSFODNN7EXAMPLE"  # AWS documented example
```

Counter-example (would be TRUE_POSITIVE):

```
AWS_SECRET_ACCESS_KEY = "wJalrX..."
```

#### Category H — Synthetic Test Artifacts

Realistic-looking but non-operational credentials placed in test fixtures,
tutorials, sample code, or documentation for instructional purposes. Distinct
from Category G in that the credential is not provider-published; it is a
project-local fabrication for local tests or examples.

Required tag in `review_notes`: `test_artifact: true`.

Examples (in `tests/fixtures/`, `examples/`, `docs/`):

```
TEST_TOKEN = "ghp_abcd1234567890abcdef..."  # in a fixture file
DUMMY_KEY = "AIzaXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # in a tutorial
```

Counter-example (would be TRUE_POSITIVE — even in tests, real credentials
are real credentials):

```
# Override condition met: nearby comment "do not commit" or "live key"
TEST_TOKEN = "ghp_realRealRealRealRealRealRealRealRR"  # do not commit
```

See "Borderline cases" below for the rules on when to override Category H
to TRUE_POSITIVE.

#### Category R — Redaction Markers

Explicitly redacted or masked values.

Examples:

```
password = "******"
token = "[REDACTED]"
secret = "xxxx"
api_key = "<REDACTED>"
```

Counter-example (would be TRUE_POSITIVE):

```
token = "eyJhbGciOi..."
```

---

### UNCERTAIN

Use `UNCERTAIN` only when available context within the allowed context
window is insufficient for confident classification.

`UNCERTAIN` is **not an escape hatch**. If TRUE_POSITIVE or FALSE_POSITIVE
criteria clearly apply, you must use them. The `uncertain_rate` is reported
alongside precision; high uncertain rates indicate either guideline gaps or
genuine corpus difficulty, not reviewer hedging.

Examples:

```
session = "9f83c2ab41..."   # no credential-shaped variable, no context
cache_key = "3fa85f64c2..."  # ambiguous use, no nearby auth signals
```

---

## Borderline Cases

Borderline cases have a default label and explicit override conditions. The
override conditions must be **observable within the allowed context window**
(see Context Window Rules). Override conditions that require external
research or interpretation are not valid override conditions.

### Random-looking identifiers

```
cache_key = "9f83c2ab41..."
```

**Default:** FALSE_POSITIVE (Category C if natural language, otherwise
default to UNCERTAIN if entropy is high but no other signal exists).

**Reason:**

- no credential-shaped variable name,
- no provider format match,
- no surrounding auth/security context.

**Override conditions to TRUE_POSITIVE (must be visible in the context window):**

- nearby variable named `*_token`, `*_key`, `*_secret`, `*_password`,
  `authorization`, or close variant within ±10 lines,
- nearby use as a Bearer header or HTTP `Authorization` value,
- inline or preceding-line comment containing `auth`, `secret`,
  `credential`, `token`, `key`,
- nearby `os.environ` / `getenv` / `.env` reference passing the value to
  an authentication-related destination.

### Test fixtures with realistic-looking credentials

```
TEST_TOKEN = "ghp_abcd1234567890abcdef..."
```

**Default:** FALSE_POSITIVE Category H (synthetic test artifact).

**Override conditions to TRUE_POSITIVE (must be visible in the context window):**

- nearby comment containing `prod`, `production`, `live`, `do not commit`,
  `real`, or `real key`,
- variable name or constant within ±10 lines containing `production`,
  `live`, or `prod`,
- URL within ±10 lines pointing to a production-shaped domain (not
  `localhost`, `127.0.0.1`, `example.com`, `*.test`, `*.local`,
  `*.invalid`, or other RFC-2606 reserved names),
- paired infrastructure identifier (account ID, project ID, organization
  ID) that is not a documented public example,
- value matches a known leaked-credential database format, indicated by an
  inline comment.

### Placeholder vs operational secret

```
API_KEY = "your-api-key-here"
```

**Default:** FALSE_POSITIVE Category F (mirror value) if the value mirrors
the variable name; otherwise Category A (concept label) for values like
`"changeme"`, `"example"`, `"replace-me"`.

**Override conditions to TRUE_POSITIVE (must be visible in the context window):**

- file path matches `**/config/production*`, `**/config/live*`,
  `**/deploy/prod*`, or similar production-shaped path,
- value is referenced (not just defined) by code that performs an
  authentication operation within ±10 lines,
- nearby comment indicating the value was substituted in deployment.

---

## Context Window Rules

When labeling a finding, the reviewer may use only:

- the value itself,
- the variable name, key, or assignment target,
- the file path and extension,
- ±10 lines of surrounding source code,
- any inline comment on the same line or the line immediately above the
  finding.

The reviewer must not consult:

- commit messages or git history,
- the repository README, documentation outside the ±10-line window, or
  external documentation,
- runtime behavior or test execution,
- web search, credential validation services, or any external lookup,
- the detector's confidence score, rule ID, or suppression status,
- the labeled status of any other row,
- the seed log or controls manifest from the recall benchmark.

External research to resolve `UNCERTAIN` cases is prohibited. If the
context window is insufficient, the row stays `UNCERTAIN`.

---

## Required Fields Per Review Row

Each labeled finding must include the following fields:

- **`human_label`** — one of `TRUE_POSITIVE`, `FALSE_POSITIVE`, `UNCERTAIN`.
- **`category`** —
  - For `TRUE_POSITIVE`: criterion `1`, `2`, or `3`.
  - For `FALSE_POSITIVE`: category `A`, `B`, `C`, `D`, `E`, `F`, `G`, `H`,
    or `R`.
  - For `UNCERTAIN`: leave blank or use `null`.
- **`review_notes`** — free text justification, plus structured tags where
  applicable: `synthetic: true`, `mirror: true`, `public_test_credential:
  true`, `test_artifact: true`.
- **`reviewer`** — reviewer identifier.
- **`review_timestamp`** — ISO 8601 timestamp.
- **`labeling_pass_id`** — pass identifier per Governance v1.1 Section 4.3
  (e.g., `SEC002-precision-2026-01`).

A row missing any required field is not a valid labeled row and must not be
included in precision calculation.

---

## Relationship to Recall Benchmark

The recall benchmark measures whether seeded synthetic controls are detected
by the scanner. The precision benchmark measures whether emitted findings
from real-world repositories are operationally meaningful and appropriately
classified.

The two benchmarks intentionally use different denominators and must not be
compared directly. Synthetic controls may appear in both workflows, but
precision metrics are not derived from recall-control counts (see Precision
Calculation below).

---

## Precision Calculation

```
precision      = TP / (TP + FP)
uncertain_rate = UNCERTAIN / (TP + FP + UNCERTAIN)
```

**Precision is calculated over real-world findings only.** Synthetic positive
controls (rows tagged `synthetic: true` in `review_notes`) are **excluded
from both numerator and denominator** of the precision calculation. They
contribute to recall measurement, not precision. Including them would
inflate precision because the benchmark itself seeded those credentials;
this exclusion is mandatory under Governance v1.1 Section 2.2.

`UNCERTAIN` rows are excluded from precision and reported separately as
`uncertain_rate`. A precision claim accompanied by an undisclosed
`uncertain_rate` is not a publishable claim.

Wilson 95% score interval (without continuity correction) is reported with
every precision number.

Every published precision result must include:

- sample size (after synthetic-control exclusion),
- Wilson 95% confidence interval,
- `uncertain_rate`,
- detector commit SHA,
- governance version,
- annotation guidelines version,
- labeling pass identifier and dates.

Results with `n < 30` (after synthetic-control exclusion) must be marked
preliminary.

---

## Sample Size Guidance

For a precision claim with Wilson 95% half-width:

- ±10 percentage points: roughly `n ≥ 35` at 90% precision,
- ±5 percentage points: roughly `n ≥ 140` at 90% precision,
- ±3 percentage points: roughly `n ≥ 380` at 90% precision.

Half-width tightens for precision values further from 50% and widens for
values nearer 50%. Choose target sample size based on the precision claim
you intend to make, not on labeling effort budgeted.

---

## Labeling Pass Procedure

1. Confirm scope registration is committed and the pass identifier is
   recorded per Governance v1.1 Section 4.3.
2. Run the precision sampling script to generate a deterministic review
   sample. Record the sampling RNG seed.
3. Open the generated CSV/JSONL review manifest.
4. For each row, review using only the allowed context window. Assign:
   - `human_label`,
   - `category`,
   - `review_notes` (with structured tags where applicable),
   - `reviewer`,
   - `review_timestamp`,
   - `labeling_pass_id`.
5. Save labeled output. Do not edit previously assigned labels in the same
   pass.
6. After the pass closes (no new labels added), wait at least 7 days before
   the blind re-review.
7. Generate a 20% blind re-review subset from the labeled rows using a
   separate recorded RNG seed. Re-label without seeing first-pass labels.
8. Compute Cohen's kappa between first-pass and re-review labels.
9. Resolve disagreements with a third pass having both prior labels visible.
   Record the resolution in `review_notes` of the resolved row.
10. Run the precision report script. The report must include all fields
    listed in Governance v1.1 Section 8.3.

A reviewer should be able to reproduce the same review sample using the
recorded sampling RNG seed, repository commit SHAs, and detector
configuration.

---

## Single-Reviewer Protocol

Until independent reviewers exist, the precision benchmark operates under
single-reviewer governance:

- 20% of labeled rows must be blind re-reviewed by the same reviewer after
  a delay of at least 7 days.
- Intra-rater Cohen's kappa is reported alongside every published precision
  number.
- Disagreements between first pass and re-review are resolved by a third
  pass with both prior labels visible. Resolved labels are recorded with
  resolution notes; original first-pass labels are archived.

**Intra-rater Cohen's kappa measures labeling consistency, not freedom from
systematic bias.** A reviewer's biases re-review their own labels the same
way the second time. Independent inter-rater agreement is required to
characterize bias. This disclaimer must accompany every published kappa
value.

When the project gains a second independent reviewer, intra-rater kappa is
replaced by inter-rater kappa, and this section is updated.

The reviewer's awareness of repository reputation, framework popularity, and
prior detector output may influence classification decisions. This risk is
partially reduced by the fixed labeling rules, the bounded context window,
and the delayed blind re-review, but is not eliminated. Independent review
is the only complete mitigation.

---

## Anti-Overfitting Rules

A new suppression rule, or a change to an existing suppression rule that
removes findings, requires **all** of the following (per Governance v1.1
Section 7.4):

1. The false-positive pattern appears across at least two distinct
   repositories, OR is a deterministic category error reproducible from a
   minimal synthetic example.
2. The suppression is expressible as deterministic, auditable, reproducible
   logic (regex, AST pattern, or named-entity match) — not a learned
   threshold tuned on the benchmark itself.
3. **Post-rule strict recall on positive controls remains within the lower
   Wilson 95% bound of the previous frozen strict-recall baseline.**

The strict-recall baseline (not any post-classification scoped recall or
other secondary metric) is the binding floor. Improvement in precision
benchmark numbers alone is not sufficient justification for suppression-rule
additions.

A single isolated false positive never justifies a suppression rule.

---

## Frozen Rules During Labeling

A precision labeling pass is itself a freeze unit. During an active pass:

- detector logic must not change,
- suppression rules must not change,
- benchmark scope must not change,
- annotation guidelines must not be edited,
- previously labeled rows must not be silently relabeled,
- new findings must not be added to the labeled set.

Labels are assigned without viewing detector confidence, rule ID, or
suppression metadata.

If the annotation guidelines must be revised mid-pass, the pass is
invalidated per Governance v1.1 Section 4.2 and restarted under the revised
guidelines on a freshly sampled corpus. Partial labels from the invalidated
pass are archived but not used to compute precision.

The detector author currently also serves as reviewer until independent
reviewers join the process. This limitation must be disclosed alongside
every published precision metric per Governance v1.1 Section 8.4.

---

## Current Scope Notes

This guidelines version (v0.2) targets:

- SEC002 findings,
- Python repositories,
- deterministic remediation-compatible contexts.

Initial review sets prioritize findings located in:

- tests and fixtures,
- tutorials and examples,
- CI configuration,
- documentation examples,
- source files (production code paths).

Current target sample size: **200–400 manually reviewed findings per
labeling pass** (after synthetic-control exclusion), supporting Wilson 95%
half-width of approximately ±3–4 percentage points at precision values near
90%.

Broader entropy-style secret detection remains outside the current precision
evaluation scope per Governance v1.1 Section 7.5.

---

## Reproducibility Requirements

Every published precision result must reference:

- detector commit SHA,
- scanned repository commit SHAs,
- governance version,
- annotation guidelines version (this document),
- labeled CSV/JSONL outputs (with raw matched values redacted to previews),
- labeling pass identifier,
- labeling pass start and end dates,
- sampling RNG seed,
- blind re-review subset RNG seed,
- reviewer identifier(s),
- intra-rater Cohen's kappa,
- `uncertain_rate`,
- sample size before and after synthetic-control exclusion.

Benchmark history must remain append-only. Silent retroactive relabeling is
prohibited. Resolved disagreements record both prior labels and the
resolution rationale.

---

## Changelog

- **v0.2 — 2026-05-09.** Pinned to Governance v1.1. Added FALSE_POSITIVE
  Category H (synthetic test artifacts). Added explicit synthetic-control
  exclusion in Precision Calculation. Replaced fake-prefix example
  `ght_1234567890abcdef` with real-prefix inert example
  `ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE0000`. Replaced interpretive
  borderline override conditions with observable signals visible within the
  context window. Added Cohen's kappa interpretation disclaimer. Added
  required fields for `labeling_pass_id`. Added sample-size guidance.
- **v0.1.** Initial draft (superseded). Operated without Governance v1.1
  framework; should not be used for any labeling pass under v1.1.
