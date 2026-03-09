"""
Autonoma — Configuration Manager

Finds and loads reviewer.config.json from the project tree.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    CONFIG_FILENAME = "reviewer.config.json"

    def find_config_file(self, start_path: str) -> Optional[str]:
        """
        Search for reviewer.config.json starting from start_path
        and walking up to the filesystem root.
        """
        try:
            current_path = Path(start_path).resolve()
            if not current_path.is_dir():
                current_path = current_path.parent

            root = Path(current_path.root)
            while current_path != root:
                config_path = current_path / self.CONFIG_FILENAME
                if config_path.exists() and config_path.is_file():
                    return str(config_path)

                parent = current_path.parent
                if parent == current_path:
                    break
                current_path = parent

            # Check root
            config_path = root / self.CONFIG_FILENAME
            if config_path.exists() and config_path.is_file():
                return str(config_path)

        except Exception:
            return None

        return None

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """Load and parse the JSON configuration file."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge override into base.
        Lists are unioned, dicts are merged recursively, scalars are overridden.
        """
        merged = base.copy()
        for key, value in override.items():
            if key in merged:
                if isinstance(value, dict) and isinstance(merged[key], dict):
                    merged[key] = self.merge_configs(merged[key], value)
                elif isinstance(value, list) and isinstance(merged[key], list):
                    merged[key] = list(set(merged[key]) | set(value))
                else:
                    merged[key] = value
            else:
                merged[key] = value
        return merged

    def resolve_config(self, file_path: str, request_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Resolve final config: start with request_config, override with repo config.
        """
        request_config = request_config or {}
        repo_config_path = self.find_config_file(file_path)
        repo_config = {}
        if repo_config_path:
            repo_config = self.load_config(repo_config_path)

        return self.merge_configs(request_config, repo_config)
