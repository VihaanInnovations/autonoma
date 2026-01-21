import re
import logging
from typing import List

logger = logging.getLogger("InvariantSentinel")

class InvariantSentinel:
    """
    Read-Only system to detect invariant violations in generated patches.
    Does NOT block execution, but downgrades success to SUSPECT.
    """
    
    def check_invariants(self, patch_content: str, original_content: str = "") -> List[str]:
        violations = []
        
        # 1. Soft Delete Invariant
        # If setting is_active=False, MUST set deleted_at
        if "is_active = False" in patch_content or "is_active=False" in patch_content:
            if "deleted_at" not in patch_content and "datetime" not in patch_content:
                violations.append("SOFT_DELETE_INVARIANT: Boolean flip without timestamp")

        # 2. Destructive Update Invariant
        # If updating a dict/object, should use .update() or individual fields, NOT overwrite.
        # This is heuristics based.
        # Example L6-01: users_db[user_id] = user (Bad) vs users_db[user_id].update(...) (Good)
        # We need to detect "assignment to dict key" where the value is a whole object.
        # This is hard to do perfectly with regex, but we can look for "users_db[.*] = user"
        if re.search(r"users_db\[.*\]\s*=\s*\w+", patch_content):
            # If not using .update or dict unpacking
            if ".update" not in patch_content and "**" not in patch_content:
                violations.append("DATA_PRESERVATION_INVARIANT: Potential destructive overwrite")

        # 3. Role Check Weakening
        # If original had "role", and patch modifies lines with "role"
        # Ideally we'd diff ASTs, but here we can check if "admin" or "role" is removed.
        # For L6-03 checks:
        if "role" in patch_content and "admin" not in patch_content:
             # Weak heuristic: modified role logic but didn't mention admin?
             pass 

        # 4. Invariant Drift (Internal Visibility)
        # If code adds filtering (internal=False) when it wasn't there?
        # Or removes it?
        # L6-04: Code added "if user.id not in users_db" (Wait that was a fix)
        # This one is tricky to generalize without domain knowledge. 
        # But we can flag "Visibility Reduction".
        
        return violations
