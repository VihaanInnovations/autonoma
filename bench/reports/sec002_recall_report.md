# SEC002 Recall Evaluation Report (Baseline v1)

> **Revision notice — 2026-05-09.**
> This report has been revised following post-baseline miss-taxonomy analysis
> (see Section 15). All measured recall values and per-family results are
> unchanged. Interpretive updates address:
> (a) `pem_private` — reclassified as FAMILY_OUT_OF_SCOPE; the 0/9 result
> reflects the absence of a registered SEC002 rule, compounded by multiline
> parser limitations, not an unresolved detection gap;
> (b) Markdown format — the 0/3 result is EXTENSION_EXCLUDED (`.md` absent
> from `DEFAULT_EXTENSIONS`), not evidence of a parser coverage gap;
> (c) benchmark-optimization framing removed from the abstract, Section 11,
> and Section 13;
> (d) Section 15 added, summarising post-baseline miss-taxonomy findings from
> the ten-repo expansion (benchmark v2, 330 controls).
> The v1 baseline numbers (53.5% strict recall, per-family and per-format
> results, Wilson intervals) are historical artifacts and have not been
> modified.

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

SEC002 is designed for structured credential detection under precision-oriented
remediation constraints rather than universal entropy-based secret discovery.

---

## 1. Motivation

Autonoma is a deterministic local-first secret remediation tool focused on safe,
auditable remediation workflows rather than maximum theoretical secret detection
recall.

The SEC002 rule targets credential-like secrets such as API keys, access tokens,
bearer tokens, and other high-risk authentication artifacts.

This evaluation measures SEC002 recall against a reproducible synthetic-control
benchmark designed to avoid benchmark contamination and avoid real credential exposure, support deterministic reruns and identify family-specific detection gaps.

This report establishes the SEC002 recall baseline (v1) against three repositories
prior to corpus expansion.

---

## 2. Benchmark Philosophy

The benchmark uses deterministic control generation and explicit contamination avoidance; it does
not attempt to maximize recall through broad entropy heuristics.

Instead, the goal is to measure structured credential detection behavior under precision-oriented constraints. Broad entropy-only detection is excluded from SEC002 unless its precision
impact can be measured against a separate labeled false-positive corpus.

---

## 3. Synthetic Control Generation

Synthetic controls are generated deterministically from:

- a fixed RNG seed,
- credential family templates,
- and seeded format renderers.

### 3.1 Alias-prefix synthetic credentials (v1 baseline)

**Note:** The v1 baseline used safe alias-prefix variants of real provider
credential structures. Benchmark governance v1.0 (Section 5, effective 2026-05-08)
supersedes this design and requires real provider prefixes with cryptographically
inert payloads for future benchmark versions. The v1 alias-prefix numbers are
preserved as historical artifacts.

The v1 aliases used were:

- `sk_live_` → `stk_live_`
- `ghp_` → `ght_`
- `AKIA` → `AXIA`
- `AIza` → `GIZA`
- `xoxb-` → `xotb-`

This design avoided:
- GitHub push-protection activation,
- provider abuse-system ingestion,
- public credential-index contamination,
- and accidental publication of live-prefix credential files.

The alias-prefix design evaluates structural credential detection behavior
under safe alias substitution rather than exact provider-literal matching.
Under governance v1.0, future benchmark versions must use real prefixes with
inert payloads.

The generator produces:

| Family             | Prefix / structure                              | Notes                                              |
| ------------------ | ----------------------------------------------- | -------------------------------------------------- |
| `stripe`           | `stk_live_` + 24 base62 chars                    | Inert payload                                      |
| `github_pat`       | `ght_` + 36 base62 chars                        | Last 6 chars are valid CRC32 of preceding body     |
| `aws_pair`         | `AXIA` + 16 chars (access) + 40 chars (secret)  | Both halves seeded together                        |
| `google_api`       | `GIZA` + 35 base62/`-_` chars                   | Inert payload                                      |
| `slack_bot`        | `xotb-` + numeric-numeric-secret                | Three-segment Slack bot token shape                |
| `jwt`              | Three-segment HS256 JWT                         | Header decodes to valid JSON                       |
| `pem_private`      | `-----BEGIN RSA PRIVATE KEY-----` envelope      | Wrapped base64 body, ~2048-bit equivalent          |
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

