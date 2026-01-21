
import os
from fastapi import APIRouter, Request, HTTPException
from starlette.config import Config
from starlette.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from typing import Optional, Dict, Any
import logging
import httpx

logger = logging.getLogger("hybrid-reviewer")

# Load environment variables
# In a real app, these would come from a secure vault or .env
config = Config(environ=os.environ)
oauth = OAuth(config)

# Multi-Provider OAuth2/OIDC Support
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Provider-specific configurations
OAUTH_PROVIDERS = {
    'google': {
        'client_id': os.getenv("GOOGLE_CLIENT_ID", ""),
        'client_secret': os.getenv("GOOGLE_CLIENT_SECRET", ""),
        'discovery_url': 'https://accounts.google.com/.well-known/openid-configuration',
        'scope': 'openid email profile'
    },
    'github': {
        'client_id': os.getenv("GITHUB_CLIENT_ID", ""),
        'client_secret': os.getenv("GITHUB_CLIENT_SECRET", ""),
        'discovery_url': 'https://token.actions.githubusercontent.com/.well-known/openid-configuration',
        'scope': 'openid email profile'
    },
    'azure': {
        'client_id': os.getenv("AZURE_CLIENT_ID", ""),
        'client_secret': os.getenv("AZURE_CLIENT_SECRET", ""),
        'tenant_id': os.getenv("AZURE_TENANT_ID", "common"),
        'discovery_url': f'https://login.microsoftonline.com/{os.getenv("AZURE_TENANT_ID", "common")}/v2.0/.well-known/openid-configuration',
        'scope': 'openid email profile'
    },
    'okta': {
        'client_id': os.getenv("OKTA_CLIENT_ID", ""),
        'client_secret': os.getenv("OKTA_CLIENT_SECRET", ""),
        'okta_domain': os.getenv("OKTA_DOMAIN", ""),
        'discovery_url': f'https://{os.getenv("OKTA_DOMAIN", "")}/.well-known/openid-configuration',
        'scope': 'openid email profile'
    }
}

# Register OAuth providers
for provider_name, provider_config in OAUTH_PROVIDERS.items():
    if provider_config['client_id'] and provider_config['client_secret']:
        try:
            oauth.register(
                name=provider_name,
                client_id=provider_config['client_id'],
                client_secret=provider_config['client_secret'],
                server_metadata_url=provider_config['discovery_url'],
                client_kwargs={
                    'scope': provider_config['scope']
                }
            )
            logger.info(f"Registered OAuth provider: {provider_name}")
        except Exception as e:
            logger.warning(f"Failed to register OAuth provider {provider_name}: {e}")

# Legacy generic OAuth (for backward compatibility)
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "dummy-client-id")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "dummy-secret")
OAUTH_DISCOVERY_URL = os.getenv("OAUTH_DISCOVERY_URL", "https://accounts.google.com/.well-known/openid-configuration")

