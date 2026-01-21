"""
Email Sender for Scheduled Reports
Handles sending compliance reports via email with retry logic and professional templates
"""
import logging
import os
import asyncio
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import smtplib
import base64
from datetime import datetime

# Import email templates
try:
    from daemon.reporting.email_templates import (
        get_email_template,
        get_plain_text_template,
        get_issue_summary_html
    )
except ImportError:
    # Fallback if templates not available
    def get_email_template(*args, **kwargs):
        return "<html><body><h1>Compliance Report</h1></body></html>"
    def get_plain_text_template(*args, **kwargs):
        return "Compliance Report"
    def get_issue_summary_html(*args, **kwargs):
        return ""

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRY_ATTEMPTS = int(os.getenv("EMAIL_MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("EMAIL_RETRY_BACKOFF", "2.0"))  # Exponential backoff multiplier
RETRY_INITIAL_DELAY = float(os.getenv("EMAIL_RETRY_INITIAL_DELAY", "1.0"))  # Initial delay in seconds

async def _send_email_attempt(
    recipients: List[str],
    report_name: str,
    report_data: Dict[str, Any],
    project_id: str
) -> bool:
    """
    Single attempt to send email. Internal function used by send_report_email with retry logic.
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Get SMTP configuration from environment variables
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        smtp_from = os.getenv("SMTP_FROM", smtp_user or "noreply@codesentinal.cloud")
        
        # If SMTP not configured, raise exception to skip retries (no point retrying without config)
        if not smtp_user or not smtp_password:
            raise ValueError(
                "SMTP not configured. Set SMTP_USER and SMTP_PASSWORD environment variables. "
                "Email delivery cannot proceed."
            )
        
        # Extract report metadata
        report_format = report_data.get("format", "html")
        generated_at = report_data.get("generated_at") or report_data.get("data", {}).get("generated_at") or datetime.now().isoformat()
        framework = report_data.get("data", {}).get("framework", "all") if report_format == "json" else report_data.get("data", {}).get("framework", "all")
        issues = report_data.get("data", {}).get("issues", []) if report_format == "json" else []
        issue_count = len(issues) if issues else 0
        
        # If we have issues from JSON format, use them; otherwise try to extract from HTML content
        if not issues and report_format == "html":
            # Try to extract issue count from HTML (basic parsing)
            content = report_data.get("content", "")
            # This is a simple heuristic - in production, you might want more sophisticated parsing
            issue_count = content.count("severity") if content else 0
        
        # Create message
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"Compliance Report: {report_name} - {project_id}"
        
        # Determine if we have an attachment
        has_attachment = report_format in ["pdf", "json"]
        
        # Generate email templates
        html_body = get_email_template(
            report_name=report_name,
            project_id=project_id,
            framework=framework,
            issue_count=issue_count,
            generated_at=generated_at,
            report_format=report_format,
            has_attachment=has_attachment
        )
        
        # Add issue summary if we have issues
        if issues and len(issues) > 0:
            issue_summary = get_issue_summary_html(issues, max_issues=10)
            # Insert issue summary before the action button section
            html_body = html_body.replace(
                '<!-- Action Button -->',
                issue_summary + '\n                            <!-- Action Button -->'
            )
        
        plain_text_body = get_plain_text_template(
            report_name=report_name,
            project_id=project_id,
            framework=framework,
            issue_count=issue_count,
            generated_at=generated_at,
            report_format=report_format,
            has_attachment=has_attachment
        )
        
        # Attach HTML and plain text versions
        msg.attach(MIMEText(plain_text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        
        # Handle attachments
        if report_format == "pdf":
            # PDF attachment
            pdf_content = report_data.get("content")
            if pdf_content:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(pdf_content)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="compliance_report_{project_id}.pdf"'
                )
                msg.attach(part)
        elif report_format == "json":
            # JSON attachment
            import json
            json_content = json.dumps(report_data.get("data", {}), indent=2)
            part = MIMEBase("application", "json")
            part.set_payload(json_content)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="compliance_report_{project_id}.json"'
            )
            msg.attach(part)
        
        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Report email sent successfully to {len(recipients)} recipients")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send report email: {e}", exc_info=True)
        raise  # Re-raise to trigger retry logic

async def send_report_email(
    recipients: List[str],
    report_name: str,
    report_data: Dict[str, Any],
    project_id: str,
    max_retries: Optional[int] = None,
    retry_backoff: Optional[float] = None,
    initial_delay: Optional[float] = None
) -> Dict[str, Any]:
    """
    Send a compliance report via email with retry logic and exponential backoff.
    
    Args:
        recipients: List of email addresses
        report_name: Name of the report
        report_data: Report data (content and format)
        project_id: Project identifier
        max_retries: Maximum number of retry attempts (default: from env or 3)
        retry_backoff: Backoff multiplier for exponential delay (default: from env or 2.0)
        initial_delay: Initial delay in seconds before first retry (default: from env or 1.0)
    
    Returns:
        Dict with 'success' (bool), 'attempts' (int), 'last_error' (str or None)
    """
    max_retries = max_retries or MAX_RETRY_ATTEMPTS
    retry_backoff = retry_backoff or RETRY_BACKOFF_BASE
    initial_delay = initial_delay or RETRY_INITIAL_DELAY
    
    last_error = None
    attempts = 0
    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        attempts = attempt + 1
        
        try:
            success = await _send_email_attempt(recipients, report_name, report_data, project_id)
            if success:
                logger.info(
                    f"Email sent successfully after {attempts} attempt(s) to {len(recipients)} recipients"
                )
                return {
                    "success": True,
                    "attempts": attempts,
                    "last_error": None
                }
        except ValueError as e:
            # Configuration errors - don't retry
            last_error = str(e)
            logger.error(f"Email configuration error: {last_error}. Skipping retries.")
            return {
                "success": False,
                "attempts": attempts,
                "last_error": last_error
            }
        except Exception as e:
            last_error = str(e)
            
            if attempt < max_retries:
                # Calculate delay with exponential backoff
                delay = initial_delay * (retry_backoff ** attempt)
                logger.warning(
                    f"Email send attempt {attempts} failed: {last_error}. "
                    f"Retrying in {delay:.2f} seconds... ({max_retries - attempt} attempts remaining)"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"Email send failed after {attempts} attempts. Last error: {last_error}"
                )
    
    # All retries exhausted
    logger.error(
        f"Failed to send email after {attempts} attempts. "
        f"Recipients: {', '.join(recipients)}. Last error: {last_error}"
    )
    
    return {
        "success": False,
        "attempts": attempts,
        "last_error": last_error
    }

