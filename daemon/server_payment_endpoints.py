"""
Payment API Endpoints for Hybrid Local AI Code Reviewer

Add these endpoints to your daemon/server.py file to enable payment processing.
Supports both Stripe and Payoneer payment methods.
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from daemon.payments.stripe_handler import StripeHandler, SubscriptionTier
from daemon.payments.payoneer_handler import PayoneerHandler

# Initialize payment handlers
stripe_handler = StripeHandler()
payoneer_handler = PayoneerHandler()

# Create router for payment endpoints
payment_router = APIRouter(prefix="/api/payment", tags=["payment"])

class CheckoutRequest(BaseModel):
    user_id: str
    tier: str  # "pro" or "enterprise"
    provider: str = "stripe"  # "stripe" or "payoneer"
    customer_email: str = None

@payment_router.post("/checkout")
async def create_checkout(request: Request, body: CheckoutRequest):
    """
    Create checkout session (Stripe or Payoneer).
    
    Body:
    - user_id: Internal user identifier
    - tier: "pro" or "enterprise"
    - provider: "stripe" (default) or "payoneer"
    - customer_email: Optional email for customer creation
    
    Returns:
    - checkout_url: URL to redirect user for payment
    - provider: Payment provider used
    """
    try:
        tier = SubscriptionTier(body.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tier. Must be 'pro' or 'enterprise'")
    
    if tier == SubscriptionTier.FREE:
        raise HTTPException(status_code=400, detail="Cannot create checkout for free tier")
    
    # Build return URLs
    base_url = str(request.base_url).rstrip('/')
    success_url = f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/payment/cancel"
    
    if body.provider == "payoneer":
        result = payoneer_handler.create_payment_link(
            user_id=body.user_id,
            tier=tier,
            return_url=success_url,
            cancel_url=cancel_url,
            customer_email=body.customer_email
        )
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        return {
            "checkout_url": result['payment_url'],
            "provider": "payoneer",
            "method": result.get('method', 'redirect')
        }
    
    else:  # Default to Stripe
        result = stripe_handler.create_checkout_session(
            user_id=body.user_id,
            tier=tier,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=body.customer_email
        )
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        return {
            "checkout_url": result['url'],
            "provider": "stripe",
            "session_id": result['session_id']
        }

@payment_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.
    
    Configure webhook endpoint in Stripe Dashboard:
    https://dashboard.stripe.com/webhooks
    
    Events to listen for:
    - checkout.session.completed
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_failed
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")
    
    event = stripe_handler.verify_webhook(payload, signature)
    if not event:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    
    result = stripe_handler.handle_webhook_event(event)
    return result

@payment_router.post("/webhook/payoneer")
async def payoneer_webhook(request: Request):
    """
    Handle Payoneer webhook events.
    
    Configure webhook endpoint in Payoneer Dashboard.
    Check Payoneer documentation for exact header name and event format.
    """
    payload = await request.body()
    # Payoneer signature header name may vary - check their docs
    signature = request.headers.get("X-Payoneer-Signature") or request.headers.get("Payoneer-Signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature header")
    
    if not payoneer_handler.verify_webhook(payload, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    
    event_data = await request.json()
    result = payoneer_handler.handle_webhook_event(event_data)
    return result

@payment_router.get("/methods")
async def get_payment_methods():
    """
    Get available payment methods.
    
    Returns list of supported payment providers and their status.
    """
    methods = []
    
    # Check Stripe availability
    stripe_available = bool(stripe_handler.api_key) if hasattr(stripe_handler, 'api_key') else False
    methods.append({
        "provider": "stripe",
        "available": stripe_available,
        "name": "Stripe",
        "description": "Credit card payments (recommended)"
    })
    
    # Check Payoneer availability
    payoneer_available = bool(payoneer_handler.api_key) if hasattr(payoneer_handler, 'api_key') else False
    methods.append({
        "provider": "payoneer",
        "available": payoneer_available,
        "name": "Payoneer",
        "description": "International payments (alternative)"
    })
    
    return {"payment_methods": methods}

# To use these endpoints, add to your main server.py:
# from daemon.server_payment_endpoints import payment_router
# app.include_router(payment_router)

