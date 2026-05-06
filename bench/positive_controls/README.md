# Positive Control Corpus

**Purpose:** Controlled regression corpus for SEC001/SEC002 recall validation.

> **This is NOT a substitute for a real leaked-secret benchmark.**
> It is a controlled positive/negative corpus used to verify that value-side gate
> changes did not over-suppress genuine credential-like values.

## Files

| File | Contents |
|------|----------|
| `sec001_passwords.py` | 5 hardcoded-password positives (SEC001) |
| `sec002_tokens.py` | 6 API-key/token positives + 6 negative controls (SEC002) |

## Annotations

Each sensitive line carries an inline annotation:

- `# EXPECT: SEC001` — scanner must detect this line as SEC001
- `# EXPECT: SEC002` — scanner must detect this line as SEC002
- `# EXPECT: SUPPRESS` — scanner must NOT produce a finding on this line

## Running the benchmark

```bash
python bench/check_positive_controls.py
```

Or via pytest:

```bash
pytest tests/test_positive_controls.py
```

## What this corpus does and does not prove

**Does prove:**
- The 5 SEC001 password values survive the placeholder and value-gate filters.
- The 6 SEC002 token values survive the placeholder, identifier, and mirror-name gates.
- The 6 known false-positive patterns (e.g. `token = "is not"`) remain suppressed.

**Does NOT prove:**
- Real-world recall across diverse codebases.
- That all credential patterns with similar structure are detected.
- Precision (these files contain only intentional positives and negatives).

## Negative control rationale

| Pattern | Gate that suppresses it |
|---------|------------------------|
| `token = "is not"` | two-word lowercase gate |
| `token = "not in"` | two-word lowercase gate |
| `token_source = "POST"` | `_PLAIN_WORD_VALUES` |
| `tokenUrl = "token"` | `_PLAIN_WORD_VALUES` |
| `apiKey = "apiKey"` | `_PLAIN_WORD_VALUES` |
| `INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"` | underscore-prefix identifier gate |
