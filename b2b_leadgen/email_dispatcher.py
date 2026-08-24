import logging
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Tuple

from b2b_leadgen.config import settings
from b2b_leadgen.history import sent_history
from b2b_leadgen.models import EnrichedLead

logger = logging.getLogger(__name__)

# Known library/framework artifact names before @
JUNK_PREFIXES = {
    "bootstrap", "splide", "jquery", "swiper", "vue", "react", "core-js",
    "lodash", "popper", "fontawesome", "font-awesome", "modernizr",
    "webpack", "babel", "angular", "gsap", "chartjs", "chart", "select2",
    "moment", "axios", "normalize", "animate", "slick", "fancybox",
    "magnific-popup", "owl.carousel", "owl-carousel", "lightbox",
    "dummy", "placeholder", "yourname", "user", "username", "test",
    "sentry", "git", "npm", "node_modules", "wixpress", "sentry-cdn"
}

# Invalid extension endings
INVALID_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".js", ".css", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".mp3", ".pdf", ".zip", ".json", ".xml"
)

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


def is_valid_business_email(email: Optional[str]) -> Tuple[bool, str]:
    """
    Strictly validates whether an email is a legitimate business contact email,
    filtering out library version tags (e.g. bootstrap@4.6.0, splide@4.1.4),
    image asset extensions, dummy placeholders, and code artifacts.
    Returns (is_valid, reason).
    """
    if not email or not isinstance(email, str):
        return False, "Empty or non-string email"

    clean = email.strip().lower().rstrip(".,;:/")

    if len(clean) < 6 or len(clean) > 100:
        return False, f"Invalid length ({len(clean)} chars)"

    if "@" not in clean or clean.count("@") != 1:
        return False, "Malformed email structure (must contain exactly one @)"

    user_part, domain_part = clean.split("@")

    if not user_part or not domain_part:
        return False, "Missing user or domain part"

    # 1. Reject code library artifacts before @
    if user_part in JUNK_PREFIXES:
        return False, f"Code library artifact detected: '{user_part}'"

    # 2. Reject domain parts that look like semver version numbers (e.g. @4.6.0, @1.2.3, @4.1.4)
    if re.match(r"^v?\d+(\.\d+)+$", domain_part):
        return False, f"Version number artifact detected: '@{domain_part}'"

    # 3. Reject file extension artifacts (.png, .jpg, .js, .css, etc.)
    if domain_part.endswith(INVALID_EXTENSIONS) or any(clean.endswith(ext) for ext in INVALID_EXTENSIONS):
        return False, f"Image or asset extension in email: '@{domain_part}'"

    # 4. Check standard regex structure
    if not EMAIL_REGEX.match(clean):
        return False, "Failed standard email RFC regex validation"

    # 5. Validate TLD (must be letters, length >= 2, e.g. .com, .org, .co, .io)
    parts = domain_part.split(".")
    tld = parts[-1]
    if not tld.isalpha() or len(tld) < 2:
        return False, f"Invalid domain TLD: '.{tld}'"

    # 6. Reject common placeholder domains
    if domain_part in ("domain.com", "example.com", "test.com", "yoursite.com", "company.com", "email.com"):
        return False, f"Placeholder domain: '{domain_part}'"

    return True, "Valid"


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """Safely retrieves an attribute from either an object or a dictionary."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_outreach_email(
    lead: Any,
    app_url: Optional[str] = None,
    sender_name: Optional[str] = None,
    price_usd: float = 0.0,
    **kwargs: Any
) -> Tuple[str, str, str]:
    """
    Builds the personalized cold outreach email for a company directing them
    to the verified lead intelligence dataset portal with instant free CSV access.
    Returns (subject, html_body, plain_text_body).
    """
    company_name = _get_attr(lead, "company_name") or "there"
    pitch = (
        _get_attr(lead, "personalized_pitch")
        or f"I came across {company_name} and was very impressed by your service offerings. We help businesses in your space streamline lead acquisition and client operations."
    )
    effective_url = (app_url or getattr(settings, "effective_app_url", "http://localhost:8501") or "http://localhost:8501").rstrip("/")
    effective_name = sender_name or getattr(settings, "sender_name", "B2B Lead Machine")

    subject = f"Growth opportunity for {company_name}"

    plain_text = f"""Hi {company_name} Team,

{pitch}

We have compiled a verified, real-time database of high-intent B2B prospects and target decision-makers in your market. You can explore the live dataset directly on our portal:
👉 {effective_url}

(Instant free dataset preview & full CSV download available on the portal).

