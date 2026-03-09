"""
Autonoma Community Edition - HTTP Server
Supports code analysis endpoints only.
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Dict, Any, List
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
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.queues.analysis_queue import AnalysisQueue
    from daemon.db.db import init_db

# Setup Logging
logger = logging.getLogger("autonoma")
logger.setLevel(logging.INFO)

try:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "daemon.log"
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
except Exception as e:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize queue
queue = AnalysisQueue()

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
    
    asyncio.create_task(queue.process_queue())
    yield

app = FastAPI(title="Autonoma Community Edition", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        if len(v.encode('utf-8')) > MAX_SIZE:
            raise ValueError(f"File content exceeds maximum size of 10MB")
        return v

class AnalyzeResponse(BaseModel):
    issues: List[Dict[str, Any]]

# Minimal auth - Community Edition uses no auth
def community_auth():
    return {"user_id": "community", "tier": "community"}

# Root endpoint
@app.get("/")
def home():
    return {
        "service": "Autonoma Community Edition",
        "status": "online", 
        "version": "1.0.0",
        "features": ["SEC001", "SEC002"]
    }

# Health check
@app.get("/health")
def health():
    return {"status": "healthy"}

# Analysis endpoint
@app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("60/minute")
async def analyze(request: Request, body: AnalyzeRequest):
    """Analyze code for security issues (SEC001, SEC002)"""
    try:
        logger.info(f"Analyzing {body.file_path}")
        task = {
            "file_path": body.file_path,
            "content": body.content,
            "project_id": body.project_id,
            "user_config": body.user_config
        }
        issues = await queue.run_analysis(task)
        return AnalyzeResponse(issues=issues)
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Streaming analysis
@app.post("/analyze/stream")
@limiter.limit("60/minute")
async def analyze_stream(request: Request, body: AnalyzeRequest):
    """Streaming analysis - sends issues as discovered"""
    
    async def generate_stream():
        try:
            task = {
                "file_path": body.file_path,
                "content": body.content,
                "project_id": body.project_id,
                "user_config": body.user_config
            }
            
            async for event in queue.run_analysis_stream(task):
                yield f"data: {json.dumps(event)}\n\n"
            
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

# Fix endpoint
@app.post("/analyze/fix")
async def analyze_fix(request: Request):
    """Generate fix for an issue"""
    from daemon.analysis.fix_engine import FixEngine
    
    data = await request.json()
    code = data.get("code")
    issue = data.get("issue")
    
    if not code or not issue:
        return {"error": "Missing code or issue description"}
    
    engine = FixEngine()
    fixed_code = await engine.generate_fix(code, issue)
    
    return {"fixed_code": fixed_code}
