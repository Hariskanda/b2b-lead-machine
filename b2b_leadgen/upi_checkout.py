import io
import os
import re
from typing import Optional, Tuple, Union
import urllib.parse
from PIL import Image
import qrcode


def generate_upi_uri(
    upi_id: str = "9019525230@fam",
    payee_name: str = "B2BLeadMachine",
    amount_inr: Union[int, float] = 499,
    transaction_note: str = "LeadExport499"
) -> str:
    """
    Generates a universal UPI intent URI according to NPCI specifications.
    Format: upi://pay?pa=9019525230@fam&pn=B2BLeadMachine&am=499&cu=INR&tn=LeadExport499
    """
    clean_amount = int(amount_inr) if int(amount_inr) == amount_inr else f"{amount_inr:.2f}"
    params = {
        "pa": upi_id.strip(),
        "pn": payee_name.strip(),
        "am": str(clean_amount),
        "cu": "INR",
        "tn": transaction_note.strip()
    }
    encoded_query = urllib.parse.urlencode(params)
    return f"upi://pay?{encoded_query}"


def generate_upi_qr_code(
    upi_id: str = "9019525230@fam",
    payee_name: str = "B2BLeadMachine",
    amount_inr: Union[int, float] = 499,
    transaction_note: str = "LeadExport499",
    custom_qr_path: Optional[str] = "assets/upi_qr.png",
    box_size: int = 10,
    border: int = 2
) -> Tuple[Union[Image.Image, str], io.BytesIO, str]:
    """
    Returns the custom branded QR code image if available, or dynamically generates a QR code from the universal UPI intent URI.
    Returns (PIL Image, BytesIO buffer, URI string).
    """
    upi_uri = generate_upi_uri(
        upi_id=upi_id,
        payee_name=payee_name,
        amount_inr=amount_inr,
        transaction_note=transaction_note
    )

    if custom_qr_path and os.path.exists(custom_qr_path):
        try:
            img = Image.open(custom_qr_path)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return img, buf, upi_uri
        except Exception:
            pass

    # Dynamic fallback QR generator
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(upi_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff").convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return img, buf, upi_uri


def validate_utr(utr: str) -> bool:
    """
    Validates that a UTR / UPI Transaction Reference is a valid 12-digit numeric identifier.
    """
    if not utr:
        return False
    clean_utr = utr.strip()
    return bool(re.match(r'^\d{12}$', clean_utr))
