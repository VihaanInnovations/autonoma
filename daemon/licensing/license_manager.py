import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class LicenseStatus:
    is_valid: bool
    company_name: str
    expiry: str
    message: str

class LicenseManager:
    """
    Simple License Manager for Enterprise Edition.
    """
    
    def check_license(self) -> LicenseStatus:
        key = os.environ.get("AUTONOMA_LICENSE_KEY", "")
        
        if not key:
            return LicenseStatus(False, "", "", "UNLICENSED TRIAL")
            
        if not key.startswith("AUTONOMA-ENT-"):
            return LicenseStatus(False, "", "", "INVALID LICENSE KEY")
            
        try:
            # Format: AUTONOMA-ENT-<COMPANY>-<EXPIRY>
            parts = key.split("-")
            if len(parts) >= 4:
                company_name = parts[2].replace("_", " ")
                expiry = parts[3]
                return LicenseStatus(True, company_name, expiry, "VALID")
            else:
                return LicenseStatus(False, "", "", "MALFORMED LICENSE KEY")
        except Exception as e:
            logger.error(f"License check failed: {e}")
            return LicenseStatus(False, "", "", "LICENSE CHECK ERROR")
