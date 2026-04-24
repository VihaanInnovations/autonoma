# Demo Project

This directory contains intentionally vulnerable Python files used by Autonoma's CI smoke tests.

## Project Structure

```
demo-project/
├── src/
│   ├── auth/
│   │   └── credentials.py      # Contains hardcoded passwords (SEC001)
│   ├── api/
│   │   ├── user_service.py     # Contains hardcoded API keys (SEC002)
│   │   └── data_handler.js     # JavaScript file with hardcoded secrets
│   └── main.py                 # Contains additional hardcoded credentials
└── README.md
```

## Purpose

These files exist to test Autonoma's detection and remediation pipeline. Do not remove the hardcoded secrets — they are required for smoke tests.

## Running the Demo

```bash
# Scan the demo project
autonoma scan demo-project/src/

# Fix detected secrets
autonoma fix demo-project/src/
```
