import ast
import logging
import tokenize
import io
import token
from typing import Optional, List, Dict, Set, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RepairResult:
    rectified_code: Optional[str]
    success: bool
    reason: str
    origin: str = "RAW" # RAW or REPAIRED_SYNTAX
    diff_stat: float = 0.0

class OverreachDetector:
    """
    Ensures syntax repair does not alter program semantics or structure.
    Hardened for Freeze Protocol V1.1.
    """
    
    def check_overreach(self, original_code: str, repaired_code: str) -> bool:
        """
        Returns True if overreach is detected.
        Checks:
        1. Identifier Immutability (Set Equality/Subset).
        2. Literal Immutability.
        3. AST Node Delta <= 10%.
        4. No new semantic structures.
        """
        # 1. AST Check (Primary)
        try:
            tree_repaired = ast.parse(repaired_code)
            
            # Since original likely fails AST parse (it has syntax error),
            # we can't do full AST comparison. 
            # We rely heavily on Token Analysis.
            
            # However, IF original happens to parse (e.g. valid syntax but wrong logic?), we check delta.
            try:
                tree_orig = ast.parse(original_code)
                # If we get here, original was valid? Then why repair? 
                # Maybe logic error masquerading as syntax?
                if self._check_ast_delta(tree_orig, tree_repaired) > 0.10:
                    logger.warning("Overreach: AST Delta > 10% (Valid->Valid)")
                    return True
            except SyntaxError:
                # Expected case. We can't check AST delta against original.
                # We enforce Token Safety.
                pass
                
        except SyntaxError:
            # Repaired code is invalid
            return True

        # 2. Token Safety (The Guardian)
        # We must ensure NO NEW identifiers or literals are introduced.
        return not self._check_token_safety(original_code, repaired_code)

    def _check_ast_delta(self, tree1: ast.AST, tree2: ast.AST) -> float:
        nodes1 = list(ast.walk(tree1))
        nodes2 = list(ast.walk(tree2))
        len1 = len(nodes1)
        if len1 == 0: return 1.0
        return abs(len(nodes2) - len1) / len1

    def _extract_tokens(self, code: str) -> Tuple[Set[str], Set[str]]:
        """Extract Identifiers and Literals from code."""
        identifiers = set()
        literals = set()
        
        try:
            # Tokenize requires bytes
            tokens = list(tokenize.tokenize(io.BytesIO(code.encode('utf-8')).readline))
            for tok in tokens:
                if tok.type == token.NAME:
                    identifiers.add(tok.string)
                elif tok.type in (token.NUMBER, token.STRING):
                    literals.add(tok.string)
        except tokenize.TokenError:
            # If tokenization fails (incomplete string etc), we return what we found so far?
            # Or treat as empty? If original is bad, we might miss some tokens.
            # But the Rule is "Repaired must not have NEW ones".
            # If original is seemingly empty of tokens due to error, we might falsely reject repair.
            # Risk: Accepting repair that adds stuff.
            # Conservative: If we can't tokenize original, we assume we found everything? No.
            # If original crashes tokenizer, we should probably HALT or rely on Text diff.
            pass
            
        return identifiers, literals

    def _check_token_safety(self, original_code: str, repaired_code: str) -> bool:
        """
        Verify that Repaired Code does not introduce NEW identifiers or literals.
        Returns True if SAFE, False if OVERREACH.
        """
        orig_ids, orig_lits = self._extract_tokens(original_code)
        rep_ids, rep_lits = self._extract_tokens(repaired_code)
        
        # 1. Identifier Check
        # Repaired identifiers must be present in Original
        # Exception: Annotations or some syntax fixes might expose identifiers previously unparsable?
        # No, tokenization usually finds them regardless of syntax error.
        new_ids = rep_ids - orig_ids
        if new_ids:
            logger.warning(f"Overreach: New Identifiers detected: {new_ids}")
            return False
            
        # 2. Literal Check
        new_lits = rep_lits - orig_lits
        if new_lits:
            logger.warning(f"Overreach: New Literals detected: {new_lits}")
            return False
            
        return True

    def check_safe_mutation(self, original_code: str, repaired_code: str) -> bool:
        """Legacy/Heuristic check."""
        return self._check_token_safety(original_code, repaired_code)


