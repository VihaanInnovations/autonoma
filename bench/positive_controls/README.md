# Positive Control Corpus

**Purpose:** Controlled regression corpus for SEC001/SEC002 recall validation.

> **This is NOT a substitute for a real leaked-secret benchmark.**
> It is a controlled positive/negative corpus used to verify that value-side gate
> changes did not over-suppress genuine credential-like values.

---

## Static annotation corpus

### Files

| File | Contents |
|------|----------|
| `sec001_passwords.py` | 5 hardcoded-password positives (SEC001) |
| `sec002_tokens.py` | 6 API-key/token positives + 6 negative controls (SEC002) |

### Annotations

Each sensitive line carries an inline annotation:

- `# EXPECT: SEC001` — scanner must detect this line as SEC001
- `# EXPECT: SEC002` — scanner must detect this line as SEC002
- `# EXPECT: SUPPRESS` — scanner must NOT produce a finding on this line

### Running the benchmark

```bash
python bench/check_positive_controls.py
```

Or via pytest:

```bash
pytest tests/test_positive_controls.py
```

### What this corpus does and does not prove

**Does prove:**
- The 5 SEC001 password values survive the placeholder and value-gate filters.
- The 6 SEC002 token values survive the placeholder, identifier, and mirror-name gates.
- The 6 known false-positive patterns (e.g. `token = "is not"`) remain suppressed.

**Does NOT prove:**
- Real-world recall across diverse codebases.
- That all credential patterns with similar structure are detected.
- Precision (these files contain only intentional positives and negatives).

### Negative control rationale

| Pattern | Gate that suppresses it |
|---------|------------------------|
| `token = "is not"` | two-word lowercase gate |
| `token = "not in"` | two-word lowercase gate |
| `token_source = "POST"` | `_PLAIN_WORD_VALUES` |
| `tokenUrl = "token"` | `_PLAIN_WORD_VALUES` |
| `apiKey = "apiKey"` | `_PLAIN_WORD_VALUES` |
| `INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"` | underscore-prefix identifier gate |

---

## Synthetic generator/seeder system

For larger-scale recall measurement across diverse formats and file positions,
use `generator.py` and `seeder.py`.

### Overview

```
generator.py  →  controls_manifest.json  →  seeder.py  →  seeded local repo
                                                         ↓
                                                    seed_log.json
                                                    (for recall measurement)
```

### Credential families

Controls are divided into two categories:

**Vendor-shaped controls** — Synthetic values with alias prefixes that approximate real provider credential formats.
These exercise prefix-keyed detection rules without using any real provider-valid prefix.

| Family | Safe alias prefix | Modeled after |
|--------|------------------|---------------|
| `stripe` | `stk_live_` | Stripe secret keys |
| `github_pat` | `ght_` | GitHub personal access tokens |
| `aws_pair` | `AXIA` | AWS access key IDs |
| `google_api` | `GIZA` | Google API keys |
| `slack_bot` | `xotb-` | Slack bot tokens |
| `jwt` | (three-segment) | JSON Web Tokens |
| `pem_private` | PEM envelope | RSA private keys |

**Generic opaque credential-shaped controls** — no vendor prefix.
These exercise high-entropy and context-sensitive detection independent of prefix memorization.

| Family | Structure |
|--------|-----------|
| `generic_bearer` | 40-char base64url |
| `opaque_api_secret` | 32-char mixed charset |
| `opaque_session_token` | segmented base62 |
| `opaque_random_cred` | 24–40 char alphanumeric |

### Format distribution

The seeder uses weighted random format selection (deterministic under RNG seed):

| Format | Weight |
|--------|--------|
| Python | 35% |
| YAML | 25% |
| .env | 20% |
| JSON | 15% |
| Markdown | 5% |

### File placement

Files are placed into realistic repo-like subdirectories chosen per-control
from a fixed pool:

```
docs/examples/   config/   scripts/   deploy/   .github/workflows/
tests/fixtures/  env/       examples/  samples/
```

No benchmark-named directories are created. All seeded paths are recorded in
`seed_log.json` for deterministic cleanup and recall measurement.

### Usage

```bash
# 1. Generate private manifest (keep this file private)
python bench/positive_controls/generator.py \
    --seed 42 \
    --per-family 5 \
    --out /private/controls_manifest.json \
    --out-redacted bench/positive_controls/controls_manifest_redacted.json

# 2. Seed into a LOCAL clone (no public remote)
python bench/positive_controls/seeder.py \
    --manifest /private/controls_manifest.json \
    --target-repo /local/path/to/cloned-repo \
    --seed-log /local/path/to/cloned-repo/seed_log.json \
    --rng-seed 99

# 3. Run scanner and compare hits against seed_log.json
```

### Cleanup

The seeder prints cleanup commands on exit. All seeded file paths are also
recorded in `seed_log.json` under `locations[].file_path`.

---

## Benchmark contamination avoidance

Autonoma's positive control system is designed to minimize contamination risk:

**No real provider prefixes.** All vendor-shaped controls use safe alias
prefixes (`stk_live_`, `ght_`, `AXIA`, `GIZA`, `xotb-`). These preserve
structural and entropy realism without matching any provider-valid credential format or
triggering public provider-issued credential namespaces.

**No public manifests with values.** The `controls_manifest.json` file that
contains actual generated values must stay private. Only the seed integer
and the redacted manifest are publishable. Values can be regenerated locally
at any time from the seed. The same seed always regenerates the identical control set,
allowing deterministic reproduction of benchmark runs.

**Randomized realistic paths.** Seeded files are placed in repo-like
directories (`config/`, `scripts/`, `examples/`, etc.) selected
deterministically by RNG seed. No single fixed directory name (such as
`_autonoma_seeded/`) appears across all seeded repos, reducing the chance
that a scanner or LLM learns to ignore a known benchmark signature.

**Local-only seeded repos.** The seeder refuses to run against a repo clone
whose git remote points to a public host. Seeded clones must never be pushed
to public remotes.