if OAUTH_CLIENT_ID != "dummy-client-id" and OAUTH_CLIENT_SECRET != "dummy-secret":
    oauth.register(
        name='sso',
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        server_metadata_url=OAUTH_DISCOVERY_URL,
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

router = APIRouter(prefix="/auth", tags=["auth"])

def get_or_create_user(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get or create user in database from OAuth user info.
    Returns user dict with user_id, email, tier.
    """
    from daemon.db.db import get_db_connection
    
    # Extract user identifier from OAuth provider
    # Different providers use different fields (sub, id, email, etc.)
    user_id = user_info.get('sub') or user_info.get('id') or user_info.get('email', '').split('@')[0]
    email = user_info.get('email', '')
    name = user_info.get('name') or user_info.get('given_name', '')
    
    if not user_id:
        raise ValueError("Could not extract user identifier from OAuth response")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if user exists
        cursor.execute("SELECT user_id, email, tier FROM User WHERE user_id = ?", (user_id,))
        user_row = cursor.fetchone()
        
        if user_row:
            # User exists, return existing data
            return {
                "user_id": user_row["user_id"],
                "email": user_row["email"] or email,
                "tier": user_row["tier"] or "free"
            }
        else:
            # Create new user
            cursor.execute(
                "INSERT INTO User (user_id, email, tier) VALUES (?, ?, ?)",
                (user_id, email, "free")
            )
            conn.commit()
            logger.info(f"Created new user from OAuth: {user_id} ({email})")
            
            return {
                "user_id": user_id,
                "email": email,
                "tier": "free"
            }
    finally:
        conn.close()

@router.get("/login/{provider}", name="login_provider")
async def login_provider(request: Request, provider: str, redirect_after: Optional[str] = None):
    """
    Initiate SSO login flow for a specific provider.
    
    Supported providers: google, github, azure, okta, sso (generic)
    
    Args:
        provider: OAuth provider name
        redirect_after: Optional frontend URL to redirect to after login
    """
    # Check if provider is registered
    try:
        oauth_client = getattr(oauth, provider)
    except AttributeError:
        # Get list of available providers
        available = [name for name in ['google', 'github', 'azure', 'okta', 'sso'] if hasattr(oauth, name)]
        raise HTTPException(
            status_code=400,
            detail=f"OAuth provider '{provider}' not configured. Available providers: {available}"
        )
    
    # Store redirect URL in session
    if redirect_after:
        request.session['redirect_after_login'] = redirect_after
    else:
        request.session['redirect_after_login'] = FRONTEND_URL
    
    # Store provider name in session
    request.session['oauth_provider'] = provider
    
    # Get callback URL
    base_url = str(request.base_url).rstrip('/')
    callback_url = f"{base_url}/auth/callback/{provider}"
    
    try:
        return await oauth.__getattr__(provider).authorize_redirect(request, callback_url)
    except Exception as e:
        logger.error(f"OAuth login error for {provider}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"OAuth login failed: {str(e)}"}
        )

@router.get("/login", name="login")
async def login(request: Request, redirect_after: Optional[str] = None):
    """
    Legacy endpoint - redirects to generic SSO or first available provider.
    """
    # Try generic SSO first, then first available provider
    if hasattr(oauth, 'sso'):
        return await login_provider(request, 'sso', redirect_after)
    else:
        # Try to find first available provider
        for provider_name in ['google', 'github', 'azure', 'okta']:
            if hasattr(oauth, provider_name):
                return await login_provider(request, provider_name, redirect_after)
        return JSONResponse(
            status_code=500,
            content={"error": "No OAuth providers configured. Set provider credentials in environment variables."}
        )

@router.get("/callback/{provider}", name="auth_provider")
async def auth_provider(request: Request, provider: str):
    """
    Callback endpoint for specific OAuth provider.
    Creates/updates user in database and redirects to frontend.
    """
    try:
        # Check if provider is registered and get OAuth client
        try:
            oauth_client = getattr(oauth, provider)
        except AttributeError:
            raise HTTPException(status_code=400, detail=f"OAuth provider '{provider}' not configured")
        
        # Get OAuth token
        token = await oauth_client.authorize_access_token(request)
        
        # Extract user info (provider-specific)
        user_info = token.get('userinfo')
        if not user_info:
            # Try parsing id_token
            user_info = await oauth_client.parse_id_token(request, token)
        
        # For GitHub, user info might be in a different format
        if not user_info and provider == 'github':
            # GitHub OAuth returns user info differently
            import httpx
            async with httpx.AsyncClient() as client:
                headers = {'Authorization': f"Bearer {token.get('access_token')}"}
                response = await client.get('https://api.github.com/user', headers=headers)
                if response.status_code == 200:
                    github_user = response.json()
                    user_info = {
                        'sub': str(github_user.get('id')),
                        'email': github_user.get('email'),
                        'name': github_user.get('name') or github_user.get('login'),
                        'picture': github_user.get('avatar_url')
                    }
        
        if not user_info:
            raise HTTPException(status_code=400, detail="Could not retrieve user information from OAuth provider")
        
        # Get or create user in database
        user = get_or_create_user(dict(user_info))
        
        # Store user in session
        request.session['user'] = {
            'user_id': user['user_id'],
            'email': user['email'],
            'tier': user['tier'],
            'name': user_info.get('name', ''),
            'picture': user_info.get('picture', ''),
            'sso_provider': provider
        }
        
        # Get redirect URL from session
        redirect_url = request.session.pop('redirect_after_login', FRONTEND_URL)
        
        # Redirect to frontend with success
        if request.headers.get('Accept', '').startswith('application/json'):
            return JSONResponse(content={
                "status": "success",
                "user": request.session['user'],
                "redirect_url": redirect_url
            })
        else:
            return RedirectResponse(url=f"{redirect_url}?auth=success")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback error for {provider}: {e}", exc_info=True)
        error_url = f"{FRONTEND_URL}?auth=error&message={str(e)}"
        if request.headers.get('Accept', '').startswith('application/json'):
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "redirect_url": error_url}
            )
        return RedirectResponse(url=error_url)

@router.get("/callback", name="auth")
async def auth(request: Request):
    """
    Legacy callback endpoint - uses provider from session.
    """
    provider = request.session.get('oauth_provider', 'sso')
    
    # Check if provider exists, fallback to available provider
    if not hasattr(oauth, provider):
        if hasattr(oauth, 'sso'):
            provider = 'sso'
        else:
            # Find first available provider
            for provider_name in ['google', 'github', 'azure', 'okta']:
                if hasattr(oauth, provider_name):
                    provider = provider_name
                    break
    
    if not provider or not hasattr(oauth, provider):
        raise HTTPException(status_code=500, detail="No OAuth provider configured")
    
    return await auth_provider(request, provider)

@router.get("/logout")
async def logout(request: Request):
    """Logout user and clear session."""
    user_id = None
    if 'user' in request.session:
        user_id = request.session['user'].get('user_id')
    
    request.session.clear()
    
    logger.info(f"User logged out: {user_id}")
    
    return JSONResponse(content={
        "status": "logged_out",
        "message": "Successfully logged out"
    })

@router.get("/me")
async def get_current_user(request: Request):
    """
    Get current authenticated user information.
    Returns user info including API keys if available.
    """
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get user's API keys from database
    from daemon.db.db import get_db_connection
    import json
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get API keys for this user (without exposing the actual keys)
        cursor.execute(
            """
            SELECT 
                id,
                created_at,
                expires_at,
                is_active,
                last_used,
                rate_limit_per_minute
            FROM api_keys
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user['user_id'],)
        )
        
        api_keys = []
        for row in cursor.fetchall():
            api_keys.append({
                "id": row["id"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "is_active": bool(row["is_active"]),
                "last_used": row["last_used"],
                "rate_limit_per_minute": row["rate_limit_per_minute"]
            })
        
        return {
            "user_id": user['user_id'],
            "email": user.get('email'),
            "tier": user.get('tier', 'free'),
            "name": user.get('name'),
            "picture": user.get('picture'),
            "api_keys": api_keys,
            "api_key_count": len(api_keys)
        }
    finally:
        conn.close()
