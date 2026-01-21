"""
FastAPI HTTP Server for Hybrid Local AI Code Reviewer
Supports both traditional and streaming analysis endpoints
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
import json
import asyncio
import sys
from pathlib import Path
import os
import logging
from logging.handlers import RotatingFileHandler
from fastapi import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from daemon.queues.analysis_queue import AnalysisQueue
    from daemon.db.db import init_db
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.queues.analysis_queue import AnalysisQueue
    from daemon.db.db import init_db

# Setup Logging
logger = logging.getLogger("hybrid-reviewer")
logger.setLevel(logging.INFO)

# Try to set up file logging, but fall back to console if it fails (e.g., in Cloud Run)
try:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "daemon.log"
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
except Exception as e:
    # Fallback to console logging if file logging fails (e.g., in Cloud Run)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(console_handler)
    logger.warning(f"File logging failed, using console logging: {e}")

# Setup Rate Limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize components (needed for lifespan)
queue = AnalysisQueue()

# Track active autonomous sessions
active_autonomy_sessions = {}  # session_id -> {status, start_time, project_id, target, fixes_applied, errors}

# Link session tracker to queue
queue.session_tracker = active_autonomy_sessions

# Lifespan event handler for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        # Continue anyway - database might be initialized later
    
    # Start queue processor in background
    asyncio.create_task(queue.process_queue())
    
    # Start scheduled reports scheduler
    scheduler_task = None
    try:
        from daemon.reporting.scheduler import start_scheduler
        scheduler_task = asyncio.create_task(start_scheduler())
        logger.info("Scheduled reports scheduler started")
    except Exception as e:
        logger.warning(f"Failed to start scheduler: {e}")
    
    yield
    
    # Shutdown
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="Hybrid Local AI Code Reviewer Daemon", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for better error messages"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    # Don't expose internal errors in production unless debug
    is_debug = logger.level == logging.DEBUG
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if is_debug else "An error occurred during analysis",
            "type": type(exc).__name__ if is_debug else "ServerError"
        }
    )

def sanitize_path(file_path: str) -> str:
    """Sanitize file path to prevent directory traversal"""
    # Remove any path traversal attempts
    path = Path(file_path)
    # Get only the filename, prevent directory traversal
    safe_path = path.name
    # Additional validation: ensure no parent directory references
    if '..' in file_path or file_path.startswith('/'):
        # For security, only use filename
        safe_path = os.path.basename(file_path)
    return safe_path

# CORS middleware for VS Code extension
from starlette.middleware.sessions import SessionMiddleware

# Add session middleware for OAuth
# In production, use a secure random secret key from environment variable
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "super-secret-key-for-dev-change-in-production")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

# CORS configuration - allow all origins in production, restricted in development
# Set ALLOW_ALL_ORIGINS=true in production (e.g., Render, Railway, Fly.io)
ALLOW_ALL_ORIGINS = os.environ.get("ALLOW_ALL_ORIGINS", "false").lower() == "true"

if ALLOW_ALL_ORIGINS:
    # Production: Allow all origins for public API (GitHub Actions, etc.)
    cors_origins = ["*"]
else:
    # Development: Restrict to localhost and VS Code
    cors_origins = [
        "vscode-webview://*", 
        "http://localhost:*", 
        "http://127.0.0.1:*"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Request models
class AnalyzeRequest(BaseModel):
    file_path: str
    content: str
    project_id: str
    user_config: Dict[str, Any] = {}

    @field_validator('content')
    @classmethod
    def validate_content_size(cls, v: str) -> str:
        MAX_SIZE = 10 * 1024 * 1024  # 10MB
        content_bytes = len(v.encode('utf-8'))
        if content_bytes > MAX_SIZE:
            raise ValueError(
                f"File content exceeds maximum size of {MAX_SIZE / 1024 / 1024}MB "
                f"(got {content_bytes / 1024 / 1024:.2f}MB)"
            )
        return v

class AnalyzeResponse(BaseModel):
    issues: List[Dict[str, Any]]

# Import API key authentication
try:
    from daemon.auth.api_key_auth import verify_api_key
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.auth.api_key_auth import verify_api_key

# Traditional endpoint (non-streaming, for backward compatibility)
@app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("20/minute")
async def analyze(
    request: Request, 
    body: AnalyzeRequest,
    user_info: dict = Depends(verify_api_key)
):
    """Traditional analysis endpoint - returns all issues at once"""
    try:
        # Get user_id and tier from API key
        user_id = user_info.get("user_id")
        tier = user_info.get("tier", "free")
        
        # Free plan limit enforcement
        from daemon.pricing.pricing_manager import PricingManager
        pricing = PricingManager()
        
        if pricing.is_free_tier(user_id):
            # Check CI/CD restriction (GitHub Actions)
            if body.project_id.startswith("github-") or body.user_config.get("source") == "github-action":
                raise HTTPException(
                    status_code=403,
                    detail="CI/CD integration requires Pro or Team plan. Please upgrade."
                )
            
            # Check repository limit (max 1 repo)
            if user_id:
                from daemon.db.db import count_user_repositories, get_db_connection
                
                # Extract repo identifier from current project_id
                if body.project_id.startswith("github-"):
                    # Format: github-owner-repo-runId
                    parts = body.project_id.split("-", 3)
                    current_repo = f"{parts[1]}-{parts[2]}" if len(parts) >= 3 else body.project_id
                else:
                    current_repo = body.project_id
                
                # Get existing repositories for this user
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT project_id FROM Project WHERE user_id = ?", (user_id,))
                existing_projects = cursor.fetchall()
                conn.close()
                
                # Extract unique repository identifiers
                existing_repos = set()
                for proj in existing_projects:
                    proj_id = proj['project_id']
                    if proj_id.startswith("github-"):
                        parts = proj_id.split("-", 3)
                        existing_repos.add(f"{parts[1]}-{parts[2]}" if len(parts) >= 3 else proj_id)
                    else:
                        existing_repos.add(proj_id)
                
                # If current repo is new and we're at limit
                if current_repo not in existing_repos and len(existing_repos) >= pricing.get_free_limit("max_repositories"):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Free plan limited to {pricing.get_free_limit('max_repositories')} repository. Please upgrade for unlimited repositories."
                    )
            
            # Check file limit per scan (max 200 files)
            # Count distinct files analyzed in this project_id (including current file)
            from daemon.db.db import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT file_path) FROM file_analysis WHERE project_id = ?", (body.project_id,))
            result = cursor.fetchone()
            files_in_project = result[0] if result else 0
            conn.close()
            
            # Check if adding this file would exceed the limit
            # We check >= because the current file hasn't been saved yet, so we're checking existing files
            if files_in_project >= pricing.get_free_limit("max_files_per_scan"):
                raise HTTPException(
                    status_code=403,
                    detail=f"Free plan limited to {pricing.get_free_limit('max_files_per_scan')} files per scan. Please upgrade for unlimited files."
                )
        
        logger.info(f"Received analysis request for {body.file_path} from user {user_id} (tier: {tier})")
        safe_path = sanitize_path(body.file_path)
        task = {
            "file_path": safe_path, # Use sanitized path
            "original_path": body.file_path, # Keep original for reference
            "content": body.content,
            "project_id": body.project_id,
            "user_config": body.user_config,
            "user_id": user_id,  # Pass user_id from API key
            "tier": tier          # Pass tier for feature gating
        }
        issues = await queue.run_analysis(task)
        return AnalyzeResponse(issues=issues)
    except HTTPException:
        raise  # Re-raise HTTPExceptions (403, etc.) without modification
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Streaming endpoint (Server-Sent Events)
@app.post("/analyze/stream")
@limiter.limit("20/minute")
async def analyze_stream(
    request: Request, 
    body: AnalyzeRequest,
    user_info: dict = Depends(verify_api_key)
):
    """Streaming analysis endpoint - sends issues as they're discovered"""
    
    # Free plan limit enforcement (same as /analyze)
    from daemon.pricing.pricing_manager import PricingManager
    pricing = PricingManager()
    
    user_id = user_info.get("user_id")
    tier = user_info.get("tier", "free")
    
    if pricing.is_free_tier(user_id):
        # Check CI/CD restriction
        if body.project_id.startswith("github-") or body.user_config.get("source") == "github-action":
            raise HTTPException(
                status_code=403,
                detail="CI/CD integration requires Pro or Team plan. Please upgrade."
            )
        
        # Check repository limit
        if user_id:
            from daemon.db.db import get_db_connection
            if body.project_id.startswith("github-"):
                parts = body.project_id.split("-", 3)
                current_repo = f"{parts[1]}-{parts[2]}" if len(parts) >= 3 else body.project_id
            else:
                current_repo = body.project_id
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT project_id FROM Project WHERE user_id = ?", (user_id,))
            existing_projects = cursor.fetchall()
            conn.close()
            
            existing_repos = set()
            for proj in existing_projects:
                proj_id = proj['project_id']
                if proj_id.startswith("github-"):
                    parts = proj_id.split("-", 3)
                    existing_repos.add(f"{parts[1]}-{parts[2]}" if len(parts) >= 3 else proj_id)
                else:
                    existing_repos.add(proj_id)
            
            if current_repo not in existing_repos and len(existing_repos) >= pricing.get_free_limit("max_repositories"):
                raise HTTPException(
                    status_code=403,
                    detail=f"Free plan limited to {pricing.get_free_limit('max_repositories')} repository. Please upgrade."
                )
        
        # Check file limit per scan
        from daemon.db.db import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT file_path) FROM file_analysis WHERE project_id = ?", (body.project_id,))
        result = cursor.fetchone()
        files_in_project = result[0] if result else 0
        conn.close()
        
        if files_in_project >= pricing.get_free_limit("max_files_per_scan"):
            raise HTTPException(
                status_code=403,
                detail=f"Free plan limited to {pricing.get_free_limit('max_files_per_scan')} files per scan. Please upgrade."
            )
    
    async def generate_stream():
        """Generator function for SSE streaming"""
        try:
            # Get user_id and tier from API key (already set above)
            
            safe_path = sanitize_path(body.file_path)
            task = {
                "file_path": safe_path, # Use sanitized path
                "original_path": body.file_path, # Keep original for reference
                "content": body.content,
                "project_id": body.project_id,
                "user_config": body.user_config,
                "user_id": user_id,  # Pass user_id from API key
                "tier": tier          # Pass tier for feature gating
            }
            
            # Create an async generator that yields issues as they're found
            async for event in queue.run_analysis_stream(task):
                # Format as SSE: "data: {json}\n\n"
                data = json.dumps(event)
                yield f"data: {data}\n\n"
            
            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
        except Exception as e:
            # Send error event
            error_event = {
                "type": "error",
                "message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


# Root endpoint
@app.get("/")
def home():
    return {
        "service": "Autonoma L5 Engine",
        "status": "online", 
        "version": "1.0.0",
        "autonomy_level": "L5"
    }


# Health Check & Management
try:
    from daemon.health import router as health_router
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.health import router as health_router

app.include_router(health_router)

# Team API
try:
    from daemon.team.team_api import router as team_router
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.team.team_api import router as team_router

app.include_router(team_router)

# Auth API (SSO)
try:
    from daemon.auth.oauth import router as auth_router
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.auth.oauth import router as auth_router

app.include_router(auth_router)

# SAML SSO Handler
try:
    from daemon.auth.saml_handler import router as saml_router
except ImportError:
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.auth.saml_handler import router as saml_router

app.include_router(saml_router)

# L5 Autonomy Dashboard API
try:
    from daemon.autonomy.dashboard_api import router as autonomy_dashboard_router
except ImportError:
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.autonomy.dashboard_api import router as autonomy_dashboard_router

app.include_router(autonomy_dashboard_router)

# Audit Logs API
try:
    from daemon.audit.audit_api import router as audit_router
except ImportError:
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.audit.audit_api import router as audit_router

app.include_router(audit_router)

# Compliance Reports API
try:
    from daemon.reporting.reports_api import router as reports_router
except ImportError:
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.reporting.reports_api import router as reports_router

app.include_router(reports_router)

# Governance Firewall API
try:
    from daemon.governance.firewall_api import router as firewall_router
except ImportError:
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.governance.firewall_api import router as firewall_router

app.include_router(firewall_router)

# Scheduled Reports API
try:
    from daemon.reporting.scheduled_reports_api import router as scheduled_reports_router
except ImportError:
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.reporting.scheduled_reports_api import router as scheduled_reports_router

app.include_router(scheduled_reports_router)

# Fix API
from daemon.analysis.fix_engine import FixEngine

@app.post("/analyze/fix")
async def analyze_fix(request: Request):
    """
    Generates a fix for a specific code snippet.
    Body: { "code": "...", "issue": "...", "model": "..." }
    """
    data = await request.json()
    code = data.get("code")
    issue = data.get("issue")
    model = data.get("model") # Optional override
    
    if not code or not issue:
        return {"error": "Missing code or issue description"}
        
    engine = FixEngine()
    fixed_code = await engine.generate_fix(code, issue, model)
    
    return {"fixed_code": fixed_code}

# Autonomy Activation (Hotwire)
from fastapi import BackgroundTasks

class AutonomyRequest(BaseModel):
    project_id: str
    target_path: Optional[str] = None # Defaults to project root or current dir

@app.post("/autonomy/activate")
async def activate_autonomy(
    request: Request,
    body: AutonomyRequest,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_api_key)
):
    """
    HOTWIRE: Activates L5 Autonomous Loop for the project.
    Scans and fixes HIGH severity bugs automatically.
    """
    user_id = user_info.get("user_id")
    tier = user_info.get("tier", "free")
    
    # 🔒 ENTERPRISE GATING
    if tier != "enterprise":
        raise HTTPException(
            status_code=403, 
            detail="L5 Autonomy requires an Enterprise license. Please upgrade."
        )
    
    # Resolve path
    target = body.target_path
    if not target:
        return {"error": "target_path is required for Hotwire mode"}
        
    logger.info(f"Activation L5 Autonomy for {target} (User: {user_id}, Tier: {tier})")
    
    # Run in background to avoid timeout
    # Note: session_id will be generated inside run_autonomous_loop
    background_tasks.add_task(
        queue.run_autonomous_loop, 
        directory_path=target, 
        project_id=body.project_id, 
        user_id=user_id
    )
    
    # Find the most recent session for this target (will be created when loop starts)
    # For now, return activation status
    return {
        "status": "activated",
        "message": "L5 Autonomous Engineer has been deployed. Watch your files change.",
        "target": target,
        "note": "Use /autonomy/status endpoint to check progress"
    }

