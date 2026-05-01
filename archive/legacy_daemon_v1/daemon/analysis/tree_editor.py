import difflib
import logging
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger("hybrid-reviewer")

try:
    from tree_sitter import Language, Parser, Node
    import tree_sitter_python
    import tree_sitter_javascript
    TREE_SITTER_AVAILABLE = True
except Exception as e:
    logger.error(f"Tree-sitter imports failed: {e}")
    TREE_SITTER_AVAILABLE = False
    Language = None
    Parser = None
    Node = None

logger = logging.getLogger("hybrid-reviewer")

class TreeEditor:
    """
    Deterministic Structural Editor using Tree-Sitter.
    Replaces fuzzy string matching with AST-based node replacement.
    """
    def __init__(self):
        try:
            if TREE_SITTER_AVAILABLE:
                self.PY_LANG = Language(tree_sitter_python.language())
                self.JS_LANG = Language(tree_sitter_javascript.language())
                self.parser = Parser()
            else:
                self.PY_LANG = None
                self.JS_LANG = None
                self.parser = None
        except Exception as e:
            logger.error(f"TreeEditor init failed: {e}")
            self.PY_LANG = None
            self.JS_LANG = None
            self.parser = None

    def _get_lang(self, file_ext: str):
        if file_ext in ['.py']:
            return self.PY_LANG
        elif file_ext in ['.js', '.jsx', '.ts', '.tsx']:
            return self.JS_LANG
        return None

    def replace(self, full_code: str, target_snippet: str, replacement_snippet: str, file_ext: str) -> Tuple[str, bool]:
        """
        Attempt to replace 'target_snippet' with 'replacement_snippet' in 'full_code'.
        Uses CST to find the best matching node masked by whitespace flexibility.
        """
        if not TREE_SITTER_AVAILABLE:
             return full_code, False

        lang = self._get_lang(file_ext)
        if not lang:
            return full_code, False # Fallback to fuzzy or fail

        # self.parser.set_language(lang) <- OLD API
        # NEW API (v0.22+): Parser(lang) OR parser = Parser(); parser.language = lang
        try:
            self.parser.language = lang
        except AttributeError:
             # Fallback if property setter not available, try set_language again or re-init?
             # If set_language missing, likely 'language' property is the way.
             # Or, re-init parser: self.parser = Parser(lang) if constructor supports it.
             pass
        # However, the error says 'set_language' is missing. 
        # Let's try assigning to .language property which is the modern standard.

        tree = self.parser.parse(bytes(full_code, "utf8"))
        root_node = tree.root_node
        
        # 1. Normalize target snippet (remove strict indentation requirements)
        normalized_target = self._normalize_whitespace(target_snippet)
        
        # 2. Walk tree to find best match
        best_node = None
        best_ratio = 0.0
        
        cursor = tree.walk()
        
        visited_nodes = []
        stack = [root_node]
        
        # Simple DFS traversal to find a node whose text matches normalized target
        while stack:
            node = stack.pop()
            
            # Avoid extremely small nodes (like punctuation) unless target is small
            if len(target_snippet) > 5 and node.end_byte - node.start_byte < 5:
                pass
            else:
                node_text = full_code[node.start_byte:node.end_byte]
                normalized_node = self._normalize_whitespace(node_text)
                
                # Check for exact normalized match
                if normalized_node == normalized_target:
                    best_node = node
                    best_ratio = 1.0
                    break
                
                # Fuzzy fallback if exact match fails
                # ratio = difflib.SequenceMatcher(None, normalized_node, normalized_target).ratio()
                # if ratio > best_ratio and ratio > 0.95:
                #    best_node = node
                #    best_ratio = ratio
            
            stack.extend(node.children)
            
        if best_node:
            logger.info(f"TreeEditor: Found structural match at bytes {best_node.start_byte}-{best_node.end_byte}")
            
            # 3. Perform Byte Replacement
            start_b = best_node.start_byte
            end_b = best_node.end_byte
            
            # Preserve indentation of the replaced node?
            # If the replacement snippet has NO indentation, we should inject the node's indentation?
            # For now, simplistic replacement. 
            
            # Logic: If target_context is a full block, replacement usually provides indentation.
            # But the LLM often strips outer indentation.
            
            # Check indentation of the start line
            node_start_line_idx = best_node.start_point.row
            lines = full_code.split('\n')
            if 0 <= node_start_line_idx < len(lines):
                line_content = lines[node_start_line_idx]
                # improved indent detection: take everything up to the first non-whitespace char
                indentation = ""
                for char in line_content:
                    if char.isspace():
                        indentation += char
                    else:
                        break
                
                # Smart Re-indentation Strategy:
                # 1. Detect relative structure of replacement
                # 2. Strip base indentation from replacement (normalize to 0)
                # 3. Apply target indentation
                replacement_snippet = self.smart_reindent(replacement_snippet, indentation)
                logger.info(f"TreeEditor: Re-indented replacement to match context (Depth: {len(indentation)})")
            
            # Reconstruct string
            full_bytes = bytes(full_code, "utf8")
            new_bytes = full_bytes[:start_b] + bytes(replacement_snippet, "utf8") + full_bytes[end_b:]
            return new_bytes.decode("utf8"), True
            
        logger.info("TreeEditor: No structural match found.")
        return full_code, False

    def smart_reindent(self, snippet: str, target_indent: str) -> str:
        """
        Adjusts the indentation of 'snippet' to match 'target_indent'.
        Handles multi-line snippets by detecting relative indentation.
        """
        lines = snippet.split('\n')
        if not lines:
            return snippet
            
        # 1. Detect base indentation of the snippet (dedent logic)
        # Find first non-empty line to establish base
        base_indent = None
        for line in lines:
            if line.strip():
                curr_indent = ""
                for char in line:
                    if char.isspace():
                        curr_indent += char
                    else:
                        break
                base_indent = curr_indent
                break
        
        if base_indent is None:
             return snippet # All empty lines

        # 2. Reconstruct with new target indent
        new_lines = []
        for line in lines:
            if not line.strip():
                # Empty line - preserve emptiness or just blank string?
                # Matching standard editors: empty line has 0 chars.
                new_lines.append("") 
                continue
            
            # If line starts with base_indent, replace it with target_indent
            if line.startswith(base_indent):
                # Preserve relative indentation beyond base
                relative_part = line[len(base_indent):]
                new_line = target_indent + relative_part
                new_lines.append(new_line)
            else:
                # Fallback: if line is less indented than base (weird), just prepend target
                new_lines.append(target_indent + line.lstrip())
                
        return "\n".join(new_lines)

    def _normalize_whitespace(self, s: str) -> str:
        return "".join(s.split())
