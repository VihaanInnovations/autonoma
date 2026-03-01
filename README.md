# Autonoma

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-local--first-lightgrey)
![Edition](https://img.shields.io/badge/community-free-brightgreen)

Most secret scanners find the problem and leave fixing to you. Autonoma fixes it — but only when it can guarantee the fix is safe. If it can't, it refuses. That's by design.

Deterministic secret remediation with strict safety boundaries.

---

## What it actually does

Autonoma scans your Python codebase for hardcoded secrets and replaces them with environment variable references. It uses AST-based analysis, not regex guessing. If the fix isn't structurally safe, it won't make it.

It runs locally. No telemetry. No cloud calls. No account.

---

## Real world test

Searched GitHub for exposed secrets using `api_key = "sk-" language:Python`. Found a real public repo with live exposed Azure Vision and OpenAI API keys. Cloned it. Ran Autonoma.

Fixed both secrets cleanly. Refused the edge case where the pattern couldn't be cleanly isolated. Nothing else in the codebase was touched.

[Watch the full demo →](#)

---

## Example

Before:

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'prod_db',
        'USER': 'admin',
        'PASSWORD': 'Pr0d@ccess2024!',       # SEC001 — hardcoded password
        'HOST': 'db.internal.company.com',
    }
}

SENDGRID_API_KEY = "SG.live-abc123xyz987_realkey"  # SEC002 — hardcoded API key
```

After:

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'prod_db',
        'USER': 'admin',
        'PASSWORD': os.getenv("PASSWORD"),      # FIXED
        'HOST': 'db.internal.company.com',
    }
}

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")   # FIXED
```

---

## What it detects

| Code | What |
|------|------|
| SEC001 | Hardcoded passwords |
| SEC002 | Hardcoded API keys |
| SEC003 | High-risk SQL string construction in `.execute()` calls |
| SEC004 | Python SSTI patterns |
| SEC005 | Insecure deserialization — pickle and unsafe yaml |

SEC001 and SEC002 get auto-fixed. SEC003–SEC005 are flagged only — Autonoma doesn't attempt structural rewrites for logic-level issues.

---

## Safety model

Autonoma only applies a fix when three conditions are met:

1. The replacement is structurally safe
2. The environment contract can be established
3. The modification doesn't introduce ambiguity

Every fix produces one of four outcomes:

| Status | Meaning |
|--------|---------|
| `FIXED` | Deterministic fix applied |
| `REFUSED` | Modification intentionally declined |
| `SKIPPED` | Already compliant |
| `FAILED` | Tool error — worth reporting |

---

## What gets refused and why

Refusal isn't a failure. It means Autonoma looked at the code and decided it couldn't guarantee the fix was safe. A wrong fix is worse than no fix.

**No Environment Contract**
```python
API_KEY = "sk-live-abc123" # REFUSED — Project lacks a .env file or dotenv dependency.
```

**Ambiguous Variable Name**
```python
x = "sk-live-abc123" # REFUSED — Cannot determine safe env var name from 'x'.
```

**Already Compliant**
```python
API_KEY = os.getenv("API_KEY", "sk-live-abc123") # REFUSED — Line already uses environment variable lookup.
```

**Ambiguous Secret Pattern**
```python
token = "Bearer " + "sk-live-abc123" # REFUSED — Could not cleanly isolate the literal assignment.
```

If Autonoma refuses something you think is safe, open an issue with the pattern. That's genuinely useful.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/VihaanInnovations/autonoma
cd autonoma

# 2. Install dependencies
# Windows:
./install.ps1

# Linux/macOS:
./install.sh

# 3. Start the daemon
# Windows:
./run.ps1

# Linux/macOS:
./run.sh

# 4. In a separate terminal, run on your repo
py -m daemon.cli analyze ./your-repo --auto-fix --verbose
```

The daemon needs to be running before you use the CLI. Two terminals, not one.

[Full installation guide →](#)

CLI is the primary interface. VS Code extension exists but is experimental — use it at your own risk.

---

## Architecture

- Python 3.10+
- AST-based secret detection and remediation for SEC001, SEC002
- Line-level pattern matching for SEC003–SEC005 — high confidence only, no taint analysis
- No remote LLM calls. No cloud dependency. Runs entirely on your machine.

---

## Enterprise

The community edition covers individual and team use with no limits. If you need policy enforcement, audit logs, approval workflows, CI/CD integration, or multi-repo orchestration — that's the enterprise tier.

Contact: visuvalingamvithushan@gmail.com

---

## Contributing

If you hit a bug, an edge case that should be refused but isn't, or something that gets refused but shouldn't — open an issue. That's the most useful contribution right now. PRs welcome too.

---

## License

MIT
