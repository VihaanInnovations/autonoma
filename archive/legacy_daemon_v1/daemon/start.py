#!/usr/bin/env python3
"""
Startup script for Autonoma Community Edition Daemon
"""
import sys
import os
import logging
from pathlib import Path

# Add current directory and parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import app
import uvicorn

if __name__ == "__main__":
    # Get port from environment or default to 8000
    port = int(os.environ.get("PORT", 8000))
    # Default to 0.0.0.0 if PORT is set (cloud deployment), else 127.0.0.1 (local)
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = os.environ.get("HOST", default_host)
    
    print(f"Starting Autonoma Community Edition Daemon on {host}:{port}")
    print("Press CTRL+C to stop")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )

