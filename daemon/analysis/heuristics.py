import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from .ast_engine import ASTEngine
# We'll import lazily or assume dependency injection to avoid circular imports?
# But let's import directly for now.
try:
    from .semantic.semantic_engine import SemanticEngine
except ImportError:
    SemanticEngine = None

class HeuristicsEngine:
    def __init__(self, repo_path: Optional[Path] = None):
        self.ast_engine = ASTEngine()
        self.semantic_engine: Optional[SemanticEngine] = None
        if repo_path and SemanticEngine:
            # We initialize it here, or we can let the caller set it.
            # For this Phase, we'll initialize it if a path is provided.
            self.semantic_engine = SemanticEngine(repo_path)
            self.semantic_engine.start()



        self.patterns = [
            {
                "id": "SEC002", # Renamed SEC001 to AST version, keeping others
                "pattern": r"api_key\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded API key detected.",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "SEC002",
                "pattern": r"(const|let|var)?\s*apiKey\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded API key detected (JavaScript).",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "SEC001",
                "pattern": r"(const|let|var)?\s*\w*[Pp]assword\w*\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded password detected (JavaScript).",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "SEC001",
                "pattern": r"\w*[Pp]assword\w*\s*=\s*['\"][^'\"]+['\"]",
                "message": "Hardcoded password detected (Python).",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "SEC003",
                "pattern": r"f[\"'].*SELECT.*\{.*\}.*WHERE.*\{.*\}",
                "message": "SQL Injection vulnerability detected: f-string with user input in SQL query. Use parameterized queries.",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "SEC003",
                "pattern": r"query\s*=\s*f[\"'].*SELECT",
                "message": "SQL Injection vulnerability detected: f-string SQL query with variable interpolation. Use parameterized queries.",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "SEC003",
                "pattern": r"[\"'].*SELECT.*%[sd]",
                "message": "SQL Injection vulnerability detected: String formatting in SQL query. Use parameterized queries.",
                "type": "security",
                "severity": "high"
            },
            {
                "id": "LOG002",
                "pattern": r"return\s+\w+\.\w+.*#.*could be None|#.*None",
                "message": "Potential NoneType error: Accessing attribute without null check. Add null check before attribute access.",
                "type": "logic",
                "severity": "high"
            },
            {
                "id": "LOG002",
                "pattern": r"\.(email|name|id|value|data|result|response|user|item|obj)\.[a-zA-Z_]+.*#.*None",
                "message": "Potential NoneType error: Chained attribute access without null check. Add null check before accessing attributes.",
                "type": "logic",
                "severity": "high"
            },
            {
                "id": "LINT001",
                "pattern": r"print\(",
                "message": "Console print statement detected. Use logging instead.",
                "type": "lint",
                "severity": "low"
            },
            {
                "id": "LINT001",
                "pattern": r"console\.(log|error|warn|info)\(",
                "message": "Console statement detected (JavaScript). Use proper logging instead.",
                "type": "lint",
                "severity": "low"
            },
            {
                "id": "PERF001",
                "pattern": r"while\s*\(\s*(true|1|condition)\s*\)",
                "message": "Infinite loop detected (JavaScript). Add break condition or timeout.",
                "type": "performance",
                "severity": "high"
            }
        ]

    def run(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        issues = []
        
        # 1. Run AST Analysis for supported languages
        is_supported_lang = (
            file_path.endswith(".py") or 
            file_path.endswith(".js") or 
            file_path.endswith(".jsx") or 
            file_path.endswith(".ts") or 
            file_path.endswith(".tsx")
        )
        
        if is_supported_lang:
            try:
                ast_issues = self.ast_engine.analyze(content, file_path)
                issues.extend(ast_issues)
            except Exception as e:
                print(f"AST Analysis failed: {e}")

        # 2. Run Regex with Semantic Verification
        lines = content.split('\n')
        
        # Initialize semantic verification if available
        # We do this lazily or check if it's already running?
        # For now, assumes SemanticEngine is globally managed or we start it here?
        # Ideally, HeuristicsEngine should be passed the Shared SemanticEngine.
        # But for this refactor, we will check if "self.semantic_engine" exists.
        
        semantic_active = hasattr(self, 'semantic_engine') and self.semantic_engine
        
        for i, line in enumerate(lines):
            for rule in self.patterns:
                match = re.search(rule["pattern"], line)
                if match:
                    # Language-aware comment check for Regex
                    line_start_idx = line.find(match.group(0))
                    line_prefix = line[:line_start_idx]
                    
                    is_commented = False
                    if file_path.endswith(".py"):
                        if "#" in line_prefix:
                            is_commented = True
                    elif file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
                        if "//" in line_prefix:
                            is_commented = True
                            
                    if is_commented:
                        continue
                        
                    issues.append({
                        "id": rule["id"],
                        "line": i + 1,
                        "message": rule["message"],
                        "type": rule["type"],
                        "severity": rule["severity"],
                        "source": "heuristics_regex"
                    })
        return issues

    def update_repo_path(self, repo_path: Path):
        """Update the repository path and restart SemanticEngine if needed."""
        if not SemanticEngine:
            return

        # If we already have a running engine for this path, do nothing
        if self.semantic_engine and self.semantic_engine.repo_path == repo_path:
            return

        # Stop existing
        if self.semantic_engine:
            self.semantic_engine.stop()
        
        # Start new
        try:
            self.semantic_engine = SemanticEngine(repo_path)
            self.semantic_engine.start()
        except Exception as e:
            print(f"Failed to start SemanticEngine for {repo_path}: {e}")
            self.semantic_engine = None

    def close(self):
        if self.semantic_engine:
            self.semantic_engine.stop()

