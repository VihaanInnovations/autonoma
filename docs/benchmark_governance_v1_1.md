# Benchmark Governance

**Governance Version:** 1.1
**Effective Date:** 2026-05-09
**Maintainer:** Vithushan / Vihaan Innovations
**Supersedes:** Governance v1.0 (2026-05-08), which remains archived per the
append-only history requirement (see v1.0 Section 9.1).
**Scope of this version:** SEC002 recall benchmark and SEC002 precision
benchmark.

---

## Purpose

This document defines the benchmark governance rules for Autonoma benchmark
generation, execution, reporting, and detector evolution. It covers both the
recall benchmark (introduced in v1.0) and the precision benchmark
(introduced in this version, v1.1).

The goal of these rules is to preserve:

- reproducibility,
- contamination resistance,
- methodological stability,
- reporting integrity,
- and comparability across benchmark versions.

These rules apply to all SEC002 benchmark runs unless explicitly superseded
by a versioned governance update. Governance updates are themselves dated
entries and form the changelog of this document.

### Relationship to v1.0

This version supersedes v1.0 in full. All v1.0 rules carry forward unless
explicitly replaced. The structural and editorial issues identified in v1.0
during pre-v1.1 review (namely, the truncated lead-in to Section 5.1 and the
missing lead-in to Section 6) are corrected in this version's restated text.
v1.0 itself is not edited; it remains archived in its original form as the
historical record.

---

## 1. Benchmark Principles

Autonoma benchmarks prioritize:

- deterministic execution,
- reproducibility,
- transparent reporting,
- stable methodology,
- contamination avoidance,
- and auditable benchmark evolution.

Benchmarks are intended to identify:

- detector strengths,
- detector limitations,
- routing gaps,
- remediation-safety boundaries,
- and architectural assumptions.

**Benchmark headline metrics are descriptive, not optimization targets.**
See Section 7.2 for the binding rules on benchmark-motivated detector
changes.

---

## 2. Primary Metrics

### 2.1 Strict Recall (recall benchmark)

Strict recall is defined as:

```
matched_controls / total_seeded_controls
```

where:

- all seeded controls remain in the denominator,
- no exclusions are applied after benchmark execution,
- all seeded controls are counted regardless of file extension, parser
  coverage, remediation eligibility, or scope interpretation.

Strict recall is the **primary recall metric** and the only headline recall
metric permitted in summaries, release notes, abstracts, executive
summaries, or any public communication including social media posts.

### 2.2 Strict Precision (precision benchmark)

Strict precision is defined as:

```
TP / (TP + FP)
```

over labeled real-world findings only.

**Synthetic positive controls (rows tagged `synthetic: true` in the
labeling output) are excluded from both numerator and denominator.** They
contribute to recall measurement, not precision. Including them would
inflate precision because the benchmark itself seeded them; this exclusion
is mandatory.

`UNCERTAIN` labels are excluded from precision and reported separately as:

```
uncertain_rate = UNCERTAIN / (TP + FP + UNCERTAIN)
```

`uncertain_rate` is reported alongside every published precision number.
A precision claim accompanied by an undisclosed `uncertain_rate` is not a
publishable precision claim.

Strict precision is the **primary precision metric** and the only headline
precision metric permitted in any public communication.

### 2.3 Mandatory confidence intervals and sample size

Wilson 95% score confidence intervals (without continuity correction) must
accompany all strict recall and strict precision reporting. Sample size
must be reported alongside every claim. Results with `n < 30` must be
marked preliminary.

### 2.4 Cross-metric reporting rule

Recall and precision numbers must not be combined into a single composite
score (F1 or otherwise) unless both component numbers are reported with
their Wilson intervals in the same communication. Composite scores
without their components must not appear in headlines, abstracts, or
public posts.

---

## 3. Scope Registration Policy

Benchmark scope must be documented before benchmark execution, separately
for recall and precision.

### 3.1 What scope registration must define

For the recall benchmark:

- supported rule families,
- supported syntactic contexts,
- supported file formats and extensions,
- known intentional exclusions, with rationale,
- remediation-safety boundaries.

For the precision benchmark:

- corpus selection criteria (which repositories and why),
- sampling methodology (how findings are selected for labeling),
- target sample size and Wilson half-width target,
- labeling pass identifier and date range,
- annotation guidelines version in effect for the pass.

### 3.2 When scope changes are allowed

Scope registration changes:

