from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, EmailStr
from .auth import TeamAuth

router = APIRouter(prefix="/api/team", tags=["team"])
auth = TeamAuth()

# Mock Team Configuration Database
TEAM_CONFIGS = {
    "default": {
        "rules": {
            "disabled_rules": ["S101", "C901"],
            "enforced_rules": ["SECURITY_HIGH"]
        },
        "excluded_files": ["legacy/*", "vendor/*"]
    }
}

# Mock Team Members Database
# In production, this would be stored in a database
TEAM_MEMBERS = {
    "default": [
        {
            "id": "1",
            "email": "admin@example.com",
            "name": "Team Admin",
            "role": "Admin",
            "added_at": "2024-01-15T10:00:00Z",
            "status": "active"
        },
        {
            "id": "2",
            "email": "dev@example.com",
            "name": "John Developer",
            "role": "Developer",
            "added_at": "2024-01-20T14:30:00Z",
            "status": "active"
        },
        {
            "id": "3",
            "email": "viewer@example.com",
            "name": "Jane Viewer",
            "role": "Viewer",
            "added_at": "2024-02-01T09:15:00Z",
            "status": "active"
        }
    ]
}

# Request/Response Models
class AddMemberRequest(BaseModel):
    email: EmailStr
    name: str
    role: str  # Admin, Developer, Viewer

class UpdateMemberRoleRequest(BaseModel):
    role: str  # Admin, Developer, Viewer

class UpdateTeamConfigRequest(BaseModel):
    rules: Optional[Dict[str, Any]] = None
    excluded_files: Optional[List[str]] = None

@router.get("/config")
async def get_team_config(token: str = Depends(auth.verify_token)) -> Dict[str, Any]:
    """
    Fetch the team configuration for the authenticated user.
    In a real app, 'token' would map to a specific Organization ID.
    """
    # Simulate fetching config
    return TEAM_CONFIGS["default"]

@router.put("/config")
async def update_team_config(
    request: UpdateTeamConfigRequest,
    token: str = Depends(auth.verify_token)
) -> Dict[str, Any]:
    """
    Update the team configuration (rules, excluded files).
    """
    # In production, map token to team_id
    team_id = "default"
    
    if team_id not in TEAM_CONFIGS:
        TEAM_CONFIGS[team_id] = {
            "rules": {
                "disabled_rules": [],
                "enforced_rules": []
            },
            "excluded_files": []
        }
    
    config = TEAM_CONFIGS[team_id]
    
    # Update rules if provided
    if request.rules is not None:
        if "rules" not in config:
            config["rules"] = {}
        if "disabled_rules" in request.rules:
            config["rules"]["disabled_rules"] = request.rules["disabled_rules"]
        if "enforced_rules" in request.rules:
            config["rules"]["enforced_rules"] = request.rules["enforced_rules"]
    
    # Update excluded files if provided
    if request.excluded_files is not None:
        config["excluded_files"] = request.excluded_files
    
    TEAM_CONFIGS[team_id] = config
    
    return {"status": "success", "config": config}

@router.post("/sync")
async def sync_stats(stats: Dict[str, Any], token: str = Depends(auth.verify_token)):
    """
    Sync local usage stats to the team dashboard.
    """
    print(f"Received stats sync from token {token}: {stats}")
    return {"status": "synced", "received_items": len(stats)}

@router.get("/members")
async def get_team_members(token: str = Depends(auth.verify_token)) -> Dict[str, Any]:
    """
    Get all team members for the authenticated team.
    """
    # In production, map token to team_id
    team_id = "default"
    members = TEAM_MEMBERS.get(team_id, [])
    return {"members": members, "total": len(members)}

@router.post("/members")
async def add_team_member(
    request: AddMemberRequest,
    token: str = Depends(auth.verify_token)
) -> Dict[str, Any]:
    """
    Add a new team member.
    """
    # Validate role
    valid_roles = ["Admin", "Developer", "Viewer"]
    if request.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )
    
    # In production, map token to team_id
    team_id = "default"
    
    # Check if member already exists
    existing_members = TEAM_MEMBERS.get(team_id, [])
    if any(m["email"] == request.email for m in existing_members):
        raise HTTPException(
            status_code=400,
            detail=f"Member with email {request.email} already exists"
        )
    
    # Generate new member ID
    import uuid
    from datetime import datetime
    new_member = {
        "id": str(uuid.uuid4()),
        "email": request.email,
        "name": request.name,
        "role": request.role,
        "added_at": datetime.utcnow().isoformat() + "Z",
        "status": "active"
    }
    
    # Add to team
    if team_id not in TEAM_MEMBERS:
        TEAM_MEMBERS[team_id] = []
    TEAM_MEMBERS[team_id].append(new_member)
    
    return {"status": "success", "member": new_member}

@router.put("/members/{member_id}/role")
async def update_member_role(
    member_id: str,
    request: UpdateMemberRoleRequest,
    token: str = Depends(auth.verify_token)
) -> Dict[str, Any]:
    """
    Update a team member's role.
    """
    # Validate role
    valid_roles = ["Admin", "Developer", "Viewer"]
    if request.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )
    
    # In production, map token to team_id
    team_id = "default"
    members = TEAM_MEMBERS.get(team_id, [])
    
    # Find and update member
    member_found = False
    for member in members:
        if member["id"] == member_id:
            member["role"] = request.role
            member_found = True
            break
    
    if not member_found:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return {"status": "success", "member_id": member_id, "new_role": request.role}

@router.delete("/members/{member_id}")
async def remove_team_member(
    member_id: str,
    token: str = Depends(auth.verify_token)
) -> Dict[str, Any]:
    """
    Remove a team member from the team.
    """
    # In production, map token to team_id
    team_id = "default"
    members = TEAM_MEMBERS.get(team_id, [])
    
    # Find and remove member
    original_count = len(members)
    TEAM_MEMBERS[team_id] = [m for m in members if m["id"] != member_id]
    
    if len(TEAM_MEMBERS[team_id]) == original_count:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return {"status": "success", "member_id": member_id, "message": "Member removed"}
