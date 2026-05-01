# Changelog

## 0.1.7

Unblocks real-world adoption with broader file-type coverage and a better fix UX.

### Added
- **Multi-format scanning**: `.env`, `.yaml`, `.yml`, `.json`, `.toml`, `.tf`, `.sh`, `.config`, `.ini`, `.properties` are now scanned by default — no flags required.
- **Dry-run diff output**: `autonoma fix --dry-run` now always shows a colored unified diff of proposed changes. Non-Python files get a text-replacement preview using `${ENV_VAR_NAME}` syntax.
- **`suggested_env_var` on refused findings**: Every refused finding now reports the suggested environment variable name and the exact line to add to `.env.example`.

### Changed
- **SEC002 policy relaxed for preview**: `SEC002` findings now qualify for `preview_only` in `--dry-run` mode even without an `.env.example`. Auto-apply still requires the env contract. No finding shows `policy_block` in dry-run mode.
- **Env contract optional for preview**: Missing `.env.example` no longer silently blocks the dry-run output. The tool shows the fix and tells the user exactly what to add to unblock auto-apply.

---

## 0.1.5

Documentation updates and parser reliability fixes.

### Added
- **README Refinements**: Added "When NOT to use Autonoma" section to set strict technical boundaries.
- **CI Lifecycle Behavior**: Documented idempotent behavior and exit code semantics for CI pipelines.
- **Visual Demo**: Integrated Animation.gif into documentation root to demonstrate behavior visually.

### Changed
- **Test Secrets**: Obfuscated remediation targets to avoid triggering GitHub repository push protection rules (GH013).
- **Documentation**: Removed duplicate safety explanations from README.md.

### Fixed
- **Heuristics Parser**: Defaulting to `None` instead of empty strings when parsing secret values to prevent false matches.

---

## 0.1.4

Release featuring pre-commit integration and safe remediation enhancements.

### Added
- **Pre-commit hook integration**: Native support for pre-commit via `hooks.yaml`.
- **Audit logic hardening**: Improved detection for instance and class attributes in AST.

### Changed
- **Refusal-first model**: Made the policy of refusing ambiguous rewrites the documented default, not an option.
- **CLI Exit Codes**: Standardized exit code `1` for all findings (removed `--fail-on-findings`).
- **Heuristics**: Updated patterns for modern secret formats (e.g., Stripe `sk_live_...`).

### Removed
- **`--open-pr`**: Removed legacy pull request automation to focus on core CLI reliability.
- **Comments**: Removed AI-generated narrative comments from source files.

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
