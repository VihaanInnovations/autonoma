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

---

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

## CI Behavior

Autonoma is designed for safe, repeatable execution in pipelines.

### First Run
- Scans the codebase and fixes all **provably safe** secrets.
- Replaces values with `os.environ` calls and adds necessary imports.
- Exits with **code 1** if any findings (fixed or unfixable) are detected.

### Subsequent Runs (Idempotent)
- **Zero Diff**: No changes are made to already-remediated code.
- **Reporting**: Only reports unresolved/unsafe cases that require manual review.
- **Stable CI**: Guarantees that the tool won't create "churn" or noise in your git history.

### Exit Codes:
- `0`: No findings.
- `1`: Findings detected (even if they were auto-fixed).
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

## When NOT to use Autonoma

Adding a remediation tool requires trust. Autonoma is **not** a replacement for general secret scanners:

- **Entropy-based detection**: If you need to find random strings that *might* be secrets, use **Gitleaks** or **TruffleHog**. Autonoma focuses on deterministic remediation of identified patterns.
- **Aggressive auto-rewrites**: If you want a tool that "guesses" how to fix complex logic or multi-line concatenations, Autonoma will frustrate you. It prefers reporting a "Refusal" over breaking your production code.
- **Non-Python languages**: The Community Edition is strictly **Python-only**.

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
