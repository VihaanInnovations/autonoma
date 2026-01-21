"""
Rate Limiting per API Key
Tracks and enforces rate limits for individual API keys
"""
from fastapi import HTTPException, Request
from daemon.db.db import get_db_connection
from datetime import datetime, timedelta
import json
from typing import Optional, List

def check_rate_limit(key_hash: str, default_limit: int = 60) -> bool:
    """
    Check if API key has exceeded rate limit.
    Returns True if allowed, False if rate limited.
    Uses sliding window (1 minute windows).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get rate limit for this key
        cursor.execute(
            "SELECT rate_limit_per_minute FROM api_keys WHERE key_hash = ?",
            (key_hash,)
        )
        result = cursor.fetchone()
        limit = result["rate_limit_per_minute"] if result and result["rate_limit_per_minute"] else default_limit
        
        # Get current window start (round down to minute)
        now = datetime.now()
        window_start = now.replace(second=0, microsecond=0)
        
        # Get or create rate limit record for this window
        cursor.execute(
            """
            SELECT request_count FROM api_key_rate_limits
            WHERE key_hash = ? AND window_start = ?
            """,
            (key_hash, window_start.isoformat())
        )
        record = cursor.fetchone()
        
        if record:
            request_count = record["request_count"]
            if request_count >= limit:
                conn.close()
                return False  # Rate limited
            
            # Increment counter
            cursor.execute(
                """
                UPDATE api_key_rate_limits
                SET request_count = request_count + 1
                WHERE key_hash = ? AND window_start = ?
                """,
                (key_hash, window_start.isoformat())
            )
        else:
            # Create new record
            cursor.execute(
                """
                INSERT INTO api_key_rate_limits (key_hash, window_start, request_count)
                VALUES (?, ?, 1)
                """,
                (key_hash, window_start.isoformat())
            )
        
        conn.commit()
        
        # Clean up old windows (older than 2 minutes)
        old_window = (window_start - timedelta(minutes=2)).isoformat()
        cursor.execute(
            "DELETE FROM api_key_rate_limits WHERE window_start < ?",
            (old_window,)
        )
        conn.commit()
        
        return True  # Allowed
    finally:
        conn.close()

def check_ip_whitelist(key_hash: str, client_ip: str) -> bool:
    """
    Check if client IP is allowed for this API key.
    Returns True if allowed, False if blocked.
    If allowed_ips is NULL, all IPs are allowed.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT allowed_ips FROM api_keys WHERE key_hash = ?",
            (key_hash,)
        )
        result = cursor.fetchone()
        
        if not result or not result["allowed_ips"]:
            # No IP restrictions - allow all
            return True
        
        # Parse JSON array of allowed IPs
        try:
            allowed_ips = json.loads(result["allowed_ips"])
            if not isinstance(allowed_ips, list):
                return True  # Invalid format - allow all
            
            # Check if client IP is in allowed list
            # Support CIDR notation (basic check)
            for allowed_ip in allowed_ips:
                if allowed_ip == client_ip:
                    return True
                # Basic CIDR check (e.g., "192.168.1.0/24")
                if '/' in allowed_ip:
                    ip_part, cidr = allowed_ip.split('/')
                    # Simple check: if IP starts with same prefix
                    if client_ip.startswith(ip_part.rsplit('.', 1)[0] + '.'):
                        return True
            
            return False  # IP not in whitelist
        except (json.JSONDecodeError, ValueError):
            # Invalid JSON - allow all (graceful degradation)
            return True
    finally:
        conn.close()

def get_rate_limit_info(key_hash: str) -> dict:
    """Get current rate limit status for an API key"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get rate limit setting
        cursor.execute(
            "SELECT rate_limit_per_minute, allowed_ips FROM api_keys WHERE key_hash = ?",
            (key_hash,)
        )
        result = cursor.fetchone()
        
        if not result:
            return {"error": "API key not found"}
        
        limit = result["rate_limit_per_minute"] or 60
        allowed_ips = None
        if result["allowed_ips"]:
            try:
                allowed_ips = json.loads(result["allowed_ips"])
            except:
                pass
        
        # Get current window usage
        now = datetime.now()
        window_start = now.replace(second=0, microsecond=0)
        
        cursor.execute(
            """
            SELECT request_count FROM api_key_rate_limits
            WHERE key_hash = ? AND window_start = ?
            """,
            (key_hash, window_start.isoformat())
        )
        record = cursor.fetchone()
        current_count = record["request_count"] if record else 0
        
        return {
            "rate_limit_per_minute": limit,
            "current_requests": current_count,
            "remaining": max(0, limit - current_count),
            "allowed_ips": allowed_ips
        }
    finally:
        conn.close()

