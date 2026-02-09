# Autonoma

> **"Refusal is a valid outcome."**

The code security scanner that knows when **not** to fix.

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Local-First](https://img.shields.io/badge/Privacy-100%25_Local-green.svg)]()
[![Model](https://img.shields.io/badge/LLM-Qwen_2.5-purple.svg)]()

---

## ⚡ See It In Action

```diff
# Before: credentials.py
- password = "supersecret123"
- api_key = "sk-live-abc123xyz"

# After: Autonoma auto-fix
+ password = os.getenv("DB_PASSWORD")
+ api_key = os.getenv("API_KEY")
```

**30 seconds to try:**
```bash
git clone https://github.com/user/autonoma-community.git
cd autonoma-community
./install.sh  # or install.ps1 on Windows
python -m daemon.cli analyze ./demo-project --auto-fix --verbose
```

---

## 🧠 What Makes Autonoma Different

Most security tools blast you with warnings. Autonoma takes a different approach:

| Outcome | Meaning |
|---------|---------|
| ✅ **SUCCESS** | Fix applied correctly |
| 🚫 **REFUSED** | Deliberately declined — would cause harm |
| ❌ **FAILED** | Unexpected error (a bug) |

**Refusal is not failure.** When Autonoma detects a hardcoded secret but can't find the environment variable contract, it refuses to fix — because a broken fix is worse than no fix.

This is **intentional restraint**.

---

## 🔒 What It Fixes (Community Edition)

| Issue | Description | Auto-Fix |
|-------|-------------|----------|
| **SEC001** | Hardcoded passwords | ✅ `os.getenv("PASSWORD")` |
| **SEC002** | Hardcoded API keys | ✅ `os.getenv("API_KEY")` |

Zero cloud. Zero telemetry. **100% local.**

---

## 🏗️ How It Works

```
Source Code → AST Parser → Secret Detection → Safety Check → Auto-Fix
                                                    ↓
                              (If unsafe → REFUSED with explanation)
```

1. **Parse** — Analyzes code at the AST level (not regex)
2. **Detect** — Finds hardcoded secrets deterministically
3. **Validate** — Checks if fix would break the code
4. **Fix or Refuse** — Applies fix only if safe; refuses with clear reason if not

---

## 🔐 Local-First, Always

- ✅ Runs entirely on your machine
- ✅ No code leaves your environment
- ✅ No cloud credentials required
- ✅ Works air-gapped

---

## 📦 Quick Start

### Windows
```powershell
./install.ps1
./run.ps1
```

### Mac / Linux
```bash
./install.sh
python -m daemon.start
```

### VS Code
Open VS Code — Autonoma connects automatically.

### CLI
```bash
python -m daemon.cli analyze ./your-repo --auto-fix --verbose
```

---

## 🚀 Enterprise Edition

The Community Edition proves the philosophy. The **Enterprise Edition** extends it:

| Feature | Community | Enterprise |
|---------|-----------|------------|
| SEC001/SEC002 (Secrets) | ✅ | ✅ |
| SEC003 (SQL Injection) | — | ✅ |
| SEC004 (XSS/SSTI) | — | ✅ |
| SEC005 (Insecure Deserialization) | — | ✅ |
| Audit Logs | — | ✅ |
| Policy Enforcement | — | ✅ |
| RBAC & Team Management | — | ✅ |
| CI/CD Integration | — | ✅ |

**[Contact for Enterprise Licensing →](mailto:enterprise@autonoma.dev)**

---

## 🛠️ Tech Stack

- **Core:** Python 3.10+
- **Parsing:** Native AST analysis
- **LLM:** Qwen 2.5-Coder (local)
- **Architecture:** Daemon + VS Code Extension

---

## 📖 Philosophy

> "A tool that fixes everything understands nothing."

Autonoma was built on a simple belief: **autonomous systems must know their limits.** The refusal to act — when action would cause harm — is a feature, not a limitation.

We don't just catch secrets. We catch ourselves before we break your code.

---

## 📄 License

MIT. Free forever. Built for the community.

---

<p align="center">
  <strong>Autonoma: Code Security with Intentional Restraint</strong>
</p>
