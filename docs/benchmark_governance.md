# Benchmark Governance

**Governance Version:** 1.0
**Effective Date:** 2026-05-08
**Maintainer:** Vithushan / Vihaan Innovations
**Scope of this version:** SEC002 recall benchmark. Precision benchmark
governance is deferred to v1.1 (see Section 11).

---

## Purpose

This document defines the benchmark governance rules for Autonoma benchmark
generation, execution, reporting, and detector evolution.

The goal of these rules is to preserve:
  reproducibility, contamination resistance, methodological stability, reporting integrity and comparability across benchmark versions.

These rules apply to all SEC002 benchmark runs unless explicitly superseded by
a versioned governance update. Governance updates are themselves dated entries
and form the changelog of this document.

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
Detector changes motivated solely by improving a benchmark headline metric,
without independent product or security justification, are prohibited.

---

## 2. Strict Recall Definition

Strict recall is defined as:

```
matched_controls / total_seeded_controls
```

where:

- all seeded controls remain in the denominator,
- no exclusions are applied after benchmark execution,
- all seeded controls are counted regardless of file extension, parser
  coverage, remediation eligibility, or scope interpretation.

Strict recall is the **primary benchmark metric** and the only headline recall
metric permitted in summaries, release notes, abstracts, executive summaries,
or any public communication including social media posts.

Wilson 95% score confidence intervals (without continuity correction) must
accompany all strict recall reporting.

---

## 3. Scope Registration Policy

Benchmark scope must be documented before benchmark execution.

### 3.1 What scope registration must define

- Supported rule families.
- Supported syntactic contexts.
- Supported file formats and extensions.
- Known intentional exclusions, with rationale.
- Remediation-safety boundaries.

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

- Post-hoc scope **narrowing** (excluding families/formats from the denominator
  after seeing they performed poorly) is prohibited.
- Post-hoc scope **expansion** (claiming retroactive coverage of families/formats
  not in the registered scope, after seeing they performed well) is prohibited.

Either move invalidates the strict-recall metric for that benchmark version.

### 3.4 Secondary analytical metrics

Metrics derived from scoped subsets, conditional analyses, or post-hoc
classifications must:

- be explicitly labeled as secondary,
- state their derivation methodology in the same paragraph they appear,
- never replace strict recall as the primary metric,
- and **must not appear in abstracts, executive summaries, release headlines,
  Reddit posts, Hacker News submissions, or social media posts.**

---

## 4. Benchmark Freeze Rules

A benchmark freeze begins once the following are fixed for a benchmark version:

- detector logic,
- benchmark methodology,
- synthetic control generation,
- seeded repo set,
- and scope registration.

During a freeze:

- detector heuristics must not change,
- benchmark scoring logic must not change,
- scope definitions must not change,
- benchmark controls must not be relabeled.

If any of the above changes occur:

- the benchmark version must be incremented,
- previous benchmark results remain historical artifacts,
- direct comparison across incompatible benchmark versions is discouraged
  unless an explicit reconciliation analysis is provided.

### 4.1 Freeze authority

Benchmark version increments require an explicit governance entry dated and
authored by the benchmark maintainer (named in the document header). The
maintainer is also the freeze-lift authority. When the project has more than
one maintainer, this section will be updated to reflect a multi-maintainer
authority model in a governance v2.

---

## 5. Synthetic Artifact Rules

This section defines the actual artifact policy in effect, which supersedes
any prior draft language about fake or alias prefixes.

### 5.1 Real prefixes with cryptographically inert payloads

Synthetic controls are designed to exercise detector routing and pattern logic, not to simulate usable credentials. Generated benchmark artifacts are prohibited from being committed to public repositories, distributed in releases, or uploaded to hosted services.

- `sk_live_` (Stripe), `ghp_` with valid CRC32 (GitHub PAT), `AKIA` (AWS),
  `AIza` (Google), `xoxb-` (Slack), three-segment HS256 JWTs with valid
  base64url headers, full `-----BEGIN RSA PRIVATE KEY-----` envelopes.

