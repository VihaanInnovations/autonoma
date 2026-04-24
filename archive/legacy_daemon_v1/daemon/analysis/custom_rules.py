import yaml
import re
import logging
import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class CustomRule:
    id: str
    pattern: str
    message: str
    severity: str
    include: List[str]
    exclude: List[str]
    regex: re.Pattern

class CustomRuleEngine:
    """
    Enterprise Custom Rule Engine.
    Allows users to define regex-based compliance rules via 'compliance_rules.yaml'.
    """
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.rules: List[CustomRule] = []
        self._load_rules()

    def _load_rules(self):
        """Load rules from compliance_rules.yaml in repo root."""
        rule_file = self.repo_path / "compliance_rules.yaml"
        if not rule_file.exists():
            return

        try:
            with open(rule_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                
            if not data or 'rules' not in data:
                logger.warning(f"Invalid compliance_rules.yaml structure in {self.repo_path}")
                return

            for raw_rule in data.get('rules', []):
                try:
                    # Validate required fields
                    if 'id' not in raw_rule or 'pattern' not in raw_rule:
                        continue
                        
                    # Compile Regex
                    pattern = raw_rule['pattern']
                    regex = re.compile(pattern, re.MULTILINE)
                    
                    self.rules.append(CustomRule(
                        id=raw_rule['id'],
                        pattern=pattern,
                        message=raw_rule.get('message', f"Custom Rule {raw_rule['id']} violation"),
                        severity=raw_rule.get('severity', 'MEDIUM').upper(),
                        include=raw_rule.get('include', ['*']),
                        exclude=raw_rule.get('exclude', []),
                        regex=regex
                    ))
                except re.error as e:
                    logger.error(f"Invalid regex for rule {raw_rule.get('id')}: {e}")
                except Exception as e:
                    logger.error(f"Error loading rule {raw_rule.get('id')}: {e}")
            
            logger.info(f"Loaded {len(self.rules)} custom rules from {rule_file}")
            
        except Exception as e:
            logger.error(f"Failed to load compliance_rules.yaml: {e}")

    def scan(self, content: str, file_path: Path) -> List[Dict[str, Any]]:
        """
        Scan content against loaded rules.
        Returns a list of issue dictionaries.
        """
        issues = []
        if not self.rules:
            return issues

        # Relativize path for glob matching
        try:
            rel_path = file_path.relative_to(self.repo_path)
            rel_path_str = str(rel_path).replace("\\", "/") # Normalize for glob
        except ValueError:
            # If text is not relative to repo (outside file), use name
            rel_path_str = file_path.name

        for rule in self.rules:
            # Check Inclusions
            matched_include = any(fnmatch.fnmatch(rel_path_str, pat) for pat in rule.include)
            # print(f"DEBUG: Checking {rel_path_str} against {rule.include} -> {matched_include}")
            if not matched_include:
                continue
            
            # Check Exclusions
            matched_exclude = any(fnmatch.fnmatch(rel_path_str, pat) for pat in rule.exclude)
            if matched_exclude:
                continue

            # Run Regex
            for match in rule.regex.finditer(content):
                # print(f"DEBUG: Matched rule {rule.id}")
                # Calculate line number
                # This can be slow for large files/many matches, but acceptable for custom regex
                start_index = match.start()
                
                # Check for comments before the match on the same line
                line_start_idx = content.rfind('\n', 0, start_index) + 1
                line_prefix = content[line_start_idx:start_index]
                
                # Language-aware comment check
                is_commented = False
                if rel_path_str.endswith(".py"):
                    if "#" in line_prefix:
                        is_commented = True
                elif rel_path_str.endswith((".js", ".ts", ".jsx", ".tsx")):
                    if "//" in line_prefix:
                        is_commented = True
                
                if is_commented:
                    # logger.debug(f"Skipping commented match for rule {rule.id}")
                    continue
                    
                line_number = content.count('\n', 0, start_index) + 1
                
                issues.append({
                    "id": rule.id,
                    "message": rule.message,
                    "severity": rule.severity,
                    "file_path": str(rel_path_str),
                    "line": line_number,
                    "type": "custom_rule",
                    "source": "custom_rule_engine"
                })
                
        return issues
