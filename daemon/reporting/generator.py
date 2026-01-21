import json
from datetime import datetime
from typing import Optional
from .compliance_map import get_compliance_tags

class ReportGenerator:
    def __init__(self):
        pass

    def generate_html_report(self, project_id: str, issues: list) -> str:
        """
        Generates a standalone HTML compliance report.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. Process Stats
        total_issues = len(issues)
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        compliance_risks = {"soc2": 0, "owasp": 0, "gdpr": 0}
        
        processed_issues = []
        
        for issue in issues:
            # Map severity
            sev = issue.get("severity", "low").lower()
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            
            # Map compliance
            # Heuristic: use 'message' or 'type' to find mapping key
            issue_type = issue.get("type", "unknown").lower()
            # Try to find a partial match in map keys
            # e.g. "potential sql injection" -> match "sql_injection"
            
            compliance = get_compliance_tags(issue_type)
            # If default, try basic keyword matching in message
            if compliance["owasp"] == "Uncategorized":
                msg = issue.get("message", "").lower()
                if "sql" in msg: compliance = get_compliance_tags("sql_injection")
                elif "secret" in msg or "key" in msg: compliance = get_compliance_tags("hardcoded_secret")
                elif "password" in msg: compliance = get_compliance_tags("hardcoded_password")
            
            if compliance.get("soc2") and compliance["soc2"] != "General Logic": compliance_risks["soc2"] += 1
            if compliance.get("owasp") and compliance["owasp"] != "Uncategorized": compliance_risks["owasp"] += 1
            if compliance.get("gdpr") and compliance["gdpr"] != "N/A": compliance_risks["gdpr"] += 1
            
            processed_issues.append({
                "raw": issue,
                "compliance": compliance
            })

        # 2. Render HTML
        # Using f-string for simplicity/zero-dependency
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Compliance Audit - {project_id}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background: #f4f6f8; }}
        .header {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        .header h1 {{ margin: 0; color: #2c3e50; }}
        .meta {{ color: #7f8c8d; font-size: 0.9em; margin-top: 5px; }}
        
        .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 20px; }}
        .stat-card {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #34495e; }}
        .stat-label {{ color: #7f8c8d; font-size: 0.9em; }}
        
        .risk-high {{ color: #e74c3c; }}
        .risk-medium {{ color: #f39c12; }}
        
        .issue-table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .issue-table th, .issue-table td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
        .issue-table th {{ background: #f8f9fa; color: #2c3e50; font-weight: 600; }}
        
        .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-right: 5px; }}
        .tag-soc2 {{ background: #e8f6f3; color: #1abc9c; border: 1px solid #a3e4d7; }}
        .tag-owasp {{ background: #ebf5fb; color: #3498db; border: 1px solid #aed6f1; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Hybrid Local AI - Compliance Audit Report</h1>
        <div class="meta">Project: {project_id} | Generated: {timestamp}</div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{total_issues}</div>
            <div class="stat-label">Total Issues</div>
        </div>
        <div class="stat-card">
            <div class="stat-value risk-high">{severity_counts.get('high', 0)}</div>
            <div class="stat-label">Critical Risks</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{compliance_risks.get('soc2', 0)}</div>
            <div class="stat-label">SOC2 Violations</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{compliance_risks.get('owasp', 0)}</div>
            <div class="stat-label">OWASP Top 10</div>
        </div>
    </div>

    <div class="section">
        <h3>Detailed Findings</h3>
        <table class="issue-table">
            <thead>
                <tr>
                    <th>Severity</th>
                    <th>Issue</th>
                    <th>Location</th>
                    <th>Compliance Impact</th>
                </tr>
            </thead>
            <tbody>
"""
        
        for item in processed_issues:
            i = item["raw"]
            c = item["compliance"]
            
            sev_class = f"risk-{i.get('severity', 'low').lower()}"
            
            compliance_html = ""
            if c["soc2"] != "General Logic":
                compliance_html += f'<span class="tag tag-soc2">SOC2: {c["soc2"]}</span><br>'
            if c["owasp"] != "Uncategorized":
                compliance_html += f'<span class="tag tag-owasp">OWASP: {c["owasp"]}</span>'
                
            row = f"""
                <tr>
                    <td class="{sev_class}"><strong>{i.get('severity', 'LOW').upper()}</strong></td>
                    <td>
                        <div>{i.get('message')}</div>
                        <div style="font-size:0.8em; color:#999; margin-top:4px;">ID: {i.get('id')}</div>
                    </td>
                    <td>{i.get('file', 'N/A')}:{i.get('line', '?')}</td>
                    <td>{compliance_html or '-'}</td>
                </tr>
            """
            html += row
            
        html += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
        return html

    def generate_pdf_report(self, project_id: str, issues: list) -> bytes:
        """
        Generates a PDF compliance report from HTML.
        Uses weasyprint library to convert HTML to PDF.
        
        Returns:
            bytes: PDF file content as bytes
            
        Raises:
            ImportError: If weasyprint is not installed
            Exception: If PDF generation fails
        """
        # Generate HTML first
        html_content = self.generate_html_report(project_id, issues)
        
        # Try to import and use weasyprint
        try:
            import weasyprint
        except ImportError:
            raise ImportError(
                "PDF export requires 'weasyprint' library. "
                "Install with: pip install weasyprint"
            )
        
        try:
            # Convert HTML to PDF
            pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
            return pdf_bytes
        except Exception as e:
            raise Exception(f"PDF generation failed: {str(e)}")