This requirement exists because detector rules that key on real prefixes
cannot be meaningfully evaluated against benchmarks built on fake prefixes.
A benchmark using `stk_live_` instead of `sk_live_` measures only whether a
detector matches strings that *resemble* credentials, not whether it matches
the real format. Such measurements are uninterpretable.

### 5.2 Payload requirements

Payloads must be:

- generated from a deterministic seeded RNG (reproducible from a published
  seed),
- random data that has not been issued by any provider,
- structurally valid for their family (correct length, character classes,
  checksum where applicable),
- cryptographically inert: incapable of validating against any provider's
  authentication API.

### 5.3 Contamination is enforced by the seeder, not by weakening credentials

The seeder must refuse to operate on any target with a Git remote pointing to
a public host (github.com, gitlab.com, bitbucket.org, codeberg.org). Bypass
flags exist for development testing only and **must not be used during
benchmark runs intended for publication**.

Generated benchmark credentials and seeded repositories must not be committed
to public repositories, included in releases, uploaded to hosted services,
or distributed outside controlled benchmark environments.

### 5.4 Public vs. private benchmark artifacts

**Public artifacts (committed to the open-source benchmark repository):**

- generator script,
- seeder script,
- recall matcher and scoring scripts,
- methodology documents (this governance doc, annotation guidelines, recall
  reports),
- redacted control manifest (values replaced with regeneration instructions),
- seeds and reproduction parameters (see Section 8.2),
- benchmark results.

**Private artifacts (excluded from Git via `.gitignore`):**

- the populated control manifest containing actual generated values,
- per-run seed logs containing seeded paths and expected values,
- seeded repository directories.

Reproducibility is preserved because the public seed and generator together
allow any reviewer to regenerate identical controls without ever exposing
credential values to public infrastructure.

---

## 6. Contamination Controls

The following controls are required:

- removal of public remotes before seeding,
- deterministic synthetic seeding,
- frozen benchmark seeds,
- reproducible control manifests,
- separation between benchmark generation and detector logic,
- prohibition of benchmark-specific heuristic tuning during active evaluation.

Detector changes whose primary motivation is "this finding was missed in
benchmark vN" must be:

- documented in the commit message as benchmark-motivated,
- flagged in the miss-analysis section of the next benchmark report,
- and disclosed in the next release notes.

This documentation requirement applies even if the change is also justified
by other reasons.

---

## 7. Allowed Detector Evolution

Detector evolution is permitted between benchmark versions. The rules in this
section define what kinds of evolution are allowed and under what conditions.

### 7.1 Permitted general evolution

Changes that are clearly motivated by general product needs — user-reported
issues, real-world false negatives, security advisories from providers, new
credential formats announced publicly — are permitted between benchmark
versions without restriction beyond normal change documentation.

### 7.2 Benchmark-motivated changes require dual justification

Detector changes whose primary motivation is improving a benchmark result
are prohibited unless **both** of the following hold:

1. The change is also justified by an independent need: a user-reported
   issue, a real-world false negative observation, a pre-registered scope
   commitment, or a published roadmap item that predates the benchmark
   result.
2. The change is documented as benchmark-motivated in the commit, the next
   benchmark report's miss-analysis section, and the next release notes.

### 7.3 Precision-preserving claims require evidence

Any change described as "precision-preserving" or "precision-neutral" must
be supported by a precision benchmark run before and after the change. The
phrase may not appear in commit messages, release notes, or reports without
this evidence.

### 7.4 Broad entropy heuristics

Broad entropy heuristics are prohibited unless supported by:

- a labeled false-positive corpus,
- a precision evaluation showing the change does not degrade precision below
  the lower Wilson 95% bound of the prior precision measurement,
- and a documented rationale published with the change.

### 7.5 New rule families

New rule families (e.g., dedicated PEM/private-key handling) require:

- separate scope documentation committed before the new rule's first
  benchmark evaluation,
- a separate benchmark evaluation specific to the new family,
- and a separate remediation-safety analysis.

A new rule family does not retroactively change the scope of prior benchmark
versions.

---

## 8. Reporting Requirements

Benchmark reports must include the following.

### 8.1 Mandatory metrics and metadata

