# Autonoma Benchmark Annotation Guidelines

Version: 0.2
Last updated: 2026-05-07
Maintainer: Vithushan (Vihaan Innovations)

## Goal

This benchmark measures whether Autonoma correctly distinguishes real credential-like values from placeholders, test strings, mirrors, labels, and framework constants.

The benchmark evaluates detector output. Labels are assigned independently of detector behavior. Reviewers do not consult detector confidence scores, rule IDs, or suppression status while labeling.

## Scope of context for labeling

Each finding is labeled using:

- The flagged value itself.
- The variable name, key, or assignment target.
- The file path and file extension.
- ±10 lines of surrounding source code.
- Any inline comment on the same line or the line immediately above.

Reviewers do not consult: commit messages, git history, external documentation, the repository README, or runtime behavior. If a label cannot be determined within this context window, use `UNCERTAIN`.

## Labels

### TRUE_POSITIVE

Use when the value meets at least one of the following operational criteria:

1. **Known credential format match.** The value matches a documented credential prefix or structure, including but not limited to:
   - Stripe: `sk_live_`, `sk_test_`, `pk_live_`, `pk_test_`, `rk_`, `whsec_`
   - GitHub: `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`
   - AWS: `AKIA`, `ASIA` (20 chars), secret access keys (40 chars, base64-ish)
   - Google: `AIza` API keys, OAuth client secrets
   - Slack: `xoxb-`, `xoxp-`, `xoxa-`, `xoxr-`
   - JWT: three base64url segments separated by dots
   - Private keys: `-----BEGIN ... PRIVATE KEY-----` blocks
   - Generic bearer tokens, session tokens, or signed URLs with credential-like structure

2. **High-entropy string in credential-shaped position.** The value is:
   - At least 16 characters,
   - Contains mixed character classes (letters + digits, or letters + digits + symbols),
   - Has Shannon entropy ≥ 3.5 bits/char, AND
   - Is assigned to a variable, key, header, or environment variable whose name suggests a credential (e.g., `*_key`, `*_token`, `*_secret`, `*_password`, `authorization`, `api_key`).

3. **Synthetic positive control.** The value is a deliberately seeded test credential matching one of the above formats, used to verify recall. Synthetic controls are labeled `TRUE_POSITIVE` and additionally tagged `synthetic: true` in `review_notes`.

Examples:

- `stk_live_abcd1234efgh5678` — known prefix, credential-shaped
- `ghp_abcd1234efgh5678ijkl9012mnop3456qrst` — GitHub PAT format
- `eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c` — JWT structure

### FALSE_POSITIVE

Use when the value clearly does not behave like a credential. Grouped by category:

**Category A — String literals that name a concept, not a value:**
- `"token"`, `"apiKey"`, `"password"`, `"secret"`, `"authorization"`

**Category B — HTTP / protocol constants:**
- `"POST"`, `"GET"`, `"Bearer"`, `"Basic"`, `"application/json"`

**Category C — Natural-language fragments:**
- `"is not"`, `"not in"`, `"does not exist"`

**Category D — Field names, identifiers, or schema labels:**
- `"_password_reset_token"` (used as a column name or i18n key)
- `"user_api_key"` as a JSON field name in a schema definition

**Category E — Framework constants and enum values:**
- Django/Flask config keys, ORM column names, enum members.

**Category F — Mirror values.** A mirror value is one where the value is a substring, exact match, or trivial case/punctuation transformation of the variable name or key:
- `password = "password"`
- `api_key = "API_KEY"`
- `token: "your-token-here"`

**Category G — Documented public-by-design test credentials.** Stripe's published test keys, AWS canary keys, GitHub example tokens from public docs. These are `FALSE_POSITIVE` because they cannot grant access; tag `review_notes` with `public_test_credential: true`.

### UNCERTAIN

Use only when the value cannot be classified using the criteria above within the defined context window.

Do not use `UNCERTAIN` to avoid making a judgment. If you can apply the criteria, you must.

### Partial / truncated / redacted values

Values containing obvious redaction markers (`xxxx`, `***`, `...`, `<REDACTED>`, `[REDACTED]`) are labeled `FALSE_POSITIVE` regardless of surrounding context. The detector should not be rewarded for flagging text that is already marked as redacted.

