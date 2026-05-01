"""
Autonoma Community Edition - Secret Fixer

Applies deterministic fixes for SEC001/SEC002.
Uses explicit refusal semantics.
"""
import re
import logging
import os
from pathlib import Path
from typing import Tuple, Optional
from dataclasses import dataclass

try:
    from .decisions import (
        DecisionOutcome, RefusalReason, FixResult
    )
except ImportError:
    DecisionOutcome = None
    RefusalReason = None
    FixResult = None

logger = logging.getLogger(__name__)


@dataclass
class SecretFixResult:
    """Result of attempting to fix a hardcoded secret."""
    outcome: str  # "SUCCESS", "REFUSED", "FAILED"
    fixed_code: Optional[str] = None
    reason: Optional[str] = None
    message: Optional[str] = None
    env_var_name: Optional[str] = None


class SecretFixer:
    """
    Community Edition: Fixes SEC001/SEC002 only.
    
    Refusal conditions:
    - No env var contract detectable (no .env file, no config pattern)
    - Variable name is ambiguous
    - File type not supported
    - Would break syntax
    """
    
    # Env var naming patterns we recognize
    ENV_VAR_PATTERNS = {
        'password': 'PASSWORD',
        'passwd': 'PASSWORD', 
        'pwd': 'PASSWORD',
        'api_key': 'API_KEY',
        'apikey': 'API_KEY',
        'api_secret': 'API_SECRET',
        'secret': 'SECRET',
        'token': 'TOKEN',
        'auth_token': 'AUTH_TOKEN',
        'auth_key': 'AUTH_KEY',
        'access_key': 'ACCESS_KEY',
        'secret_key': 'SECRET_KEY',
    }
    
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path
        self._env_contract_checked = False
        self._has_env_contract = None
    
    def check_env_contract(self) -> bool:
        """
        Check if the repo has evidence of env var usage.
        
        Evidence includes:
        - .env file exists
        - .env.example file exists
        - requirements.txt has python-dotenv
        - package.json has dotenv
        - Code imports os.getenv / process.env
        """
        if self._env_contract_checked:
            return self._has_env_contract
        
        self._env_contract_checked = True
        self._has_env_contract = False
        
        if not self.repo_path or not self.repo_path.exists():
            # Can't check, assume no contract - will refuse
            return False
        
        try:
            # Check for .env files
            env_files = ['.env', '.env.example', '.env.sample', '.env.local']
            for env_file in env_files:
                if (self.repo_path / env_file).exists():
                    self._has_env_contract = True
                    logger.debug(f"Env contract found: {env_file}")
                    return True
            
            # Check for python-dotenv in requirements
            req_file = self.repo_path / 'requirements.txt'
            if req_file.exists():
                content = req_file.read_text(encoding='utf-8', errors='ignore')
                if 'python-dotenv' in content or 'dotenv' in content:
                    self._has_env_contract = True
                    logger.debug("Env contract found: python-dotenv in requirements.txt")
                    return True
            
            # Check for dotenv in package.json
            pkg_file = self.repo_path / 'package.json'
            if pkg_file.exists():
                content = pkg_file.read_text(encoding='utf-8', errors='ignore')
                if 'dotenv' in content:
                    self._has_env_contract = True
                    logger.debug("Env contract found: dotenv in package.json")
                    return True
            
            # Check for env var usage in the code (os.getenv, process.env, etc.)
            for root, _, files in os.walk(self.repo_path):
                # Skip common directories
                if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', 'venv', '.venv']):
                    continue
                    
                for file in files:
                    if file.endswith(('.py', '.js', '.ts', '.jsx', '.tsx')):
                        try:
                            file_path = Path(root) / file
                            # Only scan small files or first 100 lines to keep it fast
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                head = "".join([f.readline() for _ in range(100)])
                                if 'os.getenv' in head or 'process.env' in head or 'os.environ' in head:
                                    self._has_env_contract = True
                                    logger.debug(f"Env contract found: usage in {file}")
                                    return True
                        except Exception:
                            continue
                    
        except Exception as e:
            logger.debug(f"Error checking env contract: {e}")
        
        return False
    
    def fix_secret(self, code: str, file_path: Path, 
                   issue_id: str, line: int = None) -> SecretFixResult:
        """
        Attempt to fix a hardcoded secret.
        
        Returns explicit outcome: SUCCESS, REFUSED, or FAILED.
        """
        # Pre-flight checks
        
        # Check 1: Is fix type supported?
        if issue_id not in ["SEC001", "SEC002"]:
            return SecretFixResult(
                outcome="REFUSED",
                reason="issue_type_not_supported",
                message=f"Issue type '{issue_id}' not supported in Community Edition"
            )
        
        # Check 2: Is file type supported?
        if not file_path:
            return SecretFixResult(
                outcome="REFUSED",
                reason="unsupported_language",
                message="No file path provided"
            )
        
        ext = file_path.suffix.lower()
        if ext not in {'.py', '.js', '.ts', '.jsx', '.tsx'}:
            return SecretFixResult(
                outcome="REFUSED",
                reason="unsupported_language",
                message=f"Language '{ext}' not supported"
            )
        
        # Check 3: Is there an env var contract?
        # This is the KEY check that prevents "shifting the problem"
        if not self.check_env_contract():
            return SecretFixResult(
                outcome="REFUSED",
                reason="env_var_contract_not_found",
                message="No .env file or dotenv dependency found. "
                        "Create a .env.example file first to establish env var contract."
            )
        
        # Apply the fix
        try:
            if issue_id == "SEC001":
                return self._fix_password(code, file_path, target_line_idx=line)
            elif issue_id == "SEC002":
                return self._fix_api_key(code, file_path, target_line_idx=line)
        except Exception as e:
            return SecretFixResult(
                outcome="FAILED",
                reason="unexpected_error",
                message=str(e)
            )
        
        return SecretFixResult(
            outcome="REFUSED",
            reason="no_fix_applied",
            message="No matching patterns found"
        )
    
    def _fix_password(self, code: str, file_path: Path, target_line_idx: Optional[int] = None) -> SecretFixResult:
        """Fix SEC001: Hardcoded password."""
        modified_code = code
        env_var_name = None
        
        if file_path.suffix == ".py":
            # Pattern supports self/cls prefixes for attribute assignments
            pattern = r"((?:self\.|cls\.)?\w*[Pp]assword\w*)(\s*:\s*[^=\n]+)?\s*(=)\s*['\"]([^'\"]+)['\"]"
            
            match = re.search(pattern, code)
            if not match:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="secret_pattern_ambiguous",
                    message="Could not locate password pattern to fix"
                )
            
            full_var_name = match.group(1)
            # Get base variable name (e.g., self.admin_password -> admin_password)
            var_name = full_var_name.split('.')[-1]
            env_var_name = self._get_env_var_name(var_name.lower())
            
            if not env_var_name:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="env_var_name_ambiguous",
                    message=f"Cannot determine safe env var name for '{var_name}'"
                )
            
            # Ensure import os
            if "import os" not in code:
                lines = modified_code.splitlines()
                lines.insert(0, "import os")
                modified_code = "\n".join(lines)
            
            # Apply fix
            def replacer(m):
                vn = m.group(1)
                th = m.group(2) if m.group(2) else ""
                op = m.group(3)
                return f"{vn}{th} {op} os.getenv('{env_var_name}')"
            
            modified_code = re.sub(pattern, replacer, modified_code)
            
        elif file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}:
            # Pattern supports this prefix for property assignments
            pattern = r"(?m)(^\s*)(const|let|var)?\s*((?:this\.)?\w*[Pp]assword\w*)\s*=\s*['\"]([^'\"]+)['\"]"
            
            match = re.search(pattern, code)
            if not match:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="secret_pattern_ambiguous",
                    message="Could not locate password pattern to fix"
                )
            
            full_var_name = match.group(3)
            var_name = full_var_name.split('.')[-1]
            env_var_name = self._get_env_var_name(var_name.lower())
            
            if not env_var_name:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="env_var_name_ambiguous",
                    message=f"Cannot determine safe env var name for '{var_name}'"
                )
            
            def replacer_js(m):
                indent = m.group(1)
                decl = m.group(2) or ""
                vn = m.group(3)
                decl_str = f"{decl} " if decl else ""
                return f"{indent}{decl_str}{vn} = process.env.{env_var_name}"
            
            modified_code = re.sub(pattern, replacer_js, modified_code)
        
        if modified_code != code:
            return SecretFixResult(
                outcome="SUCCESS",
                fixed_code=modified_code,
                env_var_name=env_var_name,
                message=f"Replaced hardcoded password with env var '{env_var_name}'"
            )
        
        return SecretFixResult(
            outcome="REFUSED",
            reason="no_fix_applied",
            message="Pattern matched but no changes made"
        )
    
    def _fix_api_key(self, code: str, file_path: Path, target_line_idx: Optional[int] = None) -> SecretFixResult:
        """Fix SEC002: Hardcoded API key."""
        modified_code = code
        env_var_name = None
        
        lines = code.splitlines()
        
        # If line is provided, restrict to that line
        process_lines = [(target_line_idx - 1, lines[target_line_idx - 1])] if target_line_idx and target_line_idx <= len(lines) else enumerate(lines)
        
        changes_made = False
        
        for idx, line in process_lines:
            # Check if this line already uses env var access to prevent duplication / crash loops
            if any(safe_p in line for safe_p in ['os.getenv', 'process.env']):
                continue
                
            if file_path.suffix == ".py":
                # Match variable assignment (includes self/cls)
                pattern1 = r"(?m)(^\s*)((?:self\.|cls\.)?\w*key\w*|(?:self\.|cls\.)?\w*token\w*|(?:self\.|cls\.)?\w*secret\w*)\s*=\s*['\"]([^'\"]{10,})['\"]"
                match1 = re.search(pattern1, line, re.IGNORECASE)
                
                # Match 2: os.environ assignment (e.g. os.environ["API_KEY"] = "secret")
                pattern2 = r"(?m)(^\s*)os\.environ\[['\"]([^'\"]+)['\"]\]\s*=\s*['\"]([^'\"]{10,})['\"]"
                match2 = re.search(pattern2, line)
                
                if match1:
                    indent, full_var_name, _ = match1.group(1), match1.group(2), match1.group(3)
                    var_name = full_var_name.split('.')[-1]
                    env_var_name = self._get_env_var_name(var_name.lower())
                    if env_var_name:
                        new_line = line.replace(match1.group(0), f"{indent}{full_var_name} = os.getenv('{env_var_name}')")
                        lines[idx] = new_line
                        changes_made = True
                
                elif match2:
                    indent, key_name, _ = match2.group(1), match2.group(2), match2.group(3)
                    env_var_name = key_name.upper()
                    new_line = line.replace(match2.group(0), f"{indent}os.environ['{key_name}'] = os.getenv('{env_var_name}')")
                    lines[idx] = new_line
                    changes_made = True
                
            elif file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}:
                # Match variable assignment (includes this)
                pattern = r"(?m)(^\s*)(const|let|var)?\s*((?:this\.)?\w*key\w*|(?:this\.)?\w*token\w*|(?:this\.)?\w*secret\w*)\s*=\s*['\"]([^'\"]{10,})['\"]"
                match = re.search(pattern, line, re.IGNORECASE)
                
                if match:
                    indent = match.group(1)
                    decl = match.group(2) or ""
                    full_var_name = match.group(3)
                    decl_str = f"{decl} " if decl else ""
                    
                    var_name = full_var_name.split('.')[-1]
                    env_var_name = re.sub(r'(?<!^)(?=[A-Z])', '_', var_name).upper()
                    if env_var_name:
                        new_line = line.replace(match.group(0), f"{indent}{decl_str}{full_var_name} = process.env.{env_var_name}")
                        lines[idx] = new_line
                        changes_made = True

        if not changes_made:
            if target_line_idx and target_line_idx <= len(lines):
                 if any(safe_p in lines[target_line_idx - 1] for safe_p in ['os.getenv', 'process.env']):
                     return SecretFixResult(
                         outcome="REFUSED",
                         reason="already_fixed",
                         message=f"Line {target_line_idx} already uses environment variable lookup"
                     )
            return SecretFixResult(
                outcome="REFUSED",
                reason="secret_pattern_ambiguous",
                message="Could not locate API key pattern to fix or determine safe env var name"
            )

        # Ensure import os if needed
        if file_path.suffix == ".py" and changes_made:
            has_import = any("import os" in l for l in lines)
            if not has_import:
                lines.insert(0, "import os")
                
        modified_code = "\n".join(lines)
        
        return SecretFixResult(
            outcome="SUCCESS",
            fixed_code=modified_code,
            env_var_name=env_var_name or "UNKNOWN",
            message=f"Replaced hardcoded key with env var '{env_var_name or 'UNKNOWN'}'"
        )
    
    def _get_env_var_name(self, var_name: str) -> Optional[str]:
        """
        Determine the appropriate env var name.
        Returns None if we can't confidently name it.
        """
        var_lower = var_name.lower().replace('-', '_')

        # If it's a specific, clear identifier (more than 6 chars), use it directly.
        # This preserves full context e.g. openai_api_key → OPENAI_API_KEY
        # Short names (e.g. "key", "pwd") fall through to pattern matching below.
        if re.match(r'^[a-z][a-z0-9_]*$', var_lower) and len(var_lower) > 6:
            return var_lower.upper()

        # Fall back to generic pattern matching for short/ambiguous names
        for pattern, env_name in self.ENV_VAR_PATTERNS.items():
            if pattern in var_lower:
                return env_name

        return None
