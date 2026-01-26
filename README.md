# Autonoma – Pilot Edition

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Local](https://img.shields.io/badge/Model-Qwen_2.5-purple.svg)]()

![Autonoma Demo](docs/media/demo.gif)


## What this project is

Autonoma (Pilot Edition) is an **open‑source, local‑first autonomous code remediation engine**.

It is built to experiment with a very specific idea: *can a tool safely detect and fix certain classes of code issues on its own, without human intervention, when the problem space is tightly constrained?*

This repository intentionally exposes **only the core autonomy engine**. It is meant for individual developers, security‑minded engineers, and early adopters who want to explore autonomous remediation in a **single‑repository, local environment**.

Everything runs on your machine. There is no hosted service and no external dependency required to function.

---

## What “L5 autonomy” means here (and what it doesn’t)

In the context of this project, **L5 autonomy** means:

* No human‑in‑the‑loop during execution
* A complete detect → reason → fix → apply cycle
* Deterministic behavior within a *bounded* problem space
* Explicitly limited scope (one repository, local execution)

It does **not** mean:

* Unrestricted self‑modifying systems
* Autonomous architectural refactors
* Organization‑level decision making
* Production or enterprise readiness

The goal is practicality, not maximal autonomy.

---

## What Autonoma can fix automatically

The Pilot Edition focuses on **a small set of high‑impact, well‑understood issue categories** where deterministic fixes are realistically possible:

* Hardcoded API keys and secrets
* Insecure password handling patterns
* Common SQL injection patterns
* Linting and basic structural issues
* Rule‑based security anti‑patterns

Autonoma uses **AST‑level analysis** (via Tree‑sitter and native parsers) to understand code structure before applying changes. A local LLM (default: Qwen 2.5‑Coder) is used to generate fixes that are constrained to minimal, structure‑preserving edits.

---

## How it works (high level)

1. **Static analysis**

   * Source code is parsed at the AST level
   * Known insecure or invalid patterns are detected deterministically

2. **Autonomous reasoning**

   * A local LLM proposes a minimal fix
   * Outputs are constrained to structured, schema‑validated responses

3. **Application**

   * Fixes are applied directly to the working tree
   * Scope is limited to the current repository

4. **Repeatability**

   * The system can be re‑run safely
   * Behavior is predictable within its defined boundaries

---

## Local‑first by design

Autonoma Pilot Edition:

* Runs entirely on your machine
* Does not send code to external services
* Does not require cloud credentials
* Can operate in air‑gapped environments

This makes it suitable for experimentation on sensitive codebases, with the understanding that **no governance or compliance guarantees are provided**.

---

## What this edition intentionally does NOT include

This repository does **not** attempt to solve enterprise‑scale problems.

It does not provide:

* Policy or governance enforcement
* Role‑based access control (RBAC)
* Approval workflows
* Audit logs or compliance reporting
* Multi‑repository or multi‑team orchestration
* SLAs, support guarantees, or certifications

If you need any of the above, this edition is not sufficient on its own.

---

## Intended use

Autonoma Pilot Edition is intended for:

* Individual developers
* Open‑source contributors
* Security research and experimentation
* Proof‑of‑concept automation
* Evaluating whether bounded autonomy is useful in practice

It is **not designed** for regulated, compliance‑bound, or production‑critical environments.

---

## Roadmap (intentionally loose)

Possible future directions include:

* Broader static analysis coverage
* Additional vulnerability classes
* Tighter execution boundaries
* Optional enterprise‑oriented layers (separate edition)

No timelines or guarantees are implied.

---

## Disclaimer

This project performs **automated code modification**.

* Always review changes before merging
* Avoid critical production branches
* No warranties are provided

Use responsibly.

---

## Feedback & contributions

This is an early‑stage project.

Issues, bug reports, and pull requests are welcome — especially those focused on correctness, safety, and determinism.

---

Autonoma Pilot Edition exists to explore what *practical, bounded autonomy* actually looks like — not to promise more than the code can deliver.


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
*   Core: Python 3.10
*   Parsing: Tree-sitter / Native AST
*   Brains: Qwen 2.5 (Local) + GPT-4/Claude (Optional Online)
*   Architecture: Dockerized Daemon + VS Code Client

---

## License
MIT. Built by one guy, for the community.
Report bugs on GitHub issues.
