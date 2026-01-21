"""
Email Templates for Scheduled Reports
Provides professional HTML email templates for compliance reports
"""
from typing import Dict, Any, List
from datetime import datetime


def get_email_template(
    report_name: str,
    project_id: str,
    framework: str,
    issue_count: int,
    generated_at: str,
    report_format: str,
    has_attachment: bool = False
) -> str:
    """
    Generate a professional HTML email template for compliance reports.
    
    Args:
        report_name: Name of the scheduled report
        project_id: Project identifier
        framework: Compliance framework (e.g., "SOC2", "GDPR", "OWASP", "all")
        issue_count: Number of issues found
        generated_at: ISO timestamp of report generation
        report_format: Format of the report (html, pdf, json)
        has_attachment: Whether the report is attached as a file
    
    Returns:
        HTML email template
    """
    # Format the generation time
    try:
        gen_time = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
        formatted_time = gen_time.strftime("%B %d, %Y at %I:%M %p")
    except:
        formatted_time = generated_at
    
    # Framework display name
    framework_display = {
        "soc2": "SOC 2",
        "gdpr": "GDPR",
        "owasp": "OWASP Top 10",
        "pci": "PCI-DSS",
        "all": "All Frameworks"
    }.get(framework.lower(), framework.upper())
    
    # Severity color mapping
    severity_colors = {
        "critical": "#dc3545",
        "high": "#fd7e14",
        "medium": "#ffc107",
        "low": "#28a745"
    }
    
    # Determine issue status
    if issue_count == 0:
        status_text = "No Issues Found"
        status_color = "#28a745"
        status_icon = "✅"
    elif issue_count <= 5:
        status_text = "Low Risk"
        status_color = "#ffc107"
        status_icon = "⚠️"
    elif issue_count <= 15:
        status_text = "Medium Risk"
        status_color = "#fd7e14"
        status_icon = "🔶"
    else:
        status_text = "High Risk"
        status_color = "#dc3545"
        status_icon = "🔴"
    
    attachment_note = ""
    if has_attachment:
        if report_format == "pdf":
            attachment_note = '<p style="margin: 15px 0; padding: 12px; background: #e7f3ff; border-left: 4px solid #2196F3; border-radius: 4px;"><strong>📎 PDF Report Attached</strong><br>The detailed compliance report is attached as a PDF file.</p>'
        elif report_format == "json":
            attachment_note = '<p style="margin: 15px 0; padding: 12px; background: #e7f3ff; border-left: 4px solid #2196F3; border-radius: 4px;"><strong>📎 JSON Report Attached</strong><br>The compliance report data is attached as JSON.</p>'
    
    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Compliance Report: {report_name}</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f5f5f5;">
    <table role="presentation" style="width: 100%; border-collapse: collapse; background-color: #f5f5f5; padding: 20px 0;">
        <tr>
            <td align="center" style="padding: 20px 0;">
                <table role="presentation" style="width: 600px; max-width: 100%; border-collapse: collapse; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600;">
                                🛡️ Compliance Report
                            </h1>
                            <p style="margin: 10px 0 0 0; color: #ffffff; font-size: 16px; opacity: 0.9;">
                                {escape_html(report_name)}
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Report Summary -->
                    <tr>
                        <td style="padding: 30px;">
                            <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin-bottom: 25px;">
                                <h2 style="margin: 0 0 20px 0; color: #333; font-size: 20px; font-weight: 600;">
                                    Report Summary
                                </h2>
                                
                                <table role="presentation" style="width: 100%; border-collapse: collapse;">
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #e0e0e0;">
                                            <strong style="color: #666; font-size: 14px;">Project:</strong>
                                            <span style="color: #333; font-size: 14px; margin-left: 10px;">{escape_html(project_id)}</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #e0e0e0;">
                                            <strong style="color: #666; font-size: 14px;">Framework:</strong>
                                            <span style="color: #333; font-size: 14px; margin-left: 10px;">{escape_html(framework_display)}</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #e0e0e0;">
                                            <strong style="color: #666; font-size: 14px;">Generated:</strong>
                                            <span style="color: #333; font-size: 14px; margin-left: 10px;">{escape_html(formatted_time)}</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0;">
                                            <strong style="color: #666; font-size: 14px;">Status:</strong>
                                            <span style="color: {status_color}; font-size: 14px; margin-left: 10px; font-weight: 600;">
                                                {status_icon} {status_text} ({issue_count} issue{'s' if issue_count != 1 else ''})
                                            </span>
                                        </td>
                                    </tr>
                                </table>
                            </div>
                            
                            {attachment_note}
                            
                            <!-- Action Button -->
                            <div style="text-align: center; margin: 30px 0;">
                                <p style="margin: 0 0 15px 0; color: #666; font-size: 14px;">
                                    This report was automatically generated by your scheduled compliance monitoring.
                                </p>
                                <p style="margin: 0; color: #999; font-size: 12px;">
                                    For questions or to modify your scheduled reports, please visit the dashboard.
                                </p>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e0e0e0;">
                            <p style="margin: 0; color: #999; font-size: 12px; line-height: 1.6;">
                                This is an automated email from CodeSentinal Compliance Monitoring.<br>
                                Please do not reply to this email.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""
    return html_template