- must be committed to the public benchmark repository before benchmark
  execution begins,
- must not be introduced in response to benchmark outcomes,
- must reference an existing user need, product roadmap item, or
  pre-existing public commitment — not a benchmark result,
- and require a dated governance or scope update entry.

### 3.3 Symmetric prohibition

**Both directions of post-hoc scope adjustment are prohibited:**

- Post-hoc scope **narrowing** (excluding families, formats, or labeled
  rows from the denominator after seeing they performed poorly) is
  prohibited.
- Post-hoc scope **expansion** (claiming retroactive coverage of families,
  formats, or labeled rows not in the registered scope, after seeing they
  performed well) is prohibited.

Either move invalidates the strict-metric (recall or precision) for that
benchmark version.

### 3.4 Secondary analytical metrics

Metrics derived from scoped subsets, conditional analyses, or post-hoc
classifications must:

- be explicitly labeled as secondary,
- state their derivation methodology in the same paragraph they appear,
- never replace strict recall or strict precision as primary metrics,
- and **must not appear in abstracts, executive summaries, release
  headlines, Reddit posts, Hacker News submissions, or social media
  posts.**

---

## 4. Benchmark Freeze Rules

A benchmark freeze begins once the following are fixed for a benchmark
version:

- detector logic,
- benchmark methodology,
- synthetic control generation (recall) or sampling methodology
  (precision),
- seeded repo set (recall) or labeled corpus (precision),
- scope registration,
- annotation guidelines (precision).

During a freeze:

- detector heuristics must not change,
- benchmark scoring logic must not change,
- scope definitions must not change,
- benchmark controls must not be relabeled (recall),
- annotation guidelines must not be edited (precision),
- previously labeled rows must not be silently relabeled (precision).

If any of the above changes occur:

- the benchmark version must be incremented,
- previous benchmark results remain historical artifacts,
- direct comparison across incompatible benchmark versions is discouraged
  unless an explicit reconciliation analysis is provided.

### 4.1 Freeze authority

Benchmark version increments require an explicit governance entry dated
and authored by the benchmark maintainer (named in the document header).
The maintainer is also the freeze-lift authority. When the project has
more than one maintainer, this section will be updated to reflect a
multi-maintainer authority model in a governance v2.

### 4.2 Precision-specific freeze: labeling pass boundaries

A precision labeling pass is itself a freeze unit. During an active pass:

- new findings must not be added to the labeled set,
- existing labels must not be edited,
- the annotation guidelines version must not change.

If the annotation guidelines must be revised mid-pass, the pass is
invalidated and restarted under the revised guidelines on a freshly
sampled corpus. Partial labels from the invalidated pass are archived but
not used to compute precision.

### 4.3 Pass identifiers

Every precision labeling pass has a unique identifier of the form
`SEC002-precision-<YYYY>-<NN>` (e.g., `SEC002-precision-2026-01`),
recorded in the precision report and in every labeled row. Pass
identifiers are append-only; they are not reused, even for invalidated
passes.

---

## 5. Synthetic Artifact Rules

### 5.1 Real prefixes with cryptographically inert payloads

Synthetic controls **must use real provider prefixes** with
cryptographically inert random payloads. They are designed to exercise
detector routing and pattern logic, not to simulate usable credentials.
Generated benchmark artifacts are prohibited from being committed to
public repositories, distributed in releases, or uploaded to hosted
services.

Examples of real provider prefixes in current use:

- `sk_live_` (Stripe),
- `ghp_` with valid CRC32 checksum (GitHub PAT),
- `AKIA` (AWS),
- `AIza` (Google),
- `xoxb-` (Slack),
- three-segment HS256 JWTs with valid base64url headers,
- full `-----BEGIN RSA PRIVATE KEY-----` envelopes.

This requirement exists because detector rules that key on real prefixes
cannot be meaningfully evaluated against benchmarks built on fake
prefixes. A benchmark using `stk_live_` instead of `sk_live_` measures
only whether a detector matches strings that *resemble* credentials, not
whether it matches the real format. Such measurements are
uninterpretable.

### 5.2 Payload requirements

Payloads must be:

- generated from a deterministic seeded RNG (reproducible from a
  published seed),
- random data that has not been issued by any provider,
- structurally valid for their family (correct length, character classes,
  checksum where applicable),
- cryptographically inert: incapable of validating against any provider's
  authentication API.

### 5.3 Contamination is enforced by the seeder, not by weakening credentials

