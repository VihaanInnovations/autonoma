"""
Autonoma Community Edition - Secret Fixer

Applies deterministic fixes for SEC001/SEC002.
Uses explicit refusal semantics.
"""
import re
import logging
from pathlib import Path
from typing import Tuple, Optional
from dataclasses import dataclass
from .naming_utils import to_env_var

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
    
    def ensure_env_contract(self, variable_name: str) -> bool:
        """
        Ensure an env var contract exists.
        
        Strategy:
        1. Check for existing .env, .env.example, .env.template, etc.
        2. If found -> Success (append to confirm if desired, but we just check presence).
           Actually, if .env.example exists, we should ensure the key is present.
        3. If NOT found -> Create .env.example at repo root.
        """
        # 1. Determine Repo Root
        root = self._get_repo_root()
        if not root:
            # Fallback to self.repo_path if set, else cwd
            root = self.repo_path if self.repo_path else Path.cwd()
            
        # 2. Check for existing contract files
        env_files = ['.env', '.env.example', '.env.sample', '.env.template', '.env.local']
        existing_contract_file = None
        for fname in env_files:
            f = root / fname
            if f.exists():
                existing_contract_file = f
                # If we found .env.example or template, prefer modifying that one
                if 'example' in fname or 'template' in fname or 'sample' in fname:
                    break
        
        # 3. If no contract, create .env.example
        target_file = existing_contract_file
        if not target_file:
            target_file = root / '.env.example'
            try:
                if not target_file.exists():
                    target_file.write_text("# Autonoma - Environment Variables\n", encoding='utf-8')
                    logger.info(f"Created {target_file.name}")
            except Exception as e:
                logger.error(f"Failed to create .env.example: {e}")
                return False
                
        # 4. Ensure variable exists in target file (Idempotency)
        # We only modify if it's a template file (example/sample/template) or if we just created it.
        # We generally AVOID touching actual .env files to avoid deleting/corrupting secrets, 
        # but the user said "Accept if any exist... If none exist -> create .env.example".
        # And "Append only if ... not already present".
        
        # Refined rule: ALWAYS update .env.example (creating if needed).
        # Ignore .env for writing (it's for values).
        
        example_file = root / '.env.example'
        if not example_file.exists():
             # Try other names?
             for fname in ['.env.template', '.env.sample']:
                 if (root / fname).exists():
                     example_file = root / fname
                     break
        
        # If still doesn't exist (e.g. we only found .env), create .env.example?
        # User said: "If none exist -> create .env.example".
        # If .env exists, we ACCEPT the contract.
        # But we should still document the new var in .env.example if possible.
        
        # Let's stick to safe path: ensure .env.example exists and has the var.
        if not example_file.exists():
             example_file = root / '.env.example'
             try:
                 example_file.write_text("# Autonoma - Environment Variables\n", encoding='utf-8')
             except Exception:
                 return False # Write fail
        
        return self._append_to_env_file(example_file, variable_name)

    def _get_repo_root(self) -> Optional[Path]:
        """Try to find git root."""
        try:
            import subprocess
            # Use cwd=self.repo_path if matched, else cwd
            cwd = self.repo_path if self.repo_path and self.repo_path.exists() else Path.cwd()
            
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'], 
                capture_output=True, 
                text=True, 
                cwd=cwd,
                check=True
            )
            val = result.stdout.strip()
            if val:
                return Path(val)
        except Exception:
            pass
        return None

    def _append_to_env_file(self, file_path: Path, var_name: str) -> bool:
        """Append variable to env file if not present (Idempotent)."""
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # Check for var_name= (at start of line)
            # Regex handles: ^VAR_NAME= or ^export VAR_NAME=
            pattern = re.compile(rf'^\s*(?:export\s+)?{re.escape(var_name)}\s*=', re.MULTILINE)
            
            if pattern.search(content):
                return True # Already exists
            
            # Append properly
            suffix = ""
            if content and not content.endswith('\n'):
                suffix = "\n"
                
            new_entry = f"{suffix}{var_name}=\n"
            
            # Atomic-ish write not strictly needed for local tool, but append mode is safe
            with open(file_path, "a", encoding='utf-8') as f:
                f.write(new_entry)
                
            return True
        except Exception as e:
            logger.error(f"Failed to append to {file_path}: {e}")
            return False
    
    def fix_secret(self, code: str, file_path: Path, 
                   issue_id: str, line: int = None) -> SecretFixResult:
        """
        Attempt to fix a hardcoded secret.
        
        Returns explicit outcome: SUCCESS, REFUSED, or FAILED.
        """
        # Pre-flight checks
        
        # Check 1: Is fix type supported?
        # Update IDs to SECK namespace
        if issue_id not in ["SECK001", "SECK002", "SEC001", "SEC002", "SECK003_WARN"]: # Support both for backward compat for now
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
        # MOVED: We now ensure contract lazily inside specific fix methods
        # to ensure we have the variable name to document.
        # if not self.check_env_contract(): ...
            
        # Check 4: Is file in sensitive context (test/docs)? (Landmine #6)
            
        # Check 4: Is file in sensitive context (test/docs)? (Landmine #6)
        if self._is_sensitive_context(file_path):
            return SecretFixResult(
                outcome="REFUSED",
                reason="sensitive_context",
                message=f"Refusing to auto-fix secret in test/doc file: {file_path.name}"
            )

        # Check 4: Is file in sensitive context (test/docs)? (Landmine #6)
        if self._is_sensitive_context(file_path):
            return SecretFixResult(
                outcome="REFUSED",
                reason="sensitive_context",
                message=f"Refusing to auto-fix secret in test/doc file: {file_path.name}"
            )

        # Apply the fix
        try:
            if issue_id in ["SECK001", "SEC001"]:
                return self._fix_password(code, file_path)
            elif issue_id in ["SECK002", "SEC002", "SECK003_WARN"]:
                return self._fix_api_key(code, file_path)
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
    
    def _fix_password(self, code: str, file_path: Path) -> SecretFixResult:
        """Fix SECK001: Hardcoded password."""
        # ... (Same logic, pattern matching doesn't depend on ID)
        return self._fix_password_impl(code, file_path) # Wait, logic is inline.
        # I'll keep the logic inline below but just wrapped in existing methods.
        # Since I'm using replace_file_content, I am replacing the block above.
        pass

    # ... (skipping inline logic for brevity in this thought trace, 
    # but I need to make sure I don't delete the methods. 
    # The replace block targets lines 172-182 approximately for the dispatch logic.
    # And then the _is_sensitive_context at the end.)

    # Wait, the tool requires me to replace contiguous block.
    # I should target the dispatch logic first.

    def _is_sensitive_context(self, file_path: Path) -> bool:
        """Check if file is in a context where auto-fix is dangerous."""
        if not file_path: return False
        
        try:
            parts = set(p.lower() for p in file_path.parts)
            
            # Segment Check
            risky_segments = {'tests', 'test', 'docs', 'examples', 'fixtures', 'spec', '__tests__', 'mock'}
            if not parts.isdisjoint(risky_segments):
                return True
                
            # Filename Logic
            name = file_path.name.lower()
            if (name.startswith("test_") or 
                name.endswith("_test.py") or 
                name.endswith(".test.js") or 
                name.endswith(".spec.js") or 
                name.startswith("mock_")):
                return True
        except Exception:
            # Fallback
            path_str = str(file_path).lower()
            if any(x in path_str for x in ["/test/", "/docs/", "/examples/"]):
                return True
            
        return False
    
    def _fix_password(self, code: str, file_path: Path) -> SecretFixResult:
        """Fix SEC001: Hardcoded password."""
        modified_code = code
        env_var_name = None
        
        if file_path.suffix == ".py":
            pattern = r"(\w*[Pp]assword\w*)(\s*:\s*[^=\n]+)?\s*(=)\s*['\"]([^'\"]+)['\"]"
            
            match = re.search(pattern, code)
            if not match:
                if "os.getenv" in code:
                    return SecretFixResult(
                        outcome="SKIPPED",
                        reason="already_fixed",
                        message="already uses env var"
                    )
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="secret_pattern_ambiguous",
                    message="Could not locate password pattern to fix"
                )
            
            var_name = match.group(1)
            env_var_name = self._get_env_var_name(var_name.lower())
            
            if not env_var_name:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="env_var_name_ambiguous",
                    message=f"Cannot determine safe env var name for '{var_name}'"
                )
            
            # Ensure Contract (Create .env.example if needed)
            if not self.ensure_env_contract(env_var_name):
                return SecretFixResult(
                     outcome="FAILED",
                     reason="env_contract_creation_failed",
                     message="Could not create/update .env.example"
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
                
                # Deterministic Naming
                env_name = to_env_var(vn)
                self.ensure_env_contract(env_name)
                
                return f"{vn}{th} {op} os.getenv('{env_name}')"
            
            modified_code = re.sub(pattern, replacer, modified_code)
            
        elif file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}:
            pattern = r"(?m)(^\s*)(const|let|var)?\s*(\w*[Pp]assword\w*)\s*=\s*['\"]([^'\"]+)['\"]"
            
            match = re.search(pattern, code)
            if not match:
                if "process.env" in code:
                    return SecretFixResult(
                        outcome="SKIPPED",
                        reason="already_fixed",
                        message="already uses env var"
                    )
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="secret_pattern_ambiguous",
                    message="Could not locate password pattern to fix"
                )
            
            var_name = match.group(3)
            env_var_name = self._get_env_var_name(var_name.lower())
            
            if not env_var_name:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="env_var_name_ambiguous",
                    message=f"Cannot determine safe env var name for '{var_name}'"
                )
            
            # Ensure Contract (Create .env.example if needed)
            if not self.ensure_env_contract(env_var_name):
                return SecretFixResult(
                     outcome="FAILED",
                     reason="env_contract_creation_failed",
                     message="Could not create/update .env.example"
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
    
    def _fix_api_key(self, code: str, file_path: Path) -> SecretFixResult:
        """Fix SEC002: Hardcoded API key."""
        modified_code = code
        env_var_name = None
        
        if file_path.suffix == ".py":
            pattern = r"(?m)(^\s*)([\w_]*(?:api_key|api_secret|auth_token|secret|token|key)[\w_]*)\s*=\s*['\"]([^'\"]{10,})['\"]"
            
            match = re.search(pattern, code)
            if not match:
                # User Feedback: If we can't find the literal pattern, but the file uses os.getenv,
                # it's likely already fixed by a previous pass.
                if "os.getenv" in code:
                    return SecretFixResult(
                        outcome="SKIPPED", # Mapped to SKIPPED in CLI
                        reason="already_fixed",
                        message="already uses env var"
                    )
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="secret_pattern_ambiguous",
                    message="Could not locate API key pattern to fix"
                )
            
            var_name = match.group(2)
            env_var_name = self._get_env_var_name(var_name.lower())
            
            if not env_var_name:
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="env_var_name_ambiguous",
                    message=f"Cannot determine safe env var name for '{var_name}'"
                )
            
            # Ensure Contract (Create .env.example if needed)
            if not self.ensure_env_contract(env_var_name):
                return SecretFixResult(
                     outcome="FAILED",
                     reason="env_contract_creation_failed",
                     message="Could not create/update .env.example"
                )
            
            # Ensure import os
            if "import os" not in code:
                lines = modified_code.splitlines()
                lines.insert(0, "import os")
                modified_code = "\n".join(lines)
            
            def replacer(m):
                indent = m.group(1)
                vn = m.group(2)
                
                # Dynamic deterministic naming using new util
                name_for_match = to_env_var(vn)
                if not name_for_match:
                     name_for_match = vn.upper()
                
                # Ensure validation (idempotent)
                self.ensure_env_contract(name_for_match)
                
                return f"{indent}{vn} = os.getenv('{name_for_match}')"
            
            modified_code = re.sub(pattern, replacer, modified_code)
            
        elif file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}:
            pattern = r"(?m)(^\s*)(const|let|var)?\s*(apiKey|apiSecret|authToken)\s*=\s*['\"]([^'\"]{10,})['\"]"
            
            match = re.search(pattern, code)
            if not match:
                if "process.env" in code:
                    return SecretFixResult(
                        outcome="SKIPPED",
                        reason="already_fixed",
                        message="already uses env var"
                    )
                return SecretFixResult(
                    outcome="REFUSED",
                    reason="secret_pattern_ambiguous",
                    message="Could not locate API key pattern to fix"
                )
            
            var_name = match.group(3)
            # Convert camelCase to SCREAMING_SNAKE_CASE
            env_var_name = re.sub(r'(?<!^)(?=[A-Z])', '_', var_name).upper()
            
            # Ensure Contract (Create .env.example if needed)
            if not self.ensure_env_contract(env_var_name):
                return SecretFixResult(
                     outcome="FAILED",
                     reason="env_contract_creation_failed",
                     message="Could not create/update .env.example"
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
                message=f"Replaced hardcoded key with env var '{env_var_name}'"
            )
        
        return SecretFixResult(
            outcome="REFUSED",
            reason="no_fix_applied",
            message="Pattern matched but no changes made"
        )
    
    def _get_env_var_name(self, var_name: str) -> Optional[str]:
        """
        Determine the appropriate env var name.
        Returns None if we can't confidently name it.
        """
        var_lower = var_name.lower().replace('-', '_')
        
        # Direct match
        for pattern, env_name in self.ENV_VAR_PATTERNS.items():
            if pattern in var_lower:
                return env_name
        
        # If it's a clear identifier, uppercase it
        if re.match(r'^[a-z][a-z0-9_]*$', var_lower):
            return var_lower.upper()
        
        return None
        
    def _is_sensitive_context(self, file_path: Path) -> bool:
        """Check if file is in a context where auto-fix is dangerous."""
        if not file_path: return False
        
        try:
            parts = set(p.lower() for p in file_path.parts)
            
            # Segment Check
            risky_segments = {'tests', 'test', 'docs', 'examples', 'fixtures', 'spec', '__tests__', 'mock'}
            if not parts.isdisjoint(risky_segments):
                return True
                
            # Filename Logic
            name = file_path.name.lower()
            if (name.startswith("test_") or 
                name.endswith("_test.py") or 
                name.endswith(".test.js") or 
                name.endswith(".spec.js") or 
                name.startswith("mock_")):
                return True
        except Exception:
            # Fallback
            path_str = str(file_path).lower()
            if any(x in path_str for x in ["/test/", "/docs/", "/examples/"]):
                return True
            
        return False
