"""
Autonoma Community Edition - High-Precision Secret Detector
Implements multi-signal detection keying off regex, entropy, and context.
"""
import re
import math
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class SecretDetector:
    """
    Lightweight, high-precision secret detector.
    Combines Regex + Entropy + Context + Suppression.
    """
    
    # 1. Regex Patterns
    # High confidence vendor patterns
    VENDOR_PATTERNS = [
        (r'sk_live_[0-9a-zA-Z]{24}', 0.9, 'Stripe Live Key'),
        (r'sk_test_[0-9a-zA-Z]{24}', 0.6, 'Stripe Test Key'), # Lower confidence (WARN_ONLY)
        (r'xoxb-[0-9]{11}-[0-9]{11}-[0-9a-zA-Z]{24}', 0.9, 'Slack Bot Token'),
        (r'sq0atp-[0-9A-Za-z\-_]{22}', 0.9, 'Square Access Token'),
    ]
    
    # Generic assignments (weaker signal, relies on entropy)
    GENERIC_PATTERN = re.compile(
        r'(?P<varname>[a-z0-9_]*(?:key|secret|token|password|auth)[a-z0-9_]*)\s*=\s*[\'"](?P<value>[^\'"]+)[\'"]', 
        re.IGNORECASE
    )
    
    # 2. Context Weights
    CONTEXT_WEIGHTS = {
        'TEST_FILE': -0.3,   # It's a test file (Downgrades to WARN_ONLY usually)
        'CONFIG_FILE': 0.1,  # It's a config file
        'SECRET_VAR': 0.2,   # Variable name looks like a secret
    }
    
    # 3. Suppression Lexicon (Placeholders)
    PLACEHOLDERS = {
        'changeme', 'change_me', 'your_key_here', 'insert_key_here',
        'example', 'sample', 'test', '12345', '123456', 'abcdef',
        'password', 'secret', 'todo', 'xxx', 'yyy', 'zzz', 'dummy_key'
    }

    def analyze_file(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Analyze a file for secrets and return a list of issues with confidence scores.
        """
        issues = []
        lines = content.split('\n')
        file_path_obj = Path(file_path)
        
        # File context score
        file_score_modifier = 0.0
        if self._is_test_file(file_path_obj):
            file_score_modifier += self.CONTEXT_WEIGHTS['TEST_FILE']
        if self._is_config_file(file_path_obj):
            file_score_modifier += self.CONTEXT_WEIGHTS['CONFIG_FILE']

        for i, line in enumerate(lines):
            if not line.strip():
                continue
                
            # A. Check Vendor Patterns (High Confidence)
            vendor_match = False
            for pattern, weight, label in self.VENDOR_PATTERNS:
                match = re.search(pattern, line)
                if match:
                    val = match.group(0)
                    if self._is_placeholder(val): 
                        continue
                     
                    final_confidence = weight + file_score_modifier
                    issues.append(self._create_issue(
                        line_num=i+1,
                        message=f"{label} detected",
                        confidence=final_confidence,
                        source="vendor_regex",
                        value=val,
                        variable_name=""
                    ))
                    vendor_match = True
                    break 
            
            if vendor_match:
                continue

            # B. Check Generic Patterns
            match = self.GENERIC_PATTERN.search(line)
            if match:
                val = match.group('value')
                var = match.group('varname')
                
                # 1. Suppression
                if self._is_placeholder(val):
                    continue
                
                # 2. Length Check (Hard Filter)
                # User Requirement: Enforce minimum length for entropy model.
                # If value is too short, entropy is misleading.
                if len(val) < 12:
                    continue 

                # 3. Base Score
                confidence = 0.3 # Base for generic match
                
                # 4. Entropy Signal
                entropy = self._calculate_shannon_entropy(val)
                if entropy > 4.5:
                    confidence += 0.4
                elif entropy < 3.2:
                    confidence -= 0.5 # Penalty for low entropy (English words)
                    
                # 5. Variable Name Context
                confidence += self.CONTEXT_WEIGHTS['SECRET_VAR']
                
                # 6. File Context
                confidence += file_score_modifier

                # Clamp
                confidence = max(0.0, min(1.0, confidence))
                
                # 7. Classification
                if confidence >= 0.4:
                    issues.append(self._create_issue(
                        line_num=i+1,
                        message=f"Possible hardcoded secret '{var}' detected (Confidence: {confidence:.2f})",
                        confidence=confidence,
                        source="generic_heuristic",
                        value=val,
                        variable_name=var
                    ))

        return issues

    def _create_issue(self, line_num: int, message: str, confidence: float, source: str, value: str, variable_name: str = "") -> Dict[str, Any]:
        """Construct the issue dictionary based on confidence thresholds."""
        confidence = max(0.0, min(1.0, confidence))
        
        # Determine Severity and Action
        if confidence >= 0.7:
            severity = "HIGH"
            can_autofix = True # TREAT_AS_SECRET
            outcome_rec = "TREAT_AS_SECRET"
        elif confidence >= 0.4:
            severity = "MEDIUM"
            can_autofix = False # WARN_ONLY
            outcome_rec = "WARN_ONLY"
        else:
            severity = "LOW"
            can_autofix = False
            outcome_rec = "IGNORE"

        # Determine ID (SECK001 vs SECK002)
        issue_id = "SECK002"
        if "password" in variable_name.lower():
            issue_id = "SECK001"

        if "aws_secret" in variable_name:
            pass
            
        # FIX ALIGNMENT: Only mark auto-fixable if variable name matches SecretFixer patterns
        # SecretFixer supports: password, api_key, secret, token, etc.
        # But generic regex might match weird things.
        # If it's a VENDOR match (source="vendor_regex"), it's implied safe to fix? 
        # Actually SecretFixer might fail if it can't find the pattern.
        # But let's assume if confidence is high, it's worth trying, 
        # UNLESS var name is known to be unsupported?
        # Better: Check if var_name is in supported set.
        
        # Supported roots from SecretFixer (simplified)
        SUPPORTED_FIX_ROOTS = {'password', 'passwd', 'pwd', 'api_key', 'apikey', 'api_secret', 'secret', 'token', 'auth_token', 'auth_key', 'access_key', 'secret_key'}
        
        # If generic heuristic, strict check
        # BUT if confidence is HIGH, we trust it enough to attempt fix (SecretFixer has its own checks)
        if source == "generic_heuristic" and can_autofix:
            # Only enforce root check for Lower/Medium confidence to avoid noise
            if confidence < 0.7:
                is_supported = False
                for root in SUPPORTED_FIX_ROOTS:
                     if root in variable_name.lower():
                        is_supported = True
                        break
                if not is_supported:
                    can_autofix = False
                    outcome_rec = "WARN_ONLY" # Downgrade to WARN if we can't fix it

        return {
            "id": issue_id,
            "line": line_num,
            "message": message,
            "confidence": confidence,
            "severity": severity,
            "can_autofix": can_autofix,
            "source": source,
            # "value_sample": REMOVED for security
            "recommendation": outcome_rec
        }

    def _is_placeholder(self, value: str) -> bool:
        """Check if value matches known placeholders."""
        val_lower = value.lower()
        
        # Direct lookup
        if val_lower in self.PLACEHOLDERS:
            return True
            
        # Robust substring check
        # Catches: replace_this, insert_key, your_api_key, dummy_val
        keywords = ["replace", "change", "example", "insert", "your_", "dummy", "sample", "todo", "here"]
        if any(k in val_lower for k in keywords):
            return True
            
        return False

    def _is_test_file(self, file_path: Path) -> bool:
        """Check if file is a test file."""
        parts = file_path.parts
        name = file_path.name.lower()
        return (
            'tests' in parts or 
            'test' in parts or 
            'spec' in parts or 
            name.startswith('test_') or 
            name.endswith('_test.py') or
            name.endswith('.test.js') or
            name.endswith('.spec.js')
        )
        
    def _is_config_file(self, file_path: Path) -> bool:
        """Check if file is a configuration file."""
        name = file_path.name.lower()
        return (
            'config' in name or 
            'settings' in name or 
            '.env' in name or
            'secrets' in name
        )

    def _calculate_shannon_entropy(self, data: str) -> float:
        """Calculate Shannon entropy of a string."""
        if not data:
            return 0
        
        entropy = 0
        length = len(data)
        
        # Count frequencies
        frequencies = {}
        for char in data:
            frequencies[char] = frequencies.get(char, 0) + 1
            
        # Calculate entropy
        for count in frequencies.values():
            p_x = count / length
            entropy -= p_x * math.log2(p_x)
            
        return entropy

