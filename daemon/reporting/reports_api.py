"""
Compliance Reports API
Provides endpoints for generating, viewing, and exporting compliance reports
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
from starlette.responses import Response, HTMLResponse
import uuid

router = APIRouter(prefix="/api/reports", tags=["Compliance Reports"])

# Import authentication
try:
    from daemon.auth.api_key_auth import verify_api_key
except ImportError:
    async def verify_api_key(request: Request, credentials=None):
        return {"user_id": "default"}

# Import report generator
from daemon.reporting.generator import ReportGenerator

# Mock report history storage (in production, use database)
REPORT_HISTORY = {}

class GenerateReportRequest(BaseModel):
    project_id: str = "default"
    framework: Optional[str] = None  # "soc2", "gdpr", "owasp", "pci", "all"
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None  # YYYY-MM-DD
    format: str = "html"  # "html", "pdf", "json"

def get_issues_for_date_range(project_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get issues for a project within a date range.
    In production, this would query the database.
    """
    # Mock issues - in production, query from database
    issues = [
        {"id": "SEC001", "severity": "high", "message": "Hardcoded AWS Secret Key found", "file": "backend/auth.py", "line": 42, "type": "hardcoded_secret", "timestamp": "2024-01-15T10:00:00Z"},
        {"id": "SEC002", "severity": "medium", "message": "Potential SQL Injection in query construction", "file": "backend/db.py", "line": 105, "type": "sql_injection", "timestamp": "2024-01-16T14:30:00Z"},
        {"id": "QA001", "severity": "low", "message": "Function 'process_data' has high cyclomatic complexity", "file": "backend/utils.py", "line": 12, "type": "high_complexity", "timestamp": "2024-01-17T09:15:00Z"},
        {"id": "GDPR001", "severity": "high", "message": "PII data found in log output", "file": "backend/logging.py", "line": 88, "type": "pii_leak", "timestamp": "2024-01-18T11:20:00Z"}
    ]
    
    # Filter by date range if provided
    if start_date or end_date:
        filtered_issues = []
        for issue in issues:
            issue_date = issue.get("timestamp", "")
            if not issue_date:
                # Include issues without timestamp if no date filter
                if not start_date and not end_date:
                    filtered_issues.append(issue)
                continue
            
            # Extract date part (YYYY-MM-DD) from timestamp
            issue_date_only = issue_date.split('T')[0] if 'T' in issue_date else issue_date.split(' ')[0]
            
            if start_date and issue_date_only < start_date:
                continue
            if end_date and issue_date_only > end_date:
                continue
            filtered_issues.append(issue)
        return filtered_issues
    
    return issues

def filter_issues_by_framework(issues: List[Dict[str, Any]], framework: Optional[str]) -> List[Dict[str, Any]]:
    """
    Filter issues by compliance framework.
    """
    if not framework or framework == "all":
        return issues
    
    from daemon.reporting.compliance_map import get_compliance_tags
    
    filtered = []
    for issue in issues:
        issue_type = issue.get("type", "unknown").lower()
        compliance = get_compliance_tags(issue_type)
        
        # Check if issue is relevant to the selected framework
        if framework == "soc2" and compliance.get("soc2") != "General Logic":
            filtered.append(issue)
        elif framework == "gdpr" and compliance.get("gdpr") != "N/A":
            filtered.append(issue)
        elif framework == "owasp" and compliance.get("owasp") != "Uncategorized":
            filtered.append(issue)
        elif framework == "pci" and compliance.get("pci") != "N/A":
            filtered.append(issue)
    
    return filtered

