"""
Autonoma Community Edition - Heuristics Engine
Detects hardcoded secrets (SEC001/SEC002) only.

Uses explicit decision outcomes (SUCCESS/REFUSED/FAILED).
"""
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    from .ast_engine import ASTEngine
except ImportError:
    ASTEngine = None

try:
    from .decisions import (
        DecisionOutcome, RefusalReason, AnalysisResult
    )
except ImportError:
    # Fallback if decisions module not available
    DecisionOutcome = None
    RefusalReason = None
    AnalysisResult = None


class HeuristicsEngine:
    """
    Community Edition: Detects SEC001/SEC002 only.
    Returns explicit outcomes, not silent failures.
    """
    
    # Supported file extensions
    SUPPORTED_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx'}
    
    # Maximum file size (100KB)
    MAX_FILE_SIZE = 100 * 1024
    
    def __init__(self, repo_path: Optional[Path] = None):
        self.ast_engine = None
        if ASTEngine:
            try:
                self.ast_engine = ASTEngine()
            except Exception:
                pass

        # Community Edition: SEC001/SEC002 only
        self.patterns = [
            # SEC002: Hardcoded API Keys (Python)
            {
                "id": "SEC002",
                "pattern": r"api_key\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded API key detected.",
                "type": "security",
                "severity": "high"
            },
            # SEC002: Hardcoded API Keys (JavaScript)
            {
                "id": "SEC002",
                "pattern": r"(const|let|var)?\s*apiKey\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded API key detected (JavaScript).",
                "type": "security",
                "severity": "high"
            },
            # SEC001: Hardcoded Passwords (JavaScript)
            {
                "id": "SEC001",
                "pattern": r"(const|let|var)?\s*\w*[Pp]assword\w*\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded password detected (JavaScript).",
                "type": "security",
                "severity": "high"
            },
            # SEC001: Hardcoded Passwords (Python)
            {
                "id": "SEC001",
                "pattern": r"\w*[Pp]assword\w*\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded password detected (Python).",
                "type": "security",
                "severity": "high"
            },
            # SEC002: Hardcoded Secrets/Tokens
            {
                "id": "SEC002",
                "pattern": r"(secret|token|auth_token|api_secret)\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded secret/token detected.",
                "type": "security",
                "severity": "high"
            },
        ]

    def analyze(self, content: str, file_path: str) -> 'AnalysisResult':
        """
        Analyze file for secrets with explicit decision outcome.
        
        Returns:
            AnalysisResult with SUCCESS, REFUSED, or FAILED outcome.
        """
        # Pre-flight checks with explicit refusals
        
        # Check: Empty file
        if not content or not content.strip():
            if AnalysisResult:
                return AnalysisResult.refused(
                    RefusalReason.FILE_EMPTY,
                    "Empty file - nothing to analyze"
                )
            return {"outcome": "REFUSED", "reason": "file_empty", "issues": []}
        
        # Check: File too large
        if len(content) > self.MAX_FILE_SIZE:
            if AnalysisResult:
                return AnalysisResult.refused(
                    RefusalReason.FILE_TOO_LARGE,
                    f"File exceeds {self.MAX_FILE_SIZE} bytes limit"
                )
            return {"outcome": "REFUSED", "reason": "file_too_large", "issues": []}
        
        # Check: Supported language
        ext = Path(file_path).suffix.lower() if file_path else ""
        if ext not in self.SUPPORTED_EXTENSIONS:
            if AnalysisResult:
                return AnalysisResult.refused(
                    RefusalReason.UNSUPPORTED_LANGUAGE,
                    f"Language '{ext}' not supported. Only Python/JavaScript allowed."
                )
            return {"outcome": "REFUSED", "reason": "unsupported_language", "issues": []}
        
        # Check: Binary content
        try:
            content.encode('utf-8')
            if '\x00' in content:
                if AnalysisResult:
                    return AnalysisResult.refused(
                        RefusalReason.FILE_BINARY,
                        "Binary file detected"
                    )
                return {"outcome": "REFUSED", "reason": "file_binary", "issues": []}
        except UnicodeError:
            if AnalysisResult:
                return AnalysisResult.refused(
                    RefusalReason.FILE_BINARY,
                    "Non-UTF8 content detected"
                )
            return {"outcome": "REFUSED", "reason": "file_binary", "issues": []}
        
        # Run analysis
        issues = self._run_detection(content, file_path)
        
        if AnalysisResult:
            return AnalysisResult.success(issues)
        return {"outcome": "SUCCESS", "issues": issues}

    def run(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Legacy API - returns just the issues list.
        Use analyze() for explicit outcomes.
        """
        result = self.analyze(content, file_path)
        if hasattr(result, 'issues'):
            return result.issues
        return result.get('issues', [])

    def _run_detection(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Core detection logic with proper error handling."""
        issues = []
        
        # 1. AST Analysis (if available)
        if self.ast_engine:
            try:
                ast_issues = self.ast_engine.analyze(content, file_path)
                issues.extend(ast_issues)
            except Exception:
                pass  # AST failed, continue with regex

        # 2. Regex Pattern Matching
        try:
            lines = content.split('\n')
            
            for i, line in enumerate(lines):
                for rule in self.patterns:
                    try:
                        match = re.search(rule["pattern"], line)
                        if match:
                            # Skip if in comment
                            if self._is_in_comment(line, match.start(), file_path):
                                continue
                            
                            # Skip if already using env var
                            if self._is_already_safe(line):
                                continue
                                
                            issues.append({
                                "id": rule["id"],
                                "line": i + 1,
                                "message": rule["message"],
                                "type": rule["type"],
                                "severity": rule["severity"],
                                "source": "heuristics_regex"
                            })
                    except Exception:
                        continue
        except Exception:
            pass
        
        return issues
    
    def _is_in_comment(self, line: str, match_pos: int, file_path: str) -> bool:
        """Check if match position is inside a comment."""
        prefix = line[:match_pos]
        ext = Path(file_path).suffix.lower() if file_path else ""
        
        if ext == ".py":
            return "#" in prefix
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            return "//" in prefix
        return False
    
    def _is_already_safe(self, line: str) -> bool:
        """Check if the line already uses safe env var access."""
        safe_patterns = [
            'os.getenv', 'os.environ', 
            'process.env', 'env.',
            'getenv(', 'environ['
        ]
        return any(p in line for p in safe_patterns)

    def update_repo_path(self, repo_path: Path):
        """Update repository path (no-op in Community Edition)."""
        pass

    def close(self):
        """Cleanup resources."""
        if self.ast_engine:
            try:
                self.ast_engine.cleanup()
            except Exception:
                pass
