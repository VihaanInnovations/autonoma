# SEC002 Recall Evaluation Report (Baseline v1)

## Abstract

We evaluate Autonoma's SEC002 detection rule against a deterministic synthetic-control
benchmark of 99 credentials across 11 families, seeded into local clones of Flask,
HTTPX, and Requests. SEC002 achieves **53.5% strict recall (Wilson 95% CI:
43.8% – 63.0%)**. Recall is concentrated on structured provider-shaped credentials
(Stripe, Slack, AWS at 100%); detection of prefix-less high-entropy tokens is at or
near 0%, and PEM private-key detection is 0/9. SEC002 is intentionally scoped to
structured credential detection rather than universal high-entropy scanning, and
broad entropy heuristics are excluded from the rule until their precision impact
can be measured rigorously. The benchmark is fully reproducible from a published
seed without exposing credential values; methodology, per-family and per-format
results, and a reproducibility checklist are reported below.

**This report captures the SEC002 recall baseline prior to additional**
**rule-coverage expansion or entropy-threshold tuning.**

SEC002 is intentionally optimized for structured credential detection under
precision-oriented remediation constraints rather than universal entropy-based
secret discovery.
---

## 1. Motivation

Autonoma is a deterministic local-first secret remediation tool focused on safe,
auditable remediation workflows rather than maximum theoretical secret detection
recall.

The SEC002 rule targets credential-like secrets such as API keys, access tokens,
bearer tokens, and other high-risk authentication artifacts.

This evaluation measures SEC002 recall against a reproducible synthetic-control
benchmark designed to:

- avoid benchmark contamination,
- avoid real credential exposure,
- support deterministic reruns,
- and identify family-specific detection gaps.

This report establishes the initial SEC002 recall baseline before additional
rule-coverage improvements.

---

## 2. Benchmark Philosophy

The benchmark prioritizes:

- reproducibility,
- deterministic control generation,
- contamination avoidance,
- and explicit family-level analysis.

The benchmark intentionally avoids:

- committing realistic provider credentials to public Git repositories,
- heuristic auto-labeling,
- hidden benchmark mutation,
- and undocumented synthetic artifacts.

The benchmark does NOT attempt to maximize recall scores through broad entropy
heuristics or generic pattern expansion. Instead, the goal is to measure
structured credential detection behavior under precision-oriented constraints.
Broad entropy-only detection is excluded from SEC002 unless its precision
impact can be measured against a separate labeled false-positive corpus.

---

## 3. Synthetic Control Generation

Synthetic controls are generated deterministically from:

- a fixed RNG seed,
- credential family templates,
- and seeded format renderers.

### 3.1 Safe alias-prefix synthetic credentials

Synthetic controls use safe alias-prefix variants derived from real provider
credential structures.

Examples:
- `sk_live_` → `stk_live_`
- `ghp_` → `ght_`
- `AKIA` → `AXIA`
- `AIza` → `GIZA`
- `xoxb-` → `xotb-`

This design intentionally avoids:
- GitHub push-protection activation,
- provider abuse-system ingestion,
- public credential-index contamination,
- and accidental publication of detector-triggering live-prefix artifacts.

The benchmark therefore evaluates structural credential detection behavior
under safe alias-prefix substitution rather than exact provider-literal
matching.

The generator produces:

| Family             | Prefix / structure                              | Notes                                              |
| ------------------ | ----------------------------------------------- | -------------------------------------------------- |
| `stripe`           | `stk_live_` + 24 base62 chars                    | Inert payload                                      |
| `github_pat`       | `ght_` + 36 base62 chars                        | Last 6 chars are valid CRC32 of preceding body     |
| `aws_pair`         | `AXIA` + 16 chars (access) + 40 chars (secret)  | Both halves seeded together                        |
| `google_api`       | `GIZA` + 35 base62/`-_` chars                   | Inert payload                                      |
| `slack_bot`        | `xotb-` + numeric-numeric-secret                | Three-segment Slack bot token shape                |
| `jwt`              | Three-segment HS256 JWT                         | Header decodes to valid JSON                       |
| `pem_private`      | `-----BEGIN RSA PRIVATE KEY-----` envelope      | Wrapped base64 body, ~2048-bit equivalent         |
| `generic_bearer`   | 40-char base64url, no prefix                    | Tests prefix-less detection                        |
| `opaque_*`         | High-entropy strings, no provider prefix        | Tests prefix-less detection                        |

All payloads are random bytes from a seeded RNG. None have been issued by any
provider, none will validate against any provider's API, and none are structurally
distinguishable from a freshly issued credential by signature alone.

### 3.2 Contamination avoidance via seeder enforcement, not fake values

