# Autonoma – Pilot Edition

## Overview

Autonoma (Pilot Edition) is an **open‑source, local‑first autonomous code remediation engine** designed to automatically detect and fix a defined class of high‑impact code issues using static analysis and LLM‑assisted reasoning.

This repository exposes **only the core autonomy engine**. It is intentionally scoped for **individual developers, security researchers, and early adopters** who want to experiment with fully automated code fixes in a controlled, single‑repository environment.

Autonoma runs **entirely on‑premise**, requires no external SaaS dependency, and is designed to be transparent, inspectable, and hackable.

---

## What “L5 Autonomy” Means in This Repo

In the context of Autonoma Pilot Edition, **L5 autonomy** means:

* No human‑in‑the‑loop during execution
* Fully automated detection → reasoning → fix → apply loop
* Deterministic remediation for a *bounded* set of issues
* Local execution with explicit scope

It **does not** mean unlimited self‑modifying behavior, unrestricted system control, or organizational‑level autonomy.

---

## Issues Autonoma Can Fix Automatically

The Pilot Edition focuses on **five high‑impact, well‑defined categories** where deterministic remediation is possible:

* Hardcoded API keys and secrets
* Insecure password handling patterns
* Common SQL injection vulnerabilities
* Linting and structural code issues
* Rule‑based security anti‑patterns

All fixes are generated through **AST‑level analysis** combined with a local LLM (default: Qwen 2.5‑Coder) to ensure structure‑aware and minimally invasive changes.

---

## How It Works (High Level)

1. **Static Analysis**

   * Source code is parsed using AST‑level inspection
   * Known insecure patterns are detected deterministically

2. **Autonomous Reasoning**

   * A local LLM is used to reason about safe, minimal fixes
   * Output is constrained to structured, schema‑validated responses

3. **Controlled Application**

   * Fixes are applied directly to the codebase
   * Scope is limited to the current repository

4. **Repeatable Execution**

   * The system can be re‑run safely
   * Behavior is predictable within defined boundaries

---

## Local‑First by Design

Autonoma Pilot Edition:

* Runs entirely on your machine
* Does not send code to external services
* Does not require cloud credentials
* Can operate in air‑gapped environments

This makes it suitable for experimentation on sensitive codebases — **with the understanding that no enterprise governance guarantees are provided**.

---

## What This Edition Is NOT

This repository **does not include** enterprise or production‑grade organizational features.

Specifically, it does **not** provide:

* Governance or policy enforcement
* Role‑based access control (RBAC)
* Approval workflows
* Audit logs or compliance reporting
* Multi‑repository or multi‑team orchestration
* SLAs, support guarantees, or security attestations

If you need any of the above, this edition is **not sufficient** on its own.

---

## Intended Use Cases

Autonoma Pilot Edition is suitable for:

* Individual developers
* Open‑source contributors
* Security research and experimentation
* Proof‑of‑concept automation
* Evaluating autonomous remediation approaches

It is **not designed** for regulated, compliance‑bound, or production‑critical enterprise deployments.

---

## Installation

> ⚠️ This is a pilot project. Expect rough edges.

Installation scripts are provided for convenience:

* `install.sh` (Linux / macOS)
* `install.ps1` (Windows)

These scripts install Autonoma locally and configure the required runtime dependencies.

Always review installation scripts before execution.

---

## License

This project is released under the **MIT License**.

You are free to use, modify, and distribute this code, including for commercial purposes, **at your own risk**.

---

## Roadmap (High Level)

Future work may include:

* Improved static analysis coverage
* Expanded vulnerability classes
* Safer execution boundaries
* Optional enterprise‑grade governance layers (separate edition)

No timeline or guarantees are provided.

---

## Disclaimer

Autonoma Pilot Edition performs **automated code modification**.

* Always review changes before merging
* Do not run against critical production branches
* No warranties are provided

Use responsibly.

---

## Feedback & Contributions

This is an early‑stage project.

Constructive feedback, issue reports, and pull requests are welcome — especially those focused on correctness, safety, and determinism.

---

**Autonoma Pilot Edition** is about exploring what *practical, bounded autonomy* looks like — not promising enterprise guarantees before they exist.
