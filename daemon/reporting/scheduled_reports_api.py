"""
Scheduled Reports API
Provides endpoints for scheduling compliance reports with cron jobs and email delivery
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import uuid
import json

router = APIRouter(prefix="/api/reports/scheduled", tags=["Scheduled Reports"])

# Import authentication
try:
    from daemon.auth.api_key_auth import verify_api_key
except ImportError:
    async def verify_api_key(request: Request, credentials=None):
        return {"user_id": "default"}

# Mock scheduled reports storage (in production, use database)
SCHEDULED_REPORTS = {}

class CreateScheduledReportRequest(BaseModel):
    name: str
    project_id: str
    framework: Optional[str] = None  # "soc2", "gdpr", "owasp", "pci", "all"
    format: str = "html"  # "html", "pdf", "json"
    schedule: str  # Cron expression (e.g., "0 9 * * 1" for every Monday at 9 AM)
    email_recipients: List[EmailStr] = []
    enabled: bool = True

class UpdateScheduledReportRequest(BaseModel):
    name: Optional[str] = None
    project_id: Optional[str] = None
    framework: Optional[str] = None
    format: Optional[str] = None
    schedule: Optional[str] = None
    email_recipients: Optional[List[EmailStr]] = None
    enabled: Optional[bool] = None

def validate_cron_expression(cron_expr: str) -> bool:
    """
    Validate cron expression using croniter library.
    Format: minute hour day month weekday
    Supports standard cron syntax including ranges, lists, and step values.
    """
    try:
        # Try importing croniter
        try:
            from croniter import croniter
        except ImportError:
            # Fallback to basic validation if croniter not available
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return False
            # Basic format check - at least ensure it has 5 parts
            return True
        
        # Use croniter to validate the expression
        # This will raise an exception if the cron expression is invalid
        now = datetime.now()
        cron = croniter(cron_expr, now)
        # Try to get the next run time - if this succeeds, the expression is valid
        cron.get_next(datetime)
        return True
        
    except Exception as e:
        # Any exception means the cron expression is invalid
        return False

@router.post("/")
async def create_scheduled_report(
    request: CreateScheduledReportRequest,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Create a new scheduled report.
    """
    user_id = user_info.get("user_id")
    
    # Validate cron expression
    if not validate_cron_expression(request.schedule):
        raise HTTPException(
            status_code=400,
            detail="Invalid cron expression. Format: 'minute hour day month weekday' (e.g., '0 9 * * 1' for every Monday at 9 AM)"
        )
    
    # Calculate next run time using croniter
    next_run_time = None
    try:
        from daemon.reporting.scheduler import get_next_run_time
        next_run_time = get_next_run_time(request.schedule)
    except:
        pass
    
    # Create scheduled report
    schedule_id = str(uuid.uuid4())
    SCHEDULED_REPORTS[schedule_id] = {
        "schedule_id": schedule_id,
        "name": request.name,
        "project_id": request.project_id,
        "framework": request.framework or "all",
        "format": request.format,
        "schedule": request.schedule,
        "email_recipients": [str(email) for email in request.email_recipients],
        "enabled": request.enabled,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": next_run_time.isoformat() if next_run_time else None,
        "run_count": 0
    }
    
    return {
        "status": "success",
        "schedule_id": schedule_id,
        "scheduled_report": SCHEDULED_REPORTS[schedule_id]
    }

@router.get("/")
async def list_scheduled_reports(
    project_id: Optional[str] = Query(None),
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    List all scheduled reports for the authenticated user.
    """
    user_id = user_info.get("user_id")
    
    # Filter by user and optionally project
    user_schedules = []
    for schedule_id, schedule in SCHEDULED_REPORTS.items():
        if schedule.get("user_id") == user_id:
            if not project_id or schedule.get("project_id") == project_id:
                user_schedules.append(schedule)
    
    # Sort by created_at descending
    user_schedules.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return {
        "scheduled_reports": user_schedules,
        "total": len(user_schedules)
    }

@router.get("/{schedule_id}")
async def get_scheduled_report(
    schedule_id: str,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get a specific scheduled report by ID.
    """
    user_id = user_info.get("user_id")
    
    if schedule_id not in SCHEDULED_REPORTS:
        raise HTTPException(status_code=404, detail="Scheduled report not found")
    
    schedule = SCHEDULED_REPORTS[schedule_id]
    
    # Check if user owns this schedule
    if schedule.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return {
        "scheduled_report": schedule
    }

@router.put("/{schedule_id}")
async def update_scheduled_report(
    schedule_id: str,
    request: UpdateScheduledReportRequest,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Update a scheduled report.
    """
    user_id = user_info.get("user_id")
    
    if schedule_id not in SCHEDULED_REPORTS:
        raise HTTPException(status_code=404, detail="Scheduled report not found")
    
    schedule = SCHEDULED_REPORTS[schedule_id]
    
    # Check if user owns this schedule
    if schedule.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Validate cron expression if provided
    if request.schedule and not validate_cron_expression(request.schedule):
        raise HTTPException(
            status_code=400,
            detail="Invalid cron expression. Format: 'minute hour day month weekday'"
        )
    
    # Update only provided fields
    if request.name is not None:
        schedule["name"] = request.name
    if request.project_id is not None:
        schedule["project_id"] = request.project_id
    if request.framework is not None:
        schedule["framework"] = request.framework
    if request.format is not None:
        schedule["format"] = request.format
    if request.schedule is not None:
        schedule["schedule"] = request.schedule
        # Recalculate next run time if schedule changed
        try:
            from daemon.reporting.scheduler import get_next_run_time
            next_run = get_next_run_time(request.schedule)
            schedule["next_run"] = next_run.isoformat() if next_run else None
        except:
            pass
    if request.email_recipients is not None:
        schedule["email_recipients"] = [str(email) for email in request.email_recipients]
    if request.enabled is not None:
        schedule["enabled"] = request.enabled
    
    schedule["updated_at"] = datetime.now().isoformat()
    
    return {
        "status": "success",
        "scheduled_report": schedule
    }

@router.delete("/{schedule_id}")
async def delete_scheduled_report(
    schedule_id: str,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Delete a scheduled report.
    """
    user_id = user_info.get("user_id")
    
    if schedule_id not in SCHEDULED_REPORTS:
        raise HTTPException(status_code=404, detail="Scheduled report not found")
    
    schedule = SCHEDULED_REPORTS[schedule_id]
    
    # Check if user owns this schedule
    if schedule.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    del SCHEDULED_REPORTS[schedule_id]
    
    return {
        "status": "success",
        "message": "Scheduled report deleted"
    }

@router.post("/{schedule_id}/run")
async def run_scheduled_report_now(
    schedule_id: str,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Manually trigger a scheduled report to run immediately.
    """
    user_id = user_info.get("user_id")
    
    if schedule_id not in SCHEDULED_REPORTS:
        raise HTTPException(status_code=404, detail="Scheduled report not found")
    
    schedule = SCHEDULED_REPORTS[schedule_id]
    
    # Check if user owns this schedule
    if schedule.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Import here to avoid circular imports
    try:
        from daemon.reporting.scheduler import execute_scheduled_report
    except ImportError:
        # Fallback if scheduler not available
        async def execute_scheduled_report(schedule_id: str):
            raise NotImplementedError("Scheduler not available")
    
    try:
        result = await execute_scheduled_report(schedule_id)
        return {
            "status": "success",
            "message": "Report executed successfully",
            "result": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute scheduled report: {str(e)}"
        )