## Review process

### Required fields per row

Every reviewed row must include:

- `human_label`: one of `TRUE_POSITIVE`, `FALSE_POSITIVE`, `UNCERTAIN`.
- `review_notes`: free-text justification, plus structured tags where applicable (`synthetic: true`, `public_test_credential: true`, `mirror: true`, `category: A|B|C|D|E|F|G`).
- `reviewer`: reviewer identifier.
- `review_timestamp`: ISO 8601.
- `criteria_applied`: which TRUE_POSITIVE criterion (1, 2, or 3) or FALSE_POSITIVE category (A–G) the label rests on.

### Reviewer agreement

The current benchmark is single-reviewer. This is disclosed openly in any precision report.

To partially mitigate single-reviewer risk:

- A minimum of 20% of all labeled findings are re-reviewed by the same reviewer at least 7 days after initial labeling, blind to the prior label.
- Intra-rater agreement (Cohen's kappa) is computed and reported alongside precision.
- Disagreements between first and second pass are resolved by a third pass with both prior labels visible, and the resolution is recorded.

When a second independent reviewer becomes available, inter-rater kappa replaces intra-rater kappa.

### Rules

1. Label based on the value and the defined context window. Variable name alone is never sufficient.
2. Do not reward Autonoma for flagging obvious placeholders, mirrors, or redacted strings.
3. Do not punish Autonoma for flagging synthetic positive controls; these are `TRUE_POSITIVE` by construction.
4. Detector logic, suppression rules, and detection thresholds are frozen for the duration of a labeling pass. Any change invalidates the pass and requires re-labeling.
5. Labels are assigned without viewing detector confidence, rule ID, or suppression metadata.

## Recall validation via positive controls

### Control set composition

The positive control set contains, at minimum, three synthetic credentials per category, drawn from:

- Stripe live secret key format
- GitHub personal access token format
- AWS access key + secret pair
- Google API key format
- Slack bot token format
- JWT (three-segment)
- PEM-encoded private key block
- Generic high-entropy bearer token (≥32 chars, entropy ≥ 4.0 bits/char)

Total minimum: 24 controls. Each is structurally valid but cryptographically inert (random data, never issued by the provider).

### Seeding

Controls are seeded into a fork of each benchmark repository at randomized file paths and line positions before the detector run. Seed locations are recorded in a separate `controls_manifest.json` not visible to the labeler during labeling.

### Recall metric

`recall = controls_detected / controls_seeded`

Recall is reported with a Wilson 95% score interval, identical methodology to precision.

### Recall threshold for "not damaged"

Per the anti-overfitting rule below, a new suppression rule is acceptable only if post-rule recall remains within the lower bound of the pre-rule Wilson 95% interval. A drop that crosses the lower bound blocks the rule.

## Precision calculation

Strict precision excludes `UNCERTAIN` from both numerator and denominator, and the `UNCERTAIN` count is reported separately:

```
precision = TP / (TP + FP)
uncertain_rate = UNCERTAIN / (TP + FP + UNCERTAIN)
```

Both are reported with **Wilson score interval at 95% confidence**, without continuity correction.

Sample size is reported alongside every precision claim. Precision claims with n < 30 are explicitly marked as preliminary.

## Anti-overfitting rule

A new suppression rule is added only when **all** of the following hold:

1. The false positive pattern appears in **at least two distinct repositories** (not just two files in one repo), OR is a deterministic category error reproducible from a minimal synthetic example.
2. The proposed rule is expressible as a deterministic, auditable check (regex, AST pattern, or named-entity match) — not a learned threshold tuned on the benchmark itself.
3. Post-rule recall on the positive control set remains within the lower bound of the pre-rule Wilson 95% confidence interval.

A single isolated false positive never justifies a suppression rule.

## Reproducibility

Every published precision or recall number is accompanied by:

- The exact commit SHA of Autonoma used.
- The exact commit SHA of each scanned repository.
- The labeled CSV/JSONL with all required fields.
- The `controls_manifest.json` (released after the labeling pass closes).
- The detector configuration file used.

Numbers without all five artifacts are not published.
