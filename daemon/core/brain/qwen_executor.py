import logging
import httpx
import re
import ast
from typing import Dict, Any, List, Tuple, Optional, Callable
from daemon.analysis.tree_editor import TreeEditor

logger = logging.getLogger(__name__)

class QwenExecutor:
    """
    Local Executor using Qwen3-4B (via Ollama).
    Applies operations from the plan using:
    1. Exact string matching (Python).
    2. Fuzzy LLM-based patching (Qwen).
    """

    def __init__(self, model: str = "qwen3:4b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.client = None  # Will be created lazily
        self._closed = False
        self.tree_editor = TreeEditor()
    
    def _ensure_client(self):
        """Ensure httpx client is created and not closed."""
        import asyncio
        try:
            # Check if current event loop is closed or closing
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                self._closed = True
                self.client = None
        except RuntimeError:
            # No event loop running - this is okay, client will work in new loop
            pass
        except Exception as e:
            # If we can't check the loop, mark as closed to be safe
            logger.debug(f"Error checking event loop in _ensure_client: {e}")
            self._closed = True
            self.client = None
        
        if self.client is None or self._closed:
            try:
                self.client = httpx.AsyncClient(timeout=120.0)
                self._closed = False
            except Exception as e:
                logger.error(f"Failed to create httpx client: {e}")
                self._closed = True
                self.client = None
                raise
    
    async def close(self):
        """Close the httpx client to prevent event loop errors."""
        if self.client and not self._closed:
            try:
                await self.client.aclose()
            except Exception:
                pass
            finally:
                self._closed = True
                self.client = None

    async def execute(
        self, 
        plan: Dict[str, Any], 
        file_map: Dict[str, str],
        incremental_validation_callback: Optional[callable] = None
    ) -> Tuple[List[str], Optional[bool]]:
        """
        Execute the plan with optional incremental validation.
        
        Args:
            plan: The JSON plan from RemoteBrain.
            file_map: Mapping of file_hash -> absolute_path.
            incremental_validation_callback: Optional callback function that takes no args
                                           and returns True if test passes, False otherwise.
                                           If provided, will be called after each operation.
            
        Returns:
            Tuple of (List of modified file paths, early_success)
            - early_success: True if incremental validation passed early, None if not used
        """
        operations = plan.get("operations", [])
        logger.info(f"[EXECUTION] Starting execution of {len(operations)} operation(s)")
        if incremental_validation_callback:
            logger.info(f"[EXECUTION] Incremental validation ENABLED - will test after each operation")
        
        modified_files = []
        failed_operations = []
        early_success = None
        
        for i, op in enumerate(operations):
            file_hash = op.get("target", {}).get("file_hash", "unknown")
            abs_path = file_map.get(file_hash)
            
            if not abs_path:
                error_msg = f"Unknown file hash: {file_hash}"
                logger.error(f"[EXECUTION] Operation {i+1}/{len(operations)} FAILED: {error_msg}")
                logger.error(f"  File hash: {file_hash}")
                logger.error(f"  Available hashes: {list(file_map.keys())[:5]}...")
                failed_operations.append({"index": i, "reason": error_msg, "file_hash": file_hash})
                continue
            
            print(f"DEBUG: Processing op {i+1} on {abs_path}")
            logger.info(f"[EXECUTION] Processing operation {i+1}/{len(operations)} on {abs_path}")
            success = await self._apply_operation(abs_path, op)
            print(f"DEBUG: Operation {i+1} success: {success}")
            
            if success:
                modified_files.append(abs_path)
                logger.info(f"[EXECUTION] Operation {i+1}/{len(operations)} SUCCESS")
                
                # Incremental validation: test after each successful operation
                if incremental_validation_callback:
                    logger.info(f"[INCREMENTAL VALIDATION] Testing after operation {i+1}/{len(operations)}...")
                    try:
                        test_passed = incremental_validation_callback()
                        if test_passed:
                            logger.info(f"[INCREMENTAL VALIDATION] Test PASSED after operation {i+1}! Early success.")
                            logger.info(f"[EXECUTION] Stopping early - fix is complete after {i+1} operation(s)")
                            early_success = True
                            break  # Stop executing remaining operations
                        else:
                            logger.debug(f"[INCREMENTAL VALIDATION] Test still failing, continuing with next operation...")
                    except Exception as e:
                        logger.warning(f"[INCREMENTAL VALIDATION] Error during validation: {e}. Continuing...")
            else:
                failed_operations.append({
                    "index": i,
                    "reason": "All matching strategies failed",
                    "file": abs_path,
                    "file_hash": file_hash
                })
                logger.error(f"[EXECUTION] Operation {i+1}/{len(operations)} FAILED")
        
        # Summary
        if early_success:
            logger.info(f"[EXECUTION] Execution stopped early: {len(modified_files)} operation(s) applied, test passed")
        else:
            logger.info(f"[EXECUTION] Execution complete: {len(modified_files)} succeeded, {len(failed_operations)} failed")
        
        if failed_operations:
            logger.warning(f"[EXECUTION] Failed operations:")
            for failed in failed_operations:
                logger.warning(f"  Operation {failed['index']+1}: {failed.get('reason', 'Unknown error')}")
        
        return list(set(modified_files)), early_success

    async def _apply_operation(self, file_path: str, op: Dict[str, Any]) -> bool:
        # Log operation attempt
        op_type = op.get("type", "unknown")
        target = op.get("target", {})
        file_hash = target.get("file_hash", "unknown")
        start_line = target.get("start_line", "?")
        end_line = target.get("end_line", "?")
        before_preview = op.get("before", "")[:100].replace('\n', ' ')
        after_preview = op.get("after", "")[:100].replace('\n', ' ')
        
        logger.info(f"[OPERATION] Attempting {op_type} on {file_path}")
        logger.debug(f"  File hash: {file_hash}, Lines: {start_line}-{end_line}")
        logger.debug(f"  Before: {before_preview}...")
        logger.debug(f"  After: {after_preview}...")
        
        # Load file
        original_content = None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                original_content = content
        except Exception as e:
            logger.error(f"[OPERATION FAILED] Read error {file_path}: {e}")
            logger.error(f"  Operation type: {op_type}, File hash: {file_hash}")
            return False

        target_content = op["before"]
        replacement = op["after"]
        
        # Log the full 'before' and 'after' blocks for debugging
        logger.debug(f"  Full 'before' block ({len(target_content)} chars):\n{target_content}")
        logger.debug(f"  Full 'after' block ({len(replacement)} chars):\n{replacement}")
        logger.debug(f"  File content preview (first 500 chars):\n{content[:500]}")
        
        # Strategy 1: Exact Replace
        if target_content in content:
            # Detect target indentation
            idx = content.find(target_content)
            line_start_idx = content.rfind('\n', 0, idx) + 1
            indentation = ""
            if line_start_idx >= 0 and line_start_idx < len(content):
                line = content[line_start_idx:idx+1]
                for char in line:
                    if char.isspace():
                        indentation += char
                    else:
                        break
            
            # Apply Smart Re-indentation
            logger.debug(f"  Exact Match: Detected indentation depth: {len(indentation)}")
            reindented_replacement = self.tree_editor.smart_reindent(replacement, indentation)
            
            # Use reindented version
            new_content = content.replace(target_content, reindented_replacement, 1)
            self._write_file(file_path, new_content)
            changes = self._compute_changes(original_content, new_content)
            logger.info(f"[OPERATION SUCCESS] Applied EXACT fix to {file_path}")
            logger.info(f"  Strategy: Exact string match (Smart Re-indented)")
            logger.debug(f"  Changes: {changes}")
            return True
        else:
            logger.debug(f"  Strategy 1 (EXACT) failed: 'before' block not found in file")
        
        # Strategy 2: Normalized Whitespace Matching
        normalized_match = self._try_normalized_match(content, target_content, replacement)
        if normalized_match:
            # Note: _try_normalized_match applies the replacement directly. 
            # We ideally want to re-indent there too, but it's harder because we reconstruct.
            # However, if we simply force re-indentation on the replacement passed to it...
            
            # Since normalized match finds the window, we can try to guess context...
            # Actually, `_try_normalized_match` should be updated or we can rely on Strategy 3 (Timer)
            # But let's apply the fix:
            self._write_file(file_path, normalized_match)
            changes = self._compute_changes(original_content, normalized_match)
            logger.info(f"[OPERATION SUCCESS] Applied NORMALIZED fix to {file_path}")
            logger.info(f"  Strategy: Normalized whitespace match")
            logger.debug(f"  Changes: {changes}")
            return True
        else:
            logger.debug(f"  Strategy 2 (NORMALIZED) failed: Normalized match not found")
        
        # Strategy 3: Tree-Sitter Based Editing (Deterministic & Multi-language)
        # This replaces the old Python-only AST/Hybrid strategies
        logger.debug(f"  Strategy 3 (TREE-SITTER): Attempting deterministic tree-based replacement...")
        file_ext = "." + file_path.split(".")[-1] if "." in file_path else ""
        ts_new_content, ts_applied = self.tree_editor.replace(content, target_content, replacement, file_ext)
        if ts_applied:
            self._write_file(file_path, ts_new_content)
            changes = self._compute_changes(original_content, ts_new_content)
            logger.info(f"[OPERATION SUCCESS] Applied TREE-SITTER fix to {file_path}")
            logger.info(f"  Strategy: Tree-Sitter CST Replacement")
            logger.debug(f"  Changes: {changes}")
            return True
        else:
             logger.debug(f"  Strategy 3 (TREE-SITTER) failed: No structural match found")
        
        # Strategy 4: Fuzzy Matching with Similarity
        fuzzy_match = self._try_fuzzy_match(content, target_content, replacement)
        if fuzzy_match:
            self._write_file(file_path, fuzzy_match)
            changes = self._compute_changes(original_content, fuzzy_match)
            logger.info(f"[OPERATION SUCCESS] Applied FUZZY fix to {file_path}")
            logger.info(f"  Strategy: Similarity-based fuzzy match")
            logger.debug(f"  Changes: {changes}")
            return True
        else:
            logger.debug(f"  Strategy 4 (FUZZY) failed: Similarity match not found")
        
        # Strategy 5: Qwen LLM Fallback
        logger.warning(f"[OPERATION] All matching strategies failed for {file_path}. Escalating to Qwen3...")
        logger.warning(f"  Failed strategies: EXACT, NORMALIZED, STRUCTURE, FUZZY")
        logger.warning(f"  Reason: 'before' block not found with any matching strategy")
        
        # Retry loop for syntax correction
        max_retries = 3
        last_error = None
        new_content = None
        
        for attempt in range(max_retries):
            retry_context = ""
            if last_error:
                logger.warning(f"[RELAYER] Syntax error in attempt {attempt}: {last_error}")
                retry_context = f"\n\nPREVIOUS ATTEMPT FAILED WITH SYNTAX ERROR:\n{last_error}\n\nPLEASE FIX THE SYNTAX AND RETURN VALID CODE."
                
            current_content_candidate = await self._prompt_qwen_apply(content, op, retry_context)
            
            if not current_content_candidate or current_content_candidate == content:
                logger.warning(f"[OPERATION] Qwen returned empty or unchanged content (Attempt {attempt+1})")
                continue

            # Validate Syntax
            validation_error = self._validate_syntax(current_content_candidate, file_path)
            if validation_error:
                last_error = validation_error
                # Continue to next retry
                continue
            
            # If we get here, syntax is valid
            new_content = current_content_candidate
            break
        
        if not new_content and last_error:
             logger.error(f"[OPERATION FAILED] Qwen failed to produce valid syntax after {max_retries} attempts.")
             logger.error(f"  Last Syntax Error: {last_error}")
             return False

        if new_content: # Validated content (syntax-wise)
            # Final content validation (did it actually apply the fix?)
            # Additional validation: ensure the replacement is actually in the result
            validation_passed = self._validate_fix_applied(new_content, target_content, replacement)
            changes = self._compute_changes(original_content, new_content)
            
            if validation_passed:
                self._write_file(file_path, new_content)
                logger.info(f"[OPERATION SUCCESS] Applied QWEN fix to {file_path} (validated)")
                logger.info(f"  Strategy: Qwen LLM fallback")
                logger.debug(f"  Changes: {changes}")
                return True
            else:
                logger.warning(f"[OPERATION WARNING] Qwen fix validation failed - replacement not found in result")
                logger.warning(f"  Validation: Replacement block not found in Qwen output")
                # Still try to write it, but log the warning
                self._write_file(file_path, new_content)
                logger.info(f"[OPERATION SUCCESS] Applied QWEN fix to {file_path} (unvalidated)")
                logger.info(f"  Strategy: Qwen LLM fallback (validation failed)")
                logger.debug(f"  Changes: {changes}")
                return True
        else:
            logger.error(f"[OPERATION FAILED] Qwen generated no usable content")
            
             
        logger.error(f"[OPERATION FAILED] All strategies failed for {file_path}")
        logger.error(f"  Operation type: {op_type}, File hash: {file_hash}")
        logger.error(f"  Failed strategies: EXACT, NORMALIZED, STRUCTURE, FUZZY, QWEN")
        logger.error(f"  Reason: Could not apply operation - 'before' block not found and Qwen failed")
        return False
    
    def _compute_changes(self, original: str, modified: str) -> str:
        """Compute and return a summary of changes between original and modified content."""
        if original == modified:
            return "No changes"
        
        original_lines = original.split('\n')
        modified_lines = modified.split('\n')
        
        # Simple diff summary
        added_lines = len(modified_lines) - len(original_lines)
        if added_lines > 0:
            change_summary = f"+{added_lines} lines"
        elif added_lines < 0:
            change_summary = f"{added_lines} lines"
        else:
            change_summary = "Same line count"
        
        # Count character changes
        char_diff = len(modified) - len(original)
        if char_diff != 0:
            change_summary += f", {char_diff:+d} chars"
        
        # Try to identify what changed (first few lines that differ)
        diff_lines = []
        max_lines = min(len(original_lines), len(modified_lines), 5)
        for i in range(max_lines):
            if i < len(original_lines) and i < len(modified_lines):
                if original_lines[i] != modified_lines[i]:
                    diff_lines.append(f"Line {i+1}: '{original_lines[i][:50]}' -> '{modified_lines[i][:50]}'")
        
        if diff_lines:
            change_summary += f"\n  Sample changes:\n    " + "\n    ".join(diff_lines[:3])
        
        return change_summary
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace for comparison: collapse multiple spaces, normalize line endings."""
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # Collapse multiple spaces to single space (but preserve indentation)
        lines = text.split('\n')
        normalized_lines = []
        for line in lines:
            # Preserve leading whitespace (indentation)
            leading_ws = len(line) - len(line.lstrip())
            content = line[leading_ws:]
            # Collapse multiple spaces in content
            content = re.sub(r' +', ' ', content)
            normalized_lines.append(' ' * leading_ws + content)
        return '\n'.join(normalized_lines)
    
    def _try_normalized_match(self, content: str, target: str, replacement: str) -> Optional[str]:
        """Try matching with normalized whitespace."""
        normalized_content = self._normalize_whitespace(content)
        normalized_target = self._normalize_whitespace(target)
        
        if normalized_target in normalized_content:
            # Find the position in normalized content
            norm_pos = normalized_content.find(normalized_target)
            
            # Map back to original content by counting characters
            # This is approximate but should work for most cases
            norm_chars_before = len(normalized_content[:norm_pos].split('\n'))
            content_lines = content.split('\n')
            target_lines = target.split('\n')
            
            # Try to find matching lines in original content
            for i in range(len(content_lines) - len(target_lines) + 1):
                window = '\n'.join(content_lines[i:i+len(target_lines)])
                if self._normalize_whitespace(window) == normalized_target:
                    # Found match, replace it
                    new_lines = content_lines[:i] + replacement.split('\n') + content_lines[i+len(target_lines):]
                    return '\n'.join(new_lines)
        
        return None
    
    def _try_hybrid_ast_exact_match(self, content: str, target: str, replacement: str) -> Optional[str]:
        """
        Hybrid approach: Use AST to find the matching node, then use exact string replacement.
        This combines the robustness of AST-based node finding with the speed and precision
        of exact string replacement.
        
        Process:
        1. Parse content and target into ASTs
        2. Find matching AST node in content
        3. Extract the actual code block for that node
        4. Use exact string replacement within that block
        5. Replace the node's code block with the modified version
        """
        try:
            # Parse content and target into ASTs
            content_ast = ast.parse(content, filename='<content>')
            target_ast = ast.parse(target, filename='<target>')
            
            # Find matching node in content_ast
            matching_node = self._find_matching_ast_node(content_ast, target_ast)
            
            if matching_node is None:
                logger.debug(f"  Hybrid: No matching AST node found")
                return None
            
            # Get line numbers for the matching node
            start_line = matching_node.lineno - 1  # Convert to 0-based
            end_line = matching_node.end_lineno if hasattr(matching_node, 'end_lineno') else start_line + 1
            
            # Extract the code block for this node
            content_lines = content.split('\n')
            node_code = '\n'.join(content_lines[start_line:end_line])
            
            # Try exact replacement within the node's code block
            if target in node_code:
                # Exact match found within node - replace it
                modified_node_code = node_code.replace(target, replacement, 1)
                
                # Reconstruct the file with the modified node
                new_lines = content_lines[:start_line] + modified_node_code.split('\n') + content_lines[end_line:]
                new_content = '\n'.join(new_lines)
                
                logger.debug(f"  Hybrid: Found exact match within AST node, applied replacement")
                return new_content
            else:
                # Try normalized whitespace match within node
                normalized_node = self._normalize_whitespace(node_code)
                normalized_target = self._normalize_whitespace(target)
                
                if normalized_target in normalized_node:
                    # Find the position in normalized space and map back
                    # This is a simplified approach - for production, we'd want more robust mapping
                    idx = normalized_node.find(normalized_target)
                    if idx >= 0:
                        # Approximate: replace in original node code using similarity
                        # For now, fall back to full AST replacement
                        logger.debug(f"  Hybrid: Found normalized match, but falling back to full AST replacement")
                        return None
                
                logger.debug(f"  Hybrid: No exact match found within AST node code block")
                return None
                
        except SyntaxError as e:
            logger.debug(f"  Hybrid: Syntax error during parsing: {e}")
            return None
        except Exception as e:
            logger.debug(f"  Hybrid: Error during hybrid matching: {e}")
            return None
    
    def _try_structure_match(self, content: str, target: str, replacement: str) -> Optional[str]:
        """
        Try matching by code structure using AST diff (AST-based for Python).
        This is more robust than string matching as it handles whitespace, comments, and formatting differences.
        """
        try:
            # Parse all three: original content, target (before), and replacement (after)
            content_ast = ast.parse(content, filename='<content>')
            target_ast = ast.parse(target, filename='<target>')
            replacement_ast = ast.parse(replacement, filename='<replacement>')
            
            # Find matching node in content_ast that corresponds to target_ast
            matching_node = self._find_matching_ast_node(content_ast, target_ast)
            
            if matching_node is None:
                logger.debug(f"  AST match: No matching node found in content AST")
                return None
            
            # Replace the matching node with the replacement AST
            # The replacement_ast might be a single node or a module with multiple nodes
            replacement_node = self._extract_replacement_node(replacement_ast)
            
            if replacement_node is None:
                logger.debug(f"  AST match: Could not extract replacement node")
                return None
            
            # Create a new AST with the replacement
            new_ast = self._replace_ast_node(content_ast, matching_node, replacement_node)
            
            if new_ast is None:
                logger.debug(f"  AST match: Failed to replace node in AST")
                return None
            
            # Convert AST back to source code
            new_content = self._ast_to_source(new_ast)
            
            if new_content and new_content != content:
                logger.debug(f"  AST match: Successfully applied AST-based replacement")
                return new_content
            else:
                logger.debug(f"  AST match: AST replacement produced no changes or empty result")
                return None
                
        except SyntaxError as e:
            logger.debug(f"  AST match: Syntax error during parsing: {e}")
            return None
        except Exception as e:
            logger.debug(f"  AST match: Error during AST processing: {e}")
            return None
    
    def _find_matching_ast_node(self, content_ast: ast.AST, target_ast: ast.AST) -> Optional[ast.AST]:
        """
        Find a node in content_ast that structurally matches target_ast.
        Uses AST comparison to find matching functions, classes, or statements.
        """
        # Extract key nodes from target_ast (functions, classes, top-level statements)
        target_nodes = self._extract_key_nodes(target_ast)
        
        if not target_nodes:
            return None
        
        # Find matching nodes in content_ast
        content_nodes = self._extract_key_nodes(content_ast)
        
        for target_node in target_nodes:
            for content_node in content_nodes:
                if self._ast_nodes_match(content_node, target_node):
                    return content_node
        
        return None
    
    def _extract_key_nodes(self, tree: ast.AST) -> List[ast.AST]:
        """Extract key nodes (functions, classes, top-level statements) from AST."""
        nodes = []
        
        if isinstance(tree, ast.Module):
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    nodes.append(node)
                elif isinstance(node, ast.If) and node.test:  # Top-level if statements
                    nodes.append(node)
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):  # Top-level calls
                    nodes.append(node)
        else:
            # If it's not a module, try to extract from it directly
            if isinstance(tree, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                nodes.append(tree)
        
        return nodes
    
    def _ast_nodes_match(self, node1: ast.AST, node2: ast.AST) -> bool:
        """
        Check if two AST nodes structurally match.
        Compares by name, type, and key structural elements.
        """
        # Type must match
        if type(node1) != type(node2):
            return False
        
        # For named nodes (functions, classes), check name
        if isinstance(node1, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            if node1.name != node2.name:
                return False
        
        # For function definitions, also check signature similarity
        if isinstance(node1, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Compare argument counts
            args1 = node1.args.args if hasattr(node1, 'args') else []
            args2 = node2.args.args if hasattr(node2, 'args') else []
            if len(args1) != len(args2):
                return False
            
            # Compare argument names
            for arg1, arg2 in zip(args1, args2):
                if arg1.arg != arg2.arg:
                    return False
        
        # Additional structural checks: compare decorators
        if hasattr(node1, 'decorator_list') and hasattr(node2, 'decorator_list'):
            if len(node1.decorator_list) != len(node2.decorator_list):
                return False
        
        # If we get here, nodes are structurally similar enough
        return True
    
    def _extract_replacement_node(self, replacement_ast: ast.AST) -> Optional[ast.AST]:
        """Extract the actual node to use as replacement from the replacement AST."""
        if isinstance(replacement_ast, ast.Module):
            if len(replacement_ast.body) == 1:
                return replacement_ast.body[0]
            elif len(replacement_ast.body) > 1:
                # Multiple statements - return the first significant one
                for node in replacement_ast.body:
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                        return node
                return replacement_ast.body[0]
            else:
                return None
        else:
            return replacement_ast
    
    def _replace_ast_node(self, tree: ast.AST, old_node: ast.AST, new_node: ast.AST) -> Optional[ast.AST]:
        """
        Replace old_node with new_node in tree AST.
        Returns a new AST with the replacement, or None if replacement failed.
        """
        class NodeReplacer(ast.NodeTransformer):
            def __init__(self, old_node, new_node):
                self.old_node = old_node
                self.new_node = new_node
                self.replaced = False
                # Create a signature for the old node to match against
                self.old_node_signature = self._create_node_signature(old_node)
            
            def _create_node_signature(self, node):
                """Create a signature to identify a node (name, type, line number)."""
                sig = {
                    'type': type(node).__name__,
                    'lineno': getattr(node, 'lineno', None),
                    'end_lineno': getattr(node, 'end_lineno', None),
                }
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    sig['name'] = node.name
                return sig
            
            def _nodes_match(self, node1, node2):
                """Check if two nodes match by signature."""
                if node1 is node2:
                    return True
                sig1 = self._create_node_signature(node1)
                sig2 = self._create_node_signature(node2)
                return sig1 == sig2
            
            def visit(self, node):
                # Check if this is the node we want to replace
                if self._nodes_match(node, self.old_node):
                    self.replaced = True
                    # Copy location info from old node to new node
                    new_node_with_location = ast.copy_location(
                        ast.fix_missing_locations(ast.deepcopy(self.new_node)),
                        node
                    )
                    return new_node_with_location
                return self.generic_visit(node)
        
        replacer = NodeReplacer(old_node, new_node)
        # Deep copy the tree to avoid modifying the original
        tree_copy = ast.deepcopy(tree)
        # Fix missing locations in the copy
        tree_copy = ast.fix_missing_locations(tree_copy)
        new_tree = replacer.visit(tree_copy)
        
        if replacer.replaced:
            return new_tree
        else:
            return None
    
    def _ast_to_source(self, tree: ast.AST) -> Optional[str]:
        """
        Convert AST back to source code.
        Uses ast.unparse() if available (Python 3.9+), otherwise falls back to simpler approach.
        """
        try:
            # Try using ast.unparse (Python 3.9+)
            if hasattr(ast, 'unparse'):
                return ast.unparse(tree)
        except Exception as e:
            logger.debug(f"  ast.unparse failed: {e}")
        
        # Fallback: Use a simple code generator
        # This is a basic implementation - for production, consider using a library
        try:
            return self._simple_ast_to_source(tree)
        except Exception as e:
            logger.debug(f"  Simple AST to source failed: {e}")
            return None
    
    def _simple_ast_to_source(self, tree: ast.AST) -> str:
        """
        Simple AST to source converter (fallback).
        Since we require Python 3.10+, ast.unparse should always be available.
        This is just a safety fallback.
        """
        # Since we require Python 3.10+, ast.unparse should be available
        # If we reach here, something unexpected happened
        # Try one more time with ast.unparse in case it was a transient issue
        try:
            if hasattr(ast, 'unparse'):
                return ast.unparse(tree)
        except Exception:
            pass
        
        # If we still can't convert, raise an error
        raise NotImplementedError(
            "AST to source conversion requires ast.unparse (Python 3.9+). "
            f"Current Python version may not support it. Please ensure you're using Python 3.9 or later."
        )
    
    def _similarity_score(self, text1: str, text2: str) -> float:
        """Calculate similarity score between two texts (0.0 to 1.0)."""
        # Simple word-based similarity
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    def _try_js_line_based_match(self, content: str, target: str, replacement: str) -> Optional[str]:
        """
        Line-based matching for JavaScript/TypeScript files.
        Matches by finding similar line sequences and replacing them.
        More lenient than exact matching but more precise than fuzzy matching.
        """
        content_lines = content.split('\n')
        target_lines = [line.strip() for line in target.split('\n') if line.strip()]
        replacement_lines = replacement.split('\n')
        
        if not target_lines:
            return None
        
        # Find the best matching sequence of lines
        best_match_idx = -1
        best_match_score = 0.0
        window_size = len(target_lines)
        
        for i in range(len(content_lines) - window_size + 1):
            window = content_lines[i:i+window_size]
            window_stripped = [line.strip() for line in window if line.strip()]
            
            # Calculate similarity between target and window
            if len(window_stripped) != len(target_lines):
                continue
            
            matches = sum(1 for w, t in zip(window_stripped, target_lines) if w == t or w.endswith(t) or t.endswith(w))
            score = matches / len(target_lines) if target_lines else 0
            
            if score > best_match_score and score >= 0.8:  # 80% match threshold
                best_match_score = score
                best_match_idx = i
        
        if best_match_idx >= 0:
            # Replace the matched lines
            new_lines = content_lines[:best_match_idx] + replacement_lines + content_lines[best_match_idx+window_size:]
            return '\n'.join(new_lines)
        
        return None
    
    def _try_fuzzy_match(self, content: str, target: str, replacement: str) -> Optional[str]:
        """Try fuzzy matching with similarity scoring."""
        content_lines = content.split('\n')
        target_lines = target.split('\n')
        replacement_lines = replacement.split('\n')
        
        # Try sliding window approach
        best_match_idx = -1
        best_score = 0.0
        window_size = len(target_lines)
        
        for i in range(len(content_lines) - window_size + 1):
            window = '\n'.join(content_lines[i:i+window_size])
            normalized_window = self._normalize_whitespace(window)
            normalized_target = self._normalize_whitespace(target)
            
            # Calculate similarity
            score = self._similarity_score(normalized_window, normalized_target)
            
            # Also check if key identifiers match (function names, class names, etc.)
            window_identifiers = set(re.findall(r'\b(def|class|async def)\s+(\w+)', window))
            target_identifiers = set(re.findall(r'\b(def|class|async def)\s+(\w+)', target))
            
            if window_identifiers == target_identifiers:
                score += 0.3  # Boost score if identifiers match
            
            if score > best_score:
                best_score = score
                best_match_idx = i
        
        # If we found a good match (similarity > 0.7), apply it
        if best_match_idx >= 0 and best_score > 0.7:
            new_lines = content_lines[:best_match_idx] + replacement_lines + content_lines[best_match_idx+window_size:]
            return '\n'.join(new_lines)
        
        return None

    def _write_file(self, path: str, content: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def _prompt_qwen_apply(self, content: str, op: Dict[str, Any], retry_context: str = "") -> str:
        # Extract example based on file type
        example = self._get_example_for_file_type(content, op)
        
        # Detect file type for better instructions
        file_type_hint = ""
        if any(keyword in content for keyword in ['const ', 'let ', 'var ', 'function ', 'class ', '=>']):
            file_type_hint = "\nNOTE: This is JavaScript/TypeScript code. Match the code structure carefully, including semicolons, braces, and arrow functions."
        elif any(keyword in content for keyword in ['def ', 'import ', 'class ', 'if __name__']):
            file_type_hint = "\nNOTE: This is Python code. Match indentation and Python syntax carefully."
        
        prompt = f"""You are a senior software engineer. Your task is to apply a code change (operation) to a file.

FILE CONTENT:
```python
{content}
```

OPERATION TO APPLY:
- Type: {op.get('type')}
- Before (to be replaced):
{op.get('before')}
- After (replacement):
{op.get('after')}

INSTRUCTIONS:
1. Return the FULL content of the file with the change applied.
2. Maintain EXACT indentation for Python code. If you are replacing a block inside a function, ensure the new block matches the surrounding indentation level.
3. Preserve all comments and structure from the original file except for the specific area being modified.
4. DO NOT explain your changes. Return ONLY the code.
{retry_context}

EXAMPLE OF CORRECT APPLICATION:
{example}

ACTUAL TASK:
FILE TO EDIT:
{content}

OPERATION:
FIND THIS CODE BLOCK (match by structure, ignore whitespace):
{op['before']}

REPLACE IT WITH THIS:
{op['after']}

OUTPUT REQUIREMENTS:
- Return the ENTIRE file with ONLY this one change
- The "AFTER" block must appear exactly as specified
- All other code must remain unchanged
- Preserve original indentation style
- Match the code structure (semicolons, braces, etc.) exactly as in the original

COMPLETE UPDATED FILE (code only, no markdown):
"""
        self._ensure_client()
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0} # Deterministic
                }
            )
            if response.status_code == 200:
                data = response.json()
                raw_response = data.get("response", "").strip()
                
                # Validate and clean the response
                validated_content = self._validate_and_clean_response(raw_response, content, op)
                return validated_content
        except Exception as e:
            logger.error(f"Qwen execution failed: {e}")
            
        return content # Fail safe
    
    def _get_example_for_file_type(self, content: str, op: Dict[str, Any]) -> str:
        """Generate an example based on file type and operation."""
        if 'def ' in op.get('before', '') or 'class ' in op.get('before', ''):
            # Python function/class example
            return """EXAMPLE:
BEFORE CODE:
@app.post("/users")
def create_user(user: User):
    users_db[user.id] = user
    return user

AFTER CODE:
@app.post("/users", status_code=201)
def create_user(user: User):
    users_db[user.id] = user
    return user

CORRECT OUTPUT: The entire file with ONLY the decorator changed (status_code=201 added)."""
        elif 'status_code' in op.get('after', '').lower():
            # FastAPI status code example
            return """EXAMPLE:
BEFORE CODE:
@app.post("/items")
def create_item(item: Item):
    return item

AFTER CODE:
@app.post("/items", status_code=201)
def create_item(item: Item):
    return item

CORRECT OUTPUT: The entire file with ONLY status_code=201 added to the decorator."""
        else:
            # Generic example
            return """EXAMPLE:
BEFORE CODE:
def example():
    return "old"

AFTER CODE:
def example():
    return "new"

CORRECT OUTPUT: The entire file with ONLY the return statement changed."""
    
    def _validate_and_clean_response(self, response: str, original_content: str, op: Dict[str, Any]) -> str:
        """Validate and clean the Qwen response before using it."""
        # Remove markdown code blocks if present
        if "```" in response:
            # Extract code from markdown
            lines = response.split('\n')
            code_lines = []
            in_code_block = False
            for line in lines:
                if line.strip().startswith('```'):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    code_lines.append(line)
            if code_lines:
                response = '\n'.join(code_lines)
        
        # Remove leading/trailing whitespace but preserve structure
        response = response.strip()
        
        # Validate that the "after" block is present
        after_block = op.get('after', '').strip()
        if after_block and after_block not in response:
            # Try normalized comparison
            normalized_response = self._normalize_whitespace(response)
            normalized_after = self._normalize_whitespace(after_block)
            if normalized_after not in normalized_response:
                logger.warning("Qwen response may not contain the expected 'after' block")
                # Still return it, but log the warning
        
        # Validate Python syntax if it's a Python file
        if response.count('def ') > 0 or response.count('class ') > 0:
            try:
                ast.parse(response)
                logger.debug("Qwen response passed Python syntax validation")
            except SyntaxError as e:
                logger.warning(f"Qwen response has syntax errors: {e}")
                # Try to fix common issues
                response = self._attempt_syntax_fix(response, original_content, op)
        
        # Ensure response is not empty and different from original
        if not response or response == original_content:
            logger.warning("Qwen response is empty or unchanged, using original")
            return original_content
        
        return response
    
    def _attempt_syntax_fix(self, response: str, original_content: str, op: Dict[str, Any]) -> str:
        """Attempt to fix common syntax errors in Qwen response."""
        # Common fixes
        fixes_applied = []
        
        # Fix: Remove extra closing braces/brackets
        if response.count('}') > original_content.count('}'):
            # Python doesn't use }, but check for other languages
            pass
        
        # Fix: Ensure proper indentation
        lines = response.split('\n')
        fixed_lines = []
        for i, line in enumerate(lines):
            # Basic indentation check - if line starts with keyword, ensure it's not indented incorrectly
            if line.strip().startswith(('def ', 'class ', 'if ', 'for ', 'while ')):
                # Check if previous line suggests this should be at module level
                if i > 0 and not lines[i-1].strip().endswith(':'):
                    # Might need to dedent
                    if line.startswith('    ') and not original_content.split('\n')[min(i, len(original_content.split('\n'))-1)].startswith('    '):
                        line = line.lstrip()
                        fixes_applied.append(f"Fixed indentation on line {i+1}")
            fixed_lines.append(line)
        
        if fixes_applied:
            logger.info(f"Applied syntax fixes: {', '.join(fixes_applied)}")
            return '\n'.join(fixed_lines)
        
        # If we can't fix it, return original (safer than broken code)
        logger.warning("Could not fix syntax errors, returning original content")
        return original_content
    
    def _validate_fix_applied(self, new_content: str, target: str, replacement: str) -> bool:
        """Validate that the fix was actually applied correctly."""
        # Check 1: Replacement should be in new content
        normalized_new = self._normalize_whitespace(new_content)
        normalized_replacement = self._normalize_whitespace(replacement)
        
        if normalized_replacement not in normalized_new:
            logger.debug("Validation: Replacement block not found in new content")
            return False
        
        # Check 2: File should be valid (basic check)
        if len(new_content) < 10:  # Too short, probably invalid
            logger.debug("Validation: New content too short")
            return False
        
        return True

    def _validate_syntax(self, content: str, file_path: str) -> Optional[str]:
        """
        Validate syntax of the code based on file extension.
        Returns error message string if invalid, None if valid.
        """
        if not content:
            return "Empty content"
            
        is_python = file_path.endswith('.py')
        
        if is_python:
            try:
                ast.parse(content)
                return None
            except SyntaxError as e:
                return f"SyntaxError: {e.msg} (Line {e.lineno})"
            except Exception as e:
                return f"Parse Error: {e}"
        
        return None
