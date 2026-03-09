# Changelog

## 0.1.0

Initial public release of the `autonoma-cli` package (Autonoma Community Edition).

### Added
- AST-based deterministic detection for:
  - `SEC001` hardcoded passwords
  - `SEC002` hardcoded API keys / secrets
  - `SEC003` high-risk SQL string construction
  - `SEC004` Python SSTI patterns
  - `SEC005` insecure deserialization patterns
- Automatic remediation for safe `SEC001` and `SEC002` cases via `--auto-fix`
- Refusal-first safety model for ambiguous or unsafe rewrites
- Git history scanning via `history-scan`
- CI-oriented exit codes via `--ci`
- Unified machine-readable JSON output via `--json`
- Unified diff preview via `--diff`
- `.autonomaignore` support
- Minimal-output mode via `--quiet`
- Multithreaded scanning via `--threads`

### Safety
- Auto-fix now emits fail-fast `os.environ["VAR"]` access for fixed secrets
- Unsafe and ambiguous rewrites are refused with reason codes
- Dry-run and diff preview do not modify files

### Notes
- Community Edition automatically fixes only safe `SEC001` and `SEC002` cases
- `SEC003`–`SEC005` are detection-only in this release