The seeder must refuse to operate on any target with a Git remote
pointing to a public host (github.com, gitlab.com, bitbucket.org,
codeberg.org). Bypass flags exist for development testing only and
**must not be used during benchmark runs intended for publication**.

Generated benchmark credentials and seeded repositories must not be
committed to public repositories, included in releases, uploaded to
hosted services, or distributed outside controlled benchmark
environments.

### 5.4 Public vs. private benchmark artifacts

**Public artifacts (committed to the open-source benchmark repository):**

- generator script,
- seeder script,
- recall matcher and scoring scripts,
- precision sampling script and labeling tooling,
- methodology documents (this governance doc, annotation guidelines,
  recall reports, precision reports),
- redacted control manifest (values replaced with regeneration
  instructions),
- seeds and reproduction parameters (see Section 8.2 and 8.3),
- benchmark results,
- labeled CSV/JSONL outputs for precision (with raw matched values
  redacted to previews per the annotation guidelines).

**Private artifacts (excluded from Git via `.gitignore`):**

- the populated control manifest containing actual generated values,
- per-run seed logs containing seeded paths and expected values,
- seeded repository directories,
- raw findings JSON files for precision corpora when they contain
  unredacted credential previews from real-world repositories.

Reproducibility is preserved because the public seed and generator
together allow any reviewer to regenerate identical recall controls
without exposing credential values, and because the precision sampling
methodology is deterministic given the recorded RNG seed and target
repository commit SHAs.

---

## 6. Contamination Controls

Benchmark contamination avoidance is a primary design goal.

### 6.1 General controls

The following controls are required for all benchmark types:

- removal of public remotes before seeding (recall) or scanning
  (precision),
- deterministic synthetic seeding (recall),
- deterministic sampling from real-world corpora (precision),
- frozen benchmark seeds,
- reproducible control manifests and sampling manifests,
- separation between benchmark generation/sampling and detector logic,
- prohibition of benchmark-specific heuristic tuning during active
  evaluation.

### 6.2 Recall benchmark controls

In addition to the general controls, the recall benchmark requires:

- private manifest exclusion from public Git,
- seeded directory exclusion from public Git,
- public-remote refusal in the seeder.

### 6.3 Precision benchmark controls

In addition to the general controls, the precision benchmark requires:

- the labeling pass operates on findings from publicly cloned
  repositories whose contents are not modified by the benchmark,
- raw credential values from real-world findings are not exfiltrated,
  copied to long-term storage, or transmitted outside the labeling
  reviewer's workstation,
- when labeled outputs are committed publicly, raw matched values are
  replaced with previews per the annotation guidelines redaction rules,
- the reviewer must not consult external sources (web search, credential
  validation services, repository commit history beyond the registered
  commit SHA) during labeling, even to resolve `UNCERTAIN` cases,
- the reviewer must not attempt to validate any candidate credential
  against a provider's authentication API, regardless of whether the
  credential appears real or synthetic.

### 6.4 Documenting benchmark-motivated detector changes

Detector changes whose primary motivation is "this finding was missed in
recall benchmark vN" or "this false positive was found in precision pass
vN" must be:

- documented in the commit message as benchmark-motivated,
- flagged in the relevant analysis section of the next benchmark report,
- and disclosed in the next release notes.

This documentation requirement applies even if the change is also
justified by other reasons.

---

## 7. Allowed Detector Evolution

Detector evolution is permitted between benchmark versions. The rules in
this section define what kinds of evolution are allowed and under what
conditions.

### 7.1 Permitted general evolution

Changes that are clearly motivated by general product needs —
user-reported issues, real-world false negatives or false positives,
security advisories from providers, new credential formats announced
publicly — are permitted between benchmark versions without restriction
beyond normal change documentation.

### 7.2 Benchmark-motivated changes require dual justification

Detector changes whose primary motivation is improving a benchmark result
are prohibited unless **both** of the following hold:

1. The change is also justified by an independent need: a user-reported
   issue, a real-world false negative or false positive observation, a
   pre-registered scope commitment, or a published roadmap item that
   predates the benchmark result.
2. The change is documented as benchmark-motivated in the commit, the
   next benchmark report's analysis section, and the next release notes.

### 7.3 Precision-preserving and recall-preserving claims require evidence

Any change described as "precision-preserving" or "precision-neutral"
must be supported by a precision benchmark run before and after the
change. Any change described as "recall-preserving" must be supported
by a recall benchmark run before and after.

