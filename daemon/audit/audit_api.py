"""
Audit Logs API
Provides endpoints for viewing, filtering, searching, and exporting audit logs
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
import csv
import io
from starlette.responses import Response

router = APIRouter(prefix="/api/audit", tags=["Audit Logs"])

# Import authentication (if available)
try:
    from daemon.auth.api_key_auth import verify_api_key
except ImportError:
    async def verify_api_key(request: Request, credentials=None):
        return {"user_id": "default"}

@router.get("/logs")
async def get_audit_logs(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search in action, target, or details"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get audit logs with filtering, search, and pagination.
    """
    from daemon.db.db import get_db_connection
    import sqlite3
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Build query with filters
        query = "SELECT * FROM AuditLog WHERE 1=1"
        params = []
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if action:
            query += " AND action = ?"
            params.append(action)
        
        if start_date:
            query += " AND DATE(timestamp) >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND DATE(timestamp) <= ?"
            params.append(end_date)
        
        if search:
            query += " AND (action LIKE ? OR target LIKE ? OR details LIKE ?)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        # Get total count
        count_query = query.replace("SELECT *", "SELECT COUNT(*)")
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]
        
        # Add ordering and pagination
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Convert to list of dicts
        logs = []
        for row in rows:
            logs.append({
                "audit_id": row["audit_id"],
                "project_id": row["project_id"],
                "user_id": row["user_id"],
                "action": row["action"],
                "target": row["target"],
                "timestamp": row["timestamp"],
                "details": json.loads(row["details"]) if row["details"] else None
            })
        
        return {
            "logs": logs,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(logs)) < total_count
        }
    finally:
        conn.close()

@router.get("/logs/actions")
async def get_action_types(
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get list of unique action types for filtering.
    """
    from daemon.db.db import get_db_connection
    import sqlite3
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT DISTINCT action FROM AuditLog ORDER BY action")
        actions = [row[0] for row in cursor.fetchall() if row[0]]
        
        return {
            "actions": actions
        }
    finally:
        conn.close()

@router.get("/logs/export")
async def export_audit_logs(
    format: str = Query("json", regex="^(json|csv)$", description="Export format"),
    project_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user_info: dict = Depends(verify_api_key)
) -> Response:
    """
    Export audit logs to CSV or JSON.
    """
    from daemon.db.db import get_db_connection
    import sqlite3
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Build query (same as get_audit_logs but without limit)
        query = "SELECT * FROM AuditLog WHERE 1=1"
        params = []
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if action:
            query += " AND action = ?"
            params.append(action)
        
        if start_date:
            query += " AND DATE(timestamp) >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND DATE(timestamp) <= ?"
            params.append(end_date)
        
        if search:
            query += " AND (action LIKE ? OR target LIKE ? OR details LIKE ?)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        query += " ORDER BY timestamp DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if format == "json":
            logs = []
            for row in rows:
                logs.append({
                    "audit_id": row["audit_id"],
                    "project_id": row["project_id"],
                    "user_id": row["user_id"],
                    "action": row["action"],
                    "target": row["target"],
                    "timestamp": row["timestamp"],
                    "details": json.loads(row["details"]) if row["details"] else None
                })
            
            return Response(
                content=json.dumps(logs, indent=2, default=str),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
                }
            )
        
        else:  # CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(["audit_id", "project_id", "user_id", "action", "target", "timestamp", "details"])
            
            # Write data
            for row in rows:
                details_str = row["details"] if row["details"] else ""
                writer.writerow([
                    row["audit_id"],
                    row["project_id"],
                    row["user_id"],
                    row["action"],
                    row["target"],
                    row["timestamp"],
                    details_str
                ])
            
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
                }
            )
    finally:
        conn.close()

@router.get("/logs/stats")
async def get_audit_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    user_info: dict = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get audit log statistics.
    """
    from daemon.db.db import get_db_connection
    import sqlite3
    from datetime import datetime, timedelta
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Total logs
        cursor.execute("SELECT COUNT(*) FROM AuditLog WHERE DATE(timestamp) >= ?", (cutoff_date,))
        total_logs = cursor.fetchone()[0]
        
        # Logs by action
        cursor.execute("""
            SELECT action, COUNT(*) as count 
            FROM AuditLog 
            WHERE DATE(timestamp) >= ?
            GROUP BY action 
            ORDER BY count DESC
            LIMIT 10
        """, (cutoff_date,))
        actions = [{"action": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Logs by user
        cursor.execute("""
            SELECT user_id, COUNT(*) as count 
            FROM AuditLog 
            WHERE DATE(timestamp) >= ?
            GROUP BY user_id 
            ORDER BY count DESC
            LIMIT 10
        """, (cutoff_date,))
        users = [{"user_id": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Daily activity
        cursor.execute("""
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM AuditLog
            WHERE DATE(timestamp) >= ?
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """, (cutoff_date,))
        daily = [{"date": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        return {
            "total_logs": total_logs,
            "period_days": days,
            "top_actions": actions,
            "top_users": users,
            "daily_activity": daily
        }
    finally:
        conn.close()

