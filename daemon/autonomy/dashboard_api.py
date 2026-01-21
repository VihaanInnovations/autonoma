from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from pathlib import Path
import json
import time
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/autonomy", tags=["L5 Autonomy Dashboard"])

# Mock data storage for fixes queue and history
# In production, this would be stored in a database
FIXES_QUEUE = [
    {
        "fix_id": "fix_001",
        "file_path": "src/auth.py",
        "issue_id": "SECURITY_001",
        "issue_message": "Potential SQL injection vulnerability",
        "severity": "high",
        "confidence": 0.85,
        "status": "pending",
        "created_at": time.time() - 3600,
        "fix_preview": "Added parameterized query to prevent SQL injection"
    },
    {
        "fix_id": "fix_002",
        "file_path": "src/utils.py",
        "issue_id": "PERFORMANCE_001",
        "issue_message": "Inefficient loop causing O(n²) complexity",
        "severity": "medium",
        "confidence": 0.92,
        "status": "pending",
        "created_at": time.time() - 1800,
        "fix_preview": "Optimized loop using dictionary lookup"
    }
]

FIXES_HISTORY = [
    {
        "fix_id": "fix_003",
        "file_path": "src/api.py",
        "issue_id": "BUG_001",
        "issue_message": "Null pointer exception in error handler",
        "severity": "high",
        "confidence": 0.95,
        "status": "applied",
        "success": True,
        "timestamp": time.time() - 86400,
        "applied_at": time.time() - 86400
    },
    {
        "fix_id": "fix_004",
        "file_path": "src/db.py",
        "issue_id": "BUG_002",
        "issue_message": "Memory leak in connection pool",
        "severity": "high",
        "confidence": 0.78,
        "status": "applied",
        "success": False,
        "timestamp": time.time() - 172800,
        "applied_at": time.time() - 172800,
        "error": "Fix caused regression in test suite"
    }
]
AUTONOMY_POLICIES = {
    "default": {
        "require_approval": True,
        "auto_apply_confidence_threshold": 0.9,
        "max_fixes_per_session": 50,
        "allowed_severities": ["high", "medium"],
        "blocked_patterns": [],
        "rollback_on_failure": True
    }
}

# Request/Response Models
class FixApprovalRequest(BaseModel):
    action: str  # "approve" or "reject"
    comment: Optional[str] = None

class PolicyUpdateRequest(BaseModel):
    require_approval: Optional[bool] = None
    auto_apply_confidence_threshold: Optional[float] = None
    max_fixes_per_session: Optional[int] = None
    allowed_severities: Optional[List[str]] = None
    blocked_patterns: Optional[List[str]] = None
    rollback_on_failure: Optional[bool] = None

class RollbackRequest(BaseModel):
    fix_id: str
    reason: Optional[str] = None

@router.get("/fixes/queue")
async def get_fixes_queue(
    status: Optional[str] = None,  # "pending", "approved", "rejected"
    limit: int = 50
) -> Dict[str, Any]:
    """
    Get the approval queue of fixes waiting for review.
    """
    # In production, this would query the database
    # For now, return mock data
    queue = FIXES_QUEUE.copy()
    
    if status:
        queue = [f for f in queue if f.get("status") == status]
    
    return {
        "fixes": queue[:limit],
        "total": len(queue),
        "pending": len([f for f in queue if f.get("status") == "pending"]),
        "approved": len([f for f in queue if f.get("status") == "approved"]),
        "rejected": len([f for f in queue if f.get("status") == "rejected"])
    }

