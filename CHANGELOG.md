# Changelog

## 0.1.5

Documentation overhaul and parser robustness improvements.

### Added
- **README Refinements**: Added "When NOT to use Autonoma" section to set strict technical boundaries.
- **CI Lifecycle Behavior**: Expanded documentation to articulate the idempotent execution model across CI iterations.
- **Visual Demo**: Integrated Animation.gif into documentation root to demonstrate behavior visually.

### Changed
- **Test Secrets**: Obfuscated remediation targets to avoid triggering GitHub repository push protection rules (GH013).
- **Documentation**: Aggressively streamlined README.md for engineering audiences by cutting duplicate safety assertions.

### Fixed
- **Heuristics Parser**: Defaulting to `None` instead of empty strings when parsing secret values to prevent false matches.

---

## 0.1.4

Release featuring pre-commit integration and safe remediation enhancements.

### Added
- **Pre-commit hook integration**: Native support for pre-commit via `hooks.yaml`.
- **Audit logic hardening**: Improved detection for instance and class attributes in AST.

### Changed
- **Safety First Guarantee**: Elevated "provably safe" remediation policy to core project identity.
- **CLI Exit Codes**: Standardized exit code `1` for all findings (removed `--fail-on-findings`).
- **Heuristics**: Updated patterns for modern secret formats (e.g., Stripe `sk_live_...`).

### Removed
- **`--open-pr`**: Removed legacy pull request automation to focus on core CLI reliability.
- **AI-narrative comments**: Cleaned up codebase for a more professional, artisanal developer voice.

---

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
