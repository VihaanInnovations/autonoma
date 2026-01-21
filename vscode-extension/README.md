# Autonoma AI - L5 Autonomous Code Engineer

**Local-first L5 Autonomous Code Engineer. Fixes bugs while you sleep. Air-gapped & Secure.**

![Banner](https://via.placeholder.com/1200x300?text=Autonoma+AI+Engine) 
*(Replace with actual screenshot)*

## Features

- **L5 Autonomy**: "Hotwire" mode fixes complex logic bugs automatically without human intervention.
- **Privacy First**: 100% On-Premise. Your code never leaves your machine.
- **Local Intelligence**: Uses `tree-sitter` for AST parsing and Symbolic Execution for deep logic checks.
- **Real-time Streaming**: Instant feedback via Server-Sent Events (SSE).
- **Ollama Integration**: Seamlessly connects to your local Llama 3 / Mistral models.
- **Symbolic Execution**: Detects "Dead Code" and logical impossibilities mathematically.
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

3. **Activate License**:
    - Open Command Palette (`Ctrl+Shift+P`)
    - Run: `Autonoma: Set API Key`
    - Enter the **License Key** provided in your email.

## Configuration

Settings can be found in `File > Preferences > Settings` under **Autonoma Configuration**.

- `hybridReviewer.enableLocalLLM`: Enable Ollama integration (Default: false).
- `hybridReviewer.enableCloudLLM`: Enable Cloud integration (Default: false).

## Troubleshooting

- **Connection Refused?**: Ensure the Autonoma Daemon is running on port 8000.
- **License Error?**: Re-enter your key using `Autonoma: Set API Key`.

## License

**Proprietary & Confidential.**
Copyright (c) 2026 Vihaan Innovations. All Rights Reserved.
Unauthorized copying of this file, via any medium is strictly prohibited.
For Enterprise License inquiries, contact: visuvalingamvithushan@gmail.com
