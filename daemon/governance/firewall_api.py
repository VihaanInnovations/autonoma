"""
Governance Firewall API
Provides endpoints for configuring firewall rules, testing rules, and viewing blocked fixes
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from datetime import datetime
import time
import re

router = APIRouter(prefix="/api/governance/firewall", tags=["Governance Firewall"])

# Import authentication
try:
    from daemon.auth.api_key_auth import verify_api_key
except ImportError:
    async def verify_api_key(request: Request, credentials=None):
        return {"user_id": "default"}

# Mock firewall rules storage (in production, use database)
FIREWALL_RULES = {
    "default": {
        "enabled": True,
        "test_mode": False,
        "blocked_patterns": [
            "eval\\(",
            "exec\\(",
            "__import__",
            "compile\\(",
            "globals\\(\\)",
            "locals\\(\\)"
        ],
        "allowed_patterns": [],
        "require_approval_for": ["high", "critical"],
        "max_complexity": "medium",
        "block_file_extensions": [".env", ".key", ".pem", ".p12"],
        "block_paths": ["/.ssh/", "/.aws/", "/secrets/"],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
}

# Mock blocked fixes log (in production, use database)
BLOCKED_FIXES_LOG = [
    {
        "block_id": "block_001",
        "fix_id": "fix_001",
        "file_path": "src/utils.py",
        "reason": "Blocked pattern matched: eval()",
        "rule_matched": "blocked_patterns",
        "pattern": "eval\\(",
        "severity": "high",
        "timestamp": time.time() - 3600,
        "test_mode": False
    },
    {
        "block_id": "block_002",
        "fix_id": "fix_002",
        "file_path": "src/config.py",
        "reason": "File path blocked: /.env",
        "rule_matched": "block_file_extensions",
        "pattern": ".env",
        "severity": "medium",
        "timestamp": time.time() - 7200,
        "test_mode": True
    }
]

class FirewallRuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    test_mode: Optional[bool] = None
    blocked_patterns: Optional[List[str]] = None
    allowed_patterns: Optional[List[str]] = None
    require_approval_for: Optional[List[str]] = None
    max_complexity: Optional[str] = None
    block_file_extensions: Optional[List[str]] = None
    block_paths: Optional[List[str]] = None

class TestRuleRequest(BaseModel):
    code_snippet: str
    file_path: Optional[str] = None
    file_extension: Optional[str] = None

def check_fix_against_rules(rules: Dict[str, Any], code_snippet: str, file_path: str = "", file_extension: str = "") -> Dict[str, Any]:
    """
    Test if a code snippet would be blocked by firewall rules.
    Returns dict with 'blocked' boolean and 'reason' if blocked.
    """
    if not rules.get("enabled", True):
        return {"blocked": False, "reason": None}
    
    # Check blocked patterns
    for pattern in rules.get("blocked_patterns", []):
        try:
            if re.search(pattern, code_snippet, re.IGNORECASE):
                return {
                    "blocked": True,
                    "reason": f"Blocked pattern matched: {pattern}",
                    "rule_matched": "blocked_patterns",
                    "pattern": pattern
                }
        except re.error:
            # Invalid regex pattern, skip
            continue
    
    # Check allowed patterns (whitelist)
    allowed_patterns = rules.get("allowed_patterns", [])
    if allowed_patterns:
        matched_allowed = False
        for pattern in allowed_patterns:
            try:
                if re.search(pattern, code_snippet, re.IGNORECASE):
                    matched_allowed = True
                    break
            except re.error:
                continue
        if not matched_allowed:
            return {
                "blocked": True,
                "reason": "Code does not match any allowed pattern",
                "rule_matched": "allowed_patterns"
            }
    
    # Check file extension
    if file_extension:
        blocked_extensions = rules.get("block_file_extensions", [])
        if file_extension.lower() in [ext.lower() for ext in blocked_extensions]:
            return {
                "blocked": True,
                "reason": f"File extension blocked: {file_extension}",
                "rule_matched": "block_file_extensions",
                "pattern": file_extension
            }
    
    # Check file path
    if file_path:
        blocked_paths = rules.get("block_paths", [])
        for blocked_path in blocked_paths:
            if blocked_path.lower() in file_path.lower():
                return {
                    "blocked": True,
                    "reason": f"File path blocked: {blocked_path}",
                    "rule_matched": "block_paths",
                    "pattern": blocked_path
                }
    
    return {"blocked": False, "reason": None}

@router.get("/rules")
async def get_firewall_rules(
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get current firewall rules configuration.
    """
    return {
        "rules": FIREWALL_RULES.get("default", {}),
        "status": "active" if FIREWALL_RULES.get("default", {}).get("enabled", True) else "disabled"
    }

