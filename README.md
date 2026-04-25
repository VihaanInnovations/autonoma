# Autonoma

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-linux%20%7C%20windows%20%7C%20macos-informational)
![Edition](https://img.shields.io/badge/Edition-Community-orange)
![PyPI Version](https://img.shields.io/pypi/v/autonoma-cli)

**Autonoma detects hardcoded secrets and replaces them with `os.environ[...]` references using AST rewrites.** Changes are applied only when the rewrite is deterministic and semantically-preserving.

- **AST-Based**: Rewrites use the parsed syntax tree, not pattern matching on raw text.
- **Local & Private**: No network calls or external dependencies.
- **CI/CD Ready**: Deterministic scan output, stable exit codes, and non-mutating scan mode.

![Autonoma Demo](docs/Animation.gif)

---

## What problem this solves

Hardcoded secrets in codebases:
- secrets get committed and stay in git history
- fixing them manually breaks code or misses edge cases
- teams detect leaks but avoid auto-fix tools because they are unsafe

Secret scanners usually stop at detection..  
Autonoma fixes them **only when the rewrite is deterministic and semantically-preserving**.

---

## Quick example

```bash
autonoma scan .
autonoma fix .
git diff
```

## Installation

```bash
pip install autonoma-cli
```

### Pre-commit Integration
Add this to your `.pre-commit-config.yaml` to scan staged Python files before commit:

```yaml
- repo: local
  hooks:
    - id: autonoma
      name: Autonoma Scan
      entry: autonoma scan
      language: system
      types: [python]
```

---

## Try it in 60 seconds

```bash
# 1. Create a test file with hardcoded secrets
cat > test_secrets.py << 'EOF'
SENDGRID_API_KEY = "sg-live-abc123xyz789"
DB_PASSWORD = "Pr0dAccess2024!"
EOF

# Also create the env contract file (required for safe remediation)
printf 'SENDGRID_API_KEY=\nDB_PASSWORD=\n' > .env.example

# 2. Scan — emits JSON findings to stdout
autonoma scan test_secrets.py

# 3. Fix — rewrites the file in place
autonoma fix test_secrets.py

# 4. Scan again — should now be clean (exit 0)
autonoma scan test_secrets.py

# 5. Inspect the result
cat test_secrets.py
```

Expected output after fix:

```python
import os
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
```

---

## Commands

### scan
Detection mode. Outputs JSON to `stdout` and a human-readable summary to `stderr`. Non-mutating — never modifies files.

```bash
# Scan a directory (JSON findings to stdout)
autonoma scan src/

# Save JSON results to a file
autonoma scan src/ > findings.json
```

**Exit codes for `scan`:**
| Code | Meaning |
|------|---------|
| `0` | No findings |
| `1` | Findings detected |
| `3` | Tool error |

### fix
Remediates hardcoded secrets using AST rewrites. Mutates files in place.

```bash
# Apply fixes
autonoma fix src/

# Preview patches before writing
autonoma fix src/ --diff

# Write remediation audit log
autonoma fix src/ --report-out audit.json
```

**Exit codes for `fix`:**
| Code | Meaning |
|------|---------|
| `0` | No findings — repo was already clean |
| `1` | Findings existed before remediation (remediation may have succeeded — check output for FIXED/REFUSED counts) |
| `3` | Tool error |

> The `fix` command exits `1` whenever it found secrets before attempting remediation, regardless of whether the rewrite succeeded. This is intentional: CI pipelines should flag the commit where secrets were introduced, even after auto-fix. Run `autonoma scan` afterward to confirm the repo is clean.

### history-scan
Analyzes git history for secrets that were added and subsequently removed or modified.

> [!NOTE]
> **Detection only.** This command does not rewrite git history or modify commits.

```bash
autonoma history-scan .
```

---

## Before / After

These are the patterns Autonoma actually fixes today.

### Before
```python
# settings.py
SENDGRID_API_KEY = "sg-live-abc123xyz789"
DB_PASSWORD = "Pr0dAccess2024!"
```

### After (`autonoma fix .`)
```python
# settings.py
import os
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
```

### Refused (refusal-first safety)
```python
# f-string — refused because the rewrite would change semantics
api_key = f"prefix_{BASE_KEY}"
# → REFUSED: refuse_fstring_mixed_expression

# Dict/nested value — refused because the target is not a simple assignment
DATABASES = {
    "default": {"PASSWORD": "Pr0d@ccess2024!"}
}
# → REFUSED: unsupported assignment target type
```

Refused findings are reported in the JSON output and cause a non-zero exit in CI. Files with refused findings are never modified.

---

## What Autonoma fixes vs refuses

| Pattern | Example | Behavior | Why |
|---------|---------|----------|-----|
| Simple assignment | `api_key = "sk-abc123"` | **Fixed** | Deterministic AST rewrite |
| Class attribute | `class C: SECRET = "abc"` | **Fixed** | Deterministic AST rewrite |
| Keyword argument | `connect(password="abc")` | **Fixed** | Deterministic AST rewrite |
| f-string | `key = f"prefix_{v}"` | **Refused** | Rewrite would change runtime behavior |
| Concatenation | `key = "sk-" + suffix` | **Refused** | Rewrite would change runtime behavior |
| Dict/nested value | `cfg = {"pass": "abc"}` | **Refused** | Not a simple assignment target |
| Multiple assignment | `A = B = "secret"` | **Refused** | Ambiguous target |
| Already safe | `key = os.getenv("KEY")` | **Skipped** | No change needed |
| Missing `.env.example` | any pattern | **Refused** | No env contract to derive variable name |

---

## CI/CD Features

- **Idempotent**: Re-running on an already-fixed file makes no changes.
- **Format-preserving**: Rewrites keep original indentation and surrounding comments intact.
- **Import-aware**: Adds `import os` only when absent; avoids duplicate imports.

## Integration & CI/CD

### GitHub Actions (Scan Only)
To fail your build if any secrets are detected:

```yaml
- name: Scan for secrets
  run: autonoma scan .
```

---

## Legacy Commands
`analyze` is retained for backwards compatibility. Migrate to `scan` or `fix`.

```bash
# Equivalent to 'autonoma scan'
autonoma analyze src/ --detect-only

# Equivalent to 'autonoma fix'
autonoma analyze src/ --auto-fix
```

---

## Constraints & Behaviors

### What it remediates
- Simple assignments: `API_KEY = "secret"`
- Class attributes: `class Config: PASS = "secret"`
- Keyword arguments: `connect(password="secret")`

### What it refuses (by design)
- **Complex Expressions**: f-strings, concatenations, or function calls on the RHS.
- **Ambiguous Targets**: Multiple assignments (`A = B = "secret"`) or tuple unpacking.
- **Nested/Dict Values**: Values inside dicts, lists, or tuples.
- **Missing Context**: If no `.env.example` or environment contract is found in the repo.

Refused cases are reported in JSON output and will cause non-zero exit codes in CI. Refused findings are not modified.

### What it does not do
- It does not use entropy/guessing (it uses heuristic name matching).
- It does not modify non-Python files in the Community Edition.
- It does not delete your code; backups are written as `<file>.bak` before modification.

---

## JSON Schema

`autonoma scan` outputs a `detect-only` report to stdout:

```json
{
  "schema_version": "1.0",
  "tool_name": "autonoma",
  "tool_version": "0.1.5",
  "generated_at": "2026-03-24T12:00:00Z",
  "mode": "detect-only",
  "summary": {
    "files_processed": 3,
    "total_findings": 2,
    "safe_to_fix": 1,
    "refused": 1
  },
  "findings": [
    {
      "file": "settings.py",
      "line": 4,
      "pattern_type": "api_key",
      "severity": "high",
      "rule_id": "SEC002",
      "safe_to_fix": true,
      "suggested_env_var": "SENDGRID_API_KEY",
      "refusal_reason": null,
      "fingerprint": "sha256:abc123..."
    }
  ]
}
```

---

## License
MIT License
