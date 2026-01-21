"""
Dependency Graph Indexer

Builds complete dependency graph for a codebase including:
- Code files and their imports
- Test files and their dependencies
- Test fixtures (conftest.py, pytest.ini)
- Config files (env, yaml, json)
- Shared utilities

This is the "moat" - cloud tools can't see the full graph.
"""

import logging
import ast
import re
from typing import Dict, Set, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DependencyGraph:
    """
    Builds complete dependency graph for a codebase.
    
    Nodes: Files, functions, classes, tests, fixtures, configs
    Edges: Imports, calls, fixtures, config references
    """
    
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)
        self.graph: Dict[str, Set[str]] = {}  # node -> {dependencies}
        self.reverse_graph: Dict[str, Set[str]] = {}  # node -> {dependents}
        self.node_metadata: Dict[str, Dict] = {}  # node -> metadata
        
    def build(self):
        """Build complete dependency graph."""
        logger.info(f"Building dependency graph for {self.repo_path}")
        
        # 1. Index code files
        self._index_code_files()
        
        # 2. Index test files
        self._index_test_files()
        
        # 3. Index test fixtures (enhanced with fixture definitions)
        self._index_test_fixtures()
        
        # 4. Index utility files (enhanced with signatures)
        self._index_utilities()
        
        # 5. Index config files
        self._index_config_files()
        
        # 6. Build reverse graph (for impact analysis)
        self._build_reverse_graph()
        
        logger.info(f"Dependency graph built: {len(self.graph)} nodes")
    
    def _index_code_files(self):
        """Index Python/Go/Java code files and their dependencies."""
        for file_path in self._find_code_files():
            node = str(file_path.relative_to(self.repo_path))
            
            # Parse file to extract dependencies
            if file_path.suffix == '.py':
                deps = self._parse_python_dependencies(file_path)
            elif file_path.suffix == '.go':
                deps = self._parse_go_dependencies(file_path)
            elif file_path.suffix in ['.java', '.kt']:
                deps = self._parse_java_dependencies(file_path)
            else:
                deps = set()
            
            self.graph[node] = deps
            self.node_metadata[node] = {
                'type': 'code',
                'language': file_path.suffix[1:],
                'path': str(file_path)
            }
    
    def _parse_python_dependencies(self, file_path: Path) -> Set[str]:
        """Parse Python file to extract imports and calls."""
        deps = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))
            
            # Extract imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]
                        dep_file = self._resolve_module_to_file(module_name, file_path.parent)
                        if dep_file:
                            deps.add(str(dep_file.relative_to(self.repo_path)))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split('.')[0]
                        dep_file = self._resolve_module_to_file(module_name, file_path.parent)
                        if dep_file:
                            deps.add(str(dep_file.relative_to(self.repo_path)))
            
        except Exception as e:
            logger.debug(f"Failed to parse {file_path}: {e}")
        
        return deps
    
    def _parse_go_dependencies(self, file_path: Path) -> Set[str]:
        """Parse Go file to extract imports."""
        deps = set()
        
        try:
            content = file_path.read_text()
            # Simple regex for Go imports
            import_pattern = r'import\s+(?:"([^"]+)"|`([^`]+)`)'
            imports = re.findall(import_pattern, content)
            
            for imp in imports:
                # Extract package name from import path
                import_path = imp[0] or imp[1]
                package_name = import_path.split('/')[-1]
                # Try to find corresponding file
                dep_file = self._find_go_file(package_name)
                if dep_file:
                    deps.add(str(dep_file.relative_to(self.repo_path)))
        
        except Exception as e:
            logger.debug(f"Failed to parse Go file {file_path}: {e}")
        
        return deps
    
    def _parse_java_dependencies(self, file_path: Path) -> Set[str]:
        """Parse Java/Kotlin file to extract imports."""
        deps = set()
        
        try:
            content = file_path.read_text()
            # Simple regex for Java imports
            import_pattern = r'import\s+([\w.]+)'
            imports = re.findall(import_pattern, content)
            
            for imp in imports:
                # Convert package to file path
                package_parts = imp.split('.')
                class_name = package_parts[-1]
                # Try to find corresponding file
                dep_file = self._find_java_file(class_name)
                if dep_file:
                    deps.add(str(dep_file.relative_to(self.repo_path)))
        
        except Exception as e:
            logger.debug(f"Failed to parse Java file {file_path}: {e}")
        
        return deps
    
    def _resolve_module_to_file(self, module_name: str, search_dir: Path) -> Optional[Path]:
        """Resolve Python module name to file path."""
        # Try relative import first
        possible_paths = [
            search_dir / f"{module_name}.py",
            search_dir / module_name / "__init__.py",
            self.repo_path / f"{module_name}.py",
            self.repo_path / module_name / "__init__.py",
            # Add src directory support
            self.repo_path / "src" / f"{module_name}.py",
            self.repo_path / "src" / module_name / "__init__.py",
        ]
        
        
        for path in possible_paths:
            if path.exists():
                return path
        
        return None
    
    def _find_go_file(self, package_name: str) -> Optional[Path]:
        """Find Go file by package name."""
        for go_file in self.repo_path.rglob('*.go'):
            try:
                content = go_file.read_text()
                if f'package {package_name}' in content:
                    return go_file
            except Exception:
                continue
        return None
    
    def _find_java_file(self, class_name: str) -> Optional[Path]:
        """Find Java/Kotlin file by class name."""
        for java_file in self.repo_path.rglob(f'*{class_name}.java'):
            return java_file
        for kt_file in self.repo_path.rglob(f'*{class_name}.kt'):
            return kt_file
        return None
    
    def _index_test_files(self):
        """Index test files and link them to code they test."""
        for test_file in self._find_test_files():
            node = str(test_file.relative_to(self.repo_path))
            
            # Find code files this test imports
            code_deps = self._parse_python_dependencies(test_file)
            
            # Filter to actual code files (not test utilities)
            code_files = {dep for dep in code_deps 
                         if self._is_code_file(dep)}
            
            self.graph[node] = code_files
            self.node_metadata[node] = {
                'type': 'test',
                'path': str(test_file),
                'tested_code': list(code_files)
            }
    
    def _index_test_fixtures(self):
        """Index test fixtures (conftest.py, pytest.ini, etc.) with full fixture definitions."""
        # Find conftest.py files
        for conftest in self.repo_path.rglob('conftest.py'):
            node = str(conftest.relative_to(self.repo_path))
            
            # Parse fixtures from conftest.py
            fixtures = self._parse_fixtures_from_file(conftest)
            
            # Find tests that use this conftest (tests in same or subdirectories)
            parent_dir = conftest.parent
            test_files = list(parent_dir.rglob('test_*.py')) + \
                        list(parent_dir.rglob('*_test.py'))
            
            fixture_deps = {str(t.relative_to(self.repo_path)) 
                           for t in test_files}
            
            # Also parse fixtures from test files themselves
            for test_file in test_files:
                test_fixtures = self._parse_fixtures_from_file(test_file)
                if test_fixtures:
                    fixtures.update(test_fixtures)
            
            self.graph[node] = set()  # Fixtures don't depend on tests
            self.node_metadata[node] = {
                'type': 'fixture',
                'path': str(conftest),
                'used_by_tests': list(fixture_deps),
                'fixtures': fixtures  # Store fixture definitions
            }
            
            # Add reverse edges: tests depend on fixtures
            for test_file in fixture_deps:
                if test_file not in self.reverse_graph:
                    self.reverse_graph[test_file] = set()
                self.reverse_graph[test_file].add(node)
    
    def _parse_fixtures_from_file(self, file_path: Path) -> Dict[str, Dict]:
        """
        Parse pytest fixtures from a file using AST.
        
        Returns dict of fixture_name -> {signature, docstring, scope, params}
        """
        fixtures = {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if function is a fixture (has @pytest.fixture decorator)
                    is_fixture = False
                    fixture_scope = 'function'  # default
                    fixture_params = []
                    
                    for decorator in node.decorator_list:
                        if isinstance(decorator, ast.Call):
                            if isinstance(decorator.func, ast.Attribute):
                                if decorator.func.attr == 'fixture':
                                    is_fixture = True
                                    # Extract scope from decorator args
                                    for keyword in decorator.keywords:
                                        if keyword.arg == 'scope':
                                            if isinstance(keyword.value, ast.Constant):
                                                fixture_scope = keyword.value.value
                        elif isinstance(decorator, ast.Attribute):
                            if decorator.attr == 'fixture':
                                is_fixture = True
                    
                    if is_fixture:
                        # Extract function signature
                        params = []
                        for arg in node.args.args:
                            param_name = arg.arg
                            param_type = None
                            if arg.annotation:
                                param_type = ast.unparse(arg.annotation) if hasattr(ast, 'unparse') else str(arg.annotation)
                            params.append({
                                'name': param_name,
                                'type': param_type
                            })
                        
                        # Extract docstring
                        docstring = ast.get_docstring(node) or ""
                        
                        # Extract return type hint
                        return_type = None
                        if node.returns:
                            return_type = ast.unparse(node.returns) if hasattr(ast, 'unparse') else str(node.returns)
                        
                        fixtures[node.name] = {
                            'name': node.name,
                            'signature': f"{node.name}({', '.join([p['name'] for p in params])})",
                            'parameters': params,
                            'return_type': return_type,
                            'docstring': docstring,
                            'scope': fixture_scope,
                            'file': str(file_path.relative_to(self.repo_path))
                        }
        
        except Exception as e:
            logger.debug(f"Failed to parse fixtures from {file_path}: {e}")
        
        return fixtures
    
    def _index_config_files(self):
        """Index config files (env, yaml, json, etc.)."""
        config_patterns = [
            '*.env', '*.env.*', '.env*',
            '*.yaml', '*.yml',
            '*.json',
            'pytest.ini', 'setup.cfg', 'pyproject.toml',
            'docker-compose.yml', 'docker-compose.yaml'
        ]
        
        for pattern in config_patterns:
            for config_file in self.repo_path.rglob(pattern):
                node = str(config_file.relative_to(self.repo_path))
                
                self.graph[node] = set()
                self.node_metadata[node] = {
                    'type': 'config',
                    'path': str(config_file),
                    'format': config_file.suffix
                }
    
    def _build_reverse_graph(self):
        """Build reverse dependency graph (for impact analysis)."""
        for node, deps in self.graph.items():
            for dep in deps:
                if dep not in self.reverse_graph:
                    self.reverse_graph[dep] = set()
                self.reverse_graph[dep].add(node)
    
    def get_context_for_test_failure(self, test_name: str, 
                                     error_message: str,
                                     test_file_path: Optional[Path] = None) -> Dict:
        """
        Returns ALL context needed to fix a test failure.
        
        This is the KEY function that solves "invisible context" problem.
        
        Args:
            test_name: Name of the failing test
            error_message: Error message from test failure
            test_file_path: Optional path to test file (if known)
        """
        # 1. Find test file
        if test_file_path and test_file_path.exists():
            test_file = test_file_path
        else:
            test_file = self._find_test_file(test_name)
        
        if not test_file or not test_file.exists():
            return {}
        
        test_node = str(test_file.relative_to(self.repo_path))
        
        # Extract keywords from error message for relevance filtering
        error_keywords = set(self._extract_keywords(error_message))
        
        # 2. Find code being tested
        code_files = self.graph.get(test_node, set())
        
        # 3. Find test fixtures
        fixtures = self.reverse_graph.get(test_node, set())
        fixtures = {f for f in fixtures 
                   if self.node_metadata.get(f, {}).get('type') == 'fixture'}
        
        # Filter fixtures by relevance
        relevant_fixtures = self._filter_relevant_fixtures(fixtures, error_keywords)
        
        # 4. Find shared utilities (test helpers, mocks) with signatures
        utility_files_set = self._find_shared_utilities(test_file)
        
        # Rank utilities by relevance (enhanced with error keywords)
        ranked_utilities = self._rank_utilities(test_file, utility_files_set, error_keywords)
        
        # Take top 5 most relevant utilities
        top_utilities = ranked_utilities[:5]
        
        utility_signatures = {}
        for util_node in top_utilities:
            if util_node in self.node_metadata:
                util_meta = self.node_metadata[util_node]
                if util_meta.get('type') == 'utility':
                    utility_signatures[util_node] = {
                        'functions': util_meta.get('functions', []),
                        'classes': util_meta.get('classes', [])
                    }
        
        # 5. Extract fixture definitions
        fixture_definitions = {}
        for fixture_node in relevant_fixtures:
            if fixture_node in self.node_metadata:
                fixture_meta = self.node_metadata[fixture_node]
                if fixture_meta.get('type') == 'fixture':
                    # Only include relevant specific fixtures from the file? 
                    # For now include all from the file, but file selection is filtered
                    fixture_definitions[fixture_node] = fixture_meta.get('fixtures', {})
        
        # 6. Find environment context
        env_context = self._find_env_context(test_file)
        
        # 7. Find related tests (similar patterns)
        related_tests = self._find_similar_tests(test_file, error_message)
        
        # 8. Find config files
        config_files = self._find_config_files_for_test(test_file)
        
        return {
            'test_file': test_node,
            'code_files': list(code_files),
            'fixtures': list(relevant_fixtures),
            'fixture_definitions': fixture_definitions,
            'utilities': list(top_utilities),
            'utility_signatures': utility_signatures,
            'env_context': env_context,
            'related_tests': list(related_tests),
            'config_files': list(config_files)
        }
    
    def get_impacted_files(self, changed_files: Set[str]) -> Set[str]:
        """
        Identify all files impacted by changes to the given files.
        (Graph-Based Impact Analysis / 'Blast Radius')
        
        Args:
            changed_files: Set of relative file paths that changed
            
        Returns:
            Set of relative paths for all impacted files (recursive)
        """
        # 1. Convert any Path objects to strings if needed
        # (Assuming inputs are strings per graph nodes)
        
        # 2. Use reachable_set logic
        return self._reachable_set(changed_files)
        
    def _reachable_set(self, start_nodes: Set[str]) -> Set[str]:
        """
        Compute reachable set from start nodes (BFS on reverse graph).
        """
        visited = set()
        queue = list(start_nodes)
        
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            
            # Add dependents (reverse graph)
            for dependent in self.reverse_graph.get(node, set()):
                if dependent not in visited:
                    queue.append(dependent)
        
        return visited
    
    def find_tests_for_nodes(self, nodes: Set[str]) -> Dict[Path, List[str]]:
        """Find tests that cover the given nodes."""
        tests = {}
        
        # Find all test files
        for test_file in self.repo_path.rglob('test_*.py'):
            test_node = str(test_file.relative_to(self.repo_path))
            
            # Check if test file imports any of the nodes
            test_deps = self.graph.get(test_node, set())
            if test_deps.intersection(nodes):
                # Extract test functions
                try:
                    content = test_file.read_text()
                    test_functions = re.findall(r'def\s+(test_\w+)', content)
                    if test_functions:
                        tests[test_file] = test_functions
                except Exception:
                    pass
        
        return tests
    
    # Helper methods
    def _find_code_files(self):
        """Find all code files."""
        patterns = ['*.py', '*.go', '*.java', '*.kt', '*.js', '*.ts']
        for pattern in patterns:
            yield from self.repo_path.rglob(pattern)
    
    def _find_test_files(self):
        """Find all test files."""
        patterns = ['test_*.py', '*_test.py', '*_test.go', '*_test.java']
        for pattern in patterns:
            yield from self.repo_path.rglob(pattern)
    
    def _is_code_file(self, path_str: str) -> bool:
        """Check if path string refers to a code file."""
        # It's already a relative path string from the graph
        full_path = self.repo_path / path_str
        if full_path.exists() and full_path.is_file():
            return True
            
        # Fallback for module names (original logic)
        possible_paths = [
            self.repo_path / f"{path_str}.py",
            self.repo_path / f"{path_str}/__init__.py",
        ]
        return any(p.exists() for p in possible_paths)
    
    def _find_test_file(self, test_name: str) -> Optional[Path]:
        """Find test file by test name."""
        # Try exact match first
        for test_file in self.repo_path.rglob('test_*.py'):
            if test_name in test_file.read_text():
                return test_file
        
        # Try pattern match
        test_pattern = test_name.replace('test_', '').replace('_', '')
        for test_file in self.repo_path.rglob('*test*.py'):
            content = test_file.read_text()
            if test_pattern.lower() in content.lower():
                return test_file
        
        return None
    
    def _find_shared_utilities(self, test_file: Path) -> Set[str]:
        """Find shared test utilities (helpers, mocks, etc.) with signatures."""
        utilities = set()
        
        # Look for common test utility patterns
        test_dir = test_file.parent
        repo_dir = self.repo_path
        
        # Search in test directory and parent directories up to repo root
        search_dirs = [test_dir]
        curr = test_dir
        while curr != repo_dir and repo_dir in curr.parents:
             curr = curr.parent
             search_dirs.append(curr)
        # Also add repo_dir if not there
        if repo_dir not in search_dirs:
            search_dirs.append(repo_dir)
        
        for search_dir in search_dirs:
            # Check for utilities by pattern
            for pattern in ['*util*.py', '*helper*.py', '*mock*.py']:
                try:
                    for util_file in search_dir.rglob(pattern):
                        # Skip __pycache__ and actual test files
                        if '__pycache__' in str(util_file):
                            continue
                        if util_file.name.startswith('test_') or util_file.name.endswith('_test.py'):
                            continue
                            
                        # Avoid duplicates
                        rel_path = str(util_file.relative_to(self.repo_path))
                        if rel_path not in utilities:
                            utilities.add(rel_path)
                except Exception:
                    pass
        
        # Also look for common utility directories (explicitly)
        for util_dir_name in ['utils', 'helpers', 'common', 'shared']:
            util_dir = repo_dir / util_dir_name
            if util_dir.exists():
                for util_file in util_dir.rglob('*.py'):
                    try:
                        rel_path = str(util_file.relative_to(self.repo_path))
                        utilities.add(rel_path)
                    except: 
                        pass
        
        return utilities
    
    def _index_utilities(self):
        """Index utility functions and classes with their signatures."""
        """This method is called during build() to index all utilities."""
        utilities_metadata = {}
        
        # Find utility files
        utility_patterns = [
            '*util*.py', '*helper*.py', '*mock*.py',
            'utils/**/*.py', 'helpers/**/*.py', 'common/**/*.py', 'shared/**/*.py'
        ]
        
        for pattern in utility_patterns:
            for util_file in self.repo_path.rglob(pattern):
                # Skip __pycache__ and actual test files
                if '__pycache__' in str(util_file):
                    continue
                if util_file.name.startswith('test_') or util_file.name.endswith('_test.py'):
                    continue
                
                node = str(util_file.relative_to(self.repo_path))
                
                # Parse functions and classes from utility file
                functions, classes = self._parse_utility_file(util_file)
                
                if functions or classes:
                    utilities_metadata[node] = {
                        'type': 'utility',
                        'path': str(util_file),
                        'functions': functions,
                        'classes': classes
                    }
                    
                    # Add to graph
                    self.graph[node] = set()
                    self.node_metadata[node] = utilities_metadata[node]
        
        return utilities_metadata
    
    def _calculate_relevance(self, text: str, query_keywords: Set[str]) -> float:
        """Calculate relevance score of text against query keywords."""
        if not text or not query_keywords:
            return 0.0
        
        # Extract keywords from text
        text_keywords = set(self._extract_keywords(text))
        if not text_keywords:
            return 0.0
            
        # Jaccard similarity-ish (overlap / query size)
        intersection = len(text_keywords.intersection(query_keywords))
        return intersection / len(query_keywords)

    def _filter_relevant_fixtures(self, fixtures: Set[str], error_keywords: Set[str], limit: int = 5) -> List[str]:
        """Filter fixture files by relevance to the error."""
        if not fixtures:
            return []
            
        # If no error keywords, return all (or top N arbitrary)
        if not error_keywords:
            return list(fixtures)[:limit]
            
        scores = []
        for fixture_node in fixtures:
            score = 0.0
            if fixture_node in self.node_metadata:
                meta = self.node_metadata[fixture_node]
                # Check actual fixture definitions
                fixture_defs = meta.get('fixtures', {})
                for name, details in fixture_defs.items():
                    # Check name and docstring
                    text = f"{name} {details.get('docstring', '')}"
                    cutoff = self._calculate_relevance(text, error_keywords)
                    if cutoff > score:
                        score = cutoff
            
            scores.append((fixture_node, score))
        
        # Sort by score desc
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return top N, but include at least one if available
        return [x[0] for x in scores[:limit]]

    def _rank_utilities(self, test_file: Path, candidates: Set[str], error_keywords: Set[str] = None) -> List[str]:
        """
        Rank utility files by relevance to the test file AND error message.
        
        Scoring:
        - +10: Explicitly imported in test file
        - +5: Function/Class from utility mentioned in test content
        - +5: Relevance to error message (keyword overlap)
        - +2: Same directory as test file
        - -1: For each directory level separation
        """
        if not candidates:
            return []
            
        scores = {}
        error_keywords = error_keywords or set()
        
        try:
            test_content = test_file.read_text()
            test_dir = test_file.parent
        except Exception:
            test_content = ""
            test_dir = Path(".")
            
        for util_node in candidates:
            score = 0
            util_path = self.repo_path / util_node
            
            # 1. Proximity Check
            try:
                # Calculate distance in directory tree
                util_dir = util_path.parent
                if util_dir == test_dir:
                    score += 2
                else:
                    if util_dir in test_dir.parents:
                        distance = len(test_dir.parts) - len(util_dir.parts)
                        score -= distance
                    else:
                        score -= 2 # Different branches
            except Exception:
                pass

            # 2. explicit Import Check
            try:
                module_name = util_path.stem
                if f"import {module_name}" in test_content or f"from {module_name}" in test_content or f"from .{module_name}" in test_content:
                    score += 10
            except:
                pass
                
            # 3. Content Usage Check & Error Relevance
            if util_node in self.node_metadata:
                meta = self.node_metadata[util_node]
                funcs = meta.get('functions', [])
                classes = meta.get('classes', [])
                
                # Check for usage in test file
                for f in funcs:
                    if f['name'] in test_content:
                        score += 5
                        break
                
                if score < 5: 
                    for c in classes:
                        if c['name'] in test_content:
                            score += 5
                            break
                            
                # Check for relevance to error (Basic RAG)
                if error_keywords:
                    # Construct text bag from utility
                    text_bag = f"{util_path.name} "
                    for f in funcs[:5]: # check top 5 funcs
                         text_bag += f"{f['name']} {f.get('docstring', '')} "
                    for c in classes[:3]:
                         text_bag += f"{c['name']} {c.get('docstring', '')} "
                    
                    relevance = self._calculate_relevance(text_bag, error_keywords)
                    # Boost score significantly if highly relevant to error
                    if relevance > 0.1:
                        score += (relevance * 20)  # Up to +20 points
            
            scores[util_node] = score
            
        # Sort by score descending
        ranked = sorted(list(candidates), key=lambda x: scores.get(x, 0), reverse=True)
        return ranked

    def _parse_utility_file(self, file_path: Path) -> tuple:
        """Parse utility file to extract function and class signatures."""
        functions = []
        classes = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Skip private functions (starting with _) unless they're fixtures
                    if node.name.startswith('_') and not any(
                        isinstance(d, (ast.Call, ast.Attribute)) 
                        and (isinstance(d, ast.Attribute) and d.attr == 'fixture' or
                             isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == 'fixture')
                        for d in node.decorator_list
                    ):
                        continue
                    
                    # Extract function signature
                    params = []
                    for arg in node.args.args:
                        param_name = arg.arg
                        param_type = None
                        if arg.annotation:
                            try:
                                param_type = ast.unparse(arg.annotation) if hasattr(ast, 'unparse') else str(arg.annotation)
                            except:
                                param_type = str(arg.annotation)
                        params.append({
                            'name': param_name,
                            'type': param_type
                        })
                    
                    docstring = ast.get_docstring(node) or ""
                    return_type = None
                    if node.returns:
                        try:
                            return_type = ast.unparse(node.returns) if hasattr(ast, 'unparse') else str(node.returns)
                        except:
                            return_type = str(node.returns)
                    
                    functions.append({
                        'name': node.name,
                        'signature': f"{node.name}({', '.join([p['name'] for p in params])})",
                        'parameters': params,
                        'return_type': return_type,
                        'docstring': docstring
                    })
                
                elif isinstance(node, ast.ClassDef):
                    # Extract class definition
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            method_params = []
                            for arg in item.args.args:
                                if arg.arg != 'self':  # Skip self parameter
                                    method_params.append(arg.arg)
                            
                            methods.append({
                                'name': item.name,
                                'signature': f"{item.name}({', '.join(method_params)})"
                            })
                    
                    docstring = ast.get_docstring(node) or ""
                    
                    classes.append({
                        'name': node.name,
                        'methods': methods,
                        'docstring': docstring
                    })
        
        except Exception as e:
            logger.debug(f"Failed to parse utility file {file_path}: {e}")
        
        return functions, classes
    
    def _find_env_context(self, test_file: Path) -> Dict:
        """Find environment context (env vars, configs)."""
        env_context = {
            'env_files': [],
            'config_files': []
        }
        
        # Find .env files
        for env_file in self.repo_path.rglob('.env*'):
            env_context['env_files'].append(
                str(env_file.relative_to(self.repo_path))
            )
        
        # Find config files
        for config_file in self.repo_path.rglob('pytest.ini'):
            env_context['config_files'].append(
                str(config_file.relative_to(self.repo_path))
            )
        
        return env_context
    
    def _find_similar_tests(self, test_file: Path, 
                           error_message: str) -> Set[str]:
        """Find tests with similar patterns (for learning)."""
        similar = set()
        
        # Extract error pattern
        error_keywords = self._extract_keywords(error_message)
        
        # Find tests with similar keywords
        for other_test in self.repo_path.rglob('test_*.py'):
            if other_test == test_file:
                continue
            
            content = other_test.read_text()
            if any(keyword in content for keyword in error_keywords):
                similar.add(str(other_test.relative_to(self.repo_path)))
        
        return similar
    
    def _find_config_files_for_test(self, test_file: Path) -> Set[str]:
        """Find config files relevant to this test."""
        configs = set()
        
        # Look in test directory and parent directories
        current_dir = test_file.parent
        while current_dir != self.repo_path.parent:
            for config_file in current_dir.glob('*.ini'):
                configs.add(str(config_file.relative_to(self.repo_path)))
            for config_file in current_dir.glob('*.yaml'):
                configs.add(str(config_file.relative_to(self.repo_path)))
            for config_file in current_dir.glob('*.yml'):
                configs.add(str(config_file.relative_to(self.repo_path)))
            current_dir = current_dir.parent
        
        return configs
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from error message."""
        # Simple keyword extraction
        keywords = []
        words = re.findall(r'\w+', text.lower())
        # Filter common words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 
                     'in', 'on', 'at', 'to', 'for', 'of', 'with'}
        keywords = [w for w in words if w not in stop_words and len(w) > 3]
        return keywords[:10]  # Top 10 keywords