@router.get("/fixes/history")
async def get_fixes_history(
    days: int = 7,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get historical fixes with analytics.
    """
    # In production, this would query flight recorder logs
    cutoff_time = time.time() - (days * 24 * 60 * 60)
    
    history = [f for f in FIXES_HISTORY if f.get("timestamp", 0) > cutoff_time]
    history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    # Calculate analytics
    total_fixes = len(history)
    successful = len([f for f in history if f.get("status") == "applied" and f.get("success", False)])
    failed = len([f for f in history if f.get("status") == "applied" and not f.get("success", False)])
    success_rate = (successful / total_fixes * 100) if total_fixes > 0 else 0
    
    return {
        "fixes": history[:limit],
        "analytics": {
            "total_fixes": total_fixes,
            "successful": successful,
            "failed": failed,
            "success_rate": round(success_rate, 2),
            "pending_approval": len([f for f in FIXES_QUEUE if f.get("status") == "pending"]),
            "average_confidence": round(sum([f.get("confidence", 0) for f in history if f.get("confidence") is not None]) / max(total_fixes, 1), 2) if total_fixes > 0 else 0
        }
    }

@router.get("/fixes/realtime")
async def get_realtime_fixes(
    since: Optional[float] = None  # Unix timestamp
) -> Dict[str, Any]:
    """
    Get real-time fix feed (for WebSocket or polling).
    Includes both queue items and recent history.
    """
    if since is None:
        since = time.time() - 300  # Last 5 minutes
    
    # Get recent fixes from history
    recent_history = [f for f in FIXES_HISTORY if f.get("timestamp", 0) > since]
    
    # Get all pending fixes from queue (they're all recent)
    recent_queue = [f for f in FIXES_QUEUE if f.get("status") == "pending"]
    
    # Combine and sort by timestamp (queue items use created_at)
    all_recent = []
    for fix in recent_history:
        all_recent.append(fix)
    for fix in recent_queue:
        all_recent.append({
            **fix,
            "timestamp": fix.get("created_at", time.time())
        })
    
    all_recent.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    return {
        "fixes": all_recent,
        "count": len(all_recent),
        "timestamp": time.time()
    }

@router.post("/fixes/{fix_id}/approve")
async def approve_fix(
    fix_id: str,
    request: FixApprovalRequest
) -> Dict[str, Any]:
    """
    Approve or reject a fix in the queue.
    """
    # Find fix in queue
    fix = next((f for f in FIXES_QUEUE if f.get("fix_id") == fix_id), None)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found in queue")
    
    # Update status
    fix["status"] = request.action
    fix["reviewed_at"] = time.time()
    fix["review_comment"] = request.comment
    
    # Move to history
    FIXES_HISTORY.append({
        **fix,
        "timestamp": time.time()
    })
    
    # Remove from queue if approved/rejected
    if request.action in ["approve", "reject"]:
        FIXES_QUEUE.remove(fix)
    
    return {
        "status": "success",
        "fix_id": fix_id,
        "action": request.action,
        "message": f"Fix {request.action}d successfully"
    }

@router.post("/fixes/{fix_id}/rollback")
async def rollback_fix(
    fix_id: str,
    request: RollbackRequest
) -> Dict[str, Any]:
    """
    Rollback an applied fix.
    """
    # Find fix in history
    fix = next((f for f in FIXES_HISTORY if f.get("fix_id") == fix_id), None)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    
    if fix.get("status") != "applied":
        raise HTTPException(status_code=400, detail="Only applied fixes can be rolled back")
    
    # Mark as rolled back
    fix["rolled_back"] = True
    fix["rollback_reason"] = request.reason
    fix["rollback_timestamp"] = time.time()
    
    return {
        "status": "success",
        "fix_id": fix_id,
        "message": "Fix rolled back successfully"
    }

@router.get("/policies")
async def get_policies() -> Dict[str, Any]:
    """
    Get current autonomy policies.
    """
    return AUTONOMY_POLICIES.get("default", {})

@router.put("/policies")
async def update_policies(
    request: PolicyUpdateRequest
) -> Dict[str, Any]:
    """
    Update autonomy policies.
    """
    current_policies = AUTONOMY_POLICIES.get("default", {})
    
    if request.require_approval is not None:
        current_policies["require_approval"] = request.require_approval
    if request.auto_apply_confidence_threshold is not None:
        current_policies["auto_apply_confidence_threshold"] = request.auto_apply_confidence_threshold
    if request.max_fixes_per_session is not None:
        current_policies["max_fixes_per_session"] = request.max_fixes_per_session
    if request.allowed_severities is not None:
        current_policies["allowed_severities"] = request.allowed_severities
    if request.blocked_patterns is not None:
        current_policies["blocked_patterns"] = request.blocked_patterns
    if request.rollback_on_failure is not None:
        current_policies["rollback_on_failure"] = request.rollback_on_failure
    
    AUTONOMY_POLICIES["default"] = current_policies
    
    return {
        "status": "success",
        "policies": current_policies
    }

@router.get("/analytics")
async def get_analytics(
    days: int = 30
) -> Dict[str, Any]:
    """
    Get comprehensive analytics for the L5 autonomy dashboard.
    """
    cutoff_time = time.time() - (days * 24 * 60 * 60)
    recent_fixes = [f for f in FIXES_HISTORY if f.get("timestamp", 0) > cutoff_time]
    
    # Calculate metrics
    total = len(recent_fixes)
    successful = len([f for f in recent_fixes if f.get("success", False)])
    failed = len([f for f in recent_fixes if f.get("status") == "applied" and not f.get("success", False)])
    
    # Group by day for chart data
    daily_stats = {}
    for fix in recent_fixes:
        date = datetime.fromtimestamp(fix.get("timestamp", time.time())).strftime("%Y-%m-%d")
        if date not in daily_stats:
            daily_stats[date] = {"total": 0, "successful": 0, "failed": 0}
        daily_stats[date]["total"] += 1
        if fix.get("success", False):
            daily_stats[date]["successful"] += 1
        elif fix.get("status") == "applied":
            daily_stats[date]["failed"] += 1
    
    # Severity breakdown
    severity_counts = {}
    for fix in recent_fixes:
        severity = fix.get("severity", "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    
    return {
        "summary": {
            "total_fixes": total,
            "successful": successful,
            "failed": failed,
            "success_rate": round((successful / total * 100) if total > 0 else 0, 2),
            "pending_approval": len([f for f in FIXES_QUEUE if f.get("status") == "pending"])
        },
        "daily_stats": daily_stats,
        "severity_breakdown": severity_counts,
        "time_range_days": days
    }

