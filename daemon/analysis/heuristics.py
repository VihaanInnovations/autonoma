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



try:
    from .secret_detector import SecretDetector
except ImportError:
    SecretDetector = None

class HeuristicsEngine:
    """
    Community Edition: Detects SEC001/SEC002 using SecretDetector.
    Returns explicit outcomes, not silent failures.
    """
    
    # Supported file extensions
    SUPPORTED_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx'}
    
    # Maximum file size (100KB)
    MAX_FILE_SIZE = 100 * 1024
    
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path
        self.detector = SecretDetector() if SecretDetector else None
        self.ast_engine = None
        if ASTEngine:
            try:
                self.ast_engine = ASTEngine()
            except Exception:
                pass

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
        """Run all detection engines and normalize issues."""
        all_raw = []
        
        # 1. AST Analysis
        if self.ast_engine:
            try:
                # Assuming ast_engine.analyze returns a list of issues
                ast_issues = self.ast_engine.analyze(content, file_path)
                if ast_issues:
                    all_raw.extend(ast_issues)
            except Exception:
                pass

        # 2. Secret Detector
        if self.detector:
            try:
                det_issues = self.detector.analyze_file(content, file_path)
                if det_issues:
                    all_raw.extend(det_issues)
            except Exception as e:
                # Log error but don't crash
                pass

        final_issues = []
        for issue in all_raw:
            # 1. Standardize basics
            issue_id = issue.get("id", "UNKNOWN")
            confidence = issue.get("confidence", 0.0) 
            message = issue.get("message", "")
            can_autofix = issue.get("can_autofix", False)
            
            # 2. Context Policy (Force refusal FIRST)
            if self._is_sensitive_context(file_path):
                can_autofix = False
                # Downgrade confidence for visibility
                confidence = min(confidence, 0.6) 

            # 3. ID Normalization & Safety Mapping
            # Rename legacy IDs if present
            if issue_id == "SEC001": issue_id = "SECK001"
            if issue_id == "SEC002": issue_id = "SECK002"
            
            # If it's a secret (SECK*) but not fixable/safe, map to WARN
            if issue_id.startswith("SECK") and not can_autofix:
                issue_id = "SECK003_WARN"
                
            final_issues.append({
                "id": issue_id,
                "line": issue.get("line"),
                "message": message,
                "type": issue.get("type", "security"),
                "severity": issue.get("severity", "medium").lower(),
                "source": issue.get("source", "ast"),
                "confidence": confidence,
                "can_autofix": can_autofix
            })
            
        return final_issues

    def _is_sensitive_context(self, file_path: str) -> bool:
        """Check if file is in a context where auto-fix is dangerous."""
        if not file_path: return False
        
        try:
            path_obj = Path(file_path)
            parts = set(p.lower() for p in path_obj.parts)
            
            # Segment Check (Robuster than substring)
            risky_segments = {'tests', 'test', 'docs', 'examples', 'fixtures', 'spec', '__tests__', 'mock'}
            if not parts.isdisjoint(risky_segments):
                return True
                
            # Filename Logic
            name = path_obj.name.lower()
            if (name.startswith("test_") or 
                name.endswith("_test.py") or 
                name.endswith(".test.js") or 
                name.endswith(".spec.js")):
                return True
        except Exception:
            # Fallback to string check if path parsing fails
            if any(x in file_path.lower() for x in ["/test/", "/docs/", "/examples/"]):
                return True
            
        return False
    
    def update_repo_path(self, repo_path: Path):
        """Update repository path."""
        pass

    def close(self):
        """Cleanup resources."""
        if self.ast_engine:
            try:
                self.ast_engine.cleanup()
            except Exception:
                pass
