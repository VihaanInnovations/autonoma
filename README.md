# Autonoma (L5 Local Agent)

**A local-first coding agent that actually fixes bugs without breaking the build.**

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Local](https://img.shields.io/badge/Model-Qwen_2.5-purple.svg)]()

![Autonoma Demo](docs/media/demo.gif)

---

## What is this?
I got tired of Copilot hallucinating imports and breaking my code.
Autonoma is a background daemon that acts as a reliable "L5" engineer.

It doesn't just autocomplete. It:
1.  **Watches file changes**.
2.  **Reasoning**: Parsed AST (Tree-sitter) > Context Window.
3.  **Inference**: Uses a fine-tuned Qwen 2.5-Coder (Local).
4.  **Validation**: Actually runs the linter/compiler on the fix. If it fails, it retries.

**Zero Hallucinations** (in theory). If it generates bad code, the validator catches it before you ever see it.

---

## Why use this over Devin/Cursor?
*   **Hybrid Architecture**: Runs Offline (No Cost) OR Online (Smartest). Your choice.
*   **Air-Gapped Ready**: Can work without any internet connection.
*   **Generic Repair**: Fixes Secrets, SQLi, XSS, and more across ANY repository.
*   **Project Audit**: Scans 1000+ files recursively with one click.

---

## Quick Start

### 1. Install
*   **Windows**: Run `./install.ps1`
*   **Mac/Linux**: Run `./install.sh`

### 2. Start (The Daemon)
*   Run `./run_pilot.ps1`
    *(This automatically creates the environment, installs dependencies, and launches the AI Engine)*

### 3. Code
*   Open VS Code. 
*   Autonoma will automatically connect.

---

## Tech Stack
*   **Core**: Python 3.10
*   **Parsing**: Tree-sitter / Native AST
*   **Brains**: Qwen 2.5 (Local) + GPT-4/Claude (Optional Online)
*   **Architecture**: Dockerized Daemon + VS Code Client

---

## License
MIT. Built by one guy, for the community.
Report bugs on GitHub issues.