The phrases may not appear in commit messages, release notes, or reports
without this evidence.

### 7.4 Suppression rule additions (anti-overfitting)

A new suppression rule, or a change to an existing suppression rule that
removes findings, requires **all** of the following:

1. The false-positive pattern appears across at least two distinct
   repositories, OR is a deterministic category error reproducible from a
   minimal synthetic example.
2. The suppression is expressible as a deterministic, auditable check
   (regex, AST pattern, named-entity match) — not a learned threshold
   tuned on the benchmark itself.
3. **Post-rule strict recall on positive controls remains within the
   lower Wilson 95% bound of the previous frozen strict-recall baseline.**

The strict-recall baseline (not any post-classification scoped recall
or other secondary metric) is the binding floor. Improvement in
precision benchmark numbers alone is not sufficient justification for
suppression-rule additions.

### 7.5 Broad entropy heuristics

Broad entropy heuristics are prohibited unless supported by:

- a labeled false-positive corpus,
- a precision evaluation showing the change does not degrade strict
  precision below the lower Wilson 95% bound of the prior precision
  measurement,
- a recall evaluation showing the change does not degrade strict recall
  below the lower Wilson 95% bound of the prior recall measurement,
- and a documented rationale published with the change.

### 7.6 Keyword list expansion

Expansion of detector keyword lists (e.g., the variable-name keyword
match used by SEC002 to qualify high-entropy findings) requires:

1. Each newly added keyword must be justified by either real-world
   observation or pre-registered scope, not by benchmark miss analysis
   alone.
2. The keyword list version is committed to the public repository with
   a dated change entry.
3. The next benchmark run reports both pre-expansion and post-expansion
   metrics, with the keyword list version recorded in reproduction
   parameters.

This rule exists because keyword expansion is the easiest path to
benchmark gaming for any detector that conditions on variable names.
It is treated as a constrained operation, not a routine improvement.

### 7.7 New rule families

New rule families (e.g., dedicated PEM/private-key handling) require:

- separate scope documentation committed before the new rule's first
  benchmark evaluation,
- a separate benchmark evaluation specific to the new family,
- and a separate remediation-safety analysis.

A new rule family does not retroactively change the scope of prior
benchmark versions.

---

## 8. Reporting Requirements

Benchmark reports must include the following.

### 8.1 Mandatory metrics and metadata

For recall reports:

- strict recall point estimate,
- Wilson 95% confidence interval,
- total seeded controls,
- total matched controls,
- per-family breakdown with confidence intervals,
- per-format breakdown with confidence intervals,
- miss-category analysis distinguishing detector misses, parser/routing
  gaps, and intentional exclusions.

For precision reports:

- strict precision point estimate,
- Wilson 95% confidence interval,
- total labeled findings (TP + FP),
- `uncertain_rate` and `UNCERTAIN` count,
- per-FP-category breakdown (categories A–G, R, and any extensions
  defined in the annotation guidelines),
- per-rule-id breakdown if more than one detector rule is in scope,
- intra-rater Cohen's kappa from the blind re-review subset,
- the blind re-review subset proportion (default 20%) and delay
  (default ≥7 days),
- list of repositories sampled with commit SHAs.

### 8.2 Mandatory recall reproduction parameters

Every recall report must include:

- benchmark version (governance and methodology version),
- generator commit SHA,
- seeder commit SHA,
- recall matcher commit SHA,
- generator seed value (`--seed`),
- per-family count (`--per-family`),
- seeder RNG seed value (`--rng-seed`),
- each target repository's commit SHA at scan time,
- Autonoma version, policy version, and engine version,
- detector configuration (any non-default settings).

A recall report missing any of the above is not a publishable benchmark
report.

### 8.3 Mandatory precision reproduction parameters

Every precision report must include:

- benchmark version (governance and methodology version),
- annotation guidelines version,
- precision sampling script commit SHA,
- precision report script commit SHA,
- sampling RNG seed,
- target sample size and achieved sample size,
- each target repository's commit SHA at scan time,
- Autonoma version, policy version, and engine version,
- keyword list version (per Section 7.6),
- detector configuration (any non-default settings),
- labeling pass identifier (per Section 4.3),
- labeling pass start and end dates,
- reviewer identifier(s),
- blind re-review subset selection seed.

A precision report missing any of the above is not a publishable
benchmark report.

### 8.4 Mandatory limitations disclosure

