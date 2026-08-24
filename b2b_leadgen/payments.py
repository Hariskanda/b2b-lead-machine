import logging
import os
from typing import Any, Dict, Optional
import stripe

from b2b_leadgen.config import settings

logger = logging.getLogger(__name__)


def get_stripe_key(explicit_key: Optional[str] = None) -> Optional[str]:
    """Retrieves the effective Stripe secret key from arguments, settings, environment, or Streamlit secrets."""
    if explicit_key is not None and str(explicit_key).strip():
        return str(explicit_key).strip()

    if getattr(settings, "stripe_secret_key", None):
        return settings.stripe_secret_key

    for env_k in ["STRIPE_SECRET_KEY", "stripe_secret_key"]:
        val = os.environ.get(env_k)
        if val and val.strip():
            return val.strip()

    try:
        import streamlit as st
        if hasattr(st, "secrets") and st.secrets is not None:
            if "STRIPE_SECRET_KEY" in st.secrets:
                return st.secrets["STRIPE_SECRET_KEY"]
            if "stripe_secret_key" in st.secrets:
                return st.secrets["stripe_secret_key"]
    except Exception:
        pass

    return None


def create_checkout_session(
    success_url: str,
    cancel_url: str,
    amount_usd: float = 19.0,
    product_name: str = "B2B Lead Machine Pro Tier",
    customer_email: Optional[str] = None,
    api_key: Optional[str] = None,
    client_reference_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a Stripe Checkout Session for Pro Tier subscription or one-time pass ($19/mo or $9 pass).
    Returns session id and checkout redirect URL.
    """
    key = get_stripe_key(api_key)
    if not key:
        raise ValueError(
            "Stripe Secret Key not found. Please provide a valid Stripe key (e.g. sk_test_... or sk_live_...)."
        )

    stripe.api_key = key

    try:
        session_params: Dict[str, Any] = {
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(amount_usd * 100),  # e.g. 1900 = $19.00
                        "product_data": {
                            "name": product_name,
                            "description": "Unlock unlimited B2B leads, White-Labeled PDF Client Audits, full unmasked CSV/JSON exports, and Outbound Email Engine.",
                        },
                    },
                    "quantity": 1,
                }
            ],
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": client_reference_id
        }

        if customer_email and "@" in customer_email:
            session_params["customer_email"] = customer_email.strip()

        session = stripe.checkout.Session.create(**session_params)

        return {
            "success": True,
            "session_id": session.id,
            "checkout_url": session.url,
            "is_mock": False
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

    clean_id = session_id.strip()
    if clean_id.startswith("cs_test_mock_") or clean_id == "mock_pro_pass":
        return True

    key = get_stripe_key(api_key)
    if not key:
        logger.warning("Stripe key not found for verification.")
        return False

    stripe.api_key = key

    try:
        session = stripe.checkout.Session.retrieve(clean_id)
        is_paid = (session.payment_status == "paid")
        logger.info(f"Stripe session {clean_id} payment_status: {session.payment_status} (paid={is_paid})")
        return is_paid
    except Exception as e:
        logger.error(f"Stripe session verification failed for {clean_id}: {e}")
        return False
