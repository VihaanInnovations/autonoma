import hashlib
from typing import List, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)

try:
    from tree_sitter import Language, Parser, Query, QueryCursor
    import tree_sitter_python
    import tree_sitter_javascript
    import tree_sitter_java
    import tree_sitter_cpp
    import tree_sitter_go
    import tree_sitter_rust
    TREE_SITTER_AVAILABLE = True
except Exception as e:
    logger.warning(f"Tree-sitter imports failed: {e}. AST analysis will be disabled.")
    TREE_SITTER_AVAILABLE = False
    Language = None
    Parser = None
    Query = None
    QueryCursor = None

class ASTEngine:
    def __init__(self):
        # HARD DISABLE TREE-SITTER due to environment binary incompatibility
        # This forces Native AST fallback which is robust.
        self.parser = None
        self.PY_LANGUAGE = None
        self.JS_LANGUAGE = None
        self.JAVA_LANGUAGE = None
        self.CPP_LANGUAGE = None
        self.GO_LANGUAGE = None
        self.RUST_LANGUAGE = None
        logger.warning("Tree-Sitter hard-disabled for stability. Using Native AST.")
        return

        try:
            self.PY_LANGUAGE = Language(tree_sitter_python.language())
            self.JS_LANGUAGE = Language(tree_sitter_javascript.language())
            self.JAVA_LANGUAGE = Language(tree_sitter_java.language())
            self.CPP_LANGUAGE = Language(tree_sitter_cpp.language())
            self.GO_LANGUAGE = Language(tree_sitter_go.language())
            self.RUST_LANGUAGE = Language(tree_sitter_rust.language())
            self.parser = Parser(self.PY_LANGUAGE) # Default to PY, switch on fly
        except Exception as e:
            print(f"Failed to initialize Tree-sitter: {e}")
            self.parser = None
            self.PY_LANGUAGE = None
            self.JS_LANGUAGE = None
            self.JAVA_LANGUAGE = None
            self.CPP_LANGUAGE = None
            self.GO_LANGUAGE = None
            self.RUST_LANGUAGE = None
            
    def cleanup(self):
        """
        Explicitly release resources.
        """
        self.parser = None
        self.PY_LANGUAGE = None
        self.JS_LANGUAGE = None
        self.JAVA_LANGUAGE = None
        self.CPP_LANGUAGE = None
        self.GO_LANGUAGE = None
        self.RUST_LANGUAGE = None

    def compute_semantic_hash(self, content: str) -> str:
        """
        Computes a hash of the AST structure, ignoring comments and formatting.
        Note: We use Python parser by default for hashing if type unknown, 
        or we could infer from context, but cache.py doesn't pass file extension easily yet.
        For now, let's try to parse as Python, if it fails heavily, maybe fallback to bytes?
        Actually, for hash, if we parse JS with PY parser, it might produce garbage tree but stable garbage.
        Better: Fallback to byte hash if language uncertain? 
        Let's keep simple: Try to parse with current parser state or default.
        """
        if not self.parser:
            return hashlib.sha256(content.encode('utf-8')).hexdigest()
            
        tree = self.parser.parse(bytes(content, "utf8"))
        semantic_str = self._get_semantic_string(tree.root_node)
        return hashlib.sha256(semantic_str.encode('utf-8')).hexdigest()

    def _get_semantic_string(self, node) -> str:
        if node.type == 'comment':
            return ""
            
        parts = [node.type]
        if node.child_count == 0:
            if node.type in ['identifier', 'string_content', 'integer', 'float', 'number']: # 'number' is common in JS
                parts.append(f":{node.text.decode('utf8')}")

        for child in node.children:
            child_str = self._get_semantic_string(child)
            if child_str:
                parts.append(child_str)
                
        return f"({' '.join(parts)})"

    def analyze(self, content: str, file_path: str = "") -> List[Dict[str, Any]]:
        # Fallback to Native Python AST if Tree-Sitter is unavailable and it's a Python file
        if not self.parser and file_path.endswith('.py'):
            try:
                return self._analyze_python_native(content)
            except Exception as e:
                logger.error(f"Native Python AST failed: {e}")
                return []
        
        if not self.parser:
            return []

        # Switch Language based on extension
        lang = self.PY_LANGUAGE
        if file_path.endswith(".js") or file_path.endswith(".ts") or file_path.endswith(".jsx") or file_path.endswith(".tsx"):
            if self.JS_LANGUAGE:
                lang = self.JS_LANGUAGE
        elif file_path.endswith(".java"):
            if self.JAVA_LANGUAGE:
                lang = self.JAVA_LANGUAGE
        elif file_path.endswith(".cpp") or file_path.endswith(".cxx") or file_path.endswith(".cc") or file_path.endswith(".h") or file_path.endswith(".hpp"):
            if self.CPP_LANGUAGE:
                lang = self.CPP_LANGUAGE
        elif file_path.endswith(".go"):
            if self.GO_LANGUAGE:
                lang = self.GO_LANGUAGE
        elif file_path.endswith(".rs"):
            if self.RUST_LANGUAGE:
                lang = self.RUST_LANGUAGE
        
        # Update parser language
        if lang != self.parser.language:
             self.parser = Parser(lang)

        issues = []
        try:
            tree = self.parser.parse(bytes(content, "utf8"))
        except Exception as e:
            # If parsing fails (e.g. binary issue), try native fallback for Python
            if file_path.endswith('.py'):
                 return self._analyze_python_native(content)
            print(f"Parsing failed: {e}")
            return []
        
        # 1. Detect Infinite Loops (while True)
        loop_query_str = ""
        if lang == self.PY_LANGUAGE:
            loop_query_str = """(while_statement condition: (true)) @loop"""
        elif lang == self.JS_LANGUAGE:
            loop_query_str = """(while_statement condition: (parenthesized_expression (true))) @loop"""
        elif lang == self.JAVA_LANGUAGE:
            loop_query_str = """(while_statement condition: (parenthesized_expression (true))) @loop"""
        elif lang == self.CPP_LANGUAGE:
            loop_query_str = """(while_statement condition: (condition_clause (true))) @loop"""
        elif lang == self.GO_LANGUAGE:
            loop_query_str = """(for_statement (block)) @loop""" 
        elif lang == self.RUST_LANGUAGE:
            loop_query_str = """(loop_expression) @loop"""

        try:
            infinite_loop_query = Query(lang, loop_query_str)
            cursor = QueryCursor(infinite_loop_query)
            captures = cursor.captures(tree.root_node)
            
            # Helper to process captures
            nodes = []
            if isinstance(captures, dict):
                nodes = captures.get('loop', [])
            elif isinstance(captures, list):
                nodes = [n for n, name in captures if name == 'loop']

            for node in nodes:
                 issues.append({
                    "id": "PERF001",
                    "line": node.start_point.row + 1,
                    "message": "Infinite loop detected (AST-verified).",
                    "type": "performance",
                    "severity": "medium",
                    "source": "ast_engine_ts"
                })
        except Exception as e:
            pass # print(f"Loop query failed: {e}")

        # 2. Detect Hardcoded Passwords
        pw_query_str = ""
        if lang == self.PY_LANGUAGE:
            pw_query_str = """(assignment left: (identifier) @var_name right: (string) @val (#match? @var_name "password")) @assignment"""
        elif lang == self.JS_LANGUAGE:
            pw_query_str = """(variable_declarator name: (identifier) @var_name value: (string) @val (#match? @var_name "password")) @assignment"""
        elif lang == self.JAVA_LANGUAGE:
            pw_query_str = """(variable_declarator name: (identifier) @var_name value: (string_literal) @val (#match? @var_name "password")) @assignment"""
        
        try:
            if pw_query_str:
                password_query = Query(lang, pw_query_str)
                cursor_pw = QueryCursor(password_query)
                captures_pw = cursor_pw.captures(tree.root_node)
                
                nodes_pw = []
                if isinstance(captures_pw, dict):
                    nodes_pw = captures_pw.get('assignment', [])
                elif isinstance(captures_pw, list):
                    nodes_pw = [n for n, name in captures_pw if name == 'assignment']

                for node in nodes_pw:
                    issues.append({
                        "id": "SEC001",
                        "line": node.start_point.row + 1,
                        "message": "Hardcoded password assignment detected (AST-verified).",
                        "type": "security",
                        "severity": "high",
                        "source": "ast_engine_ts"
                    })
        except Exception:
             pass

        return issues

    def _analyze_python_native(self, content: str) -> List[Dict[str, Any]]:
        """
        Native Python AST analysis using standard library 'ast'.
        Robust fallback when tree-sitter is broken.
        """
        import ast
        issues = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            # SEC001: Hardcoded Secrets
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id.lower()
                        secret_keywords = ['password', 'api_key', 'secret', 'token', 'key', 'cred', 'passwd']
                        if any(k in var_name for k in secret_keywords):
                            if isinstance(node.value, (ast.Constant, ast.Str)): # Python 3.8+ uses Constant
                                val = node.value.s if isinstance(node.value, ast.Str) else node.value.value
                                if isinstance(val, str) and not val.startswith("os.getenv"):
                                    issues.append({
                                        "id": "SEC001" if "password" in var_name or "secret" in var_name else "SEC002",
                                        "line": node.lineno,
                                        "message": f"Hardcoded secret '{target.id}' detected (Native AST).",
                                        "type": "security",
                                        "severity": "high",
                                        "source": "ast_engine_native"
                                    })
            # SEC003: SQL Injection (Robust Check)
            if isinstance(node, ast.Call):
                # Check for .execute() or .executemany()
                if isinstance(node.func, ast.Attribute) and node.func.attr in ['execute', 'executemany']:
                    if node.args:
                        arg0 = node.args[0]
                        is_vuln = False
                        # 1. f-strings (JoinedStr)
                        if isinstance(arg0, ast.JoinedStr):
                             is_vuln = True
                        # 2. Binary Ops (string concatenation)
                        elif isinstance(arg0, ast.BinOp) and isinstance(arg0.op, ast.Add):
                             is_vuln = True
                        # 3. % formatting
                        elif isinstance(arg0, ast.BinOp) and isinstance(arg0.op, ast.Mod):
                             is_vuln = True
                        
                        if is_vuln:
                            issues.append({
                                "id": "SEC003",
                                "line": node.lineno,
                                "message": f"SQL Injection vulnerability: unsafe data in SQL {node.func.attr} call (Native AST).",
                                "type": "security",
                                "severity": "critical",
                                "source": "ast_engine_native"
                            })

            # PERF001: Infinite Loop (while True)
            if isinstance(node, ast.While):
                if isinstance(node.test, (ast.Constant, ast.NameConstant)):
                    val = node.test.value
                    if val is True:
                        issues.append({
                            "id": "PERF001",
                            "line": node.lineno,
                            "message": "Infinite loop detected (Native AST).",
                            "type": "performance",
                            "severity": "medium",
                            "source": "ast_engine_native"
                        })
        return issues
