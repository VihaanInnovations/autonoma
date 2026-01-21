from enum import Enum
from typing import Dict
from ..db.db import get_user_tier, get_project_owner, get_all_users

class PricingTier(Enum):
    FREE = "free"
    PRO_MONTHLY = "pro_monthly"
    PRO_ANNUAL = "pro_annual"
    ENTERPRISE_MONTHLY = "enterprise_monthly"
    ENTERPRISE_ANNUAL = "enterprise_annual"
    # Legacy support
    PRO = "pro"  # Maps to PRO_MONTHLY
    ENTERPRISE = "enterprise"  # Maps to ENTERPRISE_MONTHLY

class PricingManager:
    PRICING = {
        PricingTier.FREE: 0,
        PricingTier.PRO_MONTHLY: 9,
        PricingTier.PRO_ANNUAL: 90,  # 10 months = $90
        PricingTier.ENTERPRISE_MONTHLY: 49,
        PricingTier.ENTERPRISE_ANNUAL: 490,  # 10 months = $490
        # Legacy support
        PricingTier.PRO: 9,
        PricingTier.ENTERPRISE: 49
    }
    
    # Map legacy tiers to monthly equivalents
    TIER_MAPPING = {
        "pro": "pro_monthly",
        "enterprise": "enterprise_monthly"
    }

    FEATURES = {
        "cloud_llm": [PricingTier.PRO_MONTHLY, PricingTier.PRO_ANNUAL, PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.PRO, PricingTier.ENTERPRISE],
        "advanced_rules": [PricingTier.PRO_MONTHLY, PricingTier.PRO_ANNUAL, PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.PRO, PricingTier.ENTERPRISE],
        "audit_logs": [PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.ENTERPRISE],
        "sso": [PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.ENTERPRISE],
        "ci_cd": [PricingTier.PRO_MONTHLY, PricingTier.PRO_ANNUAL, PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.PRO, PricingTier.ENTERPRISE],
        "historical_reports": [PricingTier.PRO_MONTHLY, PricingTier.PRO_ANNUAL, PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.PRO, PricingTier.ENTERPRISE],
        "export": [PricingTier.PRO_MONTHLY, PricingTier.PRO_ANNUAL, PricingTier.ENTERPRISE_MONTHLY, PricingTier.ENTERPRISE_ANNUAL, PricingTier.PRO, PricingTier.ENTERPRISE]
    }
    
    # Free plan limits
    FREE_LIMITS = {
        "max_repositories": 1,
        "max_files_per_scan": 200
    }
    
    # Payoneer Base URL (Mock for MVP)
    PAYONEER_BASE_URL = "https://payoneer.com/pay"

    def __init__(self):
        pass

    def check_access(self, user_id: str, feature: str) -> bool:
        """
        Check if a user has access to a specific feature based on their tier.
        """
        tier_str = get_user_tier(user_id)
        
        # Map legacy tiers
        if tier_str in self.TIER_MAPPING:
            tier_str = self.TIER_MAPPING[tier_str]
        
        try:
            user_tier = PricingTier(tier_str)
        except ValueError:
            user_tier = PricingTier.FREE # Default fallback

        allowed_tiers = self.FEATURES.get(feature, [])
        return user_tier in allowed_tiers
    
    def is_free_tier(self, user_id: str) -> bool:
        """Check if user is on free tier"""
        tier_str = get_user_tier(user_id)
        if tier_str in self.TIER_MAPPING:
            tier_str = self.TIER_MAPPING[tier_str]
        try:
            user_tier = PricingTier(tier_str)
            return user_tier == PricingTier.FREE
        except ValueError:
            return True  # Default to free
    
    def get_free_limit(self, limit_name: str) -> int:
        """Get free tier limit value"""
        return self.FREE_LIMITS.get(limit_name, 0)

    def get_monthly_revenue(self) -> float:
        """
        Calculate total monthly revenue based on current user tiers.
        """
        users = get_all_users()
        total_revenue = 0.0
        
        for user in users:
            tier_str = user['tier']
            try:
                tier = PricingTier(tier_str)
                total_revenue += self.PRICING.get(tier, 0)
            except ValueError:
                pass
                
        return total_revenue

    def generate_payment_link(self, user_id: str, target_tier: str) -> str:
        """
        Generate a Payoneer payment link for upgrading to a target tier.
        """
        try:
            tier = PricingTier(target_tier)
        except ValueError:
            return ""
            
        amount = self.PRICING.get(tier, 0)
        # Construct a deep link or payment request URL
        # Format: base_url?client=hybrid_reviewer&user=${user_id}&amount=${amount}
        return f"{self.PAYONEER_BASE_URL}?client=hybrid_reviewer&user={user_id}&amount={amount}&currency=USD&tier={target_tier}"
