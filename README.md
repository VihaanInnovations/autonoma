# Autonoma

    "Unlike LLM-based fixers, Autonoma doesn't guess. Every fix is AST-based and deterministic. If it can't guarantee the replacement is safe, it refuses. That's by design."

**Deterministic secret remediation with strict safety boundaries.**

Autonoma is a local-first code security tool that deterministically fixes hardcoded secrets and deliberately refuses unsafe modifications.


## Community Edition

### Autonoma Community:

- Fixes hardcoded passwords and API keys (SEC001, SEC002)
- Detects high-risk SQL string construction in `.execute()` calls (SEC003)
- Detects Python Server-Side Template Injection (SSTI) patterns (SEC004)
- Detects insecure deserialization patterns in pickle and unsafe yaml usage (SEC005)
- Refuses complex security fixes by design
- Runs fully locally. No telemetry. No cloud dependency.

Community Edition is free for individuals and teams. No usage limits. No account required.

## Example

### Before
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

### After
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

## Safety Model

Autonoma applies deterministic fixes only when:

1. The replacement is structurally safe
2. The environment contract can be established
3. The modification does not introduce ambiguity

### Outcomes:

| Status | Meaning |
| :--- | :--- |
| FIXED | Deterministic fix applied |
| REFUSED | Modification intentionally declined |
| SKIPPED | Already compliant |
| FAILED | Tool error (reportable bug) |

**Refusal is intentional — not a failure.**
When Autonoma cannot guarantee a structurally safe replacement — for example, when a secret is used across multiple scopes or inside a dynamic expression — it refuses rather than guessing. A wrong fix is worse than no fix.

## CLI Usage

```bash
python -m daemon.cli analyze ./repo --auto-fix
```

CLI is the primary supported interface.

VS Code extension: experimental preview.

## Architecture

- Python 3.10+
- Deterministic AST-based secret remediation (SEC001, SEC002)
- Conservative, line-level high-confidence pattern detection (SEC003–SEC005; no taint analysis)
- Community Edition does not rely on remote LLMs or cloud services

## Enterprise Edition

Designed for teams that require governance, auditability, and CI enforcement.

Enterprise adds:

- Policy enforcement
- Audit logs
- Approval workflows
- Multi-repository orchestration
- CI/CD integration
- Role-based access control

Contact for pricing: visuvalingamvithushan@gmail.com

## License

MIT
