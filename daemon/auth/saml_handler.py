"""
SAML 2.0 Handler for Enterprise SSO Integration
Supports Okta, Azure AD, Google Workspace, and other SAML 2.0 providers
"""
import os
import base64
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import RedirectResponse, HTMLResponse
import logging
from urllib.parse import urlencode, parse_qs

logger = logging.getLogger("hybrid-reviewer")

router = APIRouter(prefix="/auth/saml", tags=["SAML SSO"])

# SAML Configuration
SAML_ENTITY_ID = os.getenv("SAML_ENTITY_ID", "")
SAML_SSO_URL = os.getenv("SAML_SSO_URL", "")  # IdP SSO URL
SAML_CERT = os.getenv("SAML_CERT", "")  # IdP public certificate (base64)
SAML_ACS_URL = os.getenv("SAML_ACS_URL", "")  # Assertion Consumer Service URL
SAML_NAME_ID_FORMAT = os.getenv("SAML_NAME_ID_FORMAT", "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress")

def generate_saml_request(relay_state: Optional[str] = None) -> str:
    """
    Generate SAML 2.0 AuthnRequest (legacy - uses configured ACS URL).
    Returns base64-encoded SAML request.
    """
    acs_url = SAML_ACS_URL or "https://your-api-domain.com/auth/saml/acs"
    return generate_saml_request_with_acs(acs_url)

def generate_saml_request_with_acs(acs_url: str) -> str:
    """
    Generate SAML 2.0 AuthnRequest with specified ACS URL.
    Returns base64-encoded SAML request.
    """
    from datetime import datetime
    import uuid
    
    request_id = f"_{uuid.uuid4().hex}"
    issue_instant = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    saml_request = f"""<?xml version="1.0" encoding="UTF-8"?>
<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="{request_id}"
                    Version="2.0"
                    IssueInstant="{issue_instant}"
                    Destination="{SAML_SSO_URL}"
                    AssertionConsumerServiceURL="{acs_url}"
                    ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">
    <saml:Issuer>{SAML_ENTITY_ID}</saml:Issuer>
    <samlp:NameIDPolicy Format="{SAML_NAME_ID_FORMAT}" AllowCreate="true"/>
</samlp:AuthnRequest>"""
    
    # Base64 encode
    encoded = base64.b64encode(saml_request.encode()).decode()
    return encoded

def parse_saml_response(saml_response: str) -> Dict[str, Any]:
    """
    Parse SAML 2.0 Response and extract user attributes.
    Returns user information dictionary.
    """
    try:
        # Decode base64 SAML response
        decoded = base64.b64decode(saml_response)
        xml = ET.fromstring(decoded)
        
        # Register namespaces
        namespaces = {
            'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
            'saml': 'urn:oasis:names:tc:SAML:2.0:assertion'
        }
        
        # Extract NameID (user identifier)
        name_id = xml.find('.//saml:NameID', namespaces)
        user_id = name_id.text if name_id is not None else None
        
        # Extract attributes
        attributes = {}
        for attr in xml.findall('.//saml:Attribute', namespaces):
            attr_name = attr.get('Name')
            attr_value_elem = attr.find('.//saml:AttributeValue', namespaces)
            if attr_value_elem is not None:
                attributes[attr_name] = attr_value_elem.text
        
        # Map common SAML attributes to user info
        user_info = {
            'sub': user_id or attributes.get('NameID') or attributes.get('email'),
            'email': attributes.get('email') or attributes.get('EmailAddress') or attributes.get('mail'),
            'name': attributes.get('name') or attributes.get('displayName') or attributes.get('cn'),
            'given_name': attributes.get('givenName') or attributes.get('firstName'),
            'family_name': attributes.get('surname') or attributes.get('lastName'),
            'groups': attributes.get('groups') or attributes.get('memberOf', '').split(',') if attributes.get('memberOf') else []
        }
        
        # Remove None values
        user_info = {k: v for k, v in user_info.items() if v is not None}
        
        return user_info
        
    except Exception as e:
        logger.error(f"SAML response parsing error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid SAML response: {str(e)}")

@router.get("/login")
async def saml_login(request: Request, redirect_after: Optional[str] = None):
    """
    Initiate SAML 2.0 SSO login flow.
    Redirects to IdP for authentication.
    """
    if not SAML_SSO_URL or not SAML_ENTITY_ID:
        raise HTTPException(
            status_code=500,
            detail="SAML not configured. Set SAML_SSO_URL, SAML_ENTITY_ID, and SAML_CERT environment variables."
        )
    
    # Store redirect URL in session
    if redirect_after:
        request.session['redirect_after_login'] = redirect_after
    else:
        request.session['redirect_after_login'] = os.getenv("FRONTEND_URL", "http://localhost:3000")
    
    # Get ACS URL (use configured or construct from request)
    acs_url = SAML_ACS_URL
    if not acs_url:
        base_url = str(request.base_url).rstrip('/')
        acs_url = f"{base_url}/auth/saml/acs"
    
    # Generate SAML request with proper ACS URL
    saml_request = generate_saml_request_with_acs(acs_url)
    
    # Build redirect URL with SAML request
    params = {
        'SAMLRequest': saml_request
    }
    
    if redirect_after:
        params['RelayState'] = redirect_after
    
    redirect_url = f"{SAML_SSO_URL}?{urlencode(params)}"
    
    return RedirectResponse(url=redirect_url)

@router.post("/acs")
async def saml_acs(request: Request):
    """
    SAML Assertion Consumer Service (ACS) endpoint.
    Receives SAML response from IdP after authentication.
    """
    try:
        form_data = await request.form()
        saml_response = form_data.get('SAMLResponse')
        relay_state = form_data.get('RelayState')
        
        if not saml_response:
            raise HTTPException(status_code=400, detail="Missing SAMLResponse")
        
        # Parse SAML response
        user_info = parse_saml_response(saml_response)
        
        # Get or create user (reuse OAuth function)
        from daemon.auth.oauth import get_or_create_user
        user = get_or_create_user(user_info)
        
        # Store user in session
        request.session['user'] = {
            'user_id': user['user_id'],
            'email': user['email'],
            'tier': user['tier'],
            'name': user_info.get('name', ''),
            'sso_provider': 'saml'
        }
        
        # Get redirect URL
        redirect_url = request.session.pop('redirect_after_login', relay_state or os.getenv("FRONTEND_URL", "http://localhost:3000"))
        
        return RedirectResponse(url=f"{redirect_url}?auth=success")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SAML ACS error: {e}", exc_info=True)
        redirect_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        return RedirectResponse(url=f"{redirect_url}?auth=error&message={str(e)}")

@router.get("/metadata")
async def saml_metadata():
    """
    Generate SAML 2.0 Service Provider metadata.
    This should be provided to the IdP administrator.
    """
    acs_url = SAML_ACS_URL or os.getenv("SAML_ACS_URL", "https://your-api-domain.com/auth/saml/acs")
    entity_id = SAML_ENTITY_ID or os.getenv("SAML_ENTITY_ID", "https://your-api-domain.com")
    
    metadata = f"""<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
                  entityID="{entity_id}">
    <SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        <NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</NameIDFormat>
        <NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:transient</NameIDFormat>
        <NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:persistent</NameIDFormat>
        <AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                                   Location="{acs_url}"
                                   index="0"/>
    </SPSSODescriptor>
</EntityDescriptor>"""
    
    return HTMLResponse(content=metadata, media_type="application/xml")

