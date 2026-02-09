# Autonoma

> "Refusal is a valid outcome."

A local-first code security tool that knows when *not* to fix.

---

## What it does

Autonoma scans your code for hardcoded secrets and fixes them automatically — but only when it's safe to do so.

```diff
# Before
- password = "supersecret123"
- api_key = "sk-live-abc123xyz"

# After auto-fix
+ password = os.getenv("DB_PASSWORD")
+ api_key = os.getenv("API_KEY")
```

If Autonoma can't find the corresponding environment variable pattern, it refuses to fix. Broken fixes are worse than no fix at all.

---

## How results work

| Outcome | What it means |
|---------|---------------|
| SUCCESS | Fix applied |
| REFUSED | Declined on purpose — fix would break something |
| FAILED | Bug in Autonoma (report it) |

Refusal isn't failure. It's the system working as intended.

---

## What it can fix (Community Edition)

- **SEC001** — Hardcoded passwords → `os.getenv("PASSWORD")`
- **SEC002** — Hardcoded API keys → `os.getenv("API_KEY")`

Everything runs locally. No cloud, no telemetry.

---

## Quick start

**Windows:**
```powershell
./install.ps1
./run.ps1
```

**Mac/Linux:**
```bash
./install.sh
python -m daemon.start
```

**CLI usage:**
```bash
python -m daemon.cli analyze ./your-repo --auto-fix --verbose
```

Open VS Code and Autonoma connects automatically.

---

## How it works

1. Parses code at the AST level (not regex)
2. Detects hardcoded secrets
3. Checks if the fix would break anything
4. Applies fix only if safe; refuses with reason if not

---

## Local-first

- Runs on your machine
- No code sent anywhere
- No cloud credentials needed
- Works air-gapped

---

## Enterprise Edition

Community Edition covers SEC001/SEC002. Enterprise adds:

- SQL injection detection (SEC003)
- XSS/SSTI detection (SEC004)
- Insecure deserialization (SEC005)
- Audit logs, RBAC, CI/CD integration

Contact: enterprise@autonoma.dev

---

## Tech

- Python 3.10+
- Native AST parsing
- Qwen 2.5-Coder (local LLM)
- Daemon + VS Code extension

---

## Philosophy

A tool that fixes everything understands nothing. Autonoma knows its limits. The refusal to act — when action would cause harm — is the feature.

---

## License

MIT
