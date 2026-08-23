import logging
from typing import Any, Dict, Optional
import stripe

from b2b_leadgen.config import settings

logger = logging.getLogger(__name__)


def get_stripe_key(explicit_key: Optional[str] = None) -> Optional[str]:
    """Retrieves the effective Stripe secret key from arguments, settings, or Streamlit secrets."""
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()

    if settings.effective_stripe_key:
        return settings.effective_stripe_key

    try:
        import streamlit as st
        if "STRIPE_SECRET_KEY" in st.secrets:
            return st.secrets["STRIPE_SECRET_KEY"]
    except Exception:
        pass

    return None


def create_checkout_session(
    success_url: str,
    cancel_url: str,
    amount_usd: int = 300,
    product_name: str = "B2B Enriched Leads Package",
    api_key: Optional[str] = None,
    client_reference_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a Stripe Checkout Session for $300 lead package using the official Stripe Python SDK.
    Returns session id and checkout redirect URL.
    """
    key = get_stripe_key(api_key)
    if not key:
        raise ValueError(
            "Stripe Secret Key not found. Please provide a valid Stripe key (e.g. sk_test_... or sk_live_...)."
        )

    stripe.api_key = key

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(amount_usd * 100),  # In cents: 30000 = $300.00
                        "product_data": {
                            "name": product_name,
                            "description": "Unlock instant download access for verified B2B contact emails, full company summaries, and AI personalized cold pitches.",
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=client_reference_id
        )

        return {
            "success": True,
            "session_id": session.id,
            "checkout_url": session.url
        }
    except Exception as e:
        logger.error(f"Failed to create Stripe Checkout session: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def verify_checkout_session(session_id: str, api_key: Optional[str] = None) -> bool:
    """
    Verifies with Stripe API whether the checkout session was successfully paid.
    """
    if not session_id or not session_id.strip():
        return False

    key = get_stripe_key(api_key)
    if not key:
        logger.warning("Stripe key not found for verification.")
        return False

    stripe.api_key = key

    try:
        session = stripe.checkout.Session.retrieve(session_id.strip())
        is_paid = (session.payment_status == "paid")
        logger.info(f"Stripe session {session_id} payment_status: {session.payment_status} (paid={is_paid})")
        return is_paid
    except Exception as e:
        logger.error(f"Error retrieving Stripe session {session_id}: {e}")
        return False
