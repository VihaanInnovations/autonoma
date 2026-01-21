import hashlib
import json
import ast
from typing import Dict, Any, List, Optional

class Summarizer:
    """
    Deterministic Summarization Layer.
    - Hashes filenames.
    - Folds code content (summarizes/truncates).
    - Strips identifiers.
    - Includes dependency graph context (fixtures, utilities).
    """
    
    def __init__(self):
        self.file_map = {} # hash -> absolute_path

    def summarize_request(
        self, 
        task_id: str, 
        goal: str, 
        files: List[Dict[str, str]],
        dependency_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Summarize a request for Remote Brains.
        
        Args:
            task_id: Unique task identifier
            goal: Task goal/description
            files: List of files with path and content
            dependency_context: Optional dependency graph context (fixtures, utilities, etc.)
        """
        self.file_map = {} # Reset for new request
        hashed_context = []
        
        for f in files:
            abs_path = f["path"]
            content = f["content"]
            file_type = f.get("type", "unknown")  # "source", "test", "fixture", "utility", etc.
            
            # Hash filename
            f_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:12] # Short hash
            self.file_map[f_hash] = abs_path
            
            # Extract file structure and line number information
            file_structure = self._extract_file_structure(content, abs_path)
            line_info = self._extract_line_info(content)
            
            hashed_context.append({
                "file_hash": f_hash,
                "file_type": file_type,  # Add file type for clarity
                "file_path_hint": self._get_file_path_hint(abs_path),  # Add hint for LLM
                "line_info": line_info,  # Total lines, line ranges
                "file_structure": file_structure,  # Functions, classes with line numbers
                "content_summary": self._summarize_content(content)
            })
        
        # Build summary with dependency context
        summary = {
            "task_id": task_id,
            "goal": goal,
            "context": hashed_context
        }
        
        # Add dependency graph context if provided
        if dependency_context:
            # Hash fixture and utility file paths for privacy
            hashed_fixtures = []
            for fixture_file in dependency_context.get("fixtures", []):
                f_hash = hashlib.sha256(fixture_file.encode()).hexdigest()[:12]
                self.file_map[f_hash] = fixture_file
                hashed_fixtures.append(f_hash)
            
            hashed_utilities = []
            for util_file in dependency_context.get("utilities", []):
                f_hash = hashlib.sha256(util_file.encode()).hexdigest()[:12]
                self.file_map[f_hash] = util_file
                hashed_utilities.append(f_hash)
            
            summary["dependency_context"] = {
                "fixtures": hashed_fixtures,
                "fixture_definitions": dependency_context.get("fixture_definitions", {}),
                "utilities": hashed_utilities,
                "utility_signatures": dependency_context.get("utility_signatures", {}),
                "env_context": dependency_context.get("env_context", {}),
                "related_tests": dependency_context.get("related_tests", []),
                "config_files": dependency_context.get("config_files", [])
            }
            
        return summary

    def _summarize_content(self, content: str) -> str:
        # Simple implementation: First 100 lines + truncation warning
        # In a real system, this would be smarter (AST-based symbols).
        # For now, adhering to "Minimal, compressed, intent-preserving".
        lines = content.split('\n')
        if len(lines) > 200:
            return "\n".join(lines[:200]) + "\n... [TRUNCATED 200/{} lines] ...".format(len(lines))
        return content
    
    def _get_file_path_hint(self, abs_path: str) -> str:
        """Extract a hint from the file path to help LLM identify file type."""
        path_lower = abs_path.lower()
        if 'test' in path_lower or 'tests' in path_lower:
            return "TEST_FILE"
        elif 'src' in path_lower or 'source' in path_lower or 'app.py' in path_lower or 'main.py' in path_lower:
            return "SOURCE_FILE"
        elif 'conftest' in path_lower or 'fixture' in path_lower:
            return "FIXTURE_FILE"
        elif 'util' in path_lower or 'helper' in path_lower:
            return "UTILITY_FILE"
        else:
            return "OTHER"
    
    def _extract_line_info(self, content: str) -> Dict[str, Any]:
        """Extract line number information from file content."""
        lines = content.split('\n')
        total_lines = len(lines)
        
        return {
            "total_lines": total_lines,
            "line_range": f"1-{total_lines}",
            "note": f"This file has {total_lines} lines. Use line numbers 1-{total_lines} when referencing this file."
        }
    
    def _extract_file_structure(self, content: str, file_path: str) -> Dict[str, Any]:
        """
        Extract file structure (functions, classes, top-level statements) with line numbers.
        Enhanced to include more detailed AST information for better line number accuracy.
        """
        structure = {
            "functions": [],
            "classes": [],
            "top_level_statements": [],
            "code_blocks": []  # If/for/while blocks with line ranges
        }
        
        # Only parse Python files
        if not file_path.endswith('.py'):
            return structure
        
        try:
            tree = ast.parse(content, filename=file_path)
            lines = content.split('\n')
            
            # Track top-level statements (assignments, imports, etc.)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_info = {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": getattr(node, 'end_lineno', node.lineno),
                        "type": "async" if isinstance(node, ast.AsyncFunctionDef) else "function"
                    }
                    
                    # Extract decorators
                    if node.decorator_list:
                        decorators = []
                        for dec in node.decorator_list:
                            if isinstance(dec, ast.Name):
                                decorators.append(dec.id)
                            elif isinstance(dec, ast.Attribute):
                                decorators.append(f"{dec.attr}")
                            elif isinstance(dec, ast.Call):
                                if isinstance(dec.func, ast.Attribute):
                                    decorators.append(f"{dec.func.attr}()")
                                elif isinstance(dec.func, ast.Name):
                                    decorators.append(f"{dec.func.id}()")
                        func_info["decorators"] = decorators
                    
                    # Extract arguments
                    if hasattr(node, 'args'):
                        args = [arg.arg for arg in node.args.args]
                        func_info["args"] = args
                    
                    structure["functions"].append(func_info)
                
                elif isinstance(node, ast.ClassDef):
                    class_info = {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": getattr(node, 'end_lineno', node.lineno)
                    }
                    structure["classes"].append(class_info)
            
            # Extract top-level statements (module-level code)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    # Assignment statements
                    start_line = node.lineno
                    end_line = getattr(node, 'end_lineno', start_line)
                    # Get a snippet of the code for context
                    snippet = lines[start_line - 1][:50] if start_line <= len(lines) else ""
                    structure["top_level_statements"].append({
                        "type": "assignment",
                        "line": start_line,
                        "end_line": end_line,
                        "snippet": snippet.strip()
                    })
                elif isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                    # Control flow blocks
                    start_line = node.lineno
                    end_line = getattr(node, 'end_lineno', start_line)
                    node_type = type(node).__name__.lower()
                    structure["code_blocks"].append({
                        "type": node_type,
                        "line": start_line,
                        "end_line": end_line
                    })
            
            # Sort all structures by line number for easier reference
            structure["functions"].sort(key=lambda x: x["line"])
            structure["classes"].sort(key=lambda x: x["line"])
            structure["top_level_statements"].sort(key=lambda x: x["line"])
            structure["code_blocks"].sort(key=lambda x: x["line"])
        
        except SyntaxError:
            # If file has syntax errors, return empty structure
            pass
        except Exception:
            # If parsing fails for any reason, return empty structure
            pass
        
        return structure

    def get_file_map(self) -> Dict[str, str]:
        return self.file_map