Contamination is prevented by the **seeder**, not by weakening the credentials.
Seeded controls are placed only into local clones of target repositories. The
seeder refuses to operate on any clone whose Git remote points to a public host
(github.com, gitlab.com, bitbucket.org, codeberg.org). The benchmark workflow
explicitly removes the public remote before seeding.

This design preserves detector-meaningful credentials while preventing:

- GitHub push protection activation on benchmark workflows,
- public secret-scanning ingestion of synthetic values,
- benchmark contamination of future detector training/tuning,
- and accidental provider abuse-system interaction.

Each file format is exercised: Python, YAML, JSON, env (`.env.local`), and Markdown.

---

## 4. Contamination Avoidance

The benchmark uses local-only seeded repositories.

Seeded repositories are:

- cloned locally,
- detached from remote origins,
- seeded during benchmark execution,
- and never pushed publicly.

Public benchmark artifacts contain:

- generator scripts,
- seeder scripts,
- methodology,
- redacted manifests (control values replaced with regeneration instructions),
- and aggregate benchmark results.

Private manifests containing generated credential values are excluded from Git
via `.gitignore` rules covering `controls_manifest.json`, `*.seed_log.json`, and
`_autonoma_seeded/` directories inside seeded clones.

This design prevents benchmark leakage, provider scanning contamination, and
future detector overfitting against published controls. Reproducibility is
preserved because anyone can regenerate the exact same controls from the
published seed.

---

## 5. Fingerprint Identity Model

Benchmark identity uses deterministic fingerprints rather than raw credential
values.

Each control value is represented as:

```
sha256:<first 24 hex chars of SHA-256(secret_value)>
```

This allows deterministic recall matching, duplicate detection, path mismatch
diagnostics, and benchmark reproducibility, without exposing raw credential
material in logs, CI pipelines, benchmark CSV outputs, or JSON findings.

### 5.1 Why fingerprint matching replaced string matching