@router.put("/rules")
async def update_firewall_rules(
    request: FirewallRuleUpdate,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Update firewall rules configuration.
    """
    current_rules = FIREWALL_RULES.get("default", {}).copy()
    
    # Update only provided fields
    if request.enabled is not None:
        current_rules["enabled"] = request.enabled
    if request.test_mode is not None:
        current_rules["test_mode"] = request.test_mode
    if request.blocked_patterns is not None:
        current_rules["blocked_patterns"] = request.blocked_patterns
    if request.allowed_patterns is not None:
        current_rules["allowed_patterns"] = request.allowed_patterns
    if request.require_approval_for is not None:
        current_rules["require_approval_for"] = request.require_approval_for
    if request.max_complexity is not None:
        current_rules["max_complexity"] = request.max_complexity
    if request.block_file_extensions is not None:
        current_rules["block_file_extensions"] = request.block_file_extensions
    if request.block_paths is not None:
        current_rules["block_paths"] = request.block_paths
    
    current_rules["updated_at"] = datetime.now().isoformat()
    FIREWALL_RULES["default"] = current_rules
    
    return {
        "status": "success",
        "rules": current_rules
    }

@router.post("/test")
async def test_firewall_rule(
    request: TestRuleRequest,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Test a code snippet against current firewall rules.
    Returns whether it would be blocked and why.
    """
    rules = FIREWALL_RULES.get("default", {})
    
    result = check_fix_against_rules(
        rules,
        request.code_snippet,
        request.file_path or "",
        request.file_extension or ""
    )
    
    # If in test mode, log but don't actually block
    if rules.get("test_mode", False):
        result["test_mode"] = True
        result["message"] = "Test mode: This would be blocked in production"
    
    return result

@router.get("/blocked")
async def get_blocked_fixes(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    test_mode_only: Optional[bool] = Query(None),
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get log of blocked fixes.
    """
    filtered_logs = BLOCKED_FIXES_LOG.copy()
    
    # Filter by test_mode if specified
    if test_mode_only is not None:
        filtered_logs = [log for log in filtered_logs if log.get("test_mode") == test_mode_only]
    
    # Sort by timestamp descending
    filtered_logs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    # Apply pagination
    total = len(filtered_logs)
    paginated_logs = filtered_logs[offset:offset + limit]
    
    return {
        "blocked_fixes": paginated_logs,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(paginated_logs)) < total
    }

@router.post("/blocked/{block_id}/allow")
async def allow_blocked_fix(
    block_id: str,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Allow a previously blocked fix (override firewall rule).
    """
    # Find the blocked fix
    blocked_fix = next((f for f in BLOCKED_FIXES_LOG if f.get("block_id") == block_id), None)
    
    if not blocked_fix:
        raise HTTPException(status_code=404, detail="Blocked fix not found")
    
    # In production, this would trigger the fix to be applied
    # For now, just mark it as allowed
    blocked_fix["allowed"] = True
    blocked_fix["allowed_at"] = time.time()
    blocked_fix["allowed_by"] = user_info.get("user_id", "unknown")
    
    return {
        "status": "success",
        "message": "Fix allowed and will be applied",
        "blocked_fix": blocked_fix
    }

@router.get("/stats")
async def get_firewall_stats(
    days: int = Query(30, ge=1, le=365),
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get firewall statistics.
    """
    cutoff_time = time.time() - (days * 24 * 60 * 60)
    recent_blocks = [b for b in BLOCKED_FIXES_LOG if b.get("timestamp", 0) > cutoff_time]
    
    # Count by rule type
    rule_counts = {}
    for block in recent_blocks:
        rule_type = block.get("rule_matched", "unknown")
        rule_counts[rule_type] = rule_counts.get(rule_type, 0) + 1
    
    # Count by severity
    severity_counts = {}
    for block in recent_blocks:
        severity = block.get("severity", "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    
    return {
        "total_blocked": len(recent_blocks),
        "period_days": days,
        "by_rule_type": rule_counts,
        "by_severity": severity_counts,
        "test_mode_blocks": len([b for b in recent_blocks if b.get("test_mode", False)]),
        "production_blocks": len([b for b in recent_blocks if not b.get("test_mode", False)])
    }