# L5 Autonomy Live Events (SSE)
@app.get("/autonomy/events")
async def stream_autonomy_events(request: Request, user_info: dict = Depends(verify_api_key)):
    """
    Stream live autonomy events (Fixes, Reverts, Errors) to the dashboard.
    """
    from daemon.events.event_bus import get_event_bus
    
    # Enterprise Check
    # if user_info.get("tier") != "enterprise": ... (Skipping for demo simplicity)

    async def event_generator():
        bus = get_event_bus()
        q = bus.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                # Wait for next event
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# L5 Autonomy Status Endpoint
@app.get("/autonomy/status")
async def get_autonomy_status(
    project_id: str = None,
    session_id: str = None,
    user_info: dict = Depends(verify_api_key)
):
    """
    Get status of L5 Autonomous sessions.
    Returns all active sessions or a specific session if session_id provided.
    """
    user_id = user_info.get("user_id")
    tier = user_info.get("tier", "free")
    
    # Enterprise only
    if tier != "enterprise":
        raise HTTPException(
            status_code=403,
            detail="L5 Autonomy status requires Enterprise license."
        )
    
    if session_id:
        # Return specific session
        if session_id in active_autonomy_sessions:
            session = active_autonomy_sessions[session_id].copy()
            import time
            if session["status"] == "running":
                session["elapsed_time"] = time.time() - session["start_time"]
            return session
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        # Return all sessions (filter by project_id if provided)
        sessions = {}
        for sid, session in active_autonomy_sessions.items():
            if project_id is None or session.get("project_id") == project_id:
                session_copy = session.copy()
                import time
                if session_copy["status"] == "running":
                    session_copy["elapsed_time"] = time.time() - session_copy["start_time"]
                sessions[sid] = session_copy
        
        return {
            "total_sessions": len(sessions),
            "sessions": sessions
        }