def get_plain_text_template(
    report_name: str,
    project_id: str,
    framework: str,
    issue_count: int,
    generated_at: str,
    report_format: str,
    has_attachment: bool = False
) -> str:
    """
    Generate a plain text email template for compliance reports.
    
    Args:
        report_name: Name of the scheduled report
        project_id: Project identifier
        framework: Compliance framework
        issue_count: Number of issues found
        generated_at: ISO timestamp of report generation
        report_format: Format of the report
        has_attachment: Whether the report is attached
    
    Returns:
        Plain text email template
    """
    try:
        gen_time = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
        formatted_time = gen_time.strftime("%B %d, %Y at %I:%M %p")
    except:
        formatted_time = generated_at
    
    framework_display = {
        "soc2": "SOC 2",
        "gdpr": "GDPR",
        "owasp": "OWASP Top 10",
        "pci": "PCI-DSS",
        "all": "All Frameworks"
    }.get(framework.lower(), framework.upper())
    
    if issue_count == 0:
        status_text = "No Issues Found"
    elif issue_count <= 5:
        status_text = "Low Risk"
    elif issue_count <= 15:
        status_text = "Medium Risk"
    else:
        status_text = "High Risk"
    
    attachment_note = ""
    if has_attachment:
        if report_format == "pdf":
            attachment_note = "\n[PDF Report Attached]"
        elif report_format == "json":
            attachment_note = "\n[JSON Report Attached]"
    
    text_template = f"""
COMPLIANCE REPORT: {report_name}
{'=' * 60}

Report Summary:
  Project: {project_id}
  Framework: {framework_display}
  Generated: {formatted_time}
  Status: {status_text} ({issue_count} issue{'s' if issue_count != 1 else ''})
{attachment_note}

This report was automatically generated by your scheduled compliance monitoring.

For questions or to modify your scheduled reports, please visit the dashboard.

---
This is an automated email from CodeSentinal Compliance Monitoring.
Please do not reply to this email.
"""
    return text_template


def escape_html(text: str) -> str:
    """
    Escape HTML special characters to prevent XSS.
    """
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;"))


def get_issue_summary_html(issues: List[Dict[str, Any]], max_issues: int = 10) -> str:
    """
    Generate HTML summary of top issues for email preview.
    
    Args:
        issues: List of issue dictionaries
        max_issues: Maximum number of issues to display
    
    Returns:
        HTML string with issue summary
    """
    if not issues:
        return '<p style="color: #28a745; font-weight: 600;">✅ No security issues found!</p>'
    
    # Group by severity
    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    issues_sorted = sorted(
        issues,
        key=lambda x: severity_order.get(x.get("severity", "low").lower(), 0),
        reverse=True
    )
    
    top_issues = issues_sorted[:max_issues]
    
    severity_colors = {
        "critical": "#dc3545",
        "high": "#fd7e14",
        "medium": "#ffc107",
        "low": "#28a745"
    }
    
    severity_icons = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢"
    }
    
    html = '<div style="margin-top: 20px;"><h3 style="color: #333; font-size: 16px; margin-bottom: 15px;">Top Issues:</h3>'
    
    for issue in top_issues:
        severity = issue.get("severity", "low").lower()
        color = severity_colors.get(severity, "#666")
        icon = severity_icons.get(severity, "⚪")
        
        html += f'''
        <div style="padding: 12px; margin-bottom: 10px; background: #f8f9fa; border-left: 4px solid {color}; border-radius: 4px;">
            <div style="display: flex; align-items: start; gap: 10px;">
                <span style="font-size: 18px;">{icon}</span>
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: #333; margin-bottom: 4px;">
                        {escape_html(issue.get("message", "Unknown issue"))}
                    </div>
                    <div style="font-size: 12px; color: #666;">
                        <strong>File:</strong> {escape_html(issue.get("file", "Unknown"))} 
                        <span style="margin-left: 10px;"><strong>Line:</strong> {issue.get("line", "N/A")}</span>
                    </div>
                </div>
            </div>
        </div>
        '''
    
    if len(issues) > max_issues:
        html += f'<p style="color: #666; font-size: 12px; margin-top: 10px;">... and {len(issues) - max_issues} more issue(s). See attached report for full details.</p>'
    
    html += '</div>'
    
    return html

