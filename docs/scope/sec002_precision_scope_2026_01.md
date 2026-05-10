# SEC002 Precision Benchmark Scope — 2026-01

<!--
Status: draft  = work in progress, placeholder enforcement disabled
Status: frozen = published artifact, placeholder enforcement enabled
-->

Status: draft

**Benchmark ID:** SEC002-precision-2026-01
**Governance Version:** 1.1
**Annotation Guidelines Version:** 0.2
**Detector Commit SHA:** _(placeholder)_
**Labeling Pass ID:** SEC002-precision-2026-01
**Scope Registration Date:** 2026-05-10
**Labeling Pass Start:** _(placeholder)_
**Labeling Pass End:** _(placeholder)_
**Status:** Pre-pass (scope registered, pass not yet open)

## Reproducibility Metadata

**Python implementation:** CPython
**Python version (sampling):** _(placeholder)_
**Python version (report):** _(placeholder)_

Fill all placeholder fields above before freezing.  Python version pins must
match across any independent reproduction attempt because random.Random
seeding is implementation-specific.

---

## Rule Scope

**Rule covered:** SEC002 — hardcoded API keys and tokens.

SEC001, SEC003, SEC004, SEC005 are out of scope for this pass.

---

## Repo Scope

Findings are sampled from unmodified public clones of the same ten
repositories used in the recall benchmark.  Commit SHAs must match those
registered in `sec002_recall_scope_v1.md`.

| Repo | Commit SHA |
|------|------------|
| flask | _(placeholder)_ |
| httpx | _(placeholder)_ |
| requests | _(placeholder)_ |
| fastapi | _(placeholder)_ |
| django | _(placeholder)_ |
| sqlalchemy | _(placeholder)_ |
| celery | _(placeholder)_ |
| pydantic | _(placeholder)_ |
| black | _(placeholder)_ |
| mypy | _(placeholder)_ |

Repos are scanned in detect-only mode; no remediation is applied.

---

## Sampling Parameters

- Sampling script: `bench/scripts/precision_sample.py`
- Sampling RNG seed: _(placeholder)_
- Target sample size: 200–400 findings (after synthetic-control exclusion)
- Blind re-review subset seed: _(placeholder)_
- Blind re-review proportion: 20% (minimum)
- Blind re-review delay: ≥7 days after initial labeling pass closes

---

## Labeling Scope

### Included contexts

- Tests and fixtures
- Tutorials and examples
- CI configuration files
- Documentation examples
- Production source files

### Excluded from scope

- Seeded synthetic positive controls (tagged `synthetic: true`; contribute
  to recall, not precision)
- Findings in excluded file extensions (`.md`, `.rst`, `.txt`)

### Label taxonomy

Per Annotation Guidelines v0.2 (see `bench/precision/annotation_guidelines.md`):
- `TRUE_POSITIVE` (criteria 1, 2, or 3)
- `FALSE_POSITIVE` (categories A–H, R)
- `UNCERTAIN`

Synthetic controls labeled `TRUE_POSITIVE` with `synthetic: true` tag but
excluded from the precision denominator.

---

## Exclusion Scope

The following rows are excluded from precision calculation (not from
the labeled corpus):
- Rows with `synthetic == "true"` (strict string comparison; `synthetic` column is authoritative)
- Rows with `human_label == UNCERTAIN`
- Rows with unrecognised or blank `human_label`
- Rows with malformed `synthetic` field (not "true" or "false")

These exclusions are applied by `bench/scripts/precision_report.py`.

---

## Frozen Artifact References

| Artifact | Location |
|----------|----------|
| Sampling script | `bench/scripts/precision_sample.py` |
| Report script | `bench/scripts/precision_report.py` |
| Sample CSV | `bench/precision/sample_2026_01.csv` _(generated)_ |
| Labeled CSV | `bench/precision/sample_2026_01_labeled.csv` _(reviewer-filled)_ |
| Precision report | `bench/precision/report_2026_01.md` _(generated)_ |
| Annotation guidelines | `bench/precision/annotation_guidelines.md` (v0.2) |

Raw matched values in the labeled CSV must be redacted to previews
before any public commit.

---

## Reviewer

**Primary reviewer:** Vithushan (Vihaan Innovations)

Single-reviewer disclosure applies per Governance v1.1 Section 10:
the detector author also serves as sole reviewer.  Intra-rater Cohen's
kappa (computed by `precision_report.py`) measures labeling consistency,
not freedom from systematic bias.  Independent inter-rater agreement is
required to characterize bias.

---

## Governance Constraints During This Pass

While this labeling pass is open:
- Detector logic must not change.
- Suppression rules must not change.
- Annotation guidelines must not be edited.
- New findings must not be added to the sample.
- Previously assigned labels must not be silently changed.

Any required change invalidates the pass; restart under the revised scope
on a freshly sampled corpus and archive the partial labels.
