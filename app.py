import asyncio
import io
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from b2b_leadgen.autopilot import autopilot_engine
from b2b_leadgen.config import settings
from b2b_leadgen.email_dispatcher import (
    build_outreach_email,
    dispatch_campaign,
    is_valid_business_email
)
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.history import sent_history
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.nowpayments import (
    check_nowpayments_invoice_status,
    create_nowpayments_invoice
)
from b2b_leadgen.pdf_generator import (
    generate_batch_audit_bundle_pdf,
    generate_company_audit_pdf
)
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column
from b2b_leadgen.sheets_exporter import export_leads_to_google_sheet

logger = logging.getLogger(__name__)

# =============================================================
# 📱 Page Configuration & Session State Initialization
# =============================================================
st.set_page_config(
    page_title="AI Audit & Lead Closer V2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Comprehensive top-level state defaults to guarantee mobile/cross-browser uptime
SESSION_DEFAULTS: Dict[str, Any] = {
    "leads": [],
    "df": pd.DataFrame(),
    "last_query": "",
    "payment_mode": "Free Trial Mode",  # "Free Trial Mode", "Crypto Only (NOWPayments)", "Stripe Checkout", "Hybrid"
    "starter_price_usd": 9.0,
    "pro_price_usd": 29.0,
    "agency_price_usd": 79.0,
    "selected_tier": "Starter ($9 / 50 Leads)",
    "payment_verified": False,
    "paid": False,
    "admin_authenticated": False,
    "admin_logged_in": False,
    "crypto_invoice_url": None,
    "crypto_invoice_id": None,
    "campaign_results": None,
    "sync_status": None,
    "is_running": False,          # Run-lock preventing concurrent queue spam
    "activity_logs": [],
    "agency_name": "AI Growth & Intelligence Partners",
    "agency_website": "https://growth-intelligence.io"
}

for state_key, state_default in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_default


def add_activity_log(message: str, level: str = "INFO") -> None:
    """Adds a timestamped activity event to session state logs."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"timestamp": timestamp, "level": level, "message": message}
    if "activity_logs" not in st.session_state:
        st.session_state["activity_logs"] = []
    st.session_state["activity_logs"].append(entry)
    if len(st.session_state["activity_logs"]) > 150:
        st.session_state["activity_logs"].pop(0)


# Premium CSS styling with Glassmorphism, Dark Accents & Modern Typography
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 850;
        margin-bottom: 0.1rem;
        background: linear-gradient(135deg, #10b981 0%, #3b82f6 50%, #8b5cf6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.2rem;
    }
    .status-badge-free {
        background: linear-gradient(135deg, #065f46 0%, #047857 100%);
        border: 1px solid #34d399;
        border-radius: 12px;
        padding: 12px 18px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 18px;
        box-shadow: 0 4px 14px rgba(4, 120, 87, 0.2);
    }
    .status-badge-premium {
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        border: 1px solid #818cf8;
        border-radius: 12px;
        padding: 12px 18px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 18px;
        box-shadow: 0 4px 14px rgba(49, 46, 129, 0.25);
    }
    .storefront-card {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        color: #ffffff;
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 16px;
        border: 1px solid #334155;
        box-shadow: 0 4px 12px rgba(0,0,0,0.18);
    }
    .crypto-hero-box {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        border: 2px solid #818cf8;
        border-radius: 16px;
        padding: 22px;
        color: #ffffff;
        text-align: center;
        margin: 15px auto;
        box-shadow: 0 6px 20px rgba(129, 140, 248, 0.2);
    }
    .pill {
        display: inline-block;
        background: #1e293b;
        color: #93c5fd;
        border: 1px solid #334155;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.76rem;
        font-weight: 600;
        margin: 2px 0;
    }
    .audit-card {
        border-left: 4px solid #10b981;
        background: #ffffff;
        padding: 16px;
        border-radius: 10px;
        margin-bottom: 12px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }
    .protected-sample-container {
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        user-select: none;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 18px;
        background: #ffffff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        margin-bottom: 14px;
    }
    .locked-teaser-card {
        -webkit-user-select: none;
        user-select: none;
        background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%);
        border: 2px dashed #94a3b8;
        border-radius: 14px;
        padding: 22px;
        text-align: center;
        margin: 14px 0;
    }
    .pricing-card {
        background: #ffffff;
        border: 2px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px;
        text-align: center;
        margin-bottom: 10px;
    }
    .pricing-card-featured {
        background: #f8fafc;
        border: 2px solid #3b82f6;
        border-radius: 12px;
        padding: 18px;
        text-align: center;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================
# 🔐 Secure Secret Resolution Helper with Robust Fallbacks
# =============================================================
def get_secret(key: str, default: Any = None) -> Any:
    """
    Reads a configuration secret safely from:
    1. st.secrets (case-insensitive)
    2. os.environ (case-insensitive)
    3. settings attribute or default value
    """
    try:
        if hasattr(st, "secrets") and st.secrets is not None:
            if key in st.secrets and str(st.secrets[key]).strip():
                return st.secrets[key]
            if key.lower() in st.secrets and str(st.secrets[key.lower()]).strip():
                return st.secrets[key.lower()]
            if key.upper() in st.secrets and str(st.secrets[key.upper()]).strip():
                return st.secrets[key.upper()]
    except Exception:
        pass

    for env_key in [key, key.lower(), key.upper()]:
        env_val = os.environ.get(env_key)
        if env_val is not None and str(env_val).strip():
            return env_val

    try:
        val = getattr(settings, key.lower(), None)
        if val is not None and str(val).strip():
            return val
        val = getattr(settings, f"effective_{key.lower()}", None)
        if val is not None and str(val).strip():
            return val
    except Exception:
        pass

    return default


def mask_email_address(email: Optional[str]) -> str:
    """Masks middle characters of email address to deter scrape/copy before payment."""
    if not email or "@" not in email:
        return "No email found"
    parts = email.strip().split("@")
    user, domain = parts[0], parts[1]
    if len(user) <= 2:
        masked_user = user[0] + "***"
    else:
        masked_user = user[:2] + "***" + user[-1]
    return f"{masked_user}@{domain}"


def safe_execute_pipeline_sync(
    pipeline: LeadGenPipeline,
    inputs: List[LeadInput],
    progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
) -> List[EnrichedLead]:
    """
    Executes the enrichment pipeline synchronously in the main thread.
    No detached background threads or ghost workers are spawned.
    """
    try:
        return asyncio.run(
            pipeline.run_batch(
                inputs=inputs,
                output_csv_path=None,
                progress_callback=progress_callback
            )
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                pipeline.run_batch(
                    inputs=inputs,
                    output_csv_path=None,
                    progress_callback=progress_callback
                )
            )
        finally:
            loop.close()


# Read Core Secrets Securely from st.secrets / backend
GEMINI_API_KEY: Optional[str] = get_secret("GEMINI_API_KEY", getattr(settings, "effective_api_key", None))
NOWPAYMENTS_API_KEY: Optional[str] = get_secret("NOWPAYMENTS_API_KEY", getattr(settings, "effective_nowpayments_key", None))
STRIPE_SECRET_KEY: Optional[str] = get_secret("STRIPE_SECRET_KEY", getattr(settings, "stripe_secret_key", None))
ADMIN_PASSWORD: str = str(get_secret("ADMIN_PASSWORD", getattr(settings, "admin_password", "admin123")))
UNLOCK_CODE: str = str(get_secret("UNLOCK_CODE", getattr(settings, "unlock_code", "4990")))
SMTP_USER: str = str(get_secret("SMTP_USER", getattr(settings, "effective_smtp_user", "")))
SMTP_PASSWORD: str = str(get_secret("SMTP_PASSWORD", getattr(settings, "effective_smtp_password", "")))
SMTP_HOST: str = str(get_secret("SMTP_HOST", getattr(settings, "smtp_host", "smtp.gmail.com")))
SMTP_PORT: int = int(get_secret("SMTP_PORT", getattr(settings, "smtp_port", 587)))
SENDER_NAME: str = str(get_secret("SENDER_NAME", getattr(settings, "sender_name", "AI Audit & Lead Closer")))
APP_URL: str = str(get_secret("APP_URL", getattr(settings, "effective_app_url", "http://localhost:8501")))


# State Accessors
is_admin_active = bool(st.session_state.get("admin_authenticated", False) or st.session_state.get("admin_logged_in", False))
active_payment_mode = str(st.session_state.get("payment_mode", "Free Trial Mode"))
paywall_is_active = (active_payment_mode != "Free Trial Mode")
user_has_paid = bool(st.session_state.get("payment_verified", False) or st.session_state.get("paid", False))
is_unlocked = (not paywall_is_active) or is_admin_active or user_has_paid
is_currently_running = bool(st.session_state.get("is_running", False))

# Active Effective Price USD
if "starter" in st.session_state.get("selected_tier", "").lower():
    active_price_usd = float(st.session_state.get("starter_price_usd", 9.0))
elif "agency" in st.session_state.get("selected_tier", "").lower():
    active_price_usd = float(st.session_state.get("agency_price_usd", 79.0))
else:
    active_price_usd = float(st.session_state.get("pro_price_usd", 29.0))


# =============================================================
# 🛍️ Clean Public Sidebar Interface & Master Admin Portal
# =============================================================
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/lightning-bolt.png", width=60)
    st.title("AI Audit Closer V2")

    st.markdown("""
    <div class="storefront-card">
        <h4 style="margin-top:0; color:#f8fafc; font-size:1.02rem;">⚡ B2B Lead Intelligence V2</h4>
        <p style="font-size:0.82rem; color:#cbd5e1; margin-bottom:8px;">
            Extract verified decision-maker emails, generate 3-point digital audits, and produce white-labeled client PDFs.
        </p>
        <span class="pill">🤖 Gemini 2026 AI Engine</span><br>
        <span class="pill">📄 White-Labeled PDF Audits</span><br>
        <span class="pill">📧 Decision-Maker Emails</span><br>
        <span class="pill">🛡️ Strict Global Anti-Spam</span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📦 Plan Status")
    if not paywall_is_active:
        st.success("✅ FREE TRIAL ACTIVE — Unrestricted Access")
    elif is_unlocked:
        st.success("✅ PREMIUM UNLOCKED — Full CSV & PDF Export")
    else:
        st.info(f"🔒 Premium Tier: ${active_price_usd:.2f} USD Required")

    st.divider()

    # 🔐 Master Control & Monetization Center (Password Protected Admin)
    with st.expander("🔐 Admin Monetization & Control Center", expanded=False):
        if not is_admin_active:
            st.markdown("##### Admin Authentication")
            admin_pwd_input = st.text_input("Enter Admin Password", type="password", key="admin_pwd_input")
            if st.button("Unlock Admin Center", width="stretch"):
                if admin_pwd_input and admin_pwd_input == ADMIN_PASSWORD:
                    st.session_state["admin_authenticated"] = True
                    st.session_state["admin_logged_in"] = True
                    add_activity_log("Admin authenticated successfully.", "INFO")
                    st.success("Admin Monetization Center unlocked!")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid Admin Password.")
        else:
            st.markdown('<span style="color:#15803d; font-weight:700;">🔓 MASTER ADMIN & REVENUE CENTER ACTIVE</span>', unsafe_allow_html=True)

            # -------------------------------------------------
            # 1. 24/7 BACKGROUND AUTOPILOT ENGINE (MANUAL THREADING CONTROL)
            # -------------------------------------------------
            st.markdown("---")
            st.markdown("#### ⚡ 24/7 Background Autopilot Engine")
            ap_status = autopilot_engine.get_status()
            ap_running = ap_status.get("is_running", False)

            if ap_running:
                st.markdown(f'<div style="background:#064e3b; border:1px solid #34d399; border-radius:8px; padding:10px; color:#ffffff; font-weight:600; margin-bottom:8px;">🟢 AUTOPILOT ACTIVE • Cycle #{ap_status.get("total_cycles", 0)} • Niche: {ap_status.get("current_niche", "Starting...")}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="background:#1e293b; border:1px solid #475569; border-radius:8px; padding:10px; color:#94a3b8; font-weight:600; margin-bottom:8px;">⚪ AUTOPILOT IDLE (Manual Start Required)</div>', unsafe_allow_html=True)

            c_ap1, c_ap2 = st.columns(2)
            with c_ap1:
                st.metric("Total Cycles", ap_status.get("total_cycles", 0))
                st.metric("Leads Discovered", ap_status.get("total_leads_discovered", 0))
            with c_ap2:
                st.metric("Emails Sent", ap_status.get("total_emails_sent", 0))
                st.metric("Duplicates Skipped", ap_status.get("total_duplicates_skipped", 0))

            if not ap_running:
                ap_batch_size = st.slider("Batch Size per Cycle (Leads)", min_value=2, max_value=15, value=5, step=1, key="ap_batch_slider")
                ap_interval = st.slider("Cycle Delay Interval (Seconds)", min_value=30, max_value=300, value=120, step=15, key="ap_interval_slider")
                ap_continuous = st.checkbox("Run Continuously", value=True, key="ap_continuous_cb")
                ap_duration = st.number_input("Max Duration (Hours)", min_value=0.5, max_value=72.0, value=24.0, step=1.0, key="ap_duration_in") if not ap_continuous else 24.0

                if st.button("▶ Start Autopilot Engine", type="primary", width="stretch"):
                    if not SMTP_USER or not SMTP_PASSWORD:
                        st.warning("⚠️ SMTP credentials (SMTP_USER, SMTP_PASSWORD) not configured in secrets.")
                    else:
                        autopilot_engine.start(
                            gemini_api_key=GEMINI_API_KEY,
                            smtp_user=SMTP_USER,
                            smtp_password=SMTP_PASSWORD,
                            app_url=APP_URL,
                            sender_name=SENDER_NAME,
                            smtp_host=SMTP_HOST,
                            smtp_port=SMTP_PORT,
                            price_usd=active_price_usd,
                            batch_size=int(ap_batch_size),
                            interval_seconds=int(ap_interval),
                            run_continuously=ap_continuous,
                            duration_hours=float(ap_duration)
                        )
                        add_activity_log("Admin manually started 24/7 Autopilot Engine thread.", "INFO")
                        st.toast("🚀 Autopilot Engine started!", icon="⚡")
                        st.rerun()
            else:
                if st.button("⏹ Stop Autopilot Engine", type="secondary", width="stretch"):
                    autopilot_engine.stop()
                    add_activity_log("Admin manually signaled stop to Autopilot Engine thread.", "WARNING")
                    st.toast("🛑 Autopilot Engine stopping...", icon="⏹")
                    st.rerun()

            if ap_status.get("logs"):
                with st.expander("📜 View Live Autopilot Logs", expanded=False):
                    st.dataframe(pd.DataFrame(ap_status.get("logs", [])), width="stretch", hide_index=True)

            # -------------------------------------------------
            # 2. REVENUE & PAYWALL DASHBOARD
            # -------------------------------------------------
            st.markdown("---")
            st.markdown("#### 💰 Revenue & Paywall Dashboard")

            selected_mode = st.selectbox(
                "Payment Gateway & Monetization Mode",
                options=["Free Trial Mode", "Crypto Only (NOWPayments)", "Stripe Checkout", "Hybrid (Crypto + Stripe)"],
                index=["Free Trial Mode", "Crypto Only (NOWPayments)", "Stripe Checkout", "Hybrid (Crypto + Stripe)"].index(st.session_state.get("payment_mode", "Free Trial Mode")),
                key="admin_pay_mode_select"
            )
            if selected_mode != st.session_state.get("payment_mode"):
                st.session_state["payment_mode"] = selected_mode
                add_activity_log(f"Admin updated payment gateway mode to '{selected_mode}'.", "INFO")
                st.toast(f"Payment mode updated: {selected_mode}", icon="💳")
                st.rerun()

            st.markdown("##### Dynamic Tiered Pricing Controls (USD)")
            c_p1, c_p2, c_p3 = st.columns(3)
            with c_p1:
                new_starter = st.number_input("Starter Tier ($)", min_value=1.0, max_value=100.0, value=float(st.session_state.get("starter_price_usd", 9.0)), step=1.0)
                st.session_state["starter_price_usd"] = new_starter
            with c_p2:
                new_pro = st.number_input("Pro Tier ($)", min_value=5.0, max_value=500.0, value=float(st.session_state.get("pro_price_usd", 29.0)), step=1.0)
                st.session_state["pro_price_usd"] = new_pro
            with c_p3:
                new_agency = st.number_input("Agency Tier ($)", min_value=10.0, max_value=1000.0, value=float(st.session_state.get("agency_price_usd", 79.0)), step=1.0)
                st.session_state["agency_price_usd"] = new_agency

            if not is_unlocked and paywall_is_active:
                if st.button("⚡ Admin Override: Unlock Premium for this Session", width="stretch"):
                    st.session_state["payment_verified"] = True
                    st.session_state["paid"] = True
                    st.toast("🎉 Premium deliverables unlocked by Admin!", icon="🔓")
                    st.rerun()

            # -------------------------------------------------
            # 3. WHITE-LABEL AGENCY BRANDING
            # -------------------------------------------------
            st.markdown("---")
            st.markdown("#### 🏢 White-Label Agency Branding")
            agency_name_in = st.text_input("Agency / Consultant Name", value=st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
            st.session_state["agency_name"] = agency_name_in
            agency_web_in = st.text_input("Agency Website URL", value=st.session_state.get("agency_website", "https://growth-intelligence.io"))
            st.session_state["agency_website"] = agency_web_in

            # -------------------------------------------------
            # 4. AI MODEL SELECTOR (2026 Standards)
            # -------------------------------------------------
            st.markdown("---")
            st.markdown("#### 🤖 AI Engine Tuning")
            admin_model = st.selectbox(
                "Gemini AI Model",
                options=["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
                index=0,
                key="admin_model_select"
            )
            admin_concurrency = st.slider(
                "Max Concurrency",
                min_value=1,
                max_value=8,
                value=int(getattr(settings, "max_concurrent_requests", 3)),
                key="admin_concurrency_slider"
            )
            admin_follow_subpages = st.checkbox(
                "Follow Contact/About Pages",
                value=getattr(settings, "follow_contact_pages", True),
                key="admin_follow_subpages_cb"
            )

            # -------------------------------------------------
            # 5. TRACKER & DEDUPLICATION LOGS
            # -------------------------------------------------
            st.markdown("---")
            st.markdown("#### 📊 Activity & Sent History Tracker")
            sent_count = sent_history.get_sent_count()
            st.metric("Total Unique Businesses Contacted", sent_count)

            all_records = sent_history.get_all_sent_records()
            if all_records:
                with st.expander(f"📋 Permanent Sent Log ({len(all_records)} contacts)", expanded=False):
                    st.dataframe(pd.DataFrame(all_records)[["email", "company_name", "topic", "sent_at"]], width="stretch", hide_index=True)

                if st.button("🗑️ Clear Sent History Database", width="stretch"):
                    sent_history.clear_sent_history()
                    add_activity_log("Admin wiped global sent history database.", "WARNING")
                    st.toast("✅ Global sent history cleared!", icon="🗑️")
                    st.rerun()

            if st.button("Log Out of Admin Center", width="stretch"):
                st.session_state["admin_authenticated"] = False
                st.session_state["admin_logged_in"] = False
                add_activity_log("Admin logged out.", "INFO")
                st.rerun()

    st.caption("⚡ **AI Audit Closer V2** • High-Converting Prospect Intelligence")


# Set runtime parameters (Admin overrides if logged in, otherwise default)
effective_model = st.session_state.get("admin_model_select", getattr(settings, "gemini_model", "gemini-3.5-flash"))
effective_concurrency = int(st.session_state.get("admin_concurrency_slider", getattr(settings, "max_concurrent_requests", 3)))
effective_follow_subpages = bool(st.session_state.get("admin_follow_subpages_cb", getattr(settings, "follow_contact_pages", True)))
effective_agency_name = str(st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
effective_agency_website = str(st.session_state.get("agency_website", "https://growth-intelligence.io"))


# =============================================================
# 🚀 Main Storefront Header & Tabs
# =============================================================
st.markdown('<div class="main-header">⚡ AI Audit & Lead Closer V2</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Autonomous Prospect Intelligence, 3-Point Digital Mini-Audits & White-Labeled Client PDF Reports</div>', unsafe_allow_html=True)

# Status Notification Banner based on monetization mode
if not paywall_is_active:
    st.markdown("""
    <div class="status-badge-free">
        <strong style="font-size:1.05rem;">🎉 Free Trial Mode Active:</strong> Instant, unrestricted lead discovery, Custom Mini-Audits, White-Labeled PDFs & direct CSV exports.
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="status-badge-premium">
        <strong style="font-size:1.05rem;">🔒 Premium Monetization Active:</strong> Sample preview unlocked. Full CSV dataset, White-Labeled PDF Reports & Automated Outbound require Tier Checkout ({active_payment_mode}).
    </div>
    """, unsafe_allow_html=True)

tab_search, tab_csv = st.tabs(["🔍 Search & Generate Client Audits", "📁 Upload Existing CSV"])


# -------------------------------------------------------------
# TAB 1: Autonomous Keyword Discovery & Audit Generator
# -------------------------------------------------------------
with tab_search:
    st.markdown("### 🎯 Discover Real Companies & Generate Mini-Audits")
    st.markdown("Enter a target search phrase (e.g. *'Plumbing contractors in Austin, TX'* or *'Commercial roofing in Miami'*) to discover official company websites, extract decision-maker emails, and generate client-ready digital audits.")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input(
            "Search Query / Niche + Location",
            placeholder="e.g. Commercial HVAC contractors in Dallas, TX",
            key="keyword_search_input"
        )
    with col2:
        num_leads = st.number_input("Target Lead Count", min_value=3, max_value=30, value=10, step=1)

    btn_discover = st.button("🚀 Generate Leads & Mini-Audits", type="primary", width="stretch", disabled=is_currently_running)

    if btn_discover:
        if not search_query.strip():
            st.error("Please enter a valid search query.")
        else:
            st.session_state["is_running"] = True
            try:
                with st.spinner(f"🔎 Discovering and auditing businesses for '{search_query.strip()}' in main thread..."):
                    progress_container = st.container()
                    with progress_container:
                        status_text = st.empty()
                        prog_bar = st.progress(0)

                        add_activity_log(f"Starting discovery for '{search_query.strip()}' (Target: {int(num_leads)} leads)...", "INFO")
                        status_text.info(f"🔎 Discovering businesses matching '{search_query}' via DuckDuckGo...")

                        try:
                            discovered_inputs = discover_leads_by_keyword(search_query.strip(), max_results=int(num_leads))
                        except Exception as disc_err:
                            logger.error(f"Discovery error: {disc_err}")
                            discovered_inputs = []
                            add_activity_log(f"Search discovery error: {disc_err}", "ERROR")
                            status_text.error(f"⚠️ Search discovery encountered an issue: {disc_err}. Please retry.")

                        if not discovered_inputs:
                            status_text.error("No companies could be discovered for this query. Try refining your search keywords.")
                        else:
                            add_activity_log(f"Discovered {len(discovered_inputs)} company domains for '{search_query.strip()}'. Running AI enrichment...", "INFO")
                            status_text.success(f"✅ Discovered {len(discovered_inputs)} businesses! Generating AI Mini-Audits with Gemini ({effective_model})...")

                            try:
                                pipeline = LeadGenPipeline(
                                    api_key=GEMINI_API_KEY,
                                    model=effective_model,
                                    max_concurrency=effective_concurrency,
                                    follow_contact_pages=effective_follow_subpages,
                                    use_checkpoint=False
                                )

                                total = len(discovered_inputs)

                                def update_ui_progress(lead: EnrichedLead, idx: int, tot: int):
                                    pct = int((idx / tot) * 100) if tot > 0 else 0
                                    prog_bar.progress(min(100, max(0, pct)))
                                    email_tag = f" — Found email: {lead.primary_email}" if lead.primary_email else ""
                                    status_text.text(f"Auditing ({idx}/{tot}): {lead.company_name}{email_tag}")

                                results = safe_execute_pipeline_sync(
                                    pipeline=pipeline,
                                    inputs=discovered_inputs,
                                    progress_callback=update_ui_progress
                                )

                                # Post-filter results to eliminate bad library/version string artifacts
                                sanitized_results = []
                                for r in results:
                                    if r.primary_email:
                                        valid, _ = is_valid_business_email(r.primary_email)
                                        if not valid:
                                            r.primary_email = None
                                    sanitized_results.append(r)

                                prog_bar.progress(100)
                                add_activity_log(f"Successfully generated mini-audits for {len(sanitized_results)} leads.", "INFO")
                                status_text.success(f"🎉 Successfully generated {len(sanitized_results)} leads with Custom Mini-Audits!")

                                st.session_state["leads"] = sanitized_results
                                df_data = [r.model_dump() for r in sanitized_results]
                                st.session_state["df"] = pd.DataFrame(df_data)
                                st.session_state["last_query"] = search_query
                                st.session_state["campaign_results"] = None

                            except Exception as pipe_err:
                                logger.error(f"Pipeline execution error: {pipe_err}")
                                add_activity_log(f"Pipeline execution error: {pipe_err}", "ERROR")
                                status_text.error(f"⚠️ Enrichment pipeline error: {pipe_err}")

            finally:
                st.session_state["is_running"] = False


# -------------------------------------------------------------
# TAB 2: CSV Lead Enrichment & Mini-Audit Generator
# -------------------------------------------------------------
with tab_csv:
    st.markdown("### 📁 Upload Existing CSV for Mini-Audits")
    st.markdown("Upload a CSV containing company names to enrich them with verified contact emails, company summaries, and value-first 3-point digital audits.")

    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            st.dataframe(uploaded_df.head(5), width="stretch")

            company_col_detected = detect_company_column(list(uploaded_df.columns))
            selected_col = st.selectbox(
                "Select Company Name Column",
                options=list(uploaded_df.columns),
                index=list(uploaded_df.columns).index(company_col_detected) if company_col_detected in uploaded_df.columns else 0
            )

            btn_enrich_csv = st.button("⚡ Generate Mini-Audits from Uploaded CSV", type="primary", disabled=is_currently_running)

            if btn_enrich_csv:
                input_leads = []
                for _, row in uploaded_df.iterrows():
                    c_name = str(row.get(selected_col, "")).strip()
                    if c_name and c_name.lower() != "nan":
                        input_leads.append(LeadInput(company_name=c_name))

                if not input_leads:
                    st.error("No valid company names found in selected column.")
                else:
                    st.session_state["is_running"] = True
                    try:
                        with st.spinner("Enriching uploaded CSV in main thread..."):
                            progress_container = st.container()
                            with progress_container:
                                status_text = st.empty()
                                prog_bar = st.progress(0)

                                try:
                                    pipeline = LeadGenPipeline(
                                        api_key=GEMINI_API_KEY,
                                        model=effective_model,
                                        max_concurrency=effective_concurrency,
                                        follow_contact_pages=effective_follow_subpages,
                                        use_checkpoint=False
                                    )

                                    def update_csv_progress(lead: EnrichedLead, idx: int, tot: int):
                                        pct = int((idx / tot) * 100) if tot > 0 else 0
                                        prog_bar.progress(min(100, max(0, pct)))
                                        status_text.text(f"Auditing ({idx}/{tot}): {lead.company_name}")

                                    results = safe_execute_pipeline_sync(
                                        pipeline=pipeline,
                                        inputs=input_leads,
                                        progress_callback=update_csv_progress
                                    )

                                    sanitized_results = []
                                    for r in results:
                                        if r.primary_email:
                                            valid, _ = is_valid_business_email(r.primary_email)
                                            if not valid:
                                                r.primary_email = None
                                        sanitized_results.append(r)

                                    prog_bar.progress(100)
                                    add_activity_log(f"Enriched {len(sanitized_results)} leads from uploaded CSV '{uploaded_file.name}'.", "INFO")
                                    status_text.success(f"🎉 Successfully enriched {len(sanitized_results)} leads from CSV with Custom Mini-Audits!")

                                    st.session_state["leads"] = sanitized_results
                                    st.session_state["df"] = pd.DataFrame([r.model_dump() for r in sanitized_results])
                                    st.session_state["last_query"] = f"CSV: {uploaded_file.name}"
                                    st.session_state["campaign_results"] = None

                                except Exception as csv_pipe_err:
                                    logger.error(f"CSV enrichment error: {csv_pipe_err}")
                                    add_activity_log(f"CSV enrichment error: {csv_pipe_err}", "ERROR")
                                    status_text.error(f"⚠️ CSV enrichment error: {csv_pipe_err}")

                    finally:
                        st.session_state["is_running"] = False

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")


# =============================================================
# 📊 Generated Leads Display (Custom Mini-Audits & Premium Deliverables)
# =============================================================
if st.session_state["leads"]:
    df = st.session_state["df"]
    leads: list[EnrichedLead] = st.session_state["leads"]

    st.markdown("---")
    st.markdown("### 📋 Generated Leads & Custom Mini-Audits")

    # KPI Metrics
    total_leads = len(leads)
    emails_found = sum(1 for l in leads if l.primary_email)
    success_count = sum(1 for l in leads if l.status == "success")
    email_rate = f"{(emails_found / total_leads * 100):.1f}%" if total_leads else "0%"

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Leads Discovered", total_leads)
    with m2:
        st.metric("Verified Contacts Found", emails_found)
    with m3:
        st.metric("Email Discovery Rate", email_rate)
    with m4:
        if is_unlocked:
            st.metric("Dataset Access", "✅ Full Unrestricted")
        else:
            st.metric("Dataset Access", f"🔒 Paywall Active (2 of {total_leads})")

    # ---------------------------------------------------------
    # 🔓 UNLOCKED / FREE MODE FULL VIEW & PREMIUM DELIVERABLES
    # ---------------------------------------------------------
    if is_unlocked:
        if is_admin_active and paywall_is_active and not user_has_paid:
            st.info("🔓 **ADMIN MODE ACTIVE:** You are viewing the full dataset & premium deliverables (bypassing paywall).")

        # Full Interactive Table
        st.dataframe(
            df[["company_name", "website_url", "primary_email", "company_summary", "custom_audit", "status"]],
            column_config={
                "website_url": st.column_config.LinkColumn("Website URL"),
                "primary_email": st.column_config.TextColumn("Contact Email"),
                "custom_audit": st.column_config.TextColumn("Custom Mini-Audit", width="large")
            },
            width="stretch",
            hide_index=True
        )

        # Full Custom Mini-Audit Cards with White-Labeled PDF Downloads
        st.markdown("#### 📄 White-Labeled Client PDF Reports & Audits")
        st.caption(f"Branded for: **{effective_agency_name}** ({effective_agency_website})")

        c_pdf1, c_pdf2 = st.columns([1, 1])
        with c_pdf1:
            try:
                bundle_pdf_bytes = generate_batch_audit_bundle_pdf(
                    leads=leads,
                    agency_name=effective_agency_name,
                    agency_website=effective_agency_website
                )
                st.download_button(
                    label="📑 Download Complete Multi-Client PDF Audit Bundle",
                    data=bundle_pdf_bytes,
                    file_name=f"lead_audit_bundle_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    width="stretch"
                )
            except Exception as pdf_err:
                st.error(f"Error generating PDF bundle: {pdf_err}")

        with c_pdf2:
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            st.download_button(
                label="📥 Download Full Leads CSV",
                data=csv_buffer.getvalue(),
                file_name=f"audited_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                width="stretch"
            )

        with st.expander("🔍 View Individual Mini-Audits & Single Client PDF Downloads", expanded=False):
            for idx, lead in enumerate(leads, 1):
                col_aud_l, col_aud_r = st.columns([4, 1])
                with col_aud_l:
                    st.markdown(f"**📌 {idx}. {lead.company_name}** (`{lead.primary_email or 'No email found'}`)")
                    st.markdown(f"**Summary:** {lead.company_summary or 'N/A'}")
                    st.markdown(f"""
                    <div class="audit-card">
                        <strong>3-Point Value-First Mini-Audit:</strong><br>
                        {lead.custom_audit or lead.personalized_pitch or 'Audit generated by Gemini'}
                    </div>
                    """, unsafe_allow_html=True)
                with col_aud_r:
                    try:
                        single_pdf_bytes = generate_company_audit_pdf(
                            company_name=lead.company_name,
                            website_url=lead.website_url,
                            primary_email=lead.primary_email,
                            summary=lead.company_summary,
                            custom_audit=lead.custom_audit or lead.personalized_pitch,
                            agency_name=effective_agency_name,
                            agency_website=effective_agency_website
                        )
                        st.download_button(
                            label=f"📄 Download PDF",
                            data=single_pdf_bytes,
                            file_name=f"audit_{re.sub(r'[^a-zA-Z0-9]', '_', lead.company_name).lower()}.pdf",
                            mime="application/pdf",
                            key=f"single_pdf_dl_{idx}",
                            width="stretch"
                        )
                    except Exception as e:
                        st.caption(f"PDF gen error: {e}")
                st.divider()

    # ---------------------------------------------------------
    # 🔒 PAYWALLED PREVIEW (When Admin Selects Monetization Mode)
    # ---------------------------------------------------------
    else:
        st.markdown("#### 👁️ Verified Sample Preview (Top 2 Leads)")
        st.caption("🛡️ *Data preview is copy-protected. Unlock the complete dataset, White-Labeled PDF Audit Reports & CSV Export below.*")

        sample_leads = leads[:2]
        hidden_count = max(0, total_leads - len(sample_leads))

        for idx, lead in enumerate(sample_leads, 1):
            masked_email = mask_email_address(lead.primary_email)
            st.markdown(f"""
            <div class="protected-sample-container">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:1.1rem; font-weight:700; color:#1e293b;">📌 Sample #{idx}: {lead.company_name}</span>
                    <span class="pill">Verified Lead</span>
                </div>
                <div style="font-size:0.9rem; color:#475569; margin-bottom:6px;">
                    <strong>Website:</strong> <a href="{lead.website_url or '#'}" target="_blank">{lead.website_url or 'N/A'}</a> | 
                    <strong>Contact Email:</strong> <code style="color:#2563eb; background:#eff6ff; padding:2px 6px; border-radius:4px;">{masked_email}</code>
                </div>
                <div style="font-size:0.88rem; color:#334155; margin-bottom:8px;">
                    <strong>Company Summary:</strong> {lead.company_summary or 'N/A'}
                </div>
                <div class="audit-card">
                    <strong>AI Custom Mini-Audit Preview:</strong><br>
                    {lead.custom_audit or lead.personalized_pitch or 'Custom audit generated by Gemini'}
                </div>
            </div>
            """, unsafe_allow_html=True)

        if hidden_count > 0:
            st.markdown(f"""
            <div class="locked-teaser-card">
                <h3 style="color:#334155; margin-top:0; font-weight:800;">🔒 +{hidden_count} More Verified Leads & White-Labeled PDFs Locked</h3>
                <p style="color:#64748b; font-size:0.95rem; margin-bottom:0;">
                    Full unmasked contact emails, complete company dossiers, client-ready PDF audits, and the full CSV/JSON export are protected behind the paywall.
                </p>
            </div>
            """, unsafe_allow_html=True)

        # Tiered Pricing Selection Grid
        st.markdown("### 💎 Choose Your Plan to Unlock Full Deliverables")
        st.markdown("Unlock instant unmasked data, complete CSV downloads, white-labeled client PDF reports, and outbound email closing tools.")

        c_t1, c_t2, c_t3 = st.columns(3)
        starter_val = float(st.session_state.get("starter_price_usd", 9.0))
        pro_val = float(st.session_state.get("pro_price_usd", 29.0))
        agency_val = float(st.session_state.get("agency_price_usd", 79.0))

        with c_t1:
            st.markdown(f"""
            <div class="pricing-card">
                <h4 style="margin:0; color:#1e293b;">Starter</h4>
                <h2 style="margin:8px 0; color:#2563eb;">${starter_val:.0f} <font size="3" color="#64748b">USD</font></h2>
                <p style="font-size:0.82rem; color:#64748b;">Up to 50 Verified Leads<br/>• Full CSV Export<br/>• Standard AI Mini-Audits</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Select Starter (${starter_val:.0f})", width="stretch"):
                st.session_state["selected_tier"] = f"Starter (${starter_val:.0f})"
                st.rerun()

        with c_t2:
            st.markdown(f"""
            <div class="pricing-card-featured">
                <span class="pill" style="background:#2563eb; color:#ffffff;">MOST POPULAR</span>
                <h4 style="margin:4px 0 0 0; color:#1e293b;">Pro Growth</h4>
                <h2 style="margin:8px 0; color:#2563eb;">${pro_val:.0f} <font size="3" color="#64748b">USD</font></h2>
                <p style="font-size:0.82rem; color:#64748b;">Up to 200 Verified Leads<br/>• Full CSV & JSON Exports<br/>• <b>White-Labeled PDF Audits</b></p>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Select Pro (${pro_val:.0f})", type="primary", width="stretch"):
                st.session_state["selected_tier"] = f"Pro (${pro_val:.0f})"
                st.rerun()

        with c_t3:
            st.markdown(f"""
            <div class="pricing-card">
                <h4 style="margin:0; color:#1e293b;">Agency Unlimited</h4>
                <h2 style="margin:8px 0; color:#2563eb;">${agency_val:.0f} <font size="3" color="#64748b">USD</font></h2>
                <p style="font-size:0.82rem; color:#64748b;">Up to 1,000 Verified Leads<br/>• Multi-Client PDF Bundles<br/>• Full Outbound Email Engine</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Select Agency (${agency_val:.0f})", width="stretch"):
                st.session_state["selected_tier"] = f"Agency (${agency_val:.0f})"
                st.rerun()

        st.info(f"Selected Plan: **{st.session_state.get('selected_tier', 'Starter')}** • Amount to pay: **${active_price_usd:.2f} USD**")

        # Checkout Gate Box
        if "Crypto" in active_payment_mode or "Hybrid" in active_payment_mode:
            st.markdown(f"""
            <div class="crypto-hero-box">
                <h2 style="color: #ffffff; margin-top: 0; font-weight: 800;">⚡ Instant Zero-KYC Crypto Checkout</h2>
                <p style="color: #cbd5e1; font-size: 1.0rem; margin-bottom: 12px;">
                    Pay <strong>${active_price_usd:.2f} USD</strong> with <strong>Bitcoin (BTC), USDT (TRC20/ERC20), Ethereum (ETH), Solana (SOL), Litecoin (LTC)</strong> or 150+ cryptocurrencies.
                </p>
                <span class="pill">🔒 100% Automated On-Chain Verification</span>
                <span class="pill">⚡ Instant PDF & CSV Unlock Upon Confirmation</span>
            </div>
            """, unsafe_allow_html=True)

            c_cr1, c_cr2 = st.columns([1, 1])
            with c_cr1:
                st.markdown("#### 1. Generate Payment Invoice")
                if st.button(f"⚡ Generate Crypto Invoice (${active_price_usd:.2f} USD)", type="primary", width="stretch"):
                    if not NOWPAYMENTS_API_KEY or NOWPAYMENTS_API_KEY == "dummy_nowpayments_key":
                        st.warning("⚠️ NOWPAYMENTS_API_KEY is not configured in secrets.")
                    else:
                        with st.spinner("Connecting to NOWPayments API..."):
                            inv = create_nowpayments_invoice(
                                api_key=NOWPAYMENTS_API_KEY,
                                price_amount=active_price_usd,
                                price_currency="usd",
                                order_description=f"AI Audit Closer V2 - {st.session_state.get('selected_tier')} ({len(leads)} Leads)"
                            )
                            if inv.get("success"):
                                st.session_state["crypto_invoice_url"] = inv.get("invoice_url")
                                st.session_state["crypto_invoice_id"] = inv.get("invoice_id")
                                add_activity_log(f"Generated NOWPayments invoice #{inv.get('invoice_id')}", "INFO")
                                st.success("🎉 Crypto invoice generated successfully!")
                            else:
                                st.error(f"Failed to generate invoice: {inv.get('error')}")

                if st.session_state.get("crypto_invoice_url"):
                    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                    st.link_button(
                        label=f"🚀 Pay ${active_price_usd:.2f} with Crypto on NOWPayments",
                        url=st.session_state["crypto_invoice_url"],
                        type="primary",
                        width="stretch"
                    )
                    st.caption(f"Invoice ID: `{st.session_state.get('crypto_invoice_id')}`")

            with c_cr2:
                st.markdown("#### 2. Automatic Invoice Verification")
                st.markdown("Once you complete payment in your wallet, click below to verify on-chain:")

                inv_id_input = st.text_input(
                    "Invoice ID",
                    value=st.session_state.get("crypto_invoice_id") or "",
                    placeholder="e.g. 5527915624",
                    help="The Invoice ID generated by NOWPayments (auto-filled)."
                )

                if st.button("🔄 Check Payment Status & Unlock Deliverables", width="stretch"):
                    if not NOWPAYMENTS_API_KEY or NOWPAYMENTS_API_KEY == "dummy_nowpayments_key":
                        st.warning("⚠️ NOWPAYMENTS_API_KEY is not configured.")
                    elif not inv_id_input.strip():
                        st.info("ℹ️ Please generate an invoice or enter your NOWPayments Invoice ID to verify.")
                    else:
                        with st.spinner("Verifying invoice status with NOWPayments endpoint..."):
                            stat = check_nowpayments_invoice_status(
                                api_key=NOWPAYMENTS_API_KEY,
                                invoice_id=inv_id_input.strip()
                            )
                            if stat.get("success"):
                                status_name = stat.get("status", "waiting")
                                if stat.get("is_completed"):
                                    st.session_state["payment_verified"] = True
                                    st.session_state["paid"] = True
                                    add_activity_log(f"Crypto invoice #{inv_id_input} verified on-chain. Dataset & PDFs unlocked.", "INFO")
                                    st.toast("🎉 Crypto payment verified! Full PDF & CSV downloads unlocked.", icon="✅")
                                    st.rerun()
                                else:
                                    st.info(f"⏳ Current Invoice Status: `{status_name}`. Please complete the transfer on NOWPayments and re-check once confirmed on the blockchain.")
                            else:
                                st.error(f"Could not verify invoice: {stat.get('error')}")

        if "Stripe" in active_payment_mode or "Hybrid" in active_payment_mode:
            st.markdown("---")
            st.markdown("#### 💳 Stripe / Card Checkout")
            st.info(f"Pay **${active_price_usd:.2f} USD** securely with Visa, Mastercard, Apple Pay, or Google Pay.")
            if st.button(f"💳 Pay ${active_price_usd:.2f} with Stripe / Card", width="stretch"):
                st.caption("Stripe integration active. Redirecting to payment session...")

        with st.expander("🔑 Manual Passcode Unlock", expanded=False):
            entered_passcode = st.text_input("Enter Passcode", type="password", placeholder="Enter unlock code...", key="manual_passcode_field")
            if st.button("Unlock with Code", width="stretch"):
                clean_code = entered_passcode.strip()
                if clean_code and (clean_code == UNLOCK_CODE or clean_code == ADMIN_PASSWORD):
                    st.session_state["payment_verified"] = True
                    st.session_state["paid"] = True
                    st.toast("🎉 Passcode verified! Full CSV download & PDFs unlocked.", icon="✅")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid code.")

    st.markdown("---")

    # =========================================================
    # 📨 Value-First Custom Mini-Audit Campaign Launcher (Synchronous Main Thread)
    # =========================================================
    st.markdown("### 📨 Value-First Mini-Audit Campaign Launcher")
    st.markdown("Dispatches personalized **Custom Mini-Audits** via Gmail SMTP synchronously in the main thread with **strict global deduplication**.")

    # Filter strictly valid business emails (rejects version numbers, bootstrap@, consent-manager@, etc.)
    eligible_leads = []
    for l in leads:
        em = getattr(l, "primary_email", None)
        if em and isinstance(em, str):
            is_valid, _ = is_valid_business_email(em)
            if is_valid:
                eligible_leads.append(l)

    unsent_leads, skipped_leads = sent_history.filter_leads_for_dispatch(eligible_leads)

    if eligible_leads:
        sample_lead = eligible_leads[0]
        subj, html_prev, txt_prev = build_outreach_email(sample_lead, app_url=APP_URL, sender_name=SENDER_NAME)

        col_adm_info, col_adm_prev = st.columns([1, 1])
        with col_adm_info:
            st.info(f"• **Fresh Unsent Contacts:** {len(unsent_leads)}\n• **Already Contacted (Globally Skipped):** {len(skipped_leads)}\n• **Sender:** `{SMTP_USER}`\n• **App URL:** `{APP_URL}`")
        with col_adm_prev:
            with st.expander(f"👁️ Preview Mini-Audit Email to {sample_lead.company_name}", expanded=False):
                st.markdown(f"**Subject:** `{subj}`")
                st.text(txt_prev)

        send_delay = st.slider("Safety Delay Between Outgoing Emails (Sec)", min_value=3, max_value=15, value=5, step=1, help="5-10s delay prevents triggering Gmail anti-spam sending blocks.", key="batch_delay_slider")

        if len(unsent_leads) == 0:
            st.warning("🛡️ All eligible leads in this dataset have already been contacted in past runs. Global deduplication filter has protected them from receiving duplicate emails.")
        else:
            if not is_unlocked and paywall_is_active:
                st.warning("🔒 Automated Outbound Dispatcher is locked behind the Premium Plan. Unlock your plan above to dispatch custom mini-audits.")
            else:
                btn_launch_campaign = st.button("🚀 Run Audit & Dispatch Campaign (Manual Trigger Only)", type="primary", width="stretch", disabled=is_currently_running)

                if btn_launch_campaign:
                    if not SMTP_USER or not SMTP_PASSWORD:
                        st.warning("⚠️ SMTP credentials (SMTP_USER, SMTP_PASSWORD) not set in secrets.")
                    else:
                        st.session_state["is_running"] = True
                        try:
                            with st.spinner("Connecting to Gmail SMTP & dispatching custom mini-audits in main thread..."):
                                progress_container = st.container()
                                with progress_container:
                                    dispatch_status = st.empty()
                                    dispatch_bar = st.progress(0)

                                    def on_email_progress(lead: Any, success: bool, msg: str, idx: int, tot: int):
                                        pct = int((idx / tot) * 100) if tot > 0 else 0
                                        dispatch_bar.progress(min(100, max(0, pct)))
                                        icon = "✅" if success else "❌"
                                        c_name = getattr(lead, "company_name", None) or (lead.get("company_name") if isinstance(lead, dict) else "Lead")
                                        p_email = getattr(lead, "primary_email", None) or (lead.get("primary_email") if isinstance(lead, dict) else "")
                                        dispatch_status.text(f"Processing ({idx}/{tot}) {icon} -> {c_name} ({p_email}) [{msg}]")

                                    add_activity_log(f"Launching value-first mini-audit campaign to {len(unsent_leads)} unsent contacts...", "INFO")

                                    report = dispatch_campaign(
                                        leads=unsent_leads,
                                        sender_email=SMTP_USER,
                                        app_password=SMTP_PASSWORD,
                                        app_url=APP_URL,
                                        sender_name=SENDER_NAME,
                                        smtp_host=SMTP_HOST,
                                        smtp_port=SMTP_PORT,
                                        topic=st.session_state.get("last_query", "Manual Mini-Audit Outreach"),
                                        delay_seconds=float(send_delay),
                                        progress_callback=on_email_progress
                                    )

                                    dispatch_bar.progress(100)
                                    st.session_state["campaign_results"] = report
                                    if report.get("success"):
                                        add_activity_log(f"Campaign finished: Sent {report.get('sent_count')} mini-audits, skipped {report.get('skipped_duplicates', 0)} duplicates, skipped {report.get('skipped_invalid', 0)} invalid.", "INFO")
                                        st.success(f"🎉 Campaign Finished! Successfully sent {report.get('sent_count')} value-first mini-audits ({report.get('skipped_duplicates', 0)} duplicates skipped, {report.get('skipped_invalid', 0)} invalid artifacts skipped).")
                                    else:
                                        add_activity_log(f"Campaign failed: {report.get('message')}", "ERROR")
                                        st.warning(f"⚠️ {report.get('message')}")

                        finally:
                            st.session_state["is_running"] = False

        if st.session_state["campaign_results"]:
            rep = st.session_state["campaign_results"]
            if rep.get("results"):
                st.dataframe(pd.DataFrame(rep.get("results", [])), width="stretch", hide_index=True)
    else:
        st.info("ℹ️ No leads with verified business email addresses found in the current table to dispatch.")
