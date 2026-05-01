# Autonoma AI - Local Autonomous Code Fixing Agent

**Local-first autonomous code fixing agent. Fixes bugs while you sleep. Air-gapped & Secure.**

![Banner](https://via.placeholder.com/1200x300?text=Autonoma+Community+Edition)

## Features

- **Local Intelligence**: Uses `tree-sitter` for AST parsing and regex-free logic checks.
- **Privacy First**: 100% Local. Your code never leaves your machine.
- **Auto-Fix**: Automatically fixes hardcoded secrets (SEC001, SEC002) with environment variables.
- **Refusal Semantics**: Knows when *not* to fix. Declined fixes prevent breakage.
- **Real-time Streaming**: Instant feedback via Server-Sent Events (SSE).
- **Daemon Architecture**: Lightweight Python server + VS Code Client.

## Prerequisites

- **Python 3.10+**: For the Daemon.
- **Node.js 18+**: For the VS Code Extension.
- **Ollama (Optional)**: For local AI features.

## Quick Start (Installation)

1. **Install Engine**:
   - **Windows**: Run `install.ps1`
   - **Linux/Mac**: Run `install.sh`

2. **Start Engine**:
    This extension requires the **Autonoma Daemon** to be running.
    *Note: The installer usually sets this up to run automatically.*

3. **Verify Connection**:
    - Open Command Palette (`Ctrl+Shift+P`)
    - Run: `Autonoma: Analyze File` on a file with issues.

## Configuration

Settings can be found in `File > Preferences > Settings` under **Autonoma Configuration**.

- `autonoma.enableLocalLLM`: Enable Ollama integration (Default: false).
- `autonoma.enableCloudLLM`: Enable Cloud integration (Default: false).

## Troubleshooting

- **Connection Refused?**: Ensure the Autonoma Daemon is running on port 8000.

## License

MIT License. See `LICENSE.txt` for details.
