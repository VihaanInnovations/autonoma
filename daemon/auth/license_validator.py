"""
Client-side License Validator
Validates licenses with online server to prevent local tampering.
"""
import httpx
import hashlib
import time
import os
import logging
from typing import Optional, Dict
from datetime import datetime

# Import hardware fingerprinting
try:
    from .hardware_fingerprint import get_machine_id
except ImportError:
    # Fallback if hardware_fingerprint not available
    import platform
    import subprocess
    import uuid
    
    def get_machine_id() -> str:
        """Fallback machine ID generation"""
        components = [
            platform.processor() or "unknown",
            ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) 
                     for i in range(0, 8*6, 8)][::-1]),
            platform.system(),
            platform.release(),
            platform.node()
        ]
        machine_string = "|".join(str(c) for c in components)
        return hashlib.sha256(machine_string.encode()).hexdigest()[:32]

logger = logging.getLogger(__name__)

# License server URL (should be environment variable)
LICENSE_SERVER_URL = os.getenv(
    "LICENSE_SERVER_URL", 
    "https://license.autonoma.ai"  # Production URL
)

# Client secret (should match server LICENSE_SECRET)
CLIENT_SECRET = os.getenv("LICENSE_CLIENT_SECRET")
if not CLIENT_SECRET:
    if os.getenv("ENVIRONMENT", "production").lower() == "development":
        logger.warning("LICENSE_CLIENT_SECRET not set, using development fallback. Set LICENSE_CLIENT_SECRET in production!")
        CLIENT_SECRET = "change-me-in-production-dev-only"
    else:
        logger.error("LICENSE_CLIENT_SECRET environment variable is required for online license validation.")
        CLIENT_SECRET = None  # Will disable online validation

# Grace period for offline use (24 hours)
OFFLINE_GRACE_PERIOD = 86400  # 24 hours in seconds

# Cache for offline validation
_license_cache = {}

# Machine ID function is imported from hardware_fingerprint module above
# This ensures consistent machine ID generation across the codebase

def generate_signature(license_key: str, user_id: str, machine_id: str, timestamp: int) -> str:
    """Generate signature for request validation"""
    message = f"{license_key}:{user_id}:{machine_id}:{timestamp}:{CLIENT_SECRET}"
    return hashlib.sha256(message.encode()).hexdigest()

async def validate_license_online(
    license_key: str, 
    user_id: str,
    timeout: float = 5.0
) -> Dict:
    """
    Validates license with online server. Cannot be bypassed locally.
    
    Returns:
        {
            "valid": bool,
            "license_type": str | None,
            "expires_at": float | None,
            "trial_days_remaining": int | None,
            "error": str | None
        }
    """
    machine_id = get_machine_id()
    timestamp = int(time.time())
    signature = generate_signature(license_key, user_id, machine_id, timestamp)
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{LICENSE_SERVER_URL}/validate",
                json={
                    "license_key": license_key,
                    "user_id": user_id,
                    "machine_id": machine_id,
                    "timestamp": timestamp,
                    "signature": signature
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Cache result for offline grace period
                cache_key = f"{license_key}:{user_id}"
                _license_cache[cache_key] = {
                    "data": data,
                    "last_validated": time.time()
                }
                
                return data
            else:
                error_data = response.json() if response.content else {}
                return {
                    "valid": False,
                    "error": error_data.get("detail", "Validation failed")
                }
                
    except httpx.TimeoutException:
        logger.warning("License server timeout, using offline validation")
        return await validate_license_offline_with_grace_period(license_key, user_id)
    except Exception as e:
        logger.error(f"License validation error: {e}")
        return await validate_license_offline_with_grace_period(license_key, user_id)

async def validate_license_offline_with_grace_period(
    license_key: str, 
    user_id: str
) -> Dict:
    """
    Offline validation with grace period (e.g., 24 hours).
    After grace period, requires online validation.
    """
    cache_key = f"{license_key}:{user_id}"
    cached = _license_cache.get(cache_key)
    
    if cached:
        # Check if still within grace period (24 hours)
        time_since_validation = time.time() - cached["last_validated"]
        if time_since_validation < OFFLINE_GRACE_PERIOD:
            logger.info(f"Using cached license validation (offline mode)")
            return cached["data"]
    
    # Grace period expired - require online validation
    return {
        "valid": False,
        "error": "License validation required. Please connect to internet. Offline grace period expired."
    }

async def validate_license(
    license_key: str,
    user_id: str,
    require_online: bool = False
) -> Dict:
    """
    Main license validation function.
    
    Args:
        license_key: License key to validate
        user_id: User ID
        require_online: If True, always require online validation (no grace period)
    
    Returns:
        Validation result dictionary
    """
    if require_online:
        return await validate_license_online(license_key, user_id)
    else:
        # Try online first, fallback to offline with grace period
        result = await validate_license_online(license_key, user_id)
        if result.get("valid"):
            return result
        else:
            # If online failed, try offline grace period
            return await validate_license_offline_with_grace_period(license_key, user_id)

def clear_license_cache(license_key: str = None, user_id: str = None):
    """Clear license cache (useful for testing or forced re-validation)"""
    if license_key and user_id:
        cache_key = f"{license_key}:{user_id}"
        _license_cache.pop(cache_key, None)
    else:
        _license_cache.clear()

