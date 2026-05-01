from fastapi import APIRouter
from pydantic import BaseModel
import os
import time

router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    pid: int
    uptime_seconds: float

START_TIME = time.time()

@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "ok",
        "version": "0.1.0",
        "pid": os.getpid(),
        "uptime_seconds": time.time() - START_TIME
    }

@router.post("/manage/update")
async def update_daemon():
    # Stub for auto-update logic - in full implementation this would run the update script
    return {"status": "update_started", "message": "Update process triggered. Check logs."}

@router.get("/manage/check_update")
async def check_update():
    """
    Checks if a newer version is available.
    """
    # Mock remote version check
    # In prod: response = requests.get("https://updates.hybrid-reviewer.com/latest")
    remote_version = "0.1.1" 
    local_version = "0.1.0"
    
    update_available = remote_version != local_version
    
    return {
        "update_available": update_available,
        "current_version": local_version,
        "latest_version": remote_version,
        "download_url": "https://github.com/hybrid-ai-team/hybrid-reviewer/releases/latest"
    }
