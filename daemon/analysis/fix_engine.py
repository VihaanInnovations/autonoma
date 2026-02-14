"""
Autonoma Community Edition - Fix Engine
Simplified local-only fix generation using Qwen.
"""
import logging
import os
import ast
from pathlib import Path
from typing import Optional, Tuple

# Imports moved to lazy load (generate_fix)
# from daemon.core.brain.summarizer import Summarizer
# from daemon.core.brain.local_brain_planning import LocalBrainPlanning
# from daemon.core.brain.qwen_executor import QwenExecutor
from daemon.analysis.config_manager import ConfigManager
import re
from typing import Union, Dict, Any

logger = logging.getLogger("autonoma")


class FixEngine:
    """
    Community Edition Fix Engine.
    Uses local LLM only (no cloud APIs).
    """
    
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = Path(repo_path) if repo_path else None
        
        # Load config
        config_manager = ConfigManager()
        start_path = str(self.repo_path) if self.repo_path else os.getcwd()
        repo_config_path = config_manager.find_config_file(start_path)
        self.config = config_manager.load_config(repo_config_path) if repo_config_path else {}
        
        # Initialize local brain components only
        # Lazy init moved to generate_fix
        # self.summarizer = Summarizer()
        # self.local_brain = LocalBrainPlanning()
        # self.executor = QwenExecutor(model=self.config.get("local_model", "qwen2.5-coder:3b"))

    async def generate_fix(self, code: str, issue_or_msg: Union[str, Dict[str, Any]], model: str = None) -> Tuple[Optional[str], str]:
        """
        Generate a fix for the given code and issue.
        Returns: (fixed_code, status_message)
        Community Edition uses deterministic fixes for SEC001/SEC002,
        and local LLM for others.
        """
        # Parse input
        issue_id = None
        message = str(issue_or_msg)
        
        if isinstance(issue_or_msg, dict):
            issue_id = issue_or_msg.get('id')
            message = issue_or_msg.get('message', '')
            file_path = issue_or_msg.get('file', '')
            
            # Normalize issue ID
            issue_id = self._normalize_issue_id(issue_id)
            
            # STRICT REFUSAL: If issue implies no auto-fix, REFUSE immediately.
            # This covers SEC003/SEC004/SEC005 from Community Edition 
            # and any SECK* in sensitive files.
            can_autofix = issue_or_msg.get('can_autofix', True)
            if can_autofix is False:
                 logger.info(f"Refusing to fix {issue_id}: Explicitly marked as non-autofixable")
                 return None, f"REFUSED: {issue_id} Community Edition does not auto-fix complex security issues"

            if issue_id and issue_id.startswith("SECK"):
                from daemon.analysis.secret_fixer import SecretFixer
                
                fixer = SecretFixer(self.repo_path)
                # Convert string path to Path object if needed
                path_obj = Path(file_path) if file_path else None
                
                result = fixer.fix_secret(code, path_obj, issue_id)
                
                if result.outcome == "SUCCESS":
                    logger.info(f"Secret fixed: {result.message}")
                    return result.fixed_code, f"Fixed: {result.message}"
                elif result.outcome == "SKIPPED":
                    logger.info(f"Secret fix skipped: {result.message}")
                    return None, result.message
                else:
                    logger.info(f"Secret fix refused/failed: {result.outcome} - {result.message}")
                    return None, f"Refused: {result.message} ({result.reason})"

        # Local LLM Fallback (for other issues)
        try:
            # Lazy load LLM components
            if not hasattr(self, 'executor'):
                from daemon.core.brain.summarizer import Summarizer
                from daemon.core.brain.local_brain_planning import LocalBrainPlanning
                from daemon.core.brain.qwen_executor import QwenExecutor
                
                self.summarizer = Summarizer()
                self.local_brain = LocalBrainPlanning()
                self.executor = QwenExecutor(model=self.config.get("local_model", "qwen2.5-coder:3b"))
            # Prepare context
            context_files = [{
                "path": "target.py",
                "content": code,
                "type": "source"
            }]
            
            summary = self.summarizer.summarize_request(
                task_id="fix",
                goal=f"Fix this issue: {message}",
                files=context_files
            )
            
            # Get plan from local brain
            plan = await self.local_brain.plan(summary)
            if not plan:
                logger.warning("Local brain returned no plan")
                return None, "Local brain returned no plan"
            
            # Execute plan
            file_map = self.summarizer.get_file_map()
            result = await self.executor.execute(plan, file_map)
            
            if result:
                 # result.get("fixed_code") ??
                 # The original code used result.get("fixed_code", code)
                 # Wait, execute returns a dict?
                 # Step 417 line 109: result = await self.executor.execute(plan, file_map)
                 # line 112: return result.get("fixed_code", code)
                 
                 fixed = result.get("fixed_code", code)
                 return fixed, "Fixed via Local LLM"
                 
            return code, "Local LLM returned no result"
            
        except ImportError:
            logger.warning("Local brain components missing. Skipping fix.")
            return None, "Local brain components missing"
        except Exception as e:
            logger.error(f"Fix generation failed: {e}")
            return None, f"Fix generation failed: {e}"
    
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
        fixed_code, msg = await self.generate_fix(code_frame, issue_description, model)
        
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

    def _normalize_issue_id(self, issue_id: str) -> str:
        """Normalize legacy SEC issues to SECK (only SEC001/SEC002)."""
        if not issue_id:
            return issue_id
        # Only normalize specific secret IDs, leave SEC003 (SQLi) etc alone
        if issue_id in ["SEC001", "SEC002"]:
            return issue_id.replace("SEC", "SECK")
        return issue_id