class SyntaxRepairer:
    """
    Repair loop for syntax errors using LLM with strict constraints.
    Optimized for large files using Context-Window Repair.
    """
    def __init__(self, model_client):
        self.model = model_client
        self.detector = OverreachDetector()

    def _extract_line_number(self, error_trace: str) -> Optional[int]:
        import re
        # Match "line 123" or "(Line 123)"
        match = re.search(r'(?:line|Line)\s+(\d+)', error_trace)
        if match:
            return int(match.group(1))
        return None

    async def repair(self, code: str, error_trace: str) -> RepairResult:
        """
        Attempt to fix syntax error using independent client to avoid state issues.
        Uses windowing for large files to prevent timeouts.
        """
        import httpx
        
        # 1. Strategy Selection
        line_no = self._extract_line_number(error_trace)
        use_window = False
        window_start = 0
        window_end = 0
        target_code = code
        
        if line_no:
            lines = code.splitlines()
            if len(lines) > 50: # Threshold for windowing
                use_window = True
                # 0-indexed window
                window_start = max(0, line_no - 25) # Context before
                window_end = min(len(lines), line_no + 25) # Context after
                target_code = "\n".join(lines[window_start:window_end])
                logger.info(f"Syntax Repair: Using Window {window_start}-{window_end} (Line {line_no})")

        # 2. Prompt Construction
        prompt = f"""You are a Strict Syntax Repairer.
The following Python code snippet has a SyntaxError.

Error Trace:
{error_trace}

Task: Fix ONLY the syntax error in the snippet.
Rules:
1. DO NOT add new functions, classes, or logic.
2. DO NOT comment on the code.
3. DO NOT change existing logic or variable names.
4. Fix missing colons, indentation, parentheses, or simple typos.
5. Output ONLY the raw Python code for the corrected snippet.
6. Preserve indentation relative to the snippet.

Code Snippet:
```python
{target_code}
```
"""
        
        # Try simple fallback first (no external service required)
        fallback_result = self._try_simple_repair(code, error_trace, line_no)
        if fallback_result and fallback_result.success:
            logger.info("Syntax Repair: Using simple fallback repair (no LLM required)")
            return fallback_result
        
        # If fallback fails, try LLM-based repair
        try:
            # Independent client for reliability
            # Timeout 300.0s is sufficient for small snippets
            async with httpx.AsyncClient(timeout=10.0) as client:  # Reduced timeout for faster failure
                model_name = getattr(self.model, 'model', 'qwen3:4b')
                base_url = getattr(self.model, 'base_url', 'http://localhost:11434')
                logger.warning(f"DEBUG: SyntaxRepair connecting to {base_url} with model {model_name}")
                
                # Quick connectivity check
                try:
                    health_check = await client.get(f"{base_url}/api/tags", timeout=2.0)
                    if health_check.status_code != 200:
                        logger.warning(f"Syntax Repair: Ollama service unavailable (status {health_check.status_code}), using fallback")
                        return RepairResult(None, False, "Ollama service unavailable", origin="RAW")
                except Exception:
                    logger.warning("Syntax Repair: Ollama service not reachable, using fallback only")
                    return RepairResult(None, False, "Ollama service not reachable", origin="RAW")
                
                response = await client.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,
                            "stop": ["```"] 
                        }
                    },
                    timeout=30.0  # Reduced timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    raw_response = data.get("response", "").strip()
                    
                    # Clean Markdown
                    repaired_snippet = self._clean_markdown(raw_response)
                    
                    # 3. Reassemble if Windowed
                    if use_window:
                        lines = code.splitlines()
                        # Replace the window
                        # Note: LLM might change line count (e.g. split line).
                        # We just replace the block.
                        repaired_lines = repaired_snippet.splitlines()
                        
                        # Head + Repaired + Tail
                        # window_end is exclusive index in slice
                        final_lines = lines[:window_start] + repaired_lines + lines[window_end:]
                        repaired_code = "\n".join(final_lines)
                    else:
                        repaired_code = repaired_snippet
                    
                    # 4. Validate Syntax (Self-Check)
                    try:
                        ast.parse(repaired_code)
                    except SyntaxError:
                        return RepairResult(None, False, "Repaired code still invalid", origin="RAW")
                    
                    # 5. Check Overreach (Hardened)
                    if self.detector.check_overreach(code, repaired_code):
                         return RepairResult(None, False, "Overreach Detected (Identifiers/Literals Changed)", origin="REPAIRED_SYNTAX")
                    
                    return RepairResult(repaired_code, True, "Fixed", origin="REPAIRED_SYNTAX")
                else:
                     return RepairResult(None, False, f"LLM Error: {response.status_code}", origin="RAW")
             
        except httpx.ConnectError as e:
            logger.warning(f"Syntax Repair: Connection failed ({repr(e)}), fallback already attempted")
            return RepairResult(None, False, f"Connection failed: {repr(e)}", origin="RAW")
        except Exception as e:
            logger.warning(f"Syntax Repair failed: {repr(e)}")
            return RepairResult(None, False, repr(e), origin="RAW")

    def _clean_markdown(self, text: str) -> str:
        if "```" in text:
            parts = text.split("```")
            if len(parts) > 1:
                content = parts[1]
                if content.startswith("python"):
                    content = content[6:]
                return content.strip()
        return text.strip()
    
    def _try_simple_repair(self, code: str, error_trace: str, line_no: Optional[int]) -> Optional[RepairResult]:
        """
        Simple syntax repair fallback that doesn't require external services.
        Handles common syntax errors like:
        - Missing colons
        - Indentation issues
        - Missing parentheses
        - Common typos
        """
        import re
        
        if not line_no:
            return None
        
        lines = code.splitlines()
        if line_no > len(lines):
            return None
        
        error_line = lines[line_no - 1]  # Convert to 0-based index
        repaired_lines = lines.copy()
        
        # Common fixes
        fixes_applied = False
        
        # Fix 1: Missing colon after if/for/while/def/class
        if re.search(r'\b(if|for|while|def|class|elif|else|except|finally|try)\s+.*[^:]$', error_line):
            if not error_line.rstrip().endswith(':'):
                repaired_lines[line_no - 1] = error_line.rstrip() + ':'
                fixes_applied = True
        
        # Fix 2: Common indentation issues (unindent does not match)
        if "unindent does not match" in error_trace.lower():
            # Try to match indentation of previous block
            if line_no > 1:
                prev_line = lines[line_no - 2]
                prev_indent = len(prev_line) - len(prev_line.lstrip())
                current_indent = len(error_line) - len(error_line.lstrip())
                
                # If current line has more indent than expected, reduce it
                if current_indent > prev_indent + 4:  # Likely over-indented
                    # Reduce to match previous block level
                    repaired_lines[line_no - 1] = ' ' * prev_indent + error_line.lstrip()
                    fixes_applied = True
                elif current_indent < prev_indent and prev_indent > 0:
                    # Under-indented, increase to match
                    repaired_lines[line_no - 1] = ' ' * prev_indent + error_line.lstrip()
                    fixes_applied = True
        
        # Fix 3: Missing closing parenthesis/bracket
        if "unexpected EOF" in error_trace.lower() or "was never closed" in error_trace.lower():
            # Count opening vs closing
            open_parens = error_line.count('(') - error_line.count(')')
            open_brackets = error_line.count('[') - error_line.count(']')
            open_braces = error_line.count('{') - error_line.count('}')
            
            if open_parens > 0:
                repaired_lines[line_no - 1] = error_line + ')' * open_parens
                fixes_applied = True
            elif open_brackets > 0:
                repaired_lines[line_no - 1] = error_line + ']' * open_brackets
                fixes_applied = True
            elif open_braces > 0:
                repaired_lines[line_no - 1] = error_line + '}' * open_braces
                fixes_applied = True
        
        if not fixes_applied:
            return None
        
        repaired_code = '\n'.join(repaired_lines)
        
        # Validate the repair
        try:
            ast.parse(repaired_code)
            # Check overreach
            if not self.detector.check_overreach(code, repaired_code):
                return RepairResult(repaired_code, True, "Fixed with simple repair", origin="REPAIRED_SYNTAX")
        except SyntaxError:
            pass  # Simple repair didn't work
        
        return None