- Strict recall point estimate.
- Wilson 95% confidence interval.
- Total seeded controls.
- Total matched controls.
- Per-family breakdown with confidence intervals.
- Per-format breakdown with confidence intervals.
- Miss-category analysis distinguishing detector misses, parser/routing gaps,
  and intentional exclusions.

### 8.2 Mandatory reproduction parameters

Every benchmark report must include the parameters required to reproduce its
numbers:

- Benchmark version (governance and methodology version).
- Generator commit SHA.
- Seeder commit SHA.
- Recall matcher commit SHA.
- Generator seed value (`--seed`).
- Per-family count (`--per-family`).
- Seeder RNG seed value (`--rng-seed`).
- Each target repository's commit SHA at scan time.
- Autonoma version, policy version, and engine version.
- Detector configuration (any non-default settings).

A report missing any of the above is not a publishable benchmark report.

### 8.3 Mandatory limitations disclosure

Reports must include explicit disclosure of:

- benchmark sample size and resulting interval width,
- single-maintainer status (see Section 10) until independent verification
  exists,
- any known threats to validity specific to the run.

---

## 9. Benchmark Invalidation Conditions

A benchmark version becomes invalidated if any of the following occur:

- seeded controls change,
- matching logic changes,
- benchmark scope changes,
- repo selection changes materially,
- detector logic changes during a frozen benchmark cycle,
- contamination of benchmark artifacts is discovered,
- the contamination protections defined in Section 5 (local-only seeder
  enforcement, private manifest exclusion) are demonstrated to have failed
  for any control during the benchmark cycle.

### 9.1 Append-only history

The Git history of the benchmark repository must be append-only for
benchmark reports and governance documents. Force-pushes affecting benchmark
artifacts, governance documents, or scope registrations are prohibited.
Branch protection rules in the public benchmark repository must enforce
this. Invalidated benchmark versions remain archived; benchmark history is
not rewritten retroactively.

### 9.2 Recording invalidation events

When invalidation occurs, a dated governance entry must be added to this
document recording:

- the invalidated version,
- the cause of invalidation,
- whether previously published numbers must be retracted,
- and the path to the next valid benchmark version.

---

## 10. Single-Maintainer Disclosure

This benchmark currently operates under single-maintainer governance. All
scope, freeze, invalidation, and reporting decisions are made by the
maintainer named in the document header.

The maintainer is also the author of the detector being evaluated.

Until independent verification exists:

- All benchmark numbers should be interpreted as single-maintainer
  estimates.
- Claims of inter-maintainer or inter-rater agreement are not available
  and must not be implied.
- The redacted manifest, published seeds, and open-source generator and
  seeder are intended to make independent reproduction straightforward
  for any external reviewer.

When the project gains a second maintainer or a regular external reviewer,
this section will be updated, and the freeze/invalidation authority model
in Section 4.1 will be revised accordingly.

---

## 11. Precision Benchmark — Deferred to Governance v1.1

Precision benchmark governance is **out of scope for governance v1.0** and
will be defined in v1.1, which must be published before the first precision
benchmark report.

Precision governance v1.1 is expected to cover, at minimum:

- annotation protocol (already drafted as a separate annotation guidelines
  document),
- reviewer disclosure and inter-rater agreement methodology,
- anti-overfitting rules for suppression-rule additions,
- labeled false-positive corpus management (creation, versioning, access
  control),
- and separation of precision and recall benchmark cycles.

Until governance v1.1 is published, precision claims about Autonoma must
not appear in publicly distributed benchmark reports.

---

## 12. Governance Review Trigger

This governance document is reviewed and re-examined under any of the
following conditions:

- annually, on or before the anniversary of the document's effective date,
- before any benchmark version increment,
- when a second maintainer joins the project,
- when a contamination event or benchmark invalidation occurs,
- when a scope registration is added, removed, or substantively altered.

Each review either reaffirms the existing version (with a dated entry stating
no changes were made) or produces a new governance version. The previous
version remains archived.

---

## Changelog

- **v1.0 — 2026-05-08.** Initial governance document. Covers SEC002 recall
  benchmark only. Establishes strict recall as primary metric, real-prefix
  artifact policy, single-maintainer disclosure, append-only history
  requirement, and precision deferral to v1.1.