An earlier version of the recall matcher compared paths only. Initial evaluation
under the path-only matcher reported **57.6% recall**. Migrating to fingerprint
matching (where a finding counts only if its fingerprint matches the seeded
value's fingerprint) reduced the reported recall to **53.5%** — a correction of
4 percentage points.

The 4-point delta was concentrated almost entirely in the PEM family: PEM
recall dropped from 4/9 to 0/9 once fingerprint matching was applied. The earlier
"hits" were Autonoma findings located in seeded PEM files but matching artifacts
other than the PEM block itself (e.g., embedded base64 lines that triggered
unrelated heuristics).

The fingerprint matcher is the basis for all numbers in this report. The
path-only number is reported here only to document the methodology correction.

---

## 6. Repo Selection

Initial evaluation was performed against locally seeded clones of:

- Flask
- HTTPX
- Requests

These three repositories were selected as a v0.1 baseline to verify the
benchmark infrastructure end-to-end. They are widely used Python projects with
heterogeneous file structures and multiple configuration formats. **Three
repositories is a small sample and produces wide confidence intervals**;
expansion to 5–10 repositories is required before any tightened quantitative
claim about overall SEC002 recall.

All repositories were scanned locally using deterministic seeded controls,
with public remotes removed prior to seeding.

---

## 7. Recall Methodology

Each synthetic control is seeded into a target repository using a deterministic
placement strategy.

The benchmark records:

- expected file path (relative, forward-slash normalized),
- credential family,
- file format,
- and expected fingerprint.

Autonoma findings are matched using normalized forward-slash paths and
deterministic finding fingerprints.

Each seeded control is classified as exactly one of:

- `MATCHED`
- `PATH_MISMATCH`
- `VALUE_NOT_FOUND`

### Definitions

**MATCHED.** Expected fingerprint detected at expected path.

**PATH_MISMATCH.** Expected fingerprint detected elsewhere, but not at the
expected path. This indicates either a path-normalization bug in the detector
output or a path-recording bug in the seeder/matcher; investigation is required
before attributing the finding to either category.

**VALUE_NOT_FOUND.** Expected fingerprint absent from findings output. This is
treated as a true detector miss for the strict-recall metric.

Strict recall is reported as `MATCHED / total`. `PATH_MISMATCH` cases, when
present, are reported separately and not credited to recall.

---

## 8. Wilson Interval Methodology

Recall percentages are reported with 95% Wilson score confidence intervals
without continuity correction.

Wilson intervals were selected because:

- the benchmark sample size is relatively small,
- several credential families contain low observation counts (n=9 per family),
- and normal-approximation intervals perform poorly near 0% or 100%, which
  several families in this evaluation exhibit.

All percentages in this report should be interpreted together with their
confidence intervals. With n=9 per family, even 100% recall yields a Wilson
lower bound of 70.1%, and 0% recall yields a Wilson upper bound of 29.9%. These
intervals tighten substantially as repository coverage expands.

---

## 9. Family-Level Results

Overall strict recall:

- **53 / 99 controls detected**
- **53.5% strict recall**
- **95% Wilson interval: 43.8% – 63.0%**

Per-family breakdown:

| Family                 | Detected | Recall    | Wilson 95% CI       |
| ---------------------- | -------- | --------- | ------------------- |
| `stripe`               | 9 / 9    | 100.0%    | 70.1% – 100.0%      |
| `slack_bot`            | 9 / 9    | 100.0%    | 70.1% – 100.0%      |
| `aws_pair`             | 9 / 9    | 100.0%    | 70.1% – 100.0%      |
| `opaque_api_secret`    | 8 / 9    |  88.9%    | 56.5% –  98.0%      |
| `jwt`                  | 6 / 9    |  66.7%    | 35.4% –  87.9%      |
| `github_pat`           | 5 / 9    |  55.6%    | 26.7% –  81.1%      |
| `google_api`           | 4 / 9    |  44.4%    | 18.9% –  73.3%      |
| `opaque_random_cred`   | 2 / 9    |  22.2%    |  6.3% –  54.7%      |
| `generic_bearer`       | 1 / 9    |  11.1%    |  2.0% –  43.5%      |
| `opaque_session_token` | 0 / 9    |   0.0%    |  0.0% –  29.9%      |
| `pem_private`          | 0 / 9    |   0.0%    |  0.0% –  29.9%      |

The results separate cleanly into three tiers:

**Tier 1 — Structured provider credentials (100% recall).** Stripe, Slack, and
AWS are detected at every seeded location across all formats. SEC002 is correct
on these.

**Tier 2 — Partial recall on prefix-bearing credentials (44% – 89%).** GitHub
PATs, Google API keys, JWTs, and the opaque API secret family are detected
inconsistently despite having recognizable prefixes or structural signals. This
tier is the primary target for rule-coverage improvements; misses are
concentrated in specific file formats rather than spread evenly.

**Tier 3 — Absent or near-zero detection (0% – 22%).** PEM private keys
(0 / 9) and the prefix-less entropy-only families (0.0% to 22.2%) are not
meaningfully covered. PEM is the most distinctive credential pattern in this
benchmark — `-----BEGIN ... PRIVATE KEY-----` envelopes are unambiguous — and
zero detection across nine controls in three repositories indicates that either
no rule exists for PEM blocks in SEC002, or an existing rule is broken. This is 
treated as a high-priority coverage or routing gap pending
root-cause confirmation.

---

## 10. Format-Level Results

Per-format breakdown:

| Format    | Detected | Recall   | Wilson 95% CI       |
| --------- | -------- | -------- | ------------------- |
| `python`  | 26 / 38  |  68.4%   | 52.5% –  80.9%      |
| `env`     | 12 / 23  |  52.2%   | 33.0% –  70.8%      |
| `json`    |  6 / 14  |  42.9%   | 21.4% –  67.4%      |
| `yaml`    |  9 / 21  |  42.9%   | 24.5% –  63.5%      |
| `markdown`|  0 / 3   |   0.0%   |  0.0% –  56.2%      |

Python files produced the highest recall, consistent with a detector developed
primarily against Python source. Markdown produced 0/3 detection; the sample
size is too small for a confident point estimate (Wilson upper bound 56.2%),
but the direction is consistent with reduced parser coverage in non-source
formats. JSON and YAML detection at ~43% indicates a real format-handling gap,
since both formats are common credential-storage targets in production code.

The format gradient suggests that parser coverage, format-specific handling,
and extension routing significantly affect detector performance. Several
Tier 2 family misses reduce to format issues rather than family issues; for
example, three of five Google API key misses occur in `.env` files,
indicating a likely extension-routing or `.env`-specific parsing gap rather
than a `AIza`-prefix detection failure.

---

## 11. Detector Limitations

The evaluation surfaced the following SEC002 limitations:

- **PEM private-key detection produced 0 / 9 recall in this evaluation.**
  This indicates either absent PEM-family rule coverage or a failure in the
  current PEM detection path. Root-cause analysis remains ongoing.
- **Prefix-less high-entropy credentials are not meaningfully detected.**
  `generic_bearer`, `opaque_session_token`, and `opaque_random_cred` recall
  ranges from 0% to 22.2%. This is consistent with SEC002's intentional
  scoping (see Section 2); these families are reported here to quantify the
  scoping cost.
- **Format-specific gaps in JSON, YAML, and `.env` files.** Recall on these
  formats is consistently lower than Python recall, including for credential
  families that succeed in Python (e.g., GitHub PAT misses concentrated in
  `.yaml` and `.md`).
- **Markdown coverage is unverified.** With n=3, no confident claim is
  possible; the 0/3 result motivates expanded markdown sampling in v0.2.

SEC002 should not currently be interpreted as a universal high-entropy
secret detector. This limitation is partially intentional: broad entropy-only 
heuristics were excluded from SEC002 to preserve precision and deterministic 
remediation behavior. Current performance is strongest for structured,
provider-shaped, credential-like artifacts — which is consistent with its
design intent, not in spite of it.

---

## 12. Threats to Validity

The following limitations affect this benchmark:

- **Single-author, single-implementation evaluation.** Control generation,
  seeder, scanned tool, and recall matcher were all authored by the same
  individual. Independent reproduction is required to rule out correlated
  errors across the toolchain. The redacted manifest, published seed, and
  open-source generator/seeder/recall scripts are intended to make such
  reproduction straightforward.
- **Three-repository sample.** Wide confidence intervals on per-family and
  per-format results. Headline 53.5% recall has a ±10-point CI half-width;
  expansion to 5–10 repositories is required before tightening this claim.
- **Synthetic placement.** Controls are seeded by a deterministic placement
  algorithm into a dedicated subdirectory. Real production credential placement
  varies in directory depth, file naming, and surrounding context; a
  detector that performs well on this benchmark may perform differently on
  organic credential exposures.
- **Balanced family distribution.** Each family contributes nine controls,
  regardless of real-world prevalence. Family-weighted recall does not
  reflect production credential mix.
- **Detection-only scope.** This benchmark evaluates whether a finding is
  produced. It does not evaluate remediation correctness. SEC002 in this
  scan reported `safe_to_fix=0` and `refused=23` per scan, reflecting
  Autonoma's deliberate preview-only policy in the absence of an environment
  contract; this is a feature of the policy, not a benchmark failure, but
  remediation correctness is gated separately and not measured here.

---

## 13. Future Work

Future benchmark work:

- expanded repository coverage (target: 10 repos, ~330 controls),
- broader precision evaluation against labeled false-positive corpora,
- inter-rater labeling for the precision benchmark,
- remediation correctness evaluation (separately gated on env-contract policy),
- additional credential families (e.g., Azure, Heroku, npm tokens, database
  connection strings),
- and CI integration benchmarking.

Future detector work:

- PEM-family rule (highest-priority gap, 0/9 baseline),
- `.env` file extension and JSON/YAML parser coverage,
- and expanded structured credential coverage for additional providers.

Broad entropy heuristics remain intentionally excluded from SEC002 unless
their precision impact can be measured rigorously against a separate labeled
false-positive corpus. Improving Tier 3 recall by lowering entropy thresholds
without precision measurement is explicitly out of scope.

---

## 14. Reproducibility Checklist

Every number in this report can be reproduced with the following artifacts:

| Artifact                  | Where it lives                          |
| ------------------------- | --------------------------------------- |
| Generator script          | `bench/positive_controls/generator.py`  |
| Seeder script             | `bench/positive_controls/seeder.py`     |
| Recall matcher            | `bench/scripts/recall_report.py`        |
| Redacted manifest         | `bench/positive_controls/generated/controls_manifest.redacted.json` |
| Generator seed            | Published in this report (see below)    |
| Seeder RNG seed           | Published in this report (see below)    |
| Target repo commit SHAs   | Recorded per scan (see below)           |
| Autonoma version / commit | Recorded per scan (see below)           |

Reproduction steps:

1. `python generator.py --seed <SEED> --per-family <N> --out controls_manifest.json`
2. Clone each target repo, remove its public remote, and run
   `python seeder.py --manifest controls_manifest.json --target-repo <path> --rng-seed <SEED> --seed-log <repo>.seed_log.json`
3. Run `autonoma scan <path> > <repo>.findings.json` for each target.
4. Run `python recall_report.py --seed-log ... --findings ... --diagnostic-out report.csv`

Seeds and SHAs used in this report:

- Generator seed: *42*
- Per-family count: *3*
- Seeder RNG seeds:
  - Flask: 7
  - HTTPX: 8
  - Requests: 9
- Flask commit SHA: *7374c85ddefc3f4b177a698ab9f0cbb6a5c0b392*
- HTTPX commit SHA: *b5addb64f0161ff6bfe94c124ef76f6a1fba5254*
- Requests commit SHA: *04d750509b90da728e53aee8d7516426e5a1a293*
- Autonoma version: *0.1.8*
- Benchmark execution date: 2026-05-07 UTC
- Autonoma policy version: 2026-04-22.1 (per finding metadata)
- Autonoma engine version: 0.1.8 (per finding metadata)

Independent reviewers can regenerate the exact same controls from the
published seed without ever accessing private credential values, and verify
the recall numbers by repeating steps 1–4.