# Reporting API
from daemon.reporting.generator import ReportGenerator
# Note: get_analysis_results is not yet implemented - using mock data for MVP

@app.get("/manage/report")
async def generate_report(
    project_id: str = "default", 
    format: str = "html",
    request: Request = None,
    user_info: dict = Depends(verify_api_key)
):
    """
    Generates a compliance report.
    Free plan: No historical reports or export.
    """
    # Free plan limit enforcement
    from daemon.pricing.pricing_manager import PricingManager
    pricing = PricingManager()
    
    user_id = user_info.get("user_id")
    
    # Check export restriction first (PDF/JSON export requires paid plan)
    if format in ["pdf", "json"]:
        if not pricing.check_access(user_id, "export"):
            raise HTTPException(
                status_code=403,
                detail="Export (PDF/JSON) requires Pro or Team plan. Please upgrade."
            )
    
    # Free plan: No historical reports at all
    if pricing.is_free_tier(user_id):
        raise HTTPException(
            status_code=403,
            detail="Historical reports require Pro or Team plan. Please upgrade."
        )
    # For MVP, we might simple query the DB or use a mock list if DB is empty for demo
    # Let's try to get real issues from DB
    
    issues = []
    # Mocking real DB fetch for robustness in this demo step
    # issues = get_all_issues(project_id) 
    
    # Check if we have issues in memory or DB?
    # Let's include some dummy issues to show the features if empty
    issues = [
        {"id": "SEC001", "severity": "high", "message": "Hardcoded AWS Secret Key found", "file": "backend/auth.py", "line": 42, "type": "hardcoded_secret"},
        {"id": "SEC002", "severity": "medium", "message": "Potential SQL Injection in query construction", "file": "backend/db.py", "line": 105, "type": "sql_injection"},
        {"id": "QA001", "severity": "low", "message": "Function 'process_data' has high cyclomatic complexity", "file": "backend/utils.py", "line": 12, "type": "high_complexity"}
    ]
    
    try:
        generator = ReportGenerator()
        if format == "html":
            report_content = generator.generate_html_report(project_id, issues)
            return Response(content=report_content, media_type="text/html")
        
        return {"error": "Unsupported format"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed: {str(e)}"
        )

