# Autonoma

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-linux%20%7C%20windows%20%7C%20macos-informational)
![Edition](https://img.shields.io/badge/Edition-Community-orange)
![PyPI Version](https://img.shields.io/pypi/v/autonoma-cli)

**Autonoma safely remediates hardcoded secrets by rewriting them to environment variables.** Using AST transformations instead of regex, it applies changes only when they are provably semantic-preserving.

- **AST-Based**: Semantic-preserving rewrites, not regex guesswork.
- **Local & Private**: No network calls or external dependencies.
- **CI/CD Ready**: Idempotent, minimal diffs, and zero-noise operation.

![Autonoma Demo](docs/Animation.gif)

---

## What problem this solves

Hardcoded secrets in codebases:
- secrets get committed and stay in git history
- fixing them manually breaks code or misses edge cases
- teams detect leaks but avoid auto-fix tools because they are unsafe

Most tools detect them.  
Autonoma fixes them **only when it can prove the rewrite is safe**.

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
Add this to your `.pre-commit-config.yaml` to prevent secrets from entering your history:

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

## Commands

Autonoma provides the following CLI commands:

### scan
Detection mode. Outputs JSON to `stdout` and human-readable summaries to `stderr`. Ideal for CI.

```bash
# Scan a directory (outputs JSON findings to stdout)
autonoma scan src/

# To save JSON results to a file
autonoma scan src/ > findings.json
```

### fix
Remedies hardcoded secrets. Applies AST rewrites and generates audit logs.

```bash
# Apply fixes
autonoma fix src/

# Preview patches before writing
autonoma fix src/ --diff

# Write remediation audit log (determines format by suffix .md/.json)
autonoma fix src/ --report-out audit.json
```

### history-scan
Analyzes git history for secrets that were added and subsequently removed or modified. 

> [!NOTE]
> **Detection only.** This command does not rewrite git history or modify commits. 

```bash
autonoma history-scan .
```

---

## Example Workflow

### Before
```python
# settings.py
DATABASES = {
    "default": {
        "PASSWORD": "Pr0d@ccess2024!",  # SEC001
    }
}
SENDGRID_API_KEY = "demo_sendgrid_key"  # SEC002
```

### After (`autonoma fix .`)
```python
# settings.py
import os
DATABASES = {
    "default": {
        "PASSWORD": os.environ["PASSWORD"],
    }
}
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]
```

---

---

## CI/CD Features

- **Idempotent**: Zero changes after the first pass.
- **Minimal Diff**: Preserves original formatting and comments.
- **Import-aware**: Handles namespace collisions and existing imports automatically.

## Integration & CI/CD

### GitHub Actions (Scan Only)
To fail your build if any secrets are detected:

```yaml
- name: Scan for secrets
  run: autonoma scan .
```

### Exit Codes:
- `0`: No findings.
- `1`: Findings detected (even if unfixable).
- `2+`: Tool/Runtime error.

---

## Legacy Commands
`analyze` is retained for backwards compatibility. We recommend migrating to `scan` or `fix`.

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
- **Missing Context**: If no `.env` or environment contract is found in the repo.

Refused cases are reported and will cause non-zero exit codes in CI.

### What it does not do
- It does not use entropy/guessing (it uses heuristic name matching).
- It does not modify non-Python files in the Community Edition.
- It does not delete your code; backups are written as `<file>.bak` before modification.

---

## JSON Schema
Reports use a consistent top-level structure:

```json
{
  "schema_version": "1.0",
  "tool_name": "autonoma",
  "tool_version": "0.1.4",
  "generated_at": "2026-03-24T12:00:00Z",
  "summary": {
    "total_findings": 1,
    "safe_to_fix": 1,
    "refused": 0
  },
  "findings": []
}
```

---

## License
MIT License
