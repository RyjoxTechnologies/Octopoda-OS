"""
Octopoda Billing — Stripe Integration
=======================================
Handles checkout, subscription management, webhooks, and plan enforcement.

Endpoints:
    POST /v1/billing/checkout    — Create a Stripe Checkout session
    POST /v1/billing/portal      — Create a Stripe Customer Portal session
    POST /v1/billing/webhook     — Stripe webhook handler
    GET  /v1/billing/status      — Current subscription status
    GET  /v1/billing/plans        — List available plans and prices
"""

import os
import time
import logging
import hashlib
import hmac

logger = logging.getLogger("octopoda.billing")

# Stripe config from environment
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Email config (reuse Resend setup from cloud_server.py)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM_EMAIL", "Octopoda <noreply@send.octopodas.com>")
OWNER_NOTIFICATION_EMAIL = os.environ.get("OWNER_NOTIFICATION_EMAIL", "joe@octopodas.com")

# Price IDs
PRICE_MAP = {
    "pro_monthly": os.environ.get("STRIPE_PRICE_PRO_MONTHLY", ""),
    "pro_annual": os.environ.get("STRIPE_PRICE_PRO_ANNUAL", ""),
    "business_monthly": os.environ.get("STRIPE_PRICE_BUSINESS_MONTHLY", ""),
    "business_annual": os.environ.get("STRIPE_PRICE_BUSINESS_ANNUAL", ""),
    "scale_monthly": os.environ.get("STRIPE_PRICE_SCALE_MONTHLY", ""),
    "scale_annual": os.environ.get("STRIPE_PRICE_SCALE_ANNUAL", ""),
}

# Plan limits: (max_agents, max_memories, max_extractions_per_month, rate_limit_per_min)
PLAN_LIMITS = {
    #                  agents  memories    extractions  rate_limit(rpm)
    "free":           (5,     5_000,      100,    60),
    "early_adopter":  (50,    100_000,    100,    300),   # Grandfathered beta users
    "pro":            (25,    250_000,    100,    300),
    "business":       (75,    1_000_000,  100,    1000),
    "scale":          (None,  5_000_000,  100,    5000),   # None = unlimited
    "enterprise":     (None,  None,       100,    None),
}

# Map Stripe price IDs to plan names
def _price_to_plan(price_id: str) -> str:
    for key, pid in PRICE_MAP.items():
        if pid == price_id:
            return key.split("_")[0]  # "pro_monthly" -> "pro"
    return "free"


