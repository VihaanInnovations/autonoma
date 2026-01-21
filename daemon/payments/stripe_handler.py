"""
Stripe Payment Handler for Hybrid Local AI Code Reviewer

Handles subscription creation, webhook processing, and customer management.
"""
import stripe
import os
import logging
from typing import Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class SubscriptionTier(Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"

class StripeHandler:
    def __init__(self):
        # Initialize Stripe with API key from environment
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        
        if not stripe.api_key:
            logger.warning("STRIPE_SECRET_KEY not set. Payment features disabled.")
        
        # Price IDs from Stripe Dashboard - UPDATE THESE AFTER CREATING PRODUCTS
        self.price_ids = {
            SubscriptionTier.PRO: os.getenv("STRIPE_PRICE_ID_PRO", ""),
            SubscriptionTier.ENTERPRISE: os.getenv("STRIPE_PRICE_ID_ENTERPRISE", "")
        }
        
    def create_checkout_session(
        self, 
        user_id: str, 
        tier: SubscriptionTier,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None
    ) -> Dict:
        """
        Create Stripe Checkout session for subscription.
        
        Args:
            user_id: Internal user identifier
            tier: Subscription tier (PRO or ENTERPRISE)
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if user cancels
            customer_email: Optional email for customer creation
        
        Returns:
            Dict with 'session_id' and 'url', or 'error' if failed
        """
        if not stripe.api_key:
            return {'error': 'Stripe not configured'}
        
        if tier == SubscriptionTier.FREE:
            return {'error': 'Cannot create checkout for free tier'}
        
        price_id = self.price_ids.get(tier)
        if not price_id:
            return {'error': f'Price ID not configured for tier {tier.value}'}
        
        try:
            session = stripe.checkout.Session.create(
                customer_email=customer_email,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_id': user_id,
                    'tier': tier.value
                },
                subscription_data={
                    'metadata': {
                        'user_id': user_id,
                        'tier': tier.value
                    }
                },
                allow_promotion_codes=True,  # Allow discount codes
            )
            return {
                'session_id': session.id,
                'url': session.url
            }
        except stripe.error.StripeError as e:
            logger.error(f"Stripe checkout error: {e}")
            return {'error': str(e)}
    
    def create_customer_portal_session(self, customer_id: str, return_url: str) -> Dict:
        """
        Create customer portal session for managing subscription.
        
        Allows users to:
        - Update payment method
        - Cancel subscription
        - View invoices
        - Update billing information
        """
        if not stripe.api_key:
            return {'error': 'Stripe not configured'}
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return {'url': session.url}
        except stripe.error.StripeError as e:
            logger.error(f"Stripe portal error: {e}")
            return {'error': str(e)}
    
    def verify_webhook(self, payload: bytes, signature: str) -> Optional[Dict]:
        """
        Verify webhook signature and parse event.
        
        Args:
            payload: Raw request body
            signature: Stripe signature header
        
        Returns:
            Parsed event dict or None if invalid
        """
        if not self.webhook_secret:
            logger.warning("STRIPE_WEBHOOK_SECRET not set. Webhook verification disabled.")
            return None
        
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            return event
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {e}")
            return None
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return None
    
    def handle_webhook_event(self, event: Dict) -> Dict:
        """
        Handle Stripe webhook events.
        
        Supported events:
        - checkout.session.completed: Subscription created
        - customer.subscription.updated: Subscription modified
        - customer.subscription.deleted: Subscription canceled
        - invoice.payment_failed: Payment failed
        
        Returns:
            Dict with action taken
        """
        event_type = event.get('type')
        data = event.get('data', {}).get('object', {})
        
        logger.info(f"Processing webhook event: {event_type}")
        
        if event_type == 'checkout.session.completed':
            # Subscription successfully created
            subscription_id = data.get('subscription')
            metadata = data.get('metadata', {})
            user_id = metadata.get('user_id')
            tier = metadata.get('tier')
            customer_id = data.get('customer')
            
            if not user_id or not tier:
                logger.warning(f"Missing metadata in checkout session: {data.get('id')}")
                return {'action': 'skipped', 'reason': 'missing_metadata'}
            
            # Update user tier in database
            try:
                from daemon.db.db import update_user_tier, update_user_stripe_info
                update_user_tier(user_id, tier)
                if customer_id:
                    update_user_stripe_info(user_id, customer_id, subscription_id)
                logger.info(f"User {user_id} upgraded to {tier}")
                return {'action': 'tier_updated', 'user_id': user_id, 'tier': tier}
            except Exception as e:
                logger.error(f"Failed to update user tier: {e}")
                return {'action': 'error', 'error': str(e)}
        
        elif event_type == 'customer.subscription.updated':
            # Subscription updated (tier change, payment method updated, etc.)
            subscription_id = data.get('id')
            customer_id = data.get('customer')
            status = data.get('status')
            metadata = data.get('metadata', {})
            user_id = metadata.get('user_id')
            
            if status == 'active':
                # Subscription is active
                tier = metadata.get('tier', 'enterprise')  # Default to enterprise if not specified
                if user_id:
                    try:
                        from daemon.db.db import update_user_tier, update_user_stripe_info
                        update_user_tier(user_id, tier)
                        update_user_stripe_info(user_id, customer_id, subscription_id)
                        return {'action': 'subscription_active', 'user_id': user_id}
                    except Exception as e:
                        logger.error(f"Failed to update subscription: {e}")
                        return {'action': 'error', 'error': str(e)}
            
            elif status == 'past_due':
                # Payment failed, subscription is past due
                logger.warning(f"Subscription {subscription_id} is past due")
                return {'action': 'payment_past_due', 'subscription_id': subscription_id}
            
            elif status == 'canceled' or status == 'unpaid':
                # Subscription canceled or unpaid
                if user_id:
                    try:
                        from daemon.db.db import update_user_tier
                        update_user_tier(user_id, 'free')
                        logger.info(f"User {user_id} downgraded to free (subscription {status})")
                        return {'action': 'tier_downgraded', 'user_id': user_id, 'reason': status}
                    except Exception as e:
                        logger.error(f"Failed to downgrade user: {e}")
                        return {'action': 'error', 'error': str(e)}
            
            return {'action': 'subscription_updated', 'status': status}
        
        elif event_type == 'customer.subscription.deleted':
            # Subscription canceled
            metadata = data.get('metadata', {})
            user_id = metadata.get('user_id')
            
            if user_id:
                try:
                    from daemon.db.db import update_user_tier
                    update_user_tier(user_id, 'free')
                    logger.info(f"User {user_id} downgraded to free (subscription deleted)")
                    return {'action': 'tier_downgraded', 'user_id': user_id}
                except Exception as e:
                    logger.error(f"Failed to downgrade user: {e}")
                    return {'action': 'error', 'error': str(e)}
            
            return {'action': 'subscription_deleted'}
        
        elif event_type == 'invoice.payment_failed':
            # Payment failed, subscription may be past_due
            customer_id = data.get('customer')
            subscription_id = data.get('subscription')
            logger.warning(f"Payment failed for customer {customer_id}, subscription {subscription_id}")
            
            # Optionally notify user to update payment method
            return {'action': 'payment_failed', 'customer_id': customer_id}
        
        elif event_type == 'invoice.payment_succeeded':
            # Payment succeeded (renewal or initial payment)
            customer_id = data.get('customer')
            subscription_id = data.get('subscription')
            logger.info(f"Payment succeeded for customer {customer_id}, subscription {subscription_id}")
            return {'action': 'payment_succeeded', 'customer_id': customer_id}
        
        else:
            logger.debug(f"Unhandled webhook event: {event_type}")
            return {'action': 'no_action', 'event_type': event_type}

