import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

class ConfigManager:
    CONFIG_FILENAME = "reviewer.config.json"

    def __init__(self):
        pass

    def find_config_file(self, start_path: str) -> Optional[str]:
        """
        Recursively searches for reviewer.config.json starting from start_path 
        and moving up to the root.
        """
        try:
            current_path = Path(start_path).resolve()
            if not current_path.is_dir():
                current_path = current_path.parent
                
            # Loop safely up to root
            root = Path(current_path.root)
            while current_path != root:
                config_path = current_path / self.CONFIG_FILENAME
                if config_path.exists() and config_path.is_file():
                    return str(config_path)
                
                # Move up
                parent = current_path.parent
                if parent == current_path: # Safety check for root loop
                    break
                current_path = parent
            
            # Check root one last time
            config_path = root / self.CONFIG_FILENAME
            if config_path.exists() and config_path.is_file():
                return str(config_path)
                
        except Exception as e:
            print(f"Error searching for config: {e}")
            return None
            
        return None

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """
        Loads and interprets the JSON configuration file.
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load config {config_path}: {e}")
            return {}

    def merge_configs(self, base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges override_config into base_config. 
        Strategy:
        - Lists (like disabled_rules) are combined (union).
        - Scalars (enable_x) are overridden by non-None values.
        - Dictionaries are merged recursively.
        """
        merged = base_config.copy()
        
        for key, value in override_config.items():
            if key in merged:
                if isinstance(value, dict) and isinstance(merged[key], dict):
                    merged[key] = self.merge_configs(merged[key], value)
                elif isinstance(value, list) and isinstance(merged[key], list):
                    # For lists like disabled_rules, we might want union or override.
                    # Usually for 'disabled_rules', union makes sense (disable X AND Y).
                    # But for 'api_keys', maybe override?
                    # Let's default to UNION for lists to be safe for rules.
                    merged[key] = list(set(merged[key]) | set(value))
                else:
                    merged[key] = value
            else:
                merged[key] = value
                
        return merged

    def resolve_config(self, file_path: str, request_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolves the final configuration for a given file execution context.
        1. Finds repo config based on file_path.
        2. Merges Repo Config INTO Request Config (Repo Logic overrides/augments User/Request defaults).
           Wait, implementation plan said: "Request Config = User Environment", "Repo Config = Project Rules".
           If Repo says "Disable LINT001", it should be disabled regardless of User Config?
           Actually, Request Config comes from VS Code. If User unticks "Disable LINT001" in VS Code UI, they expect it to be enabled (or not disabled).
           
           Let's treat 'Repo Config' as the BASE TRUTH for the project.
           And 'Request Config' as the USER overrides (e.g. valid session keys, toggles).
           
           Actually, usually Repo Config enforces policies.
           If Repo Config says "LINT001 is invalid here", the user shouldn't see it even if they enabled it locally.
           
           Let's merge Request Config (Base) + Repo Config (Override).
        """
        repo_config_path = self.find_config_file(file_path)
        repo_config = {}
        if repo_config_path:
            # print(f"Found repo config at: {repo_config_path}")
            repo_config = self.load_config(repo_config_path)
            
        # Merge: Start with Request (User settings), Override with Repo (Project Constraints)
        final_config = self.merge_configs(request_config, repo_config)
        return final_config
