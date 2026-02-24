"""
Autonoma Community Edition - Fix Engine
Simplified local-only fix generation using Qwen.
"""
import logging
import os
import ast
from pathlib import Path
from typing import Optional, Tuple

from daemon.analysis.config_manager import ConfigManager
import re
from typing import Union, Dict, Any

logger = logging.getLogger("autonoma")


class FixEngine:
    """
    Community Edition Fix Engine.
    Deterministic fixes for SEC001/SEC002 only.
    LLM-based fixes are available in Enterprise Edition.
    """
    
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = Path(repo_path) if repo_path else None
        
        # Load config
        config_manager = ConfigManager()
        start_path = str(self.repo_path) if self.repo_path else os.getcwd()
        repo_config_path = config_manager.find_config_file(start_path)
        self.config = config_manager.load_config(repo_config_path) if repo_config_path else {}

    async def generate_fix(self, code: str, issue_or_msg: Union[str, Dict[str, Any]], model: str = None) -> Optional[str]:
        """
        Generate a fix for the given code and issue.
        Community Edition uses deterministic fixes for SEC001/SEC002.
        """
        # Parse input
        issue_id = None
        message = str(issue_or_msg)
        
        if isinstance(issue_or_msg, dict):
            issue_id = issue_or_msg.get('id')
            message = issue_or_msg.get('message', '')
            
        # Deterministic Fixes (Community Edition "Golden Path")
        # Ensure we only apply Python regex fixes to Python files
        file_path = ""
        if isinstance(issue_or_msg, dict):
            file_path = issue_or_msg.get('file', '')
            
        if issue_id in ["SEC001", "SEC002"]:
            # Delegate to SecretFixer
            try:
                from daemon.analysis.secret_fixer import SecretFixer
                fixer = SecretFixer(self.repo_path)
                
                line_idx = None
                if isinstance(issue_or_msg, dict) and 'line' in issue_or_msg:
                    line_idx = issue_or_msg['line']
                
                result = fixer.fix_secret(code, Path(file_path), issue_id, line=line_idx)
                
                if result.outcome == "SUCCESS":
                    return result.fixed_code
                elif result.outcome == "REFUSED":
                    logger.debug(f"Refused fix for {issue_id}: {result.reason} ({result.message})")
                    return code  # Return original code if refused so it doesn't crash CLI
                else:
                    logger.error(f"Failed to fix {issue_id}: {result.reason} ({result.message})")
                    return code
            except Exception as e:
                logger.error(f"Error during SecretFixer delegation for {issue_id}: {e}")
                return code

        # LLM-based fixes are Enterprise Edition only
        logger.info(f"Issue {issue_id or 'unknown'} requires LLM-based fix (Enterprise Edition). "
                     "Community Edition supports deterministic SEC001/SEC002 fixes only.")
        return None
    
    async def generate_and_verify_fix(
        self,
        code_frame: str,
        issue_description: str,
        file_path: Path,
        failing_test_name: str = None,
        model: str = None,
        timeout: float = None,
        test_file_path: Path = None,
        max_retries: int = 2
    ) -> Tuple[str, None]:
        """
        Community Edition - simplified fix without verification.
        Returns (fixed_code, None) since verification is Enterprise-only.
        """
        fixed_code = await self.generate_fix(code_frame, issue_description, model)
        
        if fixed_code and fixed_code != code_frame:
            # Validate syntax
            if self._check_syntax(fixed_code, file_path):
                return fixed_code, None
            else:
                logger.warning("Generated fix has syntax errors, returning original")
                return code_frame, None
        
        return code_frame, None
    
    def _check_syntax(self, code: str, file_path: Path) -> bool:
        """Check if code is syntactically valid Python."""
        if file_path and file_path.suffix not in ['.py', '.pyw']:
            return True  # Skip non-Python files
        
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.debug(f"Syntax error: {e}")
            return False