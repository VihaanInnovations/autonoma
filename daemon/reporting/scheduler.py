"""
Scheduled Reports Scheduler
Handles cron job execution and email delivery for scheduled reports
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("croniter not available. Install with: pip install croniter")

from daemon.reporting.scheduled_reports_api import SCHEDULED_REPORTS
from daemon.reporting.reports_api import get_issues_for_date_range, filter_issues_by_framework
from daemon.reporting.generator import ReportGenerator
from daemon.reporting.email_sender import send_report_email

logger = logging.getLogger(__name__)

def should_run_now(cron_expr: str, last_run: Optional[str] = None) -> bool:
    """
    Check if a scheduled report should run now based on cron expression.
    Uses croniter library for accurate cron expression parsing.
    """
    if not CRONITER_AVAILABLE:
        logger.error("croniter library not available. Cannot check cron schedule.")
        return False
    
    try:
        now = datetime.now()
        
        # If last_run is recent (within last 5 minutes), don't run again
        # This prevents duplicate runs if the scheduler runs multiple times quickly
        if last_run:
            try:
                last_run_dt = datetime.fromisoformat(last_run)
                if (now - last_run_dt).total_seconds() < 300:  # 5 minutes
                    return False
            except:
                pass
        
        # Use croniter to check if the cron expression matches now
        # croniter.get_next() returns the next time the cron should run
        # If the next run time is in the past or very close to now, it should run
        cron = croniter(cron_expr, now)
        next_run = cron.get_prev(datetime)  # Get previous scheduled time
        
        # Check if the previous scheduled time is within the last minute
        # This allows for some tolerance in case the scheduler is slightly delayed
        time_diff = (now - next_run).total_seconds()
        
        # Run if the last scheduled time was within the last 60 seconds
        return 0 <= time_diff <= 60
        
    except Exception as e:
        logger.error(f"Error checking cron expression '{cron_expr}': {e}")
        return False

def get_next_run_time(cron_expr: str, from_time: Optional[datetime] = None) -> Optional[datetime]:
    """
    Get the next scheduled run time for a cron expression.
    
    Args:
        cron_expr: Cron expression string
        from_time: Reference time (defaults to now)
    
    Returns:
        Next run time as datetime, or None if croniter not available
    """
    if not CRONITER_AVAILABLE:
        return None
    
    try:
        reference_time = from_time or datetime.now()
        cron = croniter(cron_expr, reference_time)
        return cron.get_next(datetime)
    except Exception as e:
        logger.error(f"Error calculating next run time for '{cron_expr}': {e}")
        return None

async def execute_scheduled_report(schedule_id: str) -> Dict[str, Any]:
    """
    Execute a scheduled report and send via email if configured.
    """
    if schedule_id not in SCHEDULED_REPORTS:
        raise ValueError(f"Scheduled report {schedule_id} not found")
    
    schedule = SCHEDULED_REPORTS[schedule_id]
    
    if not schedule.get("enabled", True):
        logger.info(f"Scheduled report {schedule_id} is disabled, skipping")
        return {"status": "skipped", "reason": "disabled"}
    
    logger.info(f"Executing scheduled report {schedule_id}: {schedule.get('name')}")
    
    try:
        # Get issues for report
        issues = get_issues_for_date_range(
            schedule.get("project_id"),
            None,  # No date range for scheduled reports - use all issues
            None
        )
        
        # Filter by framework
        framework = schedule.get("framework")
        if framework and framework != "all":
            issues = filter_issues_by_framework(issues, framework)
        
        # Generate report
        generator = ReportGenerator()
        format_type = schedule.get("format", "html")
        
        if format_type == "html":
            report_content = generator.generate_html_report(schedule.get("project_id"), issues)
            report_data = {
                "content": report_content,
                "format": "html",
                "generated_at": datetime.now().isoformat(),
                "data": {
                    "framework": framework or "all",
                    "issues": issues
                }
            }
        elif format_type == "pdf":
            try:
                pdf_bytes = generator.generate_pdf_report(schedule.get("project_id"), issues)
                report_data = {
                    "content": pdf_bytes,
                    "format": "pdf",
                    "generated_at": datetime.now().isoformat(),
                    "data": {
                        "framework": framework or "all",
                        "issues": issues
                    }
                }
            except Exception as e:
                logger.error(f"PDF generation failed: {e}")
                # Fallback to HTML
                report_content = generator.generate_html_report(schedule.get("project_id"), issues)
                report_data = {
                    "content": report_content,
                    "format": "html",
                    "generated_at": datetime.now().isoformat(),
                    "data": {
                        "framework": framework or "all",
                        "issues": issues
                    }
                }
        else:  # json
            report_data = {
                "format": "json",
                "data": {
                    "project_id": schedule.get("project_id"),
                    "framework": framework or "all",
                    "issues": issues,
                    "generated_at": datetime.now().isoformat()
                },
                "generated_at": datetime.now().isoformat()  # Also add at top level for template
            }
        
        # Send email if recipients configured
        email_recipients = schedule.get("email_recipients", [])
        email_result = None
        if email_recipients:
            try:
                email_result = await send_report_email(
                    recipients=email_recipients,
                    report_name=schedule.get("name"),
                    report_data=report_data,
                    project_id=schedule.get("project_id")
                )
                if email_result.get("success"):
                    logger.info(
                        f"Report sent via email to {len(email_recipients)} recipients "
                        f"(after {email_result.get('attempts', 1)} attempt(s))"
                    )
                else:
                    logger.error(
                        f"Failed to send email after {email_result.get('attempts', 1)} attempts: "
                        f"{email_result.get('last_error', 'Unknown error')}"
                    )
            except Exception as e:
                logger.error(f"Email sending failed with exception: {e}", exc_info=True)
                email_result = {
                    "success": False,
                    "attempts": 1,
                    "last_error": str(e)
                }
                # Continue even if email fails
        
        # Update schedule metadata
        schedule["last_run"] = datetime.now().isoformat()
        schedule["run_count"] = schedule.get("run_count", 0) + 1
        
        # Calculate next run time using croniter
        next_run = get_next_run_time(schedule.get("schedule"))
        if next_run:
            schedule["next_run"] = next_run.isoformat()
        
        return {
            "status": "success",
            "report_generated": True,
            "email_sent": email_result.get("success", False) if email_result else False,
            "email_attempts": email_result.get("attempts", 0) if email_result else 0,
            "email_error": email_result.get("last_error") if email_result and not email_result.get("success") else None,
            "issue_count": len(issues)
        }
        
    except Exception as e:
        logger.error(f"Failed to execute scheduled report {schedule_id}: {e}", exc_info=True)
        schedule["last_run"] = datetime.now().isoformat()
        raise

async def check_and_run_scheduled_reports():
    """
    Check all enabled scheduled reports and run those that should execute now.
    This function should be called periodically (e.g., every minute).
    """
    current_time = datetime.now()
    
    for schedule_id, schedule in SCHEDULED_REPORTS.items():
        if not schedule.get("enabled", True):
            continue
        
        cron_expr = schedule.get("schedule")
        last_run = schedule.get("last_run")
        
        if should_run_now(cron_expr, last_run):
            try:
                await execute_scheduled_report(schedule_id)
            except Exception as e:
                logger.error(f"Error executing scheduled report {schedule_id}: {e}")

async def start_scheduler():
    """
    Start the scheduler background task.
    Checks for scheduled reports every minute.
    """
    logger.info("Starting scheduled reports scheduler")
    
    while True:
        try:
            await check_and_run_scheduled_reports()
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
        
        # Wait 60 seconds before next check
        await asyncio.sleep(60)

