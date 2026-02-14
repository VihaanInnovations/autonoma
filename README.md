# Autonoma

**Deterministic secret remediation with strict safety boundaries.**

Autonoma is a local-first code security tool that deterministically fixes hardcoded secrets and intentionally refuses unsafe modifications.

## Community Edition

### Autonoma Community:

- Fixes hardcoded passwords and API keys (SEC001, SEC002)
- Detects SQL injection patterns (SEC003)
- Detects SSTI/XSS patterns (SEC004)
- Detects insecure deserialization (SEC005)
- Refuses complex security fixes by design
- Runs fully locally. No telemetry. No cloud dependency.

## Example

### Before
```python
password = "supersecret123"
api_key = "sk-live-abc123xyz"
```

### After
```python
password = os.getenv("PASSWORD")
api_key = os.getenv("API_KEY")
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

## CLI Usage

```bash
python -m daemon.cli analyze ./repo --auto-fix
```

CLI is the primary supported interface.

VS Code extension: experimental preview.

## Architecture

- Python 3.10+
- Deterministic AST-based secret remediation
- Conservative high-confidence pattern detection (no taint analysis)
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

Contact: visuvalingamvithushan@gmail.com

## License

MIT