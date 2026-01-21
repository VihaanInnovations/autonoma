# Autonoma (Pilot Edition) - Manual

**No-nonsense guide to setting up the Autonoma L5 Agent.**

This zip contains:
1.  **Daemon** (Python/Rust core) - The thing that actually fixes bugs.
2.  **VS Code Extension** (Interface) - The thing you click.

---

## ⚡ Quick Install

**Windows**
Run `install.ps1`.
(Right-click -> "Run with PowerShell").

**Linux/Mac**
Run `install.sh`.

*If you are paranoid about running random scripts from the internet (fair), read the Manual Install section below.*

---

## 🛠️ Manual Install (Air-Gapped)

If you want full control or are running this on a secure rig:

### 1. Set up the Daemon
The daemon needs Python 3.10+. It monitors your files and runs the Qwen model.

```bash
cd daemon
python -m venv venv
# Activate it
source venv/bin/activate  # Windows: .\venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Start it up
python start.py
```
*Keep this terminal window open.*

### 2. Install the Extension
1.  Open VS Code.
2.  `Ctrl+Shift+P` -> "Extensions: Install from VSIX".
3.  Point it to the `.vsix` file in the `vscode-extension` folder.
4.  Reload VS Code.

---

## 🎮 How to Use
Status bar (bottom right) shows the state.
*   **Green**: Ready.
*   **Spinning**: Working.

**Triggering it:**
It watches for file saves. If it sees a linter error or a security risk (like a hardcoded key), it wakes up.
1.  It parses the file (Tree-sitter).
2.  It isolates the function in question.
3.  It patches it.
4.  It verifies the fix works.

**Forcing a run:**
`Ctrl+Shift+P` -> "Autonoma: Fix This File".

---

## FAQ
**"Why L5?"**
Because it validates its own code. If the fix breaks the build, it reverts. No human loop needed.

**"Do I need an API Key?"**
No. It runs local models (Qwen 2.5). Your code stays on your machine.

**support**: `github.com/VihaanInnovations/autonoma`