# Tier Management
from daemon.db.db import set_user_tier
try:
    from daemon.audit_logger import AuditLogger
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.audit_logger import AuditLogger

class TierUpdateRequest(BaseModel):
    user_id: str
    tier: str

@app.post("/api/tier")
@limiter.limit("10/minute")
async def update_user_tier(request: Request, body: TierUpdateRequest):
    """Update user tier (free, pro, enterprise)"""
    valid_tiers = ["free", "pro", "enterprise"]
    if body.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of {valid_tiers}")

    try:
        logger.info(f"Updating tier for user {body.user_id} to {body.tier}")
        set_user_tier(body.user_id, body.tier)
        
        # Log Audit Event
        # For API requests, project_id is context dependent. We can use "system" or empty.
        audit = AuditLogger("system_api", body.user_id)
        audit.log("TIER_UPDATE", "User", {"new_tier": body.tier})
        
        return {"status": "success", "user_id": body.user_id, "tier": body.tier}
    except Exception as e:
        logger.error(f"Failed to update tier: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# API Key Management
import secrets
import hashlib
from datetime import datetime, timedelta

class GenerateAPIKeyRequest(BaseModel):
    user_id: str
    expires_days: int = 365
    rate_limit_per_minute: Optional[int] = None  # Default based on tier
    allowed_ips: Optional[List[str]] = None  # JSON array of IPs, None = all IPs

@app.post("/api/keys/generate")
async def generate_api_key(request: Request, body: GenerateAPIKeyRequest):
    """
    Generate new API key for a user.
    TODO: Add authentication check here (require user to be logged in)
    For now, allow any user_id (add proper auth later)
    """
    # Generate secure API key
    api_key = f"cs_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Get user tier from database
    from daemon.db.db import get_user_tier, get_db_connection
    import sqlite3
    
    # Check if user exists and get tier
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tier FROM User WHERE user_id = ?", (body.user_id,))
    user_row = cursor.fetchone()
    
    if user_row:
        tier = user_row["tier"] or "free"
    else:
        # User doesn't exist, create it with free tier
        tier = "free"
        cursor.execute(
            "INSERT INTO User (user_id, email, tier) VALUES (?, ?, ?)",
            (body.user_id, f"{body.user_id}@example.com", tier)
        )
        conn.commit()
    
    # Set default rate limits based on tier
    if body.rate_limit_per_minute is None:
        # Default rate limits by tier
        rate_limits = {
            "free": 20,
            "pro": 100,
            "enterprise": 1000
        }
        rate_limit = rate_limits.get(tier, 20)
    else:
        rate_limit = body.rate_limit_per_minute
    
    # Process allowed IPs
    allowed_ips_json = None
    if body.allowed_ips:
        import json
        allowed_ips_json = json.dumps(body.allowed_ips)
    
    # Calculate expiration
    expires_at = (datetime.now() + timedelta(days=body.expires_days)).isoformat()
    
    # Store in database
    from daemon.db.db import get_db_connection
    import sqlite3
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO api_keys (key_hash, user_id, expires_at, is_active, rate_limit_per_minute, allowed_ips)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (key_hash, body.user_id, expires_at, rate_limit, allowed_ips_json)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="User already has an active API key")
    finally:
        conn.close()
    
    logger.info(f"Generated API key for user {body.user_id} (tier: {tier}, rate_limit: {rate_limit})")
    
    return {
        "api_key": api_key,  # Return plaintext key (only shown once!)
        "user_id": body.user_id,
        "tier": tier,
        "expires_at": expires_at,
        "rate_limit_per_minute": rate_limit,
        "allowed_ips": body.allowed_ips,
        "warning": "Save this API key now - it will not be shown again!"
    }