Best regards,
{effective_name}
Automated Outbound Intelligence
{effective_url}
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: #1e293b;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            background-color: #f8fafc;
        }}
        .container {{
            max-width: 600px;
            margin: 20px auto;
            background: #ffffff;
            border-radius: 12px;
            border: 1px solid #e2e8f0;
            overflow: hidden;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
        }}
        .header {{
            background: linear-gradient(135deg, #2563eb, #4f46e5);
            color: #ffffff;
            padding: 24px;
            text-align: center;
        }}
        .content {{
            padding: 28px;
        }}
        .pitch-box {{
            background: #f1f5f9;
            border-left: 4px solid #3b82f6;
            padding: 16px;
            border-radius: 6px;
            margin: 18px 0;
            font-size: 15px;
            color: #0f172a;
        }}
        .cta-button {{
            display: inline-block;
            background-color: #2563eb;
            color: #ffffff !important;
            text-decoration: none;
            padding: 14px 28px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 15px;
            margin: 20px 0;
            text-align: center;
        }}
        .footer {{
            background: #f8fafc;
            padding: 18px;
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
            border-top: 1px solid #e2e8f0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0; font-weight: 700;">Opportunity for {company_name}</h2>
        </div>
        <div class="content">
            <p>Hi <strong>{company_name} Team</strong>,</p>
            
            <div class="pitch-box">
                {pitch}
            </div>

            <p>We've built an autonomous lead intelligence system that continuously tracks and verifies targeted business contacts and prospect data in your niche.</p>
            
            <p style="text-align: center;">
                <a href="{effective_url}" class="cta-button" target="_blank">
                    ⚡ View Verified Lead List & Download CSV
                </a>
            </p>

            <p style="font-size: 13px; color: #64748b; text-align: center;">
                ✨ <em>Free instant access & full CSV download available on portal.</em>
            </p>

            <p>Best regards,<br>
            <strong>{effective_name}</strong><br>
            <span style="color: #64748b; font-size: 13px;">B2B Lead Machine Outbound System</span></p>
        </div>
        <div class="footer">
            Sent via B2B Lead Machine Outbound Dispatcher • <a href="{effective_url}" style="color: #64748b;">Visit App</a>
        </div>
    </div>
</body>
</html>
"""

    return subject, html_body, plain_text


def _connect_smtp_server(
    host: str,
    port: int,
    user: str,
    password: str
) -> smtplib.SMTP:
    """
    Initializes and connects to the SMTP server with TLS/SSL negotiation and authentication.
    Resolves 'please run connect() first' by ensuring full connection setup before return.
    """
    clean_password = password.replace(" ", "").strip()
    logger.info(f"Connecting to SMTP server at {host}:{port}...")

    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
        server.ehlo()
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()

    server.login(user, clean_password)
    logger.info(f"Successfully authenticated SMTP session for {user}")
    return server


def send_single_email(
    server: smtplib.SMTP,
    sender_email: str,
    recipient_email: str,
    subject: str,
    html_body: str,
    plain_text: str,
    sender_name: str = "B2B Lead Machine",
    **kwargs: Any
) -> bool:
    """Sends a single multipart email using an existing active SMTP session."""
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject

    part1 = MIMEText(plain_text, "plain", "utf-8")
    part2 = MIMEText(html_body, "html", "utf-8")
    msg.attach(part1)
    msg.attach(part2)

    server.sendmail(sender_email, [recipient_email], msg.as_string())
    return True


def dispatch_campaign(
    leads: List[Any],
    sender_email: Optional[str] = None,
    app_password: Optional[str] = None,
    app_url: Optional[str] = None,
    sender_name: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    price_usd: float = 6.0,
    topic: str = "",
    delay_seconds: float = 5.0,
    progress_callback: Optional[Callable[[Any, bool, str, int, int], None]] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Autonomously dispatches personalized pitches via Gmail SMTP with:
    1. Robust SMTP connection & auto-reconnection handling (resolving 'please run connect() first').
    2. Strict email validation filter (skipping code artifacts like bootstrap@4.6.0 or splide@4.1.4).
    3. Sent-history deduplication check (preventing duplicate sends).
    4. Gmail rate-limiting protection with configurable safety delays (default 5.0s).
    """
    user = (sender_email or getattr(settings, "effective_smtp_user", "") or "").strip()
    password = (app_password or getattr(settings, "effective_smtp_password", "") or "").strip()
    url = app_url or getattr(settings, "effective_app_url", "http://localhost:8501") or "http://localhost:8501"
    name = sender_name or getattr(settings, "sender_name", "B2B Lead Machine") or "B2B Lead Machine"
    host = smtp_host or getattr(settings, "smtp_host", "smtp.gmail.com") or "smtp.gmail.com"
    port = smtp_port or getattr(settings, "smtp_port", 587) or 587

    if not user or not password:
        return {
            "success": False,
            "message": "Gmail address and 16-character App Password are required to dispatch emails. Please configure them in secrets or .env file.",
            "total_leads": len(leads),
            "eligible_leads": 0,
            "sent_count": 0,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
            "failed_count": 0,
            "results": []
        }

    # Extract leads that have non-empty email values
    candidates = []
    for l in leads:
        em = _get_attr(l, "primary_email")
        if em and isinstance(em, str) and "@" in em:
            candidates.append(l)

    if not candidates:
        return {
            "success": False,
            "message": "No eligible leads with verified email addresses found.",
            "total_leads": len(leads),
            "eligible_leads": 0,
            "sent_count": 0,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
            "failed_count": 0,
            "results": []
        }

    results = []
    sent_count = 0
    skipped_duplicates = 0
    skipped_invalid = 0
    failed_count = 0
    total_candidates = len(candidates)

    server = None
    try:
        # 1. Establish initial verified connection before iteration
        server = _connect_smtp_server(host, port, user, password)

        for idx, lead in enumerate(candidates, 1):
            raw_recipient = str(_get_attr(lead, "primary_email", "")).strip()
            c_name = str(_get_attr(lead, "company_name", "there"))
            p_pitch = str(_get_attr(lead, "personalized_pitch", ""))

            # 🛡️ 2. Strict Email Validation Filter (e.g. Reject bootstrap@4.6.0, splide@4.1.4, invalid assets)
            is_valid, validation_reason = is_valid_business_email(raw_recipient)
            if not is_valid:
                skipped_invalid += 1
                logger.warning(f"🚫 Skipping invalid email '{raw_recipient}' ({validation_reason}).")
                if progress_callback:
                    progress_callback(lead, False, f"Skipped: {validation_reason}", idx, total_candidates)

                results.append({
                    "company_name": c_name,
                    "email": raw_recipient,
                    "status": "skipped_invalid",
                    "error": f"Invalid email format ({validation_reason})",
                    "pitch": p_pitch
                })
                continue

            recipient = raw_recipient.lower()

            # 🛡️ 3. Deduplication Check against persistent history database
            if sent_history.is_email_sent(recipient):
                skipped_duplicates += 1
                logger.info(f"⏩ Skipping {recipient} (already emailed in past campaign).")
                if progress_callback:
                    progress_callback(lead, True, "Skipped (already in sent history)", idx, total_candidates)

                results.append({
                    "company_name": c_name,
                    "email": recipient,
                    "status": "skipped_duplicate",
                    "error": "Already contacted in previous cycle",
                    "pitch": p_pitch
                })
                continue

            subject, html_body, plain_text = build_outreach_email(lead, app_url=url, sender_name=name, price_usd=price_usd)

            # 4. Send Email with auto-reconnection and rate-limit handling
            send_success = False
            err_msg = ""
            for attempt in range(2):
                try:
                    send_single_email(
                        server=server,
                        sender_email=user,
                        recipient_email=recipient,
                        subject=subject,
                        html_body=html_body,
                        plain_text=plain_text,
                        sender_name=name
                    )
                    send_success = True
                    break
                except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, BrokenPipeError, ConnectionResetError) as disc_err:
                    logger.warning(f"SMTP connection dropped on attempt {attempt+1}: {disc_err}. Reconnecting...")
                    try:
                        server = _connect_smtp_server(host, port, user, password)
                    except Exception as rec_err:
                        err_msg = f"SMTP Reconnect failed: {rec_err}"
                        break
                except smtplib.SMTPResponseException as resp_err:
                    # Gmail Rate Limit / Quota Check (421, 450, 451, 452, 550)
                    code = resp_err.smtp_code
                    msg = str(resp_err.smtp_error)
                    if code in (421, 450, 451, 452, 550) and ("limit" in msg.lower() or "quota" in msg.lower() or "blocked" in msg.lower()):
                        err_msg = f"Gmail rate limit / sending quota reached (Code {code}): {msg}"
                        logger.error(err_msg)
                    else:
                        err_msg = f"SMTP Error ({code}): {msg}"
                    break
                except Exception as ex:
                    err_msg = str(ex)
                    break

            if send_success:
                sent_count += 1
                status = "sent"
                # 📝 Record in persistent sent history
                sent_history.record_sent_email(
                    email=recipient,
                    company_name=c_name,
                    topic=topic or "General Outreach",
                    pitch=p_pitch
                )
                if progress_callback:
                    progress_callback(lead, True, "Sent successfully", idx, total_candidates)
            else:
                failed_count += 1
                status = "failed"
                logger.error(f"Failed to send email to {recipient}: {err_msg}")
                if progress_callback:
                    progress_callback(lead, False, err_msg, idx, total_candidates)

            results.append({
                "company_name": c_name,
                "email": recipient,
                "status": status,
                "error": err_msg,
                "pitch": p_pitch
            })

            # ⏱️ 5. Rate-Limit Safety Delay between sends (e.g. 5-10s)
            if idx < total_candidates and delay_seconds > 0:
                time.sleep(delay_seconds)

    except Exception as e:
        logger.error(f"SMTP Connection / Authentication failure: {e}")
        return {
            "success": False,
            "message": f"SMTP Authentication/Connection error: {e}. Ensure you are using a valid 16-character Gmail App Password.",
            "total_leads": len(leads),
            "eligible_leads": total_candidates,
            "sent_count": sent_count,
            "skipped_duplicates": skipped_duplicates,
            "skipped_invalid": skipped_invalid,
            "failed_count": total_candidates - sent_count - skipped_duplicates - skipped_invalid,
            "results": results
        }
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

    return {
        "success": True,
        "total_leads": len(leads),
        "eligible_leads": total_candidates,
        "sent_count": sent_count,
        "skipped_duplicates": skipped_duplicates,
        "skipped_invalid": skipped_invalid,
        "failed_count": failed_count,
        "results": results
    }
