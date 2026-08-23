import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Tuple

from b2b_leadgen.config import settings
from b2b_leadgen.models import EnrichedLead

logger = logging.getLogger(__name__)


def build_outreach_email(
    lead: EnrichedLead,
    app_url: Optional[str] = None,
    sender_name: Optional[str] = None,
    price_usd: float = 6.0
) -> Tuple[str, str, str]:
    """
    Builds the personalized cold outreach email for a company directing them
    to the secure zero-KYC crypto checkout (accepting USDT, BTC, LTC, ETH, etc. via NOWPayments).
    Returns (subject, html_body, plain_text_body).
    """
    company_name = lead.company_name or "there"
    pitch = (
        lead.personalized_pitch
        or f"I came across {company_name} and was very impressed by your service offerings. We help businesses in your space streamline lead acquisition and client operations."
    )
    effective_url = (app_url or getattr(settings, "effective_app_url", "http://localhost:8501") or "http://localhost:8501").rstrip("/")
    effective_name = sender_name or getattr(settings, "sender_name", "B2B Lead Machine")
    effective_price = price_usd or getattr(settings, "crypto_price_usd", 6.0)

    subject = f"Growth opportunity for {company_name}"

    plain_text = f"""Hi {company_name} Team,

{pitch}

We have compiled a verified, real-time database of high-intent B2B prospects and target decision-makers in your market. You can explore the live dataset directly on our portal:
👉 {effective_url}

(You can instantly unlock and download the entire verified dataset for ${effective_price:.2f} USD via our automated, zero-KYC crypto checkout accepting USDT, Bitcoin, Ethereum, Solana, and Litecoin).

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
        .badge {{
            display: inline-block;
            background: #eef2ff;
            color: #4338ca;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            margin-top: 8px;
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
                    ⚡ View Verified Lead List & Download
                </a>
            </p>

            <p style="font-size: 13px; color: #64748b; text-align: center;">
                🔒 <em>Instant zero-KYC crypto checkout available (${effective_price:.2f} USD accepting USDT, BTC, ETH, SOL, LTC via NOWPayments).</em>
            </p>

            <p>Best regards,<br>
            <strong>{effective_name}</strong><br>
            <span style="color: #64748b; font-size: 13px;">B2B Lead Machine Outbound System</span></p>
        </div>
        <div class="footer">
            Sent automatically via B2B Lead Machine Outbound Dispatcher • <a href="{effective_url}" style="color: #64748b;">Visit App</a>
        </div>
    </div>
</body>
</html>
"""

    return subject, html_body, plain_text


def send_single_email(
    server: smtplib.SMTP,
    sender_email: str,
    recipient_email: str,
    subject: str,
    html_body: str,
    plain_text: str,
    sender_name: str = "B2B Lead Machine"
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
    leads: List[EnrichedLead],
    sender_email: Optional[str] = None,
    app_password: Optional[str] = None,
    app_url: Optional[str] = None,
    sender_name: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    price_usd: float = 6.0,
    delay_seconds: float = 1.0,
    progress_callback: Optional[Callable[[EnrichedLead, bool, str, int, int], None]] = None
) -> Dict[str, Any]:
    """
    Autonomously dispatches personalized pitches via Gmail SMTP to all leads with verified emails.
    Directs recipients to the zero-KYC crypto checkout portal.
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
            "failed_count": 0,
            "results": []
        }

    eligible_leads = [l for l in leads if l.primary_email and "@" in l.primary_email]
    if not eligible_leads:
        return {
            "success": False,
            "message": "No eligible leads with verified email addresses found.",
            "total_leads": len(leads),
            "eligible_leads": 0,
            "sent_count": 0,
            "failed_count": 0,
            "results": []
        }

    results = []
    sent_count = 0
    failed_count = 0
    total_eligible = len(eligible_leads)

    logger.info(f"Connecting to Gmail SMTP server {host}:{port}...")

    server = None
    try:
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password.replace(" ", ""))
        logger.info(f"Successfully authenticated as {user}")

        for idx, lead in enumerate(eligible_leads, 1):
            recipient = lead.primary_email.strip()
            subject, html_body, plain_text = build_outreach_email(lead, app_url=url, sender_name=name, price_usd=price_usd)

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
                sent_count += 1
                status = "sent"
                err_msg = ""
                if progress_callback:
                    progress_callback(lead, True, "Sent successfully", idx, total_eligible)
            except Exception as e:
                failed_count += 1
                status = "failed"
                err_msg = str(e)
                logger.error(f"Failed to send email to {recipient}: {e}")
                if progress_callback:
                    progress_callback(lead, False, str(e), idx, total_eligible)

            results.append({
                "company_name": lead.company_name,
                "email": recipient,
                "status": status,
                "error": err_msg,
                "pitch": lead.personalized_pitch
            })

            if idx < total_eligible and delay_seconds > 0:
                time.sleep(delay_seconds)

    except Exception as e:
        logger.error(f"SMTP Connection/Authentication error: {e}")
        return {
            "success": False,
            "message": f"SMTP Authentication error: {e}. Ensure you are using a 16-character Gmail App Password.",
            "total_leads": len(leads),
            "eligible_leads": total_eligible,
            "sent_count": sent_count,
            "failed_count": total_eligible - sent_count,
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
        "eligible_leads": total_eligible,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "results": results
    }
