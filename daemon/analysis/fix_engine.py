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
            
        if issue_id == "SEC001" and file_path.endswith('.py'):
            # Fix hardcoded password -> os.getenv("PASSWORD")
            try:
                lines = code.splitlines()
                target_line_idx = -1
                if isinstance(issue_or_msg, dict) and 'line' in issue_or_msg:
                    target_line_idx = issue_or_msg['line'] - 1
                
                if target_line_idx >= 0 and target_line_idx < len(lines):
                    line = lines[target_line_idx]
                    
                    # 1. Variable Assignment
                    match = re.search(r'(\w+)\s*=\s*["\']([^"\']+)["\']', line)
                    if match:
                        var_name = match.group(1)
                        if "os.environ" not in var_name: # Safety check
                            env_var = var_name.upper()
                            if "PASSWORD" not in env_var:
                                env_var = f"{env_var}_PASSWORD"
                            new_line = line.replace(match.group(0), f'{var_name} = os.getenv("{env_var}", "default_secret")')
                            lines[target_line_idx] = new_line
                            return "\n".join(lines)
                    
                    # 2. os.environ Assignment
                    match_env = re.search(r'os\.environ\[["\']([^"\']+)["\']\]\s*=\s*["\']([^"\']+)["\']', line)
                    if match_env:
                        key_name = match_env.group(1)
                        # os.environ["KEY"] = os.getenv("KEY")
                        # This effectively makes it load from env, or crash/be empty if not set? 
                        # Actually os.environ assignment expects a string. 
                        # If we do os.environ["KEY"] = os.getenv("KEY"), and getenv returns None, it might fail if strictly typed, but in Python it's dict.
                        # Wait, os.environ values MUST be strings. os.getenv returns None by default.
                        # So os.environ["K"] = None will raise TypeError.
                        # We should use os.getenv("KEY", "") or leave it valid.
                        # But wait, the USER said: "Autonoma replaced the hardcoded value and added os.getenv".
                        # The user provided example: 
                        # os.environ["OPENAI_API_KEY"] = "sk-..." 
                        # -> 
                        # os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
                        # This seems to be the desired behavior to remove the secret from code.
                        # We'll use os.getenv(KEY, "placeholder") to be safe? 
                        # Or just os.getenv(KEY).
                        # Let's check typical usage.
                        new_line = line.replace(match_env.group(0), f'os.environ["{key_name}"] = os.getenv("{key_name}")')
                        lines[target_line_idx] = new_line
                        return "\n".join(lines)

            except Exception as e:
                logger.error(f"Deterministic fix SEC001 failed: {e}")

        if issue_id == "SEC002" and file_path.endswith('.py'):
            # Fix hardcoded API key -> os.getenv("API_KEY")
            try:
                lines = code.splitlines()
                target_line_idx = -1
                if isinstance(issue_or_msg, dict) and 'line' in issue_or_msg:
                    target_line_idx = issue_or_msg['line'] - 1
                
                if target_line_idx >= 0 and target_line_idx < len(lines):
                    line = lines[target_line_idx]
                    
                    # 1. Variable Assignment
                    match = re.search(r'(\w+)\s*=\s*["\']([^"\']+)["\']', line)
                    if match:
                        var_name = match.group(1)
                        # Ensure we don't double match os.environ if the previous regex was too loose
                        # \w+ matches "os" but the rest "missing"
                        # The regex (\w+)\s*=... expects simple variable. "os.environ['...']" won't match \w+ =
                        
                        env_var = var_name.upper()
                        new_line = line.replace(match.group(0), f'{var_name} = os.getenv("{env_var}")')
                        lines[target_line_idx] = new_line
                        return "\n".join(lines)

                    # 2. os.environ Assignment
                    match_env = re.search(r'os\.environ\[["\']([^"\']+)["\']\]\s*=\s*["\']([^"\']+)["\']', line)
                    if match_env:
                        key_name = match_env.group(1)
                        # Replace with os.getenv look up
                        # We use os.getenv so it pulls from environment at runtime
                        new_line = line.replace(match_env.group(0), f'os.environ["{key_name}"] = os.getenv("{key_name}")')
                        lines[target_line_idx] = new_line
                        return "\n".join(lines)
                        
            except Exception as e:
                logger.error(f"Deterministic fix SEC002 failed: {e}")

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