**Tier 3 — Absent or near-zero detection (0% – 22%).** `pem_private` (0/9) and
the prefix-less entropy-only families (0.0% to 22.2%) are not meaningfully
covered.

For `pem_private`: post-baseline analysis (see Section 15) established that no
detection rule for PEM private-key envelopes exists in SEC002 or any other
current Autonoma rule. The 0/9 result is the expected outcome given this absence.
Three compounding factors prevent detection even if a rule were to be added
incrementally to SEC002: Python triple-quoted strings (`"""..."""`) are not matched
by the single-quote regex `['"][^'"]+['"]`; YAML block scalars (`|`) render the
key material on subsequent indented lines, invisible to single-line `key: value`
pattern matching; and AST-safe deterministic remediation for multiline PEM blobs
is not currently implemented and would be high-risk. This family is treated as
FAMILY_OUT_OF_SCOPE for SEC002 baseline v1. Adding PEM detection, if warranted,
requires a separate rule family under the governance v1.0 Section 7.5 process; it
does not retroactively change the scope or denominator of this benchmark version.

For the prefix-less entropy families (`opaque_random_cred`, `generic_bearer`,
`opaque_session_token`): the low recall is consistent with SEC002's intentional
design. These families are reported here to quantify the scoping cost, not as
gaps requiring immediate remediation. See Section 15 for the post-baseline
miss-taxonomy breakdown of these families.

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
primarily against Python source. JSON and YAML detection at ~43% indicates a
real format-handling gap, since both formats are common credential-storage
targets in production code.

Markdown produced 0/3 detection. Post-baseline analysis (see Section 15)
established that `.md` is completely absent from both `DEFAULT_EXTENSIONS` and
`ALL_SUPPORTED_EXTENSIONS` in `src/autonoma/_internal/heuristics.py` — files
are excluded before any scanner or parser runs. The 0/3 result is
EXTENSION_EXCLUDED (an architectural scope decision), not evidence of a parser
coverage gap. The three seeded Markdown controls remain in the strict-recall
denominator; EXTENSION_EXCLUDED is an analytical classification of the miss
cause, not a retroactive scope exclusion.

The format gradient on Python, YAML, JSON, and env suggests that parser
coverage, format-specific handling, and extension routing materially affect
detector performance for in-scope formats. Several Tier 2 family misses reduce
to format issues; for example, three of five Google API key misses occur in
`.env` files, indicating a likely extension-routing or `.env`-specific parsing
gap rather than a prefix-detection failure.

---

## 11. Detector Limitations

The evaluation surfaced the following SEC002 limitations:

- **`pem_private` family has no registered SEC002 detection rule (0 / 9 recall).**
  Post-baseline analysis established that no PEM-family rule exists in SEC002
  or any current Autonoma rule. The 0/9 result is expected given this absence.
  Three compounding factors would prevent naive extension of existing patterns:
  triple-quoted Python strings, YAML block scalars, and the absence of
  AST-safe multiline remediation. This is FAMILY_OUT_OF_SCOPE for SEC002
  baseline v1. Adding PEM detection requires the governance v1.0 Section 7.5
  new-rule-family process, including a separate scope document, separate
  benchmark evaluation, and separate remediation-safety analysis.
- **Prefix-less high-entropy credentials are not meaningfully detected.**
  `generic_bearer`, `opaque_session_token`, and `opaque_random_cred` recall
  ranges from 0% to 22.2%. This is consistent with SEC002's intentional
  design; these families are reported here to quantify the scoping cost.
  Post-baseline miss-taxonomy analysis attributes these misses primarily to
  KEYWORD_GAP (var_names used by the seeder fall outside the SEC002 keyword
  sets) rather than to absent value-pattern rules (see Section 15).