Reports must include explicit disclosure of:

- benchmark sample size and resulting interval width,
- single-maintainer / single-reviewer status (see Section 10) until
  independent verification exists,
- for precision reports: that intra-rater Cohen's kappa measures
  labeling consistency, not freedom from systematic bias, and that
  independent inter-rater agreement is required to characterize bias,
- any known threats to validity specific to the run.

---

## 9. Benchmark Invalidation Conditions

A benchmark version becomes invalidated if any of the following occur:

- seeded controls change (recall),
- sampled findings change (precision),
- matching logic changes (recall) or labeling logic changes (precision),
- benchmark scope changes,
- repo selection changes materially,
- detector logic changes during a frozen benchmark cycle,
- annotation guidelines change during an active labeling pass
  (precision; see Section 4.2),
- contamination of benchmark artifacts is discovered,
- the contamination protections defined in Section 5 and Section 6
  (local-only seeder enforcement, private manifest exclusion,
  precision contamination controls) are demonstrated to have failed
  for any control or labeled row during the benchmark cycle.

### 9.1 Append-only history

The Git history of the benchmark repository must be append-only for
benchmark reports, governance documents, scope registrations, and
labeled precision outputs. Force-pushes affecting these artifacts are
prohibited. Branch protection rules in the public benchmark repository
must enforce this. Invalidated benchmark versions remain archived;
benchmark history is not rewritten retroactively.

### 9.2 Recording invalidation events

When invalidation occurs, a dated governance entry must be added to this
document recording:

- the invalidated version,
- the cause of invalidation,
- whether previously published numbers must be retracted,
- and the path to the next valid benchmark version.

---

## 10. Single-Maintainer and Single-Reviewer Disclosure

This benchmark currently operates under single-maintainer governance.
All scope, freeze, invalidation, and reporting decisions are made by the
maintainer named in the document header.

The maintainer is also the author of the detector being evaluated.

For the precision benchmark specifically, the maintainer is currently
also the sole reviewer performing labeling.

Until independent verification exists:

- All benchmark numbers should be interpreted as single-maintainer and,
  for precision, single-reviewer estimates.
- Claims of inter-maintainer or inter-rater agreement are not available
  and must not be implied.
- Intra-rater Cohen's kappa from blind re-review measures labeling
  consistency, not freedom from systematic bias. A reviewer's biases
  re-review their own labels the same way the second time. Independent
  inter-rater agreement is required to characterize bias.
- The redacted manifest, published seeds, open-source generator,
  seeder, sampling script, and labeling tooling are intended to make
  independent reproduction straightforward for any external reviewer.

When the project gains a second maintainer, this section will be
updated, and the freeze/invalidation authority model in Section 4.1
will be revised accordingly. When the project gains a second
independent reviewer for precision labeling, intra-rater kappa is
replaced by inter-rater kappa in the precision report.

---

## 11. Governance Review Trigger

This governance document is reviewed and re-examined under any of the
following conditions:

- annually, on or before the anniversary of the document's effective
  date,
- before any benchmark version increment,
- when a second maintainer joins the project,
- when a second independent reviewer joins the precision labeling
  process,
- when a contamination event or benchmark invalidation occurs,
- when a scope registration is added, removed, or substantively
  altered.

Each review either reaffirms the existing version (with a dated entry
stating no changes were made) or produces a new governance version. The
previous version remains archived.

---

## Changelog

- **v1.1 — 2026-05-09.** Adds precision benchmark governance. Introduces
  strict precision as the primary precision metric (Section 2.2),
  precision scope registration (Section 3.1), labeling-pass freeze
  semantics (Section 4.2 and 4.3), precision contamination controls
  (Section 6.3), keyword-list expansion rule (Section 7.6), precision
  reporting requirements (Section 8.1 and 8.3), and single-reviewer
  disclosure (Section 10). Restates Section 5.1 and Section 6 with the
  framing fixes identified in v1.0 pre-v1.1 review; v1.0 itself is
  unchanged per append-only history. Renumbers v1.0 Section 11
  (precision deferral) out of existence — this version delivers what
  v1.0 deferred. Renumbers v1.0 Section 12 (review trigger) to Section
  11 in this version.
- **v1.0 — 2026-05-08.** Initial governance document. Covers SEC002
  recall benchmark only. Establishes strict recall as primary metric,
  real-prefix artifact policy, single-maintainer disclosure,
  append-only history requirement, and precision deferral to v1.1.
