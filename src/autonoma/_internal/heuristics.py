"""
Autonoma — Heuristics Engine
Detects hardcoded secrets (SEC001/SEC002) only.

Uses explicit decision outcomes (SUCCESS/REFUSED/FAILED).
Patterns are language-aware: Python rules only fire on .py files,
JavaScript rules only fire on .js/.ts/.jsx/.tsx files.
"""
import re
from typing import List, Dict, Any, Optional, Set
from pathlib import Path

from .ast_engine import ASTEngine
from ..decisions import DecisionOutcome, RefusalReason, AnalysisResult
from ..audit import truncate_secret, detect_provider, generate_fingerprint


def _file_ext(file_path: str) -> str:
    """Return file extension, treating dotfiles like .env as extension '.env'."""
    p = Path(file_path)
    s = p.suffix.lower()
    if not s and p.name.startswith('.'):
        return p.name.lower()
    return s


# Default: scan all common secret-bearing file types without flags.
DEFAULT_EXTENSIONS = {
    '.py', '.env', '.yaml', '.yml', '.json', '.toml',
    '.tf', '.sh', '.config', '.ini', '.properties',
}

# All languages the engine knows how to scan (for --include-ext validation)
ALL_SUPPORTED_EXTENSIONS = {
    '.py', '.js', '.jsx', '.ts', '.tsx',
    '.env', '.yaml', '.yml', '.json', '.toml',
    '.tf', '.sh', '.config', '.ini', '.properties',
}


