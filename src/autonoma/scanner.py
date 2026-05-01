"""
Autonoma — Scanner

Thin wrapper around HeuristicsEngine.
Stateless: takes content + file_path, returns issues.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from ._internal.heuristics import HeuristicsEngine, DEFAULT_EXTENSIONS


class Scanner:
    """Stateless file scanner for SEC001/SEC002."""

    def __init__(self, allowed_extensions: Optional[Set[str]] = None):
        self._extensions = allowed_extensions or DEFAULT_EXTENSIONS
        self._engine = HeuristicsEngine(allowed_extensions=self._extensions)

    @property
    def extensions(self) -> Set[str]:
        return self._extensions

    def scan(self, content: str, file_path: str, disabled_rules: Set[str] = None) -> List[Dict[str, Any]]:
        """
        Scan file content for security issues.

        Returns list of issues, filtered by disabled_rules.
        """
        disabled_rules = disabled_rules or set()
        issues = self._engine.run(content, file_path)
        return [i for i in issues if i.get("id") not in disabled_rules]

    def close(self):
        self._engine.close()