@app.get("/api/keys")
async def list_api_keys(
    request: Request,
    user_info: dict = Depends(verify_api_key)
):
    """List API keys for authenticated user"""
    user_id = user_info.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from daemon.db.db import get_db_connection
    import sqlite3
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 
            id,
            created_at,
            expires_at,
            is_active,
            last_used
        FROM api_keys
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    keys = cursor.fetchall()
    conn.close()
    
    return {
        "keys": [
            {
                "id": k["id"],
                "created_at": k["created_at"],
                "expires_at": k["expires_at"],
                "is_active": bool(k["is_active"]),
                "last_used": k["last_used"]
            }
            for k in keys
        ]
    }

class RotateAPIKeyRequest(BaseModel):
    old_key_hash: Optional[str] = None  # Optional: if provided, deactivate old key
    expires_days: int = 365
    rate_limit_per_minute: Optional[int] = None
    allowed_ips: Optional[List[str]] = None

@app.post("/api/keys/rotate")
async def rotate_api_key(
    request: Request,
    body: RotateAPIKeyRequest,
    user_info: dict = Depends(verify_api_key)
):
    """
    Rotate API key: Deactivate old key and generate new one.
    Requires authentication with existing API key.
    """
    user_id = user_info.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Get user tier
    from daemon.db.db import get_user_tier
    tier = get_user_tier(user_id) or "free"
    
    # Generate new API key
    new_api_key = f"cs_{secrets.token_urlsafe(32)}"
    new_key_hash = hashlib.sha256(new_api_key.encode()).hexdigest()
    
    # Set default rate limits based on tier
    if body.rate_limit_per_minute is None:
        rate_limits = {"free": 20, "pro": 100, "enterprise": 1000}
        rate_limit = rate_limits.get(tier, 20)
    else:
        rate_limit = body.rate_limit_per_minute
    
    # Process allowed IPs
    allowed_ips_json = None
    if body.allowed_ips:
        allowed_ips_json = json.dumps(body.allowed_ips)
    
    expires_at = (datetime.now() + timedelta(days=body.expires_days)).isoformat()
    
    from daemon.db.db import get_db_connection
    import sqlite3
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Deactivate old key if provided
        if body.old_key_hash:
            cursor.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key_hash = ? AND user_id = ?",
                (body.old_key_hash, user_id)
            )
        
        # Create new key
        cursor.execute(
            """
            INSERT INTO api_keys (key_hash, user_id, expires_at, is_active, rate_limit_per_minute, allowed_ips)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (new_key_hash, user_id, expires_at, rate_limit, allowed_ips_json)
        )
        conn.commit()
        
        logger.info(f"Rotated API key for user {user_id}")
        
        return {
            "api_key": new_api_key,
            "user_id": user_id,
            "tier": tier,
            "expires_at": expires_at,
            "rate_limit_per_minute": rate_limit,
            "allowed_ips": body.allowed_ips,
            "warning": "Save this API key now - it will not be shown again!"
        }
    finally:
        conn.close()

class UpdateAPIKeyRequest(BaseModel):
    key_id: int
    rate_limit_per_minute: Optional[int] = None
    allowed_ips: Optional[List[str]] = None
    is_active: Optional[bool] = None

@app.put("/api/keys/update")
async def update_api_key(
    request: Request,
    body: UpdateAPIKeyRequest,
    user_info: dict = Depends(verify_api_key)
):
    """Update API key settings (rate limit, IP whitelist, active status)"""
    user_id = user_info.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from daemon.db.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify key belongs to user
    cursor.execute(
        "SELECT user_id FROM api_keys WHERE id = ?",
        (body.key_id,)
    )
    result = cursor.fetchone()
    if not result or result["user_id"] != user_id:
        conn.close()
        raise HTTPException(status_code=404, detail="API key not found")
    
    # Build update query
    updates = []
    params = []
    
    if body.rate_limit_per_minute is not None:
        updates.append("rate_limit_per_minute = ?")
        params.append(body.rate_limit_per_minute)
    
    if body.allowed_ips is not None:
        updates.append("allowed_ips = ?")
        params.append(json.dumps(body.allowed_ips) if body.allowed_ips else None)
    
    if body.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if body.is_active else 0)
    
    if not updates:
        conn.close()
        raise HTTPException(status_code=400, detail="No fields to update")
    
    params.append(body.key_id)
    params.append(user_id)
    
    cursor.execute(
        f"UPDATE api_keys SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
        params
    )
    conn.commit()
    conn.close()
    
    logger.info(f"Updated API key {body.key_id} for user {user_id}")
    
    return {"status": "success", "key_id": body.key_id}

@app.delete("/api/keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    request: Request,
    user_info: dict = Depends(verify_api_key)
):
    """Revoke (deactivate) an API key"""
    user_id = user_info.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from daemon.db.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify key belongs to user and deactivate
    cursor.execute(
        "UPDATE api_keys SET is_active = 0 WHERE id = ? AND user_id = ?",
        (key_id, user_id)
    )
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="API key not found")
    
    conn.commit()
    conn.close()
    
    logger.info(f"Revoked API key {key_id} for user {user_id}")
    
    return {"status": "success", "key_id": key_id, "message": "API key revoked"}

@app.get("/api/keys/{key_id}/rate-limit")
async def get_rate_limit_info(
    key_id: int,
    request: Request,
    user_info: dict = Depends(verify_api_key)
):
    """Get rate limit status for an API key"""
    user_id = user_info.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from daemon.db.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get key hash
    cursor.execute(
        "SELECT key_hash FROM api_keys WHERE id = ? AND user_id = ?",
        (key_id, user_id)
    )
    result = cursor.fetchone()
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="API key not found")
    
    key_hash = result["key_hash"]
    conn.close()
    
    # Get rate limit info
    from daemon.auth.rate_limiter import get_rate_limit_info
    return get_rate_limit_info(key_hash)

# CSRF Protection
import secrets

@app.get("/api/csrf-token")
async def get_csrf_token(request: Request):
    """Generate and return CSRF token for state-changing operations"""
    if 'csrf_token' not in request.session:
        request.session['csrf_token'] = secrets.token_urlsafe(32)
    return {"csrf_token": request.session['csrf_token']}

async def verify_csrf_token_optional(request: Request):
    """Verify CSRF token if provided (optional for backward compatibility)"""
    csrf_token = request.headers.get("X-CSRF-Token")
    if csrf_token:
        # If CSRF token is provided, validate it
        session_token = request.session.get('csrf_token')
        if not session_token:
            raise HTTPException(status_code=403, detail="CSRF token not found in session")
        if csrf_token != session_token:
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    # If no CSRF token provided, allow (for backward compatibility with API key auth)
    return True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