class HeuristicsEngine:
    """
    Detects SEC001/SEC002 only.
    Returns explicit outcomes, not silent failures.

    Patterns are tagged with the languages they apply to.
    A pattern only fires if the file extension matches.
    """

    MAX_FILE_SIZE = 100 * 1024  # 100KB

    def __init__(self, repo_path: Optional[Path] = None,
                 allowed_extensions: Optional[Set[str]] = None):
        self.allowed_extensions = allowed_extensions or DEFAULT_EXTENSIONS

        self.ast_engine = None
        try:
            self.ast_engine = ASTEngine()
        except Exception:
            pass

        # Each pattern is tagged with the set of extensions it applies to.
        self.patterns = [
            # --- Python-only patterns ---
            {
                "id": "SEC001",
                "pattern": r"(?i)['\"]?\w*(?:password|passwd|pwd)\w*['\"]?\s*[:=]\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded password detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".py"},
                "pattern_type": "password",
            },
            {
                "id": "SEC002",
                "pattern": r"(?i)['\"]?\w*(?:api_key|apikey)\w*['\"]?\s*[:=]\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded API key detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".py"},
                "pattern_type": "api_key",
            },
            {
                "id": "SEC002",
                "pattern": (
                    r"(?i)['\"]?\w*(?:secret_key|secret|token|auth_token|api_secret|"
                    r"access_key|private_key)\w*['\"]?\s*[:=]\s*['\"][^'\"]+['\"]"
                ),
                "message": "Hardcoded secret/token detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".py"},
                "pattern_type": "token",
            },
            # --- JavaScript/TypeScript-only patterns ---
            {
                "id": "SEC002",
                "pattern": r"(const|let|var)\s+apiKey\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded API key detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".js", ".jsx", ".ts", ".tsx"},
                "pattern_type": "api_key",
            },
            {
                "id": "SEC001",
                "pattern": r"(const|let|var)\s+\w*[Pp]assword\w*\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded password detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".js", ".jsx", ".ts", ".tsx"},
                "pattern_type": "password",
            },
            {
                "id": "SEC002",
                "pattern": r"(const|let|var)\s+(secret|token|authToken|apiSecret)\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded secret/token detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".js", ".jsx", ".ts", ".tsx"},
                "pattern_type": "token",
            },
            # --- .env / .config / .ini / .properties / .sh: KEY=VALUE format ---
            {
                "id": "SEC001",
                "pattern": r"(?i)(?:export\s+)?\w*(?:password|passwd|pwd)\w*\s*=\s*\S+",
                "message": "Hardcoded password detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".env", ".config", ".ini", ".properties", ".sh"},
                "pattern_type": "password",
            },
            {
                "id": "SEC002",
                "pattern": (
                    r"(?i)(?:export\s+)?\w*(?:secret|api_key|api_secret|auth_token|"
                    r"auth_key|access_key|private_key|token|stripe|sendgrid|twilio|"
                    r"mailgun|github_token|heroku|cloudinary)\w*\s*=\s*\S+"
                ),
                "message": "Hardcoded API key/secret detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".env", ".config", ".ini", ".properties", ".sh"},
                "pattern_type": "api_key",
            },
            # --- YAML / YML: key: value format ---
            {
                "id": "SEC001",
                "pattern": r"(?i)['\"]?\w*(?:password|passwd|pwd)\w*['\"]?\s*:\s+\S+",
                "message": "Hardcoded password detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".yaml", ".yml"},
                "pattern_type": "password",
            },
            {
                "id": "SEC002",
                "pattern": (
                    r"(?i)['\"]?\w*(?:api_key|secret_key|secret|auth_token|auth_key|"
                    r"access_key|private_key|token)\w*['\"]?\s*:\s+\S+"
                ),
                "message": "Hardcoded API key/secret detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".yaml", ".yml"},
                "pattern_type": "api_key",
            },
            # --- JSON: "key": "value" format ---
            {
                "id": "SEC001",
                "pattern": r'(?i)"\w*(?:password|passwd|pwd)\w*"\s*:\s*"[^"]+"',
                "message": "Hardcoded password detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".json"},
                "pattern_type": "password",
            },
            {
                "id": "SEC002",
                "pattern": (
                    r'(?i)"\w*(?:api_key|secret_key|secret|auth_token|auth_key|'
                    r'access_key|private_key|token)\w*"\s*:\s*"[^"]+"'
                ),
                "message": "Hardcoded API key/secret detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".json"},
                "pattern_type": "api_key",
            },
            # --- TOML / Terraform HCL: key = "value" format ---
            {
                "id": "SEC001",
                "pattern": r'(?i)["\']?\w*(?:password|passwd|pwd)\w*["\']?\s*=\s*["\'][^"\']+["\']',
                "message": "Hardcoded password detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".toml", ".tf"},
                "pattern_type": "password",
            },
            {
                "id": "SEC002",
                "pattern": (
                    r'(?i)["\']?\w*(?:api_key|secret_key|secret|auth_token|auth_key|'
                    r'access_key|private_key|token)\w*["\']?\s*=\s*["\'][^"\']+["\']'
                ),
                "message": "Hardcoded API key/secret detected.",
                "type": "security",
                "severity": "high",
                "extensions": {".toml", ".tf"},
                "pattern_type": "api_key",
            },
        ]

    def analyze(self, content: str, file_path: str) -> AnalysisResult:
        """Analyze file for secrets with explicit decision outcome."""
        if not content or not content.strip():
            return AnalysisResult.refused(
                RefusalReason.FILE_EMPTY,
                "Empty file - nothing to analyze"
            )

        if len(content) > self.MAX_FILE_SIZE:
            return AnalysisResult.refused(
                RefusalReason.FILE_TOO_LARGE,
                f"File exceeds {self.MAX_FILE_SIZE} bytes limit"
            )

        ext = _file_ext(file_path) if file_path else ""
        if ext not in self.allowed_extensions:
            return AnalysisResult.refused(
                RefusalReason.UNSUPPORTED_LANGUAGE,
                f"Extension '{ext}' not in allowed set {self.allowed_extensions}."
            )

        try:
            content.encode('utf-8')
            if '\x00' in content:
                return AnalysisResult.refused(
                    RefusalReason.FILE_BINARY,
                    "Binary file detected"
                )
        except UnicodeError:
            return AnalysisResult.refused(
                RefusalReason.FILE_BINARY,
                "Non-UTF8 content detected"
            )

        issues = self._run_detection(content, file_path)
        return AnalysisResult.success(issues)

    def run(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Legacy API — returns just the issues list."""
        result = self.analyze(content, file_path)
        return result.issues

    # Suffixes that indicate metadata about secrets, not actual secrets.
    _METADATA_SUFFIXES = (
        '_chars', '_characters', '_charset',
        '_min_length', '_max_length', '_length', '_len',
        '_pattern', '_regex', '_regexp', '_format',
        '_policy', '_rules', '_requirements',
        '_expiry', '_ttl', '_timeout', '_age',
        '_hash', '_algorithm', '_algo', '_method',
        '_header', '_field', '_name', '_label', '_prompt',
        '_prefix', '_suffix', '_separator',
        '_encoding', '_salt_length',
        '_file', '_path', '_dir', '_url', '_env',
        '_type', '_mode', '_level', '_version',
    )

    def _is_metadata_variable(self, var_name: str) -> bool:
        """Return True if the variable describes secret metadata, not a secret."""
        lower = var_name.lower().strip()
        return any(lower.endswith(s) for s in self._METADATA_SUFFIXES)

    def _run_detection(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Core detection logic. Only applies patterns matching the file extension."""
        issues = []
        ext = _file_ext(file_path) if file_path else ""

        # 1. AST analysis (Python only, handled internally by ASTEngine)
        if self.ast_engine and ext == ".py":
            try:
                ast_issues = self.ast_engine.analyze(content, file_path)
                issues.extend(ast_issues)
            except Exception:
                pass

        # 2. Regex — only patterns whose extension set includes this file's extension
        try:
            lines = content.split('\n')

            for i, line in enumerate(lines):
                for rule in self.patterns:
                    # Skip rules that don't apply to this extension
                    if ext not in rule.get("extensions", set()):
                        continue

                    try:
                        match = re.search(rule["pattern"], line)
                        if match:
                            if self._is_in_comment(line, match.start(), file_path):
                                continue
                            if self._is_already_safe(line):
                                continue

                            # Extract var name and strip quotes
                            matched_text = match.group(0)
                            parts = re.split(r'[:=]', matched_text, 1)
                            var_part = parts[0].strip()
                            if len(var_part) >= 2 and var_part[0] in ("'", '"') and var_part[-1] == var_part[0]:
                                var_part = var_part[1:-1]
                            
                            # Extract the raw secret value and strip quotes
                            secret_val_part = parts[1].strip() if len(parts) > 1 else ""
                            if len(secret_val_part) >= 2 and secret_val_part[0] in ("'", '"') and secret_val_part[-1] == secret_val_part[0]:
                                secret_val_part = secret_val_part[1:-1]
                                
                            # Strip leading keywords (JS: const/let/var, shell: export)
                            for kw in ("const ", "let ", "var ", "export ", "EXPORT "):
                                if var_part.startswith(kw):
                                    var_part = var_part[len(kw):].strip()
                                    break
                            if self._is_metadata_variable(var_part):
                                continue

                            issues.append({
                                "id": rule["id"],
                                "line": i + 1,
                                "col_offset": match.start(),
                                "end_col_offset": match.end(),
                                "message": rule["message"],
                                "type": rule["type"],
                                "severity": rule["severity"],
                                "source": "heuristics_regex",
                                "pattern_type": rule.get("pattern_type", "unknown"),
                                "var_name": var_part,
                                "truncated_secret": truncate_secret(secret_val_part),
                                "provider": detect_provider(secret_val_part),
                                "fingerprint": generate_fingerprint(secret_val_part),
                            })
                    except Exception:
                        continue
        except Exception:
            pass

        # Deduplicate: AST and regex can both fire on the same line.
        # Prefer AST-sourced findings (more accurate) over regex for the same (line, id).
        seen: dict = {}
        for issue in issues:
            key = (issue["line"], issue["id"])
            if key not in seen or issue.get("source", "").startswith("ast"):
                seen[key] = issue
        return list(seen.values())

    def _is_in_comment(self, line: str, match_pos: int, file_path: str) -> bool:
        """Check if match position is inside a comment."""
        prefix = line[:match_pos]
        ext = _file_ext(file_path) if file_path else ""

        if ext in {".py", ".yaml", ".yml", ".env", ".sh", ".config", ".ini", ".properties", ".toml"}:
            return "#" in prefix
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            return "//" in prefix
        elif ext == ".tf":
            return "#" in prefix or "//" in prefix
        return False

    def _is_already_safe(self, line: str) -> bool:
        """Check if the line already uses safe env var access."""
        safe_patterns = [
            'os.getenv', 'os.environ',
            'process.env', 'env.',
            'getenv(', 'environ['
        ]
        return any(p in line for p in safe_patterns)

    def close(self):
        """Cleanup resources."""
        if self.ast_engine:
            try:
                self.ast_engine.cleanup()
            except Exception:
                pass