@router.post("/generate")
async def generate_report(
    request: GenerateReportRequest,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Generate a compliance report with framework selection and date range.
    """
    user_id = user_info.get("user_id")
    
    # Get issues for date range
    issues = get_issues_for_date_range(
        request.project_id,
        request.start_date,
        request.end_date
    )
    
    # Filter by framework
    if request.framework:
        issues = filter_issues_by_framework(issues, request.framework)
    
    # Generate report
    generator = ReportGenerator()
    
    if request.format == "html":
        report_content = generator.generate_html_report(request.project_id, issues)
        
        # Save to history
        report_id = str(uuid.uuid4())
        REPORT_HISTORY[report_id] = {
            "report_id": report_id,
            "project_id": request.project_id,
            "framework": request.framework or "all",
            "start_date": request.start_date,
            "end_date": request.end_date,
            "format": request.format,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "issue_count": len(issues)
        }
        
        return {
            "status": "success",
            "report_id": report_id,
            "format": "html",
            "content": report_content
        }
    
    elif request.format == "json":
        # Generate JSON report
        report_data = {
            "project_id": request.project_id,
            "framework": request.framework or "all",
            "start_date": request.start_date,
            "end_date": request.end_date,
            "generated_at": datetime.now().isoformat(),
            "total_issues": len(issues),
            "issues": issues
        }
        
        # Save to history
        report_id = str(uuid.uuid4())
        REPORT_HISTORY[report_id] = {
            "report_id": report_id,
            "project_id": request.project_id,
            "framework": request.framework or "all",
            "start_date": request.start_date,
            "end_date": request.end_date,
            "format": request.format,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "issue_count": len(issues)
        }
        
        return {
            "status": "success",
            "report_id": report_id,
            "format": "json",
            "data": report_data
        }
    
    elif request.format == "pdf":
        # Generate PDF using ReportGenerator
        try:
            pdf_bytes = generator.generate_pdf_report(request.project_id, issues)
            
            # Save to history
            report_id = str(uuid.uuid4())
            REPORT_HISTORY[report_id] = {
                "report_id": report_id,
                "project_id": request.project_id,
                "framework": request.framework or "all",
                "start_date": request.start_date,
                "end_date": request.end_date,
                "format": request.format,
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "issue_count": len(issues)
            }
            
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="compliance_report_{request.project_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
                }
            )
        except ImportError as e:
            # Fallback: return error message
            raise HTTPException(
                status_code=500,
                detail="PDF export requires 'weasyprint' library. Install with: pip install weasyprint. For now, please use HTML format."
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"PDF generation failed: {str(e)}"
            )
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {request.format}")

@router.get("/history")
async def get_report_history(
    project_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get report history for the authenticated user.
    """
    user_id = user_info.get("user_id")
    
    # Filter reports by user and optionally project
    user_reports = []
    for report_id, report in REPORT_HISTORY.items():
        if report.get("user_id") == user_id:
            if not project_id or report.get("project_id") == project_id:
                user_reports.append(report)
    
    # Sort by created_at descending
    user_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    # Apply limit
    user_reports = user_reports[:limit]
    
    return {
        "reports": user_reports,
        "total": len(user_reports)
    }

@router.get("/history/{report_id}")
async def get_report(
    report_id: str,
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get a specific report by ID.
    """
    user_id = user_info.get("user_id")
    
    if report_id not in REPORT_HISTORY:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report = REPORT_HISTORY[report_id]
    
    # Check if user owns this report
    if report.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Regenerate report content if needed
    issues = get_issues_for_date_range(
        report.get("project_id"),
        report.get("start_date"),
        report.get("end_date")
    )
    
    if report.get("framework") and report.get("framework") != "all":
        issues = filter_issues_by_framework(issues, report.get("framework"))
    
    generator = ReportGenerator()
    
    if report.get("format") == "html":
        content = generator.generate_html_report(report.get("project_id"), issues)
        return {
            "report": report,
            "content": content
        }
    else:
        return {
            "report": report,
            "message": "Report content not available for this format"
        }

@router.get("/frameworks")
async def get_frameworks(
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get available compliance frameworks.
    """
    return {
        "frameworks": [
            {"id": "all", "name": "All Frameworks", "description": "Include all compliance frameworks"},
            {"id": "soc2", "name": "SOC 2", "description": "Service Organization Control 2"},
            {"id": "gdpr", "name": "GDPR", "description": "General Data Protection Regulation"},
            {"id": "owasp", "name": "OWASP Top 10", "description": "OWASP Top 10 Security Risks"},
            {"id": "pci", "name": "PCI-DSS", "description": "Payment Card Industry Data Security Standard"}
        ]
    }

