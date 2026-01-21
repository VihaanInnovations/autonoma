"""
Payoneer Payment Handler for Hybrid Local AI Code Reviewer

Payoneer is useful for:
- International customers (lower fees in some regions)
- B2B transactions
- Alternative payment method for users who prefer Payoneer
- Cross-border payments
"""
import os
import logging
import hashlib
import hmac
import json
from typing import Dict, Optional
from enum import Enum
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

class SubscriptionTier(Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"

class PayoneerHandler:
    def __init__(self):
        # Payoneer API credentials from environment
        self.api_key = os.getenv("PAYONEER_API_KEY", "")
        self.partner_id = os.getenv("PAYONEER_PARTNER_ID", "")
        self.program_id = os.getenv("PAYONEER_PROGRAM_ID", "")
        self.base_url = os.getenv("PAYONEER_BASE_URL", "https://api.payoneer.com")
        
        # Payment notification webhook secret
        self.webhook_secret = os.getenv("PAYONEER_WEBHOOK_SECRET", "")
        
        if not self.api_key:
            logger.warning("PAYONEER_API_KEY not set. Payoneer payment features disabled.")
        
        # Pricing (matches PricingManager)
        self.pricing = {
            SubscriptionTier.PRO: 9.0,
            SubscriptionTier.ENTERPRISE: 49.0
        }
    
    def create_payment_link(
        self,
        user_id: str,
        tier: SubscriptionTier,
        return_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None
    ) -> Dict:
        """
        Create Payoneer payment link for subscription.
        
        Note: Payoneer typically requires:
        1. User to have a Payoneer account
        2. Pre-registration or onboarding flow
        3. Different integration approach than Stripe
        
        This implementation uses Payoneer's payment request API.
        
        Returns:
            Dict with 'payment_url' or 'error'
        """
        if not self.api_key:
            return {'error': 'Payoneer not configured'}
        
        if tier == SubscriptionTier.FREE:
            return {'error': 'Cannot create payment for free tier'}
        
        amount = self.pricing.get(tier, 0)
        if amount == 0:
            return {'error': f'Invalid tier: {tier.value}'}
        
        try:
            # Payoneer payment request parameters
            # Note: Actual Payoneer API may vary - check their latest documentation
            payment_data = {
                'partner_id': self.partner_id,
                'program_id': self.program_id,
                'amount': amount,
                'currency': 'USD',
                'description': f'Hybrid Reviewer {tier.value.capitalize()} Subscription',
                'return_url': return_url,
                'cancel_url': cancel_url,
                'metadata': json.dumps({
                    'user_id': user_id,
                    'tier': tier.value,
                    'recurring': 'monthly'
                }),
                'customer_email': customer_email or '',
            }
            
            # Generate signature for API request
            signature = self._generate_signature(payment_data)
            payment_data['signature'] = signature
            
            # Construct payment URL
            # Payoneer typically uses a hosted payment page
            payment_url = f"{self.base_url}/v4/programs/{self.program_id}/payments/request"
            
            # For hosted payment page, redirect user to this URL
            # Or use Payoneer's JavaScript SDK for embedded payments
            
            return {
                'payment_url': payment_url,
                'payment_data': payment_data,
                'method': 'redirect'  # or 'embedded' if using JS SDK
            }
            
        except Exception as e:
            logger.error(f"Payoneer payment link error: {e}")
            return {'error': str(e)}
    
    def _generate_signature(self, data: Dict) -> str:
        """
        Generate HMAC signature for Payoneer API request.
        
        Payoneer uses HMAC-SHA256 for request authentication.
        """
        if not self.webhook_secret:
            return ""
        
        # Sort parameters and create query string
        sorted_params = sorted(data.items())
        query_string = urlencode(sorted_params)
        
        # Generate HMAC signature
        signature = hmac.new(
            self.webhook_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """
        Verify Payoneer webhook signature.
        
        Args:
            payload: Raw request body
            signature: Payoneer signature header
        
        Returns:
            True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("PAYONEER_WEBHOOK_SECRET not set. Webhook verification disabled.")
            return False
        
        try:
            # Payoneer uses HMAC-SHA256 for webhook signatures
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Webhook verification error: {e}")
            return False
    
    def handle_webhook_event(self, event_data: Dict) -> Dict:
        """
        Handle Payoneer webhook events.
        
        Payoneer webhook events include:
        - payment.completed
        - payment.failed
        - payment.refunded
        - subscription.renewed
        - subscription.canceled
        
        Returns:
            Dict with action taken
        """
        event_type = event_data.get('event_type', '')
        payment_data = event_data.get('data', {})
        
        logger.info(f"Processing Payoneer webhook event: {event_type}")
        
        # Extract metadata
        metadata_str = payment_data.get('metadata', '{}')
        try:
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
        except:
            metadata = {}
        
        user_id = metadata.get('user_id')
        tier = metadata.get('tier')
        payment_id = payment_data.get('payment_id')
        status = payment_data.get('status')
        
        if event_type == 'payment.completed':
            # Payment successful
            if user_id and tier:
                try:
                    from daemon.db.db import update_user_tier
                    update_user_tier(user_id, tier)
                    logger.info(f"User {user_id} upgraded to {tier} via Payoneer")
                    return {
                        'action': 'tier_updated',
                        'user_id': user_id,
                        'tier': tier,
                        'payment_id': payment_id
                    }
                except Exception as e:
                    logger.error(f"Failed to update user tier: {e}")
                    return {'action': 'error', 'error': str(e)}
            
            return {'action': 'payment_completed', 'payment_id': payment_id}
        
        elif event_type == 'payment.failed':
            # Payment failed
            logger.warning(f"Payoneer payment failed: {payment_id}")
            return {
                'action': 'payment_failed',
                'payment_id': payment_id,
                'user_id': user_id
            }
        
        elif event_type == 'subscription.renewed':
            # Monthly subscription renewed
            if user_id:
                # Ensure tier is still active
                try:
                    from daemon.db.db import get_user_tier
                    current_tier = get_user_tier(user_id)
                    if current_tier != tier:
                        from daemon.db.db import update_user_tier
                        update_user_tier(user_id, tier)
                    return {'action': 'subscription_renewed', 'user_id': user_id}
                except Exception as e:
                    logger.error(f"Failed to handle renewal: {e}")
                    return {'action': 'error', 'error': str(e)}
            
            return {'action': 'subscription_renewed', 'payment_id': payment_id}
        
        elif event_type == 'subscription.canceled':
            # Subscription canceled
            if user_id:
                try:
                    from daemon.db.db import update_user_tier
                    update_user_tier(user_id, 'free')
                    logger.info(f"User {user_id} downgraded to free (Payoneer subscription canceled)")
                    return {'action': 'tier_downgraded', 'user_id': user_id}
                except Exception as e:
                    logger.error(f"Failed to downgrade user: {e}")
                    return {'action': 'error', 'error': str(e)}
            
            return {'action': 'subscription_canceled', 'payment_id': payment_id}
        
        elif event_type == 'payment.refunded':
            # Payment refunded
            if user_id:
                try:
                    from daemon.db.db import update_user_tier
                    update_user_tier(user_id, 'free')
                    logger.info(f"User {user_id} downgraded to free (Payoneer refund)")
                    return {'action': 'tier_downgraded', 'user_id': user_id, 'reason': 'refund'}
                except Exception as e:
                    logger.error(f"Failed to handle refund: {e}")
                    return {'action': 'error', 'error': str(e)}
            
            return {'action': 'payment_refunded', 'payment_id': payment_id}
        
        else:
            logger.debug(f"Unhandled Payoneer webhook event: {event_type}")
            return {'action': 'no_action', 'event_type': event_type}
    
    def check_payment_status(self, payment_id: str) -> Dict:
        """
        Check status of a Payoneer payment.
        
        Useful for polling or manual verification.
        """
        if not self.api_key:
            return {'error': 'Payoneer not configured'}
        
        try:
            # Payoneer API call to check payment status
            # This is a placeholder - actual API endpoint may vary
            # Check Payoneer API documentation for exact endpoint
            
            # Example API call structure:
            # response = requests.get(
            #     f"{self.base_url}/v4/payments/{payment_id}",
            #     headers={'Authorization': f'Bearer {self.api_key}'}
            # )
            
            return {
                'payment_id': payment_id,
                'status': 'pending',  # or 'completed', 'failed', etc.
                'note': 'Implement actual Payoneer API call based on their documentation'
            }
        except Exception as e:
            logger.error(f"Payment status check error: {e}")
            return {'error': str(e)}

