import logging
from typing import Any, Dict, Optional
import httpx

from b2b_leadgen.config import settings

logger = logging.getLogger(__name__)

NOWPAYMENTS_API_BASE = "https://api.nowpayments.io/v1"


def get_nowpayments_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """Generates standard headers for NOWPayments API requests."""
    key = api_key or settings.effective_nowpayments_key or ""
    return {
        "x-api-key": key.strip(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def create_nowpayments_invoice(
    api_key: str,
    price_amount: float = 6.0,
    price_currency: str = "usd",
    order_id: Optional[str] = None,
    order_description: str = "B2B Lead Machine - Verified Leads Export",
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a zero-KYC crypto payment invoice via NOWPayments API.
    Returns the parsed response dictionary containing 'invoice_url' and 'id'.
    """
    if not api_key:
        return {
            "success": False,
            "error": "NOWPAYMENTS_API_KEY is not configured."
        }

    url = f"{NOWPAYMENTS_API_BASE}/invoice"
    payload = {
        "price_amount": float(price_amount),
        "price_currency": price_currency.lower(),
        "order_description": order_description
    }
    if order_id:
        payload["order_id"] = str(order_id)
    if success_url:
        payload["success_url"] = success_url
    if cancel_url:
        payload["cancel_url"] = cancel_url

    headers = get_nowpayments_headers(api_key)

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code in (200, 201):
                data = response.json()
                return {
                    "success": True,
                    "invoice_id": str(data.get("id", "")),
                    "invoice_url": data.get("invoice_url"),
                    "price_amount": data.get("price_amount", price_amount),
                    "price_currency": data.get("price_currency", price_currency),
                    "raw": data
                }
            else:
                err_msg = f"NOWPayments API Error ({response.status_code}): {response.text}"
                logger.error(err_msg)
                return {
                    "success": False,
                    "error": err_msg
                }
    except Exception as e:
        err_msg = f"Failed to connect to NOWPayments API: {e}"
        logger.error(err_msg)
        return {
            "success": False,
            "error": err_msg
        }


def check_nowpayments_invoice_status(
    api_key: str,
    invoice_id: str
) -> Dict[str, Any]:
    """
    Queries the invoice status from https://api.nowpayments.io/v1/invoice/{invoice_id}
    using the generated Invoice ID and verifies if the status is 'finished' or 'confirmed'.
    """
    if not api_key or not invoice_id:
        return {
            "success": False,
            "error": "API Key and Invoice ID are required."
        }

    clean_id = invoice_id.strip()
    headers = get_nowpayments_headers(api_key)
    url = f"{NOWPAYMENTS_API_BASE}/invoice/{clean_id}"

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                status = str(data.get("payment_status") or data.get("status") or data.get("invoice_status") or "waiting").lower()
                is_completed = status in ("finished", "confirmed", "sending", "success", "paid")
                return {
                    "success": True,
                    "status": status,
                    "is_completed": is_completed,
                    "raw": data
                }

            # Fallback check on payment endpoint if invoice endpoint returns non-200
            pay_url = f"{NOWPAYMENTS_API_BASE}/payment/{clean_id}"
            pay_resp = client.get(pay_url, headers=headers)
            if pay_resp.status_code == 200:
                pay_data = pay_resp.json()
                status = str(pay_data.get("payment_status") or "waiting").lower()
                is_completed = status in ("finished", "confirmed", "sending", "success", "paid")
                return {
                    "success": True,
                    "status": status,
                    "is_completed": is_completed,
                    "raw": pay_data
                }

            return {
                "success": False,
                "error": f"Invoice lookup failed (HTTP {response.status_code}): {response.text}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def check_nowpayments_payment_status(
    api_key: str,
    payment_id: str
) -> Dict[str, Any]:
    """
    Checks the status of a specific payment ID on the blockchain.
    """
    return check_nowpayments_invoice_status(api_key=api_key, invoice_id=payment_id)


def check_nowpayments_api_health(api_key: Optional[str] = None) -> bool:
    """Checks if NOWPayments API is reachable."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{NOWPAYMENTS_API_BASE}/status")
            return resp.status_code == 200
    except Exception:
        return False