def _stripe_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Make a request to the Stripe API."""
    import requests
    url = f"https://api.stripe.com/v1{endpoint}"
    headers = {"Authorization": f"Bearer {STRIPE_SECRET_KEY}"}
    if method == "GET":
        resp = requests.get(url, headers=headers, params=data, timeout=15)
    else:
        resp = requests.post(url, headers=headers, data=data, timeout=15)
    return resp.json()


def _get_or_create_stripe_customer(tenant_id: str, email: str, name: str = "") -> str:
    """Get existing Stripe customer ID or create one."""
    # Search for existing customer by email
    result = _stripe_request("GET", "/customers", {"email": email, "limit": 1})
    customers = result.get("data", [])
    if customers:
        return customers[0]["id"]

    # Create new customer
    customer_data = {"email": email, "metadata[tenant_id]": tenant_id}
    if name:
        customer_data["name"] = name
    result = _stripe_request("POST", "/customers", customer_data)
    return result.get("id", "")


def create_checkout_session(tenant_id: str, email: str, plan: str,
                            billing: str = "monthly", name: str = "",
                            success_url: str = None, cancel_url: str = None) -> dict:
    """Create a Stripe Checkout session for upgrading.

    Args:
        tenant_id: The tenant upgrading
        email: Tenant email
        plan: "pro", "business", or "scale"
        billing: "monthly" or "annual"
        name: Customer name
        success_url: Redirect after successful payment
        cancel_url: Redirect if cancelled
    """
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}

    price_key = f"{plan}_{billing}"
    price_id = PRICE_MAP.get(price_key)
    if not price_id:
        return {"error": f"Invalid plan/billing combination: {plan}/{billing}"}

    customer_id = _get_or_create_stripe_customer(tenant_id, email, name)
    if not customer_id:
        return {"error": "Failed to create Stripe customer"}

    default_success = "https://octopodas.com/dashboard?upgraded=true"
    default_cancel = "https://octopodas.com/pricing"

    session_data = {
        "customer": customer_id,
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": success_url or default_success,
        "cancel_url": cancel_url or default_cancel,
        "metadata[tenant_id]": tenant_id,
        "metadata[plan]": plan,
        "subscription_data[metadata][tenant_id]": tenant_id,
        "subscription_data[metadata][plan]": plan,
    }
    result = _stripe_request("POST", "/checkout/sessions", session_data)

    if "url" in result:
        return {"checkout_url": result["url"], "session_id": result["id"]}
    return {"error": result.get("error", {}).get("message", "Checkout creation failed")}


def create_portal_session(tenant_id: str, email: str) -> dict:
    """Create a Stripe Customer Portal session for managing subscription."""
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}

    customer_id = _get_or_create_stripe_customer(tenant_id, email)
    if not customer_id:
        return {"error": "No Stripe customer found"}

    result = _stripe_request("POST", "/billing_portal/sessions", {
        "customer": customer_id,
        "return_url": "https://octopodas.com/dashboard",
    })

    if "url" in result:
        return {"portal_url": result["url"]}
    return {"error": result.get("error", {}).get("message", "Portal creation failed")}


def get_subscription_status(tenant_id: str, email: str) -> dict:
    """Get current subscription status for a tenant."""
    if not STRIPE_SECRET_KEY:
        return {"plan": "free", "stripe_configured": False}

    # Find customer
    result = _stripe_request("GET", "/customers", {"email": email, "limit": 1})
    customers = result.get("data", [])
    if not customers:
        return {"plan": "free", "has_subscription": False}

    customer_id = customers[0]["id"]

    # Get active subscriptions
    subs = _stripe_request("GET", "/subscriptions", {
        "customer": customer_id,
        "status": "active",
        "limit": 1,
    })
    sub_list = subs.get("data", [])
    if not sub_list:
        # Check for past_due (grace period)
        subs = _stripe_request("GET", "/subscriptions", {
            "customer": customer_id,
            "status": "past_due",
            "limit": 1,
        })
        sub_list = subs.get("data", [])

    if not sub_list:
        return {"plan": "free", "has_subscription": False}

    sub = sub_list[0]
    price_id = sub.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")
    plan = sub.get("metadata", {}).get("plan", _price_to_plan(price_id))

    return {
        "plan": plan,
        "has_subscription": True,
        "status": sub["status"],
        "current_period_end": sub.get("current_period_end"),
        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
        "subscription_id": sub["id"],
        "customer_id": customer_id,
    }


def handle_webhook_event(payload: bytes, signature: str) -> dict:
    """Handle a Stripe webhook event.

    Verifies signature and processes subscription changes.
    Returns action taken.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("No webhook secret configured, skipping signature verification")
        import json
        event = json.loads(payload)
    else:
        # Verify webhook signature
        event = _verify_webhook_signature(payload, signature)
        if not event:
            return {"error": "Invalid webhook signature"}

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(data)
    elif event_type == "customer.subscription.updated":
        return _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(data)
    elif event_type == "invoice.payment_failed":
        return _handle_payment_failed(data)
    else:
        return {"handled": False, "event_type": event_type}