- **Format-specific gaps in JSON, YAML, and `.env` files.** Recall on these
  formats is consistently lower than Python recall, including for credential
  families that succeed in Python.
- **Markdown files are EXTENSION_EXCLUDED.** `.md` is absent from
  `DEFAULT_EXTENSIONS`; files are excluded before any scanner or parser runs.
  The 0/3 result is an architectural boundary, not a parser coverage failure.
  Expanding Markdown coverage would require a separate extraction strategy
  and false-positive analysis.

SEC002 should not currently be interpreted as a universal high-entropy
secret detector. This limitation is partially intentional: broad entropy-only
heuristics were excluded from SEC002 to preserve precision and deterministic
remediation behavior. Current performance is strongest for structured,
provider-shaped, credential-like artifacts — which is consistent with its
design intent.

---

## 12. Threats to Validity

The following limitations affect this benchmark:

- **Single-author, single-implementation evaluation.** Control generation,
  seeder, scanned tool, and recall matcher were all authored by the same
  individual. Independent reproduction is required to rule out correlated
  errors across the toolchain. The redacted manifest, published seed, and
  open-source generator/seeder/recall scripts are support independent reproduction 
  of these numbers.
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
- **Alias-prefix controls (v1 only).** This baseline used alias prefixes
  rather than real provider prefixes. Benchmark governance v1.0 (Section 5)
  requires real prefixes for future versions. Numbers from v1 and future
  real-prefix versions are not directly comparable; reconciliation analysis
  will be required.

---

## 13. Future Work

Future benchmark work:

- expanded repository coverage (target: 10 repos, ~330 controls; completed
  in benchmark v2 — see Section 15),
- broader precision evaluation against labeled false-positive corpora,
- inter-rater labeling for the precision benchmark,
- remediation correctness evaluation (separately gated on env-contract policy),
- additional credential families (e.g., Azure, Heroku, npm tokens, database
  connection strings),
- and CI integration benchmarking.

Future detector work:

- `.env` file extension and JSON/YAML parser coverage improvements,
- expanded structured credential coverage for additional Tier 2 providers,
- and evaluation of PEM-family detection as a candidate for a separate
  rule family, subject to the governance v1.0 Section 7.5 process (separate
  scope document, benchmark evaluation, and remediation-safety analysis
  required before any recall claim).

Broad entropy heuristics remain intentionally excluded from SEC002 unless
their precision impact can be measured rigorously against a separate labeled
false-positive corpus.

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

---

## 15. Post-Baseline Miss Taxonomy Findings

*This section summarises findings from the ten-repo benchmark expansion
(benchmark v2, 330 controls, 10 repos). It is post-baseline analysis and is
explicitly secondary to the v1 baseline numbers above. The v1 strict recall
of 53.5% is unchanged. None of the findings in this section retroactively
alter the v1 strict-recall denominator or per-family numbers.*

### 15.1 Benchmark v2 overview

The benchmark corpus was expanded to ten repositories and 330 seeded controls
(33 controls per repo, 30 per family across 11 families). The expanded run
produced 57.0% strict recall (188 / 330). Per-family and per-repo breakdowns
are reported separately in `bench/reports/sec002_recall_diagnostic_v2.csv` and
`bench/reports/sec002_miss_pattern_analysis.md`.

The benchmark v2 numbers are a separate measurement on a different corpus size;
they are not a revision of the v1 numbers.

### 15.2 Miss-taxonomy categories

The 142 VALUE_NOT_FOUND cases in benchmark v2 were classified using the
miss-taxonomy defined in `bench/scripts/analyze_misses.py`. The prior
single-bucket DETECTOR_MISS label has been replaced by three categories
that reflect distinct failure modes at different layers of the detection
pipeline:

| Category             | Count | % of Misses | Description                                                    |
| -------------------- | ----- | ----------- | -------------------------------------------------------------- |
| EXTENSION_EXCLUDED   |    14 |        9.9% | File type absent from `DEFAULT_EXTENSIONS`; never scanned      |
| FAMILY_OUT_OF_SCOPE  |    50 |       35.2% | Family not covered by any registered SEC002 rule               |
| KEYWORD_GAP          |    77 |       54.2% | Value parser-accessible; keyword routing never evaluated it    |
| PARSER_GAP           |     0 |        0.0% | Parser extraction failed before SEC002 evaluation (in-scope families) |
| DETECTOR_MISS        |     1 |        0.7% | Keyword routing evaluated value; SEC002 still failed to detect |
| REMEDIATION_UNSAFE   |     0 |        0.0% | Detection possible; remediation policy blocked                 |
| BENCHMARK_ARTIFACT   |     0 |        0.0% | Seeding or fingerprinting issue                                |

### 15.3 Architecture/routing failures vs. parser failures vs. true detector failures

The taxonomy distinguishes three fundamentally different failure modes that
the prior DETECTOR_MISS bucket conflated:

**KEYWORD_GAP (77 cases — architecture/routing failure).**
The credential value was in a supported file format and the parser extracted
the value correctly. SEC002 routing never evaluated it because the variable or
key name assigned by the seeder — e.g., `gh_pat`, `gcp_key`, `api_bearer`,
`auth_bearer`, `user_session`, `access_session`, `session_jwt` — does not appear
in any SEC002 keyword pattern list. Fixing KEYWORD_GAP cases requires extending
the keyword sets, not changing detection logic. Keyword additions require FP
validation per governance v1.0 Section 7.4 before deployment.

Affected families: `generic_bearer` (23 non-markdown misses),
`opaque_session_token` (21), `google_api` (12), `jwt` (11),
`github_pat` (10).

**PARSER_GAP (0 cases — extraction failure).**
For in-scope families, the parser successfully surfaced all values in supported
formats. No in-scope family currently produces PARSER_GAP misses. The parser
limitations documented for `pem_private` (triple-quoted Python strings, YAML
block scalars) exist but belong to the FAMILY_OUT_OF_SCOPE classification, not
PARSER_GAP, because the family has no registered SEC002 rule. PARSER_GAP is
defined for completeness and for future use when in-scope families with multiline
value formats are added.

**DETECTOR_MISS (1 case — true detection failure).**
One `opaque_api_secret` control in an ENV file has keyword-matching conditions
met (`secret` in the var_name) and a parser-accessible value, but SEC002 failed
to detect it. The likely cause is a value-side gate that rejects values
containing special characters (`$`, `*`, `@`). This is the only case in the
330-control corpus where keyword routing evaluated a value but detection failed.

### 15.4 Implications for the v1 baseline interpretation

The KEYWORD_GAP finding revises the interpretation of several v1 Tier 2
families. Partial recall for `github_pat` (55.6%), `google_api` (44.4%),
`jwt` (66.7%), `generic_bearer` (11.1%), and `opaque_session_token` (0%)
in the v1 baseline is explained primarily by keyword-routing failures, not
absent value-pattern rules. The detector evaluated seedings assigned
keyword-matching var_names and missed seedings assigned non-keyword var_names.
This pattern was not visible in the v1 three-family data alone due to the
small per-family sample (n=9).

The `pem_private` 0/9 result in v1, previously framed as a pending root-cause
investigation, is now attributed to FAMILY_OUT_OF_SCOPE: no registered SEC002
rule exists for PEM families, and detection is additionally blocked by
multiline parser limitations.

The Markdown 0/3 result in v1, previously described as uncertain due to sample
size, is now attributed to EXTENSION_EXCLUDED: `.md` is absent from
`DEFAULT_EXTENSIONS`, and files are excluded before any scanner or parser runs.
The 0/3 result is not informative about parser coverage — it measures only that
the extension exclusion is in effect.

### 15.5 Source

Full classification detail, per-family breakdown, and per-format breakdowns
are in `bench/reports/sec002_miss_pattern_analysis.md` and
`bench/reports/sec002_miss_pattern_analysis.json`, generated by
`bench/scripts/analyze_misses.py`. The benchmark v2 diagnostic CSV is at
`bench/reports/sec002_recall_diagnostic_v2.csv`.
