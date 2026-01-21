"""
API Key Authentication for CodeSentinal
Maps API keys to user_id for subscription tier checking
Includes rate limiting and IP whitelisting
"""
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from daemon.db.db import get_db_connection
import hashlib
from datetime import datetime
from typing import Optional, Dict

security = HTTPBearer(auto_error=False)

# Import rate limiting functions
try:
    from daemon.auth.rate_limiter import check_rate_limit, check_ip_whitelist
except ImportError:
    # Fallback for when running as module directly
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from daemon.auth.rate_limiter import check_rate_limit, check_ip_whitelist

async def verify_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Dict[str, Optional[str]]:
    """
    Verify API key and return user info.
    Includes rate limiting and IP whitelist checking.
    Returns user_id and tier for subscription checking.
    
    If no API key provided, returns free tier with no user_id.
    """
    if not credentials:
        # No API key provided - default to free tier with no user
        return {"user_id": None, "tier": "free"}
    
    api_key = credentials.credentials
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Get client IP address
    client_ip = request.client.host if request.client else "unknown"
    # Check X-Forwarded-For header (for proxies/load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get user info from API key
        cursor.execute(
            """
            SELECT 
                ak.user_id,
                u.tier,
                ak.is_active,
                ak.expires_at
            FROM api_keys ak
            JOIN User u ON ak.user_id = u.user_id
            WHERE ak.key_hash = ?
            """,
            (key_hash,)
        )
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        user_id = result["user_id"]
        tier = result["tier"] or "free"
        is_active = result["is_active"]
        expires_at = result["expires_at"]
        
        if not is_active:
            conn.close()
            raise HTTPException(status_code=401, detail="API key is inactive")
        
        if expires_at:
            try:
                # Handle both ISO format and SQLite timestamp format
                if isinstance(expires_at, str):
                    if 'T' in expires_at:
                        expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    else:
                        expires_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                else:
                    expires_dt = datetime.fromisoformat(str(expires_at))
                
                if expires_dt < datetime.now():
                    conn.close()
                    raise HTTPException(status_code=401, detail="API key has expired")
            except (ValueError, AttributeError) as e:
                # If date parsing fails, log but don't block (graceful degradation)
                pass
        
        # Check IP whitelist
        if not check_ip_whitelist(key_hash, client_ip):
            conn.close()
            raise HTTPException(
                status_code=403, 
                detail=f"IP address {client_ip} is not allowed for this API key"
            )
        
        # Check rate limit
        if not check_rate_limit(key_hash):
            conn.close()
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again later."
            )
        
        # Update last_used timestamp
        cursor.execute(
            "UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE key_hash = ?",
            (key_hash,)
        )
        conn.commit()
        
        return {"user_id": user_id, "tier": tier}
    finally:
        conn.close()