def _verify_webhook_signature(payload: bytes, signature: str) -> dict:
    """Verify Stripe webhook signature."""
    import json
    if not signature:
        logger.warning("Webhook called without Stripe-Signature header")
        return None
    try:
        # Parse the Stripe-Signature header (format: t=...,v1=...)
        elements = {}
        for item in signature.split(","):
            if "=" not in item:
                continue
            k, v = item.split("=", 1)
            elements[k.strip()] = v.strip()
        timestamp = elements.get("t", "")
        expected_sig = elements.get("v1", "")
        if not timestamp or not expected_sig:
            logger.warning("Webhook signature missing t= or v1= component")
            return None

        # Compute expected signature
        signed_payload = f"{timestamp}.".encode() + payload
        computed = hmac.new(
            STRIPE_WEBHOOK_SECRET.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(computed, expected_sig):
            logger.error("Webhook signature mismatch")
            return None

        # Check timestamp (reject events older than 5 minutes)
        if abs(time.time() - int(timestamp)) > 300:
            logger.error("Webhook timestamp too old")
            return None

        return json.loads(payload)
    except Exception as e:
        logger.error("Webhook verification error: %s", e)
        return None


def _send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend. Returns True on success."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email to %s (subject: %s)", to, subject)
        return False
    try:
        import requests as _req
        resp = _req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": [to], "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            logger.error("Resend send failed to %s: %s %s", to, resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        logger.error("Email send exception to %s: %s", to, e)
        return False


def _lookup_tenant(tenant_id: str = None, customer_id: str = None) -> dict:
    """Look up tenant email + plan by tenant_id OR stripe_customer_id."""
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        conn = tm._conn()
        try:
            cur = conn.cursor()
            if tenant_id:
                cur.execute("SELECT tenant_id, email, first_name, plan FROM tenants WHERE tenant_id=%s",
                            (tenant_id,))
            elif customer_id:
                cur.execute("SELECT tenant_id, email, first_name, plan FROM tenants WHERE stripe_customer_id=%s",
                            (customer_id,))
            else:
                return {}
            row = cur.fetchone()
            if not row:
                return {}
            return {"tenant_id": row[0], "email": row[1],
                    "first_name": row[2] or "", "plan": row[3] or "free"}
        finally:
            tm._release(conn)
    except Exception as e:
        logger.error("tenant lookup failed: %s", e)
        return {}


def _plan_display(plan: str) -> str:
    return {"pro": "Pro", "business": "Business", "scale": "Scale",
            "enterprise": "Enterprise", "free": "Free"}.get(plan, plan.title())


def _email_shell(title: str, body_html: str) -> str:
    return f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:40px 20px;">
  <div style="text-align:center;margin-bottom:24px;">
    <h1 style="color:#1a1a2e;font-size:22px;margin:0;">🐙 Octopoda</h1>
    <p style="color:#666;font-size:13px;margin:4px 0 0;">Agent Memory Infrastructure</p>
  </div>
  <div style="background:#f8f9fa;border-radius:12px;padding:28px;">
    <h2 style="color:#1a1a2e;font-size:18px;margin:0 0 12px;">{title}</h2>
    {body_html}
  </div>
  <p style="color:#999;font-size:12px;text-align:center;margin:20px 0 0;">
    Questions? Reply to this email or message joe@octopodas.com.
  </p>
</div>
"""


def _send_customer_welcome(email: str, first_name: str, plan: str):
    """Email the customer after a successful upgrade."""
    if not email:
        return
    name = f" {first_name}" if first_name else ""
    plan_name = _plan_display(plan)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    max_agents, max_memories, *_ = limits
    agents_str = "unlimited" if max_agents is None else f"{max_agents:,}"
    mem_str = "unlimited" if max_memories is None else f"{max_memories:,}"
    body = f"""
    <p style="color:#333;font-size:15px;margin:0 0 14px;">Hey{name}, your <strong>Octopoda {plan_name}</strong> plan is active.</p>
    <p style="color:#555;font-size:14px;margin:0 0 14px;">You can now run up to <strong>{agents_str} agents</strong> and store up to <strong>{mem_str} memories</strong>. Everything on your account has been upgraded immediately — no restart needed.</p>
    <p style="color:#555;font-size:14px;margin:0 0 18px;">Manage your subscription, update payment method or download invoices any time from the billing portal in your dashboard.</p>
    <a href="https://octopodas.com/dashboard" style="display:inline-block;background:#1a1a2e;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;font-size:14px;font-weight:600;">Open dashboard →</a>
    """
    _send_email(email, f"Welcome to Octopoda {plan_name}", _email_shell(f"Welcome to {plan_name} 🎉", body))


def _send_customer_cancel_confirm(email: str, first_name: str, prior_plan: str):
    """Email the customer after they cancel (downgrade to free)."""
    if not email:
        return
    name = f" {first_name}" if first_name else ""
    body = f"""
    <p style="color:#333;font-size:15px;margin:0 0 14px;">Hey{name}, your Octopoda {_plan_display(prior_plan)} subscription has been cancelled.</p>
    <p style="color:#555;font-size:14px;margin:0 0 14px;">You've been moved back to the free tier. <strong>Your data is safe</strong> — all agents and memories are preserved. You just won't be able to create new ones above the free-tier limits (5 agents, 5K memories) until you resubscribe.</p>
    <p style="color:#555;font-size:14px;margin:0 0 14px;">If there's a reason you're leaving — a missing feature, a bug, or just wrong-shaped — I'd genuinely love to hear it. Reply to this email.</p>
    <a href="https://octopodas.com/pricing" style="display:inline-block;background:#1a1a2e;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;font-size:14px;font-weight:600;">Resubscribe →</a>
    """
    _send_email(email, "Your Octopoda subscription was cancelled",
                _email_shell("Sorry to see you go", body))


def _send_customer_payment_failed(email: str, first_name: str):
    """Email the customer when a card charge fails."""
    if not email:
        return
    name = f" {first_name}" if first_name else ""
    body = f"""
    <p style="color:#333;font-size:15px;margin:0 0 14px;">Hey{name}, we couldn't charge your card for your Octopoda subscription.</p>
    <p style="color:#555;font-size:14px;margin:0 0 14px;">Stripe will retry automatically over the next 7 days. To avoid any interruption, update your payment method in the billing portal.</p>
    <p style="color:#555;font-size:14px;margin:0 0 18px;">If payment isn't resolved within 7 days your account will revert to the free tier. Your data stays safe regardless.</p>
    <a href="https://octopodas.com/dashboard" style="display:inline-block;background:#b45309;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;font-size:14px;font-weight:600;">Update payment method →</a>
    """
    _send_email(email, "Action needed: Octopoda payment failed",
                _email_shell("Your payment didn't go through", body))


def _notify_owner(event: str, tenant_email: str, plan: str,
                  tenant_id: str = "", extra: str = ""):
    """Email Joe when something important happens in billing."""
    if not OWNER_NOTIFICATION_EMAIL:
        return
    plan_name = _plan_display(plan)
    subject_map = {
        "upgraded":  f"💸 New {plan_name} customer: {tenant_email}",
        "updated":   f"🔄 Plan changed to {plan_name}: {tenant_email}",
        "cancelled": f"❌ Cancelled ({plan_name}): {tenant_email}",
        "failed":    f"⚠️ Payment failed: {tenant_email}",
    }
    subject = subject_map.get(event, f"Billing event ({event}): {tenant_email}")
    body = f"""
    <p style="color:#333;font-size:15px;margin:0 0 12px;"><strong>{event.upper()}</strong></p>
    <table style="width:100%;font-size:14px;color:#333;">
      <tr><td style="padding:4px 0;color:#666;">Tenant</td><td>{tenant_email}</td></tr>
      <tr><td style="padding:4px 0;color:#666;">Tenant ID</td><td style="font-family:monospace;font-size:12px;">{tenant_id}</td></tr>
      <tr><td style="padding:4px 0;color:#666;">Plan</td><td>{plan_name}</td></tr>
      {('<tr><td style="padding:4px 0;color:#666;">Detail</td><td>' + extra + '</td></tr>') if extra else ''}
      <tr><td style="padding:4px 0;color:#666;">Time</td><td>{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</td></tr>
    </table>
    """
    _send_email(OWNER_NOTIFICATION_EMAIL, subject,
                _email_shell("Octopoda billing event", body))


def _handle_checkout_completed(session: dict) -> dict:
    """Handle successful checkout — upgrade tenant plan + send emails."""
    tenant_id = session.get("metadata", {}).get("tenant_id", "")
    plan = session.get("metadata", {}).get("plan", "")
    customer_id = session.get("customer", "")
    subscription_id = session.get("subscription", "")

    if not tenant_id or not plan:
        logger.warning("Checkout completed but missing tenant_id or plan in metadata")
        return {"error": "Missing metadata"}

    # Upgrade DB
    _upgrade_tenant(tenant_id, plan, customer_id, subscription_id)
    logger.info("Tenant %s upgraded to %s", tenant_id, plan)

    # Email flow (best-effort, never break the webhook response)
    try:
        t = _lookup_tenant(tenant_id=tenant_id)
        if t.get("email"):
            _send_customer_welcome(t["email"], t.get("first_name", ""), plan)
            _notify_owner("upgraded", t["email"], plan, tenant_id)
    except Exception as e:
        logger.error("Post-upgrade email flow failed for %s: %s", tenant_id, e)

    return {"action": "upgraded", "tenant_id": tenant_id, "plan": plan}


def _handle_subscription_updated(subscription: dict) -> dict:
    """Handle subscription change (upgrade/downgrade)."""
    tenant_id = subscription.get("metadata", {}).get("tenant_id", "")
    if not tenant_id:
        return {"handled": False, "reason": "no tenant_id in metadata"}

    price_id = subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")
    new_plan = subscription.get("metadata", {}).get("plan", _price_to_plan(price_id))

    _upgrade_tenant(tenant_id, new_plan)
    logger.info("Tenant %s subscription updated to %s", tenant_id, new_plan)

    try:
        t = _lookup_tenant(tenant_id=tenant_id)
        if t.get("email"):
            _notify_owner("updated", t["email"], new_plan, tenant_id)
    except Exception as e:
        logger.error("Post-update notify failed for %s: %s", tenant_id, e)

    return {"action": "plan_updated", "tenant_id": tenant_id, "plan": new_plan}


def _handle_subscription_deleted(subscription: dict) -> dict:
    """Handle subscription cancellation — downgrade to free.

    IMPORTANT: Does NOT delete agents or memories. Just blocks new creation
    beyond free tier limits.
    """
    tenant_id = subscription.get("metadata", {}).get("tenant_id", "")
    if not tenant_id:
        return {"handled": False, "reason": "no tenant_id in metadata"}

    # Capture prior plan BEFORE downgrade so the email can mention it
    t = _lookup_tenant(tenant_id=tenant_id) or {}
    prior_plan = t.get("plan", "pro")

    _upgrade_tenant(tenant_id, "free")
    logger.info("Tenant %s downgraded to free (subscription cancelled)", tenant_id)

    try:
        if t.get("email"):
            _send_customer_cancel_confirm(t["email"], t.get("first_name", ""), prior_plan)
            _notify_owner("cancelled", t["email"], prior_plan, tenant_id)
    except Exception as e:
        logger.error("Post-cancel email flow failed for %s: %s", tenant_id, e)

    return {"action": "downgraded", "tenant_id": tenant_id, "plan": "free"}


def _handle_payment_failed(invoice: dict) -> dict:
    """Handle failed payment — warn customer + notify owner, don't downgrade.

    Grace period: 7 days. Stripe retries automatically.
    """
    customer_id = invoice.get("customer", "")
    amount_due = invoice.get("amount_due", 0) / 100.0
    currency = (invoice.get("currency") or "usd").upper()
    logger.warning("Payment failed for customer %s (amount=%.2f %s) — Stripe will retry",
                   customer_id, amount_due, currency)

    try:
        t = _lookup_tenant(customer_id=customer_id)
        if t.get("email"):
            _send_customer_payment_failed(t["email"], t.get("first_name", ""))
            _notify_owner("failed", t["email"], t.get("plan", "?"),
                          t.get("tenant_id", ""),
                          extra=f"{currency} {amount_due:.2f} charge declined")
    except Exception as e:
        logger.error("Payment-failed email flow failed for customer %s: %s", customer_id, e)

    return {"action": "payment_failed_warning", "customer_id": customer_id}


def _upgrade_tenant(tenant_id: str, plan: str,
                    customer_id: str = None, subscription_id: str = None):
    """Update tenant plan and limits in the database."""
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    max_agents, max_memories, max_extractions, rate_limit = limits

    # Use None as "unlimited" — set to very high number in DB
    if max_agents is None:
        max_agents = 999999
    if max_memories is None:
        max_memories = 999999999

    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        conn = tm._conn()
        try:
            cur = conn.cursor()
            update_fields = [
                "plan = %s",
                "max_agents = %s",
                "max_memories = %s",
            ]
            params = [plan, max_agents, max_memories]

            if customer_id:
                update_fields.append("stripe_customer_id = %s")
                params.append(customer_id)
            if subscription_id:
                update_fields.append("stripe_subscription_id = %s")
                params.append(subscription_id)

            params.append(tenant_id)
            sql = f"UPDATE tenants SET {', '.join(update_fields)} WHERE tenant_id = %s"
            cur.execute(sql, params)
            conn.commit()
            logger.info("Tenant %s updated: plan=%s agents=%s memories=%s",
                       tenant_id, plan, max_agents, max_memories)
        finally:
            tm._release(conn)
    except Exception as e:
        logger.error("Failed to upgrade tenant %s: %s", tenant_id, e)


def get_plans() -> list:
    """Return available plans with pricing info."""
    return [
        {
            "name": "Free",
            "slug": "free",
            "price_monthly": 0,
            "price_annual": 0,
            "agents": 5,
            "memories": 5000,
            "ai_extractions": 100,
            "features": ["5 agents", "5K memories", "100 AI extractions",
                        "Basic loop detection", "1 shared space", "Community support"],
        },
        {
            "name": "Pro",
            "slug": "pro",
            "price_monthly": 19,
            "price_annual": 182,
            "stripe_monthly": PRICE_MAP.get("pro_monthly", ""),
            "stripe_annual": PRICE_MAP.get("pro_annual", ""),
            "agents": 25,
            "memories": 250000,
            "ai_extractions": 10000,
            "features": ["25 agents", "250K memories", "10K AI extractions/mo",
                        "Full loop detection v2", "5 shared spaces", "Export/import",
                        "Email support (48hr)"],
        },
        {
            "name": "Business",
            "slug": "business",
            "price_monthly": 49,
            "price_annual": 470,
            "stripe_monthly": PRICE_MAP.get("business_monthly", ""),
            "stripe_annual": PRICE_MAP.get("business_annual", ""),
            "agents": 75,
            "memories": 1000000,
            "ai_extractions": 50000,
            "features": ["75 agents", "1M memories", "50K AI extractions/mo",
                        "Full loop detection v2", "25 shared spaces", "Export/import",
                        "10 team members", "Priority support (12hr)", "99.5% SLA"],
        },
        {
            "name": "Scale",
            "slug": "scale",
            "price_monthly": 99,
            "price_annual": 950,
            "stripe_monthly": PRICE_MAP.get("scale_monthly", ""),
            "stripe_annual": PRICE_MAP.get("scale_annual", ""),
            "agents": "Unlimited",
            "memories": 5000000,
            "ai_extractions": "Unlimited",
            "features": ["Unlimited agents", "5M memories", "Unlimited AI extractions",
                        "Full loop detection v2 + alerts", "Unlimited shared spaces",
                        "Export/import", "25 team members", "Priority support (4hr)",
                        "99.9% SLA", "Webhooks unlimited"],
        },
        {
            "name": "Enterprise",
            "slug": "enterprise",
            "price_monthly": "Custom",
            "price_annual": "Custom",
            "agents": "Unlimited",
            "memories": "Unlimited",
            "ai_extractions": "Unlimited",
            "features": ["Everything in Scale", "Unlimited everything",
                        "Dedicated support", "99.99% SLA", "SSO/SAML",
                        "Custom integrations", "On-premise option"],
        },
    ]
