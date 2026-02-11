"""
Autonoma Community Edition - AST Engine
Detects hardcoded secrets (SEC001/SEC002) using native Python AST.
"""
import hashlib
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ASTEngine:
    """AST-based security analyzer for hardcoded secrets detection."""
    
    def __init__(self):
        # Community Edition uses native Python AST only
        self.parser = None
        logger.debug("ASTEngine initialized (native Python AST mode)")

    def cleanup(self):
        """Cleanup resources."""
        pass

    def compute_semantic_hash(self, content: str) -> str:
        """Compute hash of content for caching."""
        try:
            return hashlib.sha256(content.encode('utf-8')).hexdigest()
        except Exception:
            return ""

    def analyze(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        """
        Analyze source code for hardcoded secrets.
        Community Edition: Only SEC001 (passwords) and SEC002 (API keys).
        """
        issues = []
        
        # Only support Python files for AST analysis
        if not file_path.endswith('.py'):
            return issues
        
        try:
            issues = self._analyze_python_native(content)
        except Exception as e:
            logger.debug(f"AST analysis failed: {e}")
        
        return issues

    def _analyze_python_native(self, content: str) -> List[Dict[str, Any]]:
        """
        Native Python AST analysis for hardcoded secrets.
        Robust fallback that doesn't crash on edge cases.
        """
        import ast
        issues = []
        
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []  # Graceful return on syntax errors
        except Exception:
            return []

        try:
            for node in ast.walk(tree):
                # Detect hardcoded secrets in assignments
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            var_name = target.id.lower()
                            
                            # Secret keywords for SEC001/SEC002
                            secret_keywords = [
                                'password', 'passwd', 'pwd',  # SEC001
                                'api_key', 'apikey', 'secret', 'token', 
                                'auth_token', 'auth', 'credential', 'key'  # SEC002
                            ]
                            
                            if any(k in var_name for k in secret_keywords):
                                # Check if value is a string literal
                                if isinstance(node.value, (ast.Constant, ast.Str)):
                                    try:
                                        val = node.value.s if isinstance(node.value, ast.Str) else node.value.value
                                    except AttributeError:
                                        val = getattr(node.value, 'value', None)
                                    
                                    if isinstance(val, str) and len(val) > 0:
                                        # Skip if it's already an env lookup
                                        if 'os.getenv' in val or 'os.environ' in val:
                                            continue
                                        
                                        # Determine issue type
                                        is_password = any(k in var_name for k in ['password', 'passwd', 'pwd'])
                                        issue_id = "SEC001" if is_password else "SEC002"
                                        
                                        issues.append({
                                            "id": issue_id,
                                            "line": node.lineno,
                                            "message": f"Hardcoded {'password' if is_password else 'secret'} '{target.id}' detected.",
                                            "type": "security",
                                            "severity": "high",
                                            "source": "ast_engine_native"
                                        })
        except Exception as e:
            logger.debug(f"AST walk failed: {e}")
        
        return issues
