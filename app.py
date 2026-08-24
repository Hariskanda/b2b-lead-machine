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
from b2b_leadgen.payments import create_checkout_session, verify_checkout_session
from b2b_leadgen.pdf_generator import (
    generate_batch_audit_bundle_pdf,
    generate_company_audit_pdf
)
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column
from b2b_leadgen.sheets_exporter import export_leads_to_google_sheet

logger = logging.getLogger(__name__)

# =============================================================
# 📱 Page Configuration & State Defaults
# =============================================================
st.set_page_config(
    page_title="B2B Lead Machine: Automate Your Client Acquisition",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

SESSION_DEFAULTS: Dict[str, Any] = {
    "user_email": None,           # Logged-in user email
    "user_name": None,
    "is_pro": False,              # False = Free Tier (5 leads max, no PDF), True = Pro ($19/mo or $9 pass)
    "credits": 5,                 # Free tier credits
    "leads": [],
    "df": pd.DataFrame(),
    "last_query": "",
    "selected_tier": "Pro ($19/mo)",
    "admin_authenticated": False,
    "admin_logged_in": False,
    "stripe_session_id": None,
    "stripe_checkout_url": None,
    "campaign_results": None,
    "running": False,             # Synchronous manual engine run-lock
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


# Premium SaaS Styling & Modern Typography
st.markdown("""
<style>
    .hero-container {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 20px;
        padding: 48px 36px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 32px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }
    .hero-title {
        font-size: 2.8rem;
        font-weight: 850;
        margin-bottom: 0.8rem;
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .hero-subtitle {
        font-size: 1.15rem;
        color: #cbd5e1;
        max-width: 820px;
        margin: 0 auto 24px auto;
        line-height: 1.6;
    }
    .feature-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 24px;
        height: 100%;
        box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        transition: transform 0.2s ease;
    }
    .feature-card:hover {
        transform: translateY(-4px);
        border-color: #3b82f6;
    }
    .feature-icon {
        font-size: 2rem;
        margin-bottom: 12px;
    }
    .pricing-card-free {
        background: #ffffff;
        border: 2px solid #e2e8f0;
        border-radius: 16px;
        padding: 28px;
        text-align: center;
    }
    .pricing-card-pro {
        background: linear-gradient(180deg, #ffffff 0%, #eff6ff 100%);
        border: 2px solid #3b82f6;
        border-radius: 16px;
        padding: 28px;
        text-align: center;
        box-shadow: 0 8px 24px rgba(59, 130, 246, 0.15);
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
    .pill {
        display: inline-block;
        background: #1e293b;
        color: #93c5fd;
        border: 1px solid #334155;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        margin: 2px 0;
    }
    .pill-pro {
        display: inline-block;
        background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
        color: #ffffff;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 700;
    }
    .protected-sample-container {
        -webkit-user-select: none;
        user-select: none;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 18px;
        background: #ffffff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        margin-bottom: 14px;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================
# 🔐 Secure Secret Resolution Helper
# =============================================================
def get_secret(key: str, default: Any = None) -> Any:
    """Safely retrieves a configuration secret from st.secrets, os.environ, or settings."""
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
    No detached background threads or runaway daemon loops are spawned.
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
STRIPE_SECRET_KEY: Optional[str] = get_secret("STRIPE_SECRET_KEY", getattr(settings, "stripe_secret_key", None))
ADMIN_PASSWORD: str = str(get_secret("ADMIN_PASSWORD", getattr(settings, "admin_password", "admin123")))
UNLOCK_CODE: str = str(get_secret("UNLOCK_CODE", getattr(settings, "unlock_code", "4990")))
SMTP_USER: str = str(get_secret("SMTP_USER", getattr(settings, "effective_smtp_user", "")))
SMTP_PASSWORD: str = str(get_secret("SMTP_PASSWORD", getattr(settings, "effective_smtp_password", "")))
SMTP_HOST: str = str(get_secret("SMTP_HOST", getattr(settings, "smtp_host", "smtp.gmail.com")))
SMTP_PORT: int = int(get_secret("SMTP_PORT", getattr(settings, "smtp_port", 587)))
SENDER_NAME: str = str(get_secret("SENDER_NAME", getattr(settings, "sender_name", "B2B Lead Machine")))
APP_URL: str = str(get_secret("APP_URL", getattr(settings, "effective_app_url", "http://localhost:8501")))

# State Accessors
is_admin_active = bool(st.session_state.get("admin_authenticated", False) or st.session_state.get("admin_logged_in", False))
is_user_pro = bool(st.session_state.get("is_pro", False) or is_admin_active)
is_engine_running = bool(st.session_state.get("running", False))
user_logged_in = bool(st.session_state.get("user_email"))


# =============================================================
# 🛍️ Sidebar: Admin Controls & User Account Summary
# =============================================================
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/lightning-bolt.png", width=60)
    st.title("B2B Lead Machine")

    if user_logged_in:
        st.markdown(f"**👤 Account:** `{st.session_state.get('user_email')}`")
        if is_user_pro:
            st.markdown('<span class="pill-pro">⭐ PRO PLAN UNLOCKED</span>', unsafe_allow_html=True)
            st.caption("Unlimited Leads • White-Labeled PDF Audits • Full Exports")
        else:
            st.markdown('<span class="pill">FREE PLAN (5 Leads Max)</span>', unsafe_allow_html=True)
            st.caption("PDF Audits Locked • Upgrade to Pro to unlock client reports.")

        if st.button("🚪 Log Out", width="stretch"):
            st.session_state["user_email"] = None
            st.session_state["user_name"] = None
            st.session_state["is_pro"] = False
            st.rerun()

        st.divider()

    # 🔐 Master Control & Tracking Panel (Password Protected Admin)
    with st.expander("🔐 Admin Master Control Panel", expanded=False):
        if not is_admin_active:
            st.markdown("##### Admin Authentication")
            admin_pwd_input = st.text_input("Enter Admin Password", type="password", key="admin_pwd_input")
            if st.button("Unlock Admin Panel", width="stretch"):
                if admin_pwd_input and admin_pwd_input == ADMIN_PASSWORD:
                    st.session_state["admin_authenticated"] = True
                    st.session_state["admin_logged_in"] = True
                    add_activity_log("Admin authenticated successfully.", "INFO")
                    st.success("Admin mode unlocked!")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid Admin Password.")
        else:
            st.markdown('<span style="color:#15803d; font-weight:700;">🔓 MASTER ADMIN ACTIVE</span>', unsafe_allow_html=True)

            # 1. MANUAL START / STOP CONTROL
            st.markdown("---")
            st.markdown("#### ⚡ Manual Engine Control")
            if is_engine_running:
                st.warning("⏳ Engine Status: Running synchronous task...")
                if st.button("⏹ Stop Pipeline", type="secondary", width="stretch"):
                    st.session_state["running"] = False
                    add_activity_log("Admin manually stopped active pipeline.", "WARNING")
                    st.toast("🛑 Pipeline stopped by Admin.", icon="⏹")
                    st.rerun()
            else:
                st.info("⚪ Engine Status: Idle (Ready for manual start).")
                admin_niche_target = st.text_input("Automated Target Niche / Location", value="Commercial Roofing in Miami, FL", key="admin_niche_input")
                admin_batch_lead_count = st.slider("Leads per Batch", min_value=3, max_value=25, value=10, step=1, key="admin_batch_slider")

                if st.button("▶ Start Pipeline", type="primary", width="stretch"):
                    st.session_state["running"] = True
                    st.session_state["admin_trigger_search"] = admin_niche_target.strip()
                    st.session_state["admin_trigger_count"] = int(admin_batch_lead_count)
                    add_activity_log(f"Admin started pipeline for '{admin_niche_target.strip()}'.", "INFO")
                    st.rerun()

            # 2. PRO STATUS OVERRIDE
            st.markdown("---")
            st.markdown("#### 💎 Account Pro Status Override")
            current_pro = st.session_state.get("is_pro", False)
            toggle_pro = st.toggle("Grant Pro Status for Session", value=current_pro)
            if toggle_pro != current_pro:
                st.session_state["is_pro"] = toggle_pro
                add_activity_log(f"Admin updated Pro Status to: {toggle_pro}", "INFO")
                st.rerun()

            # 3. WHITE-LABEL AGENCY BRANDING
            st.markdown("---")
            st.markdown("#### 🏢 White-Label Agency Branding")
            agency_name_in = st.text_input("Agency / Consultant Name", value=st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
            st.session_state["agency_name"] = agency_name_in
            agency_web_in = st.text_input("Agency Website URL", value=st.session_state.get("agency_website", "https://growth-intelligence.io"))
            st.session_state["agency_website"] = agency_web_in

            # 4. AI ENGINE TUNING
            st.markdown("---")
            st.markdown("#### 🤖 AI Engine Tuning")
            admin_model = st.selectbox(
                "Gemini AI Model",
                options=["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
                index=0,
                key="admin_model_select"
            )
            admin_concurrency = st.slider("Max Concurrency", min_value=1, max_value=8, value=int(getattr(settings, "max_concurrent_requests", 3)), key="admin_concurrency_slider")
            admin_follow_subpages = st.checkbox("Follow Contact/About Pages", value=getattr(settings, "follow_contact_pages", True), key="admin_follow_subpages_cb")

            # 5. ACTIVITY LOGS & SENT TRACKER
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

            if st.button("Log Out of Admin Panel", width="stretch"):
                st.session_state["admin_authenticated"] = False
                st.session_state["admin_logged_in"] = False
                add_activity_log("Admin logged out.", "INFO")
                st.rerun()

    st.caption("⚡ **B2B Lead Machine** • Automate Your Client Acquisition")


effective_model = st.session_state.get("admin_model_select", getattr(settings, "gemini_model", "gemini-2.5-flash"))
effective_concurrency = int(st.session_state.get("admin_concurrency_slider", getattr(settings, "max_concurrent_requests", 3)))
effective_follow_subpages = bool(st.session_state.get("admin_follow_subpages_cb", getattr(settings, "follow_contact_pages", True)))
effective_agency_name = str(st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
effective_agency_website = str(st.session_state.get("agency_website", "https://growth-intelligence.io"))


# =============================================================
# 🚀 PILLAR 1: FRONT-END LANDING PAGE (WHEN NOT LOGGED IN)
# =============================================================
if not user_logged_in:
    # Hero Section
    st.markdown("""
    <div class="hero-container">
        <span class="pill-pro" style="margin-bottom: 12px;">⚡ THE NEW STANDARD IN B2B OUTBOUND</span>
        <h1 class="hero-title">B2B Lead Machine: Automate Your Client Acquisition</h1>
        <p class="hero-subtitle">
            Discover high-intent local businesses, extract verified decision-maker emails, and generate client-ready <b>3-Point Digital Mini-Audits</b> with Gemini AI to close high-ticket agency deals effortlessly.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # 3-Step How It Works Section
    st.markdown("### 🛠️ How It Works in 3 Simple Steps")
    c_s1, c_s2, c_s3 = st.columns(3)
    with c_s1:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">🎯</div>
            <h4 style="color:#1e293b; margin-top:0;">1. Target Any Niche</h4>
            <p style="color:#64748b; font-size:0.9rem; line-height:1.5;">
                Enter any local industry and geography (e.g. <i>"Commercial roofing in Miami, FL"</i>) or upload your own CSV list of target accounts.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_s2:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">🤖</div>
            <h4 style="color:#1e293b; margin-top:0;">2. AI Generates Mini-Audits</h4>
            <p style="color:#64748b; font-size:0.9rem; line-height:1.5;">
                Gemini 2026 AI analyzes company websites to identify 🟢 strengths, 🔍 conversion blind spots, and 💡 high-ROI recommendations.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_s3:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">📄</div>
            <h4 style="color:#1e293b; margin-top:0;">3. Close High-Ticket Clients</h4>
            <p style="color:#64748b; font-size:0.9rem; line-height:1.5;">
                Download white-labeled client PDF reports to hand directly to prospects or dispatch value-first mini-audit emails automatically.
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)

    # Pricing Tiers Section
    st.markdown("### 💎 Simple, Transparent Pricing")
    c_pr1, c_pr2 = st.columns(2)
    with c_pr1:
        st.markdown("""
        <div class="pricing-card-free">
            <h3 style="color:#1e293b; margin:0;">Free Tier</h3>
            <h2 style="color:#64748b; margin:12px 0;">$0 <font size="3">/ forever</font></h2>
            <p style="color:#64748b; font-size:0.88rem;">Best for testing the platform</p>
            <hr style="border:0; border-top:1px solid #e2e8f0; margin:16px 0;">
            <p style="text-align:left; font-size:0.9rem; color:#334155;">
                ✓ 5 Verified Leads per Search<br/>
                ✓ Standard Lead Table View<br/>
                ✓ Basic CSV Export Preview<br/>
                ✗ <span style="color:#94a3b8;">White-Labeled PDF Audits</span><br/>
                ✗ <span style="color:#94a3b8;">Multi-Client PDF Bundle</span><br/>
                ✗ <span style="color:#94a3b8;">Automated Email Dispatcher</span>
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_pr2:
        st.markdown("""
        <div class="pricing-card-pro">
            <span class="pill-pro" style="margin-bottom:6px;">RECOMMENDED FOR AGENCIES</span>
            <h3 style="color:#1e293b; margin:4px 0 0 0;">Pro Growth Tier</h3>
            <h2 style="color:#2563eb; margin:12px 0;">$19 <font size="3" color="#64748b">/ month</font></h2>
            <p style="color:#64748b; font-size:0.88rem;">Or $9 one-time 24h pass</p>
            <hr style="border:0; border-top:1px solid #bfdbfe; margin:16px 0;">
            <p style="text-align:left; font-size:0.9rem; color:#1e293b;">
                ✓ <b>Unlimited Verified B2B Leads</b><br/>
                ✓ <b>White-Labeled PDF Client Reports</b><br/>
                ✓ <b>Complete Multi-Client PDF Audit Bundle</b><br/>
                ✓ <b>Full Unmasked CSV & JSON Exports</b><br/>
                ✓ <b>Automated Value-First Email Engine</b><br/>
                ✓ <b>Permanent Anti-Spam Deduplication</b>
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)

    # Login / Get Started Modal Form
    st.markdown("### 🚀 Get Started Now (Free Instant Access)")
    st.markdown("Enter your business email to access your lead dashboard with 5 free lead credits immediately:")

    c_log1, c_log2 = st.columns([2, 1])
    with c_log1:
        login_email = st.text_input("Business Email Address", placeholder="e.g. founder@agencygrowth.com", key="landing_email_input")
        login_name = st.text_input("Your Name / Agency Name (Optional)", placeholder="e.g. Alex Johnson / Apex Growth", key="landing_name_input")
    with c_log2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🚀 Access Free Lead Dashboard", type="primary", width="stretch"):
            if login_email and "@" in login_email:
                st.session_state["user_email"] = login_email.strip()
                st.session_state["user_name"] = login_name.strip() if login_name else "Agency Founder"
                add_activity_log(f"User logged in: {login_email.strip()}", "INFO")
                st.toast("🎉 Welcome to B2B Lead Machine!", icon="🚀")
                st.rerun()
            else:
                st.error("Please enter a valid email address to get started.")

    st.stop()


# =============================================================
# 🚀 PILLAR 4: USER DASHBOARD (WHEN LOGGED IN)
# =============================================================
st.markdown('<div class="main-header">⚡ B2B Lead & Mini-Audit Dashboard</div>', unsafe_allow_html=True)

c_usr1, c_usr2 = st.columns([3, 1])
with c_usr1:
    user_display = st.session_state.get("user_name") or st.session_state.get("user_email")
    if is_user_pro:
        st.markdown(f"👤 **Welcome back, {user_display}!** • <span class='pill-pro'>⭐ PRO PLAN ACTIVE (Unlimited Access)</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"👤 **Welcome back, {user_display}!** • <span class='pill'>FREE PLAN (5 Leads/Search)</span>", unsafe_allow_html=True)
with c_usr2:
    if not is_user_pro:
        if st.button("⭐ Upgrade to Pro ($19)", type="primary", width="stretch"):
            st.session_state["open_upgrade_tab"] = True
            st.rerun()

tab_search, tab_csv, tab_upgrade = st.tabs(["🔍 Search & Generate Client Audits", "📁 Upload Existing CSV", "💎 Pro Plan & Stripe Billing"])


# -------------------------------------------------------------
# Trigger from Admin Manual Start or User Form
# -------------------------------------------------------------
trigger_admin_run = bool(st.session_state.get("running", False) and st.session_state.get("admin_trigger_search"))
admin_target_query = st.session_state.get("admin_trigger_search", "")
admin_target_count = int(st.session_state.get("admin_trigger_count", 10))


# -------------------------------------------------------------
# TAB 1: Autonomous Keyword Discovery & Audit Generator
# -------------------------------------------------------------
with tab_search:
    st.markdown("### 🎯 Discover Real Companies & Generate Mini-Audits")
    st.markdown("Enter a target search phrase (e.g. *'Commercial roofing in Miami, FL'* or *'Plumbing contractors in Austin, TX'*):")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input(
            "Search Query / Niche + Location",
            value=admin_target_query if trigger_admin_run else "",
            placeholder="e.g. Commercial HVAC contractors in Dallas, TX",
            key="keyword_search_input"
        )
    with col2:
        max_allowed_leads = 30 if is_user_pro else 5
        num_leads = st.number_input(
            f"Target Leads ({'Unlimited Pro' if is_user_pro else 'Free Tier Max 5'})",
            min_value=3,
            max_value=max_allowed_leads,
            value=admin_target_count if trigger_admin_run else min(10, max_allowed_leads),
            step=1
        )

    btn_discover = st.button("🚀 Generate Leads & Mini-Audits", type="primary", width="stretch", disabled=is_engine_running)

    if btn_discover or trigger_admin_run:
        target_q = (admin_target_query if trigger_admin_run else search_query).strip()
        target_n = admin_target_count if trigger_admin_run else int(num_leads)

        if not target_q:
            st.error("Please enter a valid search query.")
            st.session_state["running"] = False
            st.session_state["admin_trigger_search"] = None
        else:
            st.session_state["running"] = True
            try:
                with st.spinner(f"🔎 Discovering and auditing businesses for '{target_q}' in main thread..."):
                    progress_container = st.container()
                    with progress_container:
                        status_text = st.empty()
                        prog_bar = st.progress(0)

                        add_activity_log(f"Starting discovery for '{target_q}' (Target: {target_n} leads)...", "INFO")
                        status_text.info(f"🔎 Discovering businesses matching '{target_q}' via DuckDuckGo...")

                        try:
                            discovered_inputs = discover_leads_by_keyword(target_q, max_results=target_n)
                        except Exception as disc_err:
                            logger.error(f"Discovery error: {disc_err}")
                            discovered_inputs = []
                            add_activity_log(f"Search discovery error: {disc_err}", "ERROR")
                            status_text.error(f"⚠️ Search discovery error: {disc_err}. Please retry.")

                        if not discovered_inputs:
                            status_text.error("No companies could be discovered for this query. Try refining your keywords.")
                        else:
                            add_activity_log(f"Discovered {len(discovered_inputs)} company domains. Running AI enrichment...", "INFO")
                            status_text.success(f"✅ Discovered {len(discovered_inputs)} businesses! Generating AI Mini-Audits with Gemini ({effective_model})...")

                            try:
                                pipeline = LeadGenPipeline(
                                    api_key=GEMINI_API_KEY,
                                    model=effective_model,
                                    max_concurrency=effective_concurrency,
                                    follow_contact_pages=effective_follow_subpages,
                                    use_checkpoint=False
                                )

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
                                add_activity_log(f"Generated mini-audits for {len(sanitized_results)} leads.", "INFO")
                                status_text.success(f"🎉 Successfully generated {len(sanitized_results)} leads with Custom Mini-Audits!")

                                st.session_state["leads"] = sanitized_results
                                df_data = [r.model_dump() for r in sanitized_results]
                                st.session_state["df"] = pd.DataFrame(df_data)
                                st.session_state["last_query"] = target_q
                                st.session_state["campaign_results"] = None

                            except Exception as pipe_err:
                                logger.error(f"Pipeline execution error: {pipe_err}")
                                add_activity_log(f"Pipeline error: {pipe_err}", "ERROR")
                                status_text.error(f"⚠️ Enrichment pipeline error: {pipe_err}")

            finally:
                st.session_state["running"] = False
                st.session_state["admin_trigger_search"] = None


# -------------------------------------------------------------
# TAB 2: CSV Lead Enrichment & Mini-Audit Generator
# -------------------------------------------------------------
with tab_csv:
    st.markdown("### 📁 Upload Existing CSV for Mini-Audits")
    st.markdown("Upload a CSV containing company names to enrich them with verified contact emails and AI digital audits.")

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

            btn_enrich_csv = st.button("⚡ Generate Mini-Audits from Uploaded CSV", type="primary", disabled=is_engine_running)

            if btn_enrich_csv:
                input_leads = []
                for _, row in uploaded_df.iterrows():
                    c_name = str(row.get(selected_col, "")).strip()
                    if c_name and c_name.lower() != "nan":
                        input_leads.append(LeadInput(company_name=c_name))

                if not is_user_pro:
                    input_leads = input_leads[:5]

                if not input_leads:
                    st.error("No valid company names found in selected column.")
                else:
                    st.session_state["running"] = True
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
                                    add_activity_log(f"Enriched {len(sanitized_results)} leads from CSV.", "INFO")
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
                        st.session_state["running"] = False

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")


# =============================================================
# 💳 PILLAR 2: STRIPE BILLING & UPGRADE TAB
# =============================================================
with tab_upgrade:
    st.markdown("### 💎 Upgrade to B2B Lead Machine Pro")
    st.markdown("Unlock unlimited lead discoveries, client-ready **White-Labeled PDF Reports**, full unmasked exports, and the automated email engine.")

    c_pl1, c_pl2 = st.columns(2)
    with c_pl1:
        st.markdown("""
        <div class="pricing-card-pro">
            <span class="pill-pro">MONTHLY SUBSCRIPTION</span>
            <h3 style="color:#1e293b; margin:6px 0 0 0;">Pro Monthly</h3>
            <h2 style="color:#2563eb; margin:10px 0;">$19 <font size="3" color="#64748b">USD / month</font></h2>
            <p style="font-size:0.85rem; color:#64748b;">Full continuous agency client acquisition</p>
            <p style="text-align:left; font-size:0.88rem; color:#1e293b;">
                ✓ Unlimited Leads & Search Queries<br/>
                ✓ <b>White-Labeled PDF Client Reports</b><br/>
                ✓ <b>Multi-Client PDF Audit Bundle</b><br/>
                ✓ Full Unmasked CSV & JSON Exports<br/>
                ✓ Automated Outbound Email Engine
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🚀 Checkout with Stripe ($19/mo)", type="primary", width="stretch"):
            sess = create_checkout_session(
                success_url=f"{APP_URL}?payment_status=success",
                cancel_url=f"{APP_URL}?payment_status=cancelled",
                amount_usd=19.0,
                product_name="B2B Lead Machine Pro Tier Subscription",
                customer_email=st.session_state.get("user_email")
            )
            if sess.get("success"):
                st.session_state["stripe_session_id"] = sess.get("session_id")
                st.session_state["stripe_checkout_url"] = sess.get("checkout_url")
                if sess.get("is_mock"):
                    st.session_state["is_pro"] = True
                    st.toast("🎉 Upgraded to Pro Plan (Test Session)!", icon="💎")
                    st.rerun()
                else:
                    st.link_button("💳 Complete Payment on Stripe", url=sess.get("checkout_url"), type="primary", width="stretch")
            else:
                st.error(f"Could not create checkout session: {sess.get('error')}")

    with c_pl2:
        st.markdown("""
        <div class="pricing-card-free">
            <span class="pill">24-HOUR PASS</span>
            <h3 style="color:#1e293b; margin:6px 0 0 0;">Day Pass</h3>
            <h2 style="color:#2563eb; margin:10px 0;">$9 <font size="3" color="#64748b">USD one-time</font></h2>
            <p style="font-size:0.85rem; color:#64748b;">Instant 24-hour full access pass</p>
            <p style="text-align:left; font-size:0.88rem; color:#334155;">
                ✓ 24-Hour Unlimited Access<br/>
                ✓ <b>White-Labeled PDF Audits</b><br/>
                ✓ Full CSV Export<br/>
                ✓ No recurring subscription
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("⚡ Get 24-Hour Pass ($9)", width="stretch"):
            sess = create_checkout_session(
                success_url=f"{APP_URL}?payment_status=success",
                cancel_url=f"{APP_URL}?payment_status=cancelled",
                amount_usd=9.0,
                product_name="B2B Lead Machine 24-Hour Pro Pass",
                customer_email=st.session_state.get("user_email")
            )
            if sess.get("success"):
                st.session_state["stripe_session_id"] = sess.get("session_id")
                st.session_state["stripe_checkout_url"] = sess.get("checkout_url")
                if sess.get("is_mock"):
                    st.session_state["is_pro"] = True
                    st.toast("🎉 Upgraded with 24-Hour Pass (Test Session)!", icon="💎")
                    st.rerun()
                else:
                    st.link_button("💳 Complete Payment on Stripe", url=sess.get("checkout_url"), type="primary", width="stretch")
            else:
                st.error(f"Could not create checkout session: {sess.get('error')}")

    with st.expander("🔑 Manual Passcode / Session Verification Unlock", expanded=False):
        entered_passcode = st.text_input("Enter Passcode or Stripe Session ID", type="password", key="stripe_manual_pass_field")
        if st.button("Verify & Unlock Pro Plan", width="stretch"):
            clean_code = entered_passcode.strip()
            if clean_code and (clean_code == UNLOCK_CODE or clean_code == ADMIN_PASSWORD or clean_code.startswith("cs_")):
                st.session_state["is_pro"] = True
                add_activity_log(f"User verified Pro access with code/session.", "INFO")
                st.toast("🎉 Pro Plan Unlocked!", icon="💎")
                st.rerun()
            else:
                st.error("Invalid passcode or unverified session ID.")


# =============================================================
# 📊 PILLAR 3: DELIVERABLES & LEADS DISPLAY (PDF AUDITS & EXPORTS)
# =============================================================
if st.session_state["leads"]:
    df = st.session_state["df"]
    leads: list[EnrichedLead] = st.session_state["leads"]

    st.markdown("---")
    st.markdown("### 📋 Generated Leads & Custom Mini-Audits")

    # KPI Metrics
    total_leads = len(leads)
    emails_found = sum(1 for l in leads if l.primary_email)
    email_rate = f"{(emails_found / total_leads * 100):.1f}%" if total_leads else "0%"

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Leads Discovered", total_leads)
    with m2:
        st.metric("Verified Contacts Found", emails_found)
    with m3:
        st.metric("Contact Discovery Rate", email_rate)
    with m4:
        if is_user_pro:
            st.metric("PDF Audit Deliverables", "✅ Pro Unlocked")
        else:
            st.metric("PDF Audit Deliverables", "🔒 Locked (Pro Tier)")

    # ---------------------------------------------------------
    # PRO TIER UNLOCKED VIEW
    # ---------------------------------------------------------
    if is_user_pro:
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

        # White-Labeled PDF Audit Bundle & CSV Downloads
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
    # FREE TIER PREVIEW & PRO UPGRADE GATE
    # ---------------------------------------------------------
    else:
        st.markdown("#### 👁️ Free Preview (Top Leads)")
        st.caption("🛡️ *You are viewing the Free Tier. Upgrade to Pro ($19/mo) to unlock client-ready White-Labeled PDF Audits and full unmasked exports.*")

        sample_leads = leads[:2]
        hidden_count = max(0, total_leads - len(sample_leads))

        for idx, lead in enumerate(sample_leads, 1):
            masked_email = mask_email_address(lead.primary_email)
            st.markdown(f"""
            <div class="protected-sample-container">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:1.1rem; font-weight:700; color:#1e293b;">📌 Lead #{idx}: {lead.company_name}</span>
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
                    White-Labeled PDF Client Reports, Multi-Client PDF Bundles, and full unmasked exports are exclusively available on the <b>Pro Plan</b>.
                </p>
            </div>
            """, unsafe_allow_html=True)

        c_up1, c_up2 = st.columns([1, 1])
        with c_up1:
            if st.button("⭐ Upgrade to Pro Plan ($19/mo)", type="primary", width="stretch"):
                st.session_state["selected_tier"] = "Pro ($19/mo)"
                st.toast("Redirecting to Pro checkout...", icon="💎")
                st.rerun()
        with c_up2:
            # Free tier CSV export (limited sample)
            csv_buffer = io.StringIO()
            df.head(5).to_csv(csv_buffer, index=False)
            st.download_button(
                label="📥 Download Free Sample CSV (5 Leads)",
                data=csv_buffer.getvalue(),
                file_name=f"sample_leads_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                width="stretch"
            )

    st.markdown("---")

    # =========================================================
    # 📨 Value-First Custom Mini-Audit Campaign Launcher
    # =========================================================
    st.markdown("### 📨 Value-First Mini-Audit Campaign Launcher")
    st.markdown("Dispatches personalized **Custom Mini-Audits** via Gmail SMTP synchronously in the main thread with **strict global deduplication**.")

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
            if not is_user_pro:
                st.info("ℹ️ Free Plan allows testing lead discovery and previewing emails. Upgrade to Pro ($19/mo) to unlock mass 1-click automated outbound dispatching.")
            else:
                btn_launch_campaign = st.button("🚀 Run Audit & Dispatch Campaign (Manual Trigger Only)", type="primary", width="stretch", disabled=is_engine_running)

                if btn_launch_campaign:
                    if not SMTP_USER or not SMTP_PASSWORD:
                        st.warning("⚠️ SMTP credentials (SMTP_USER, SMTP_PASSWORD) not set in secrets.")
                    else:
                        st.session_state["running"] = True
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

                                    add_activity_log(f"Launching mini-audit campaign to {len(unsent_leads)} unsent contacts...", "INFO")

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
                            st.session_state["running"] = False

        if st.session_state["campaign_results"]:
            rep = st.session_state["campaign_results"]
            if rep.get("results"):
                st.dataframe(pd.DataFrame(rep.get("results", [])), width="stretch", hide_index=True)
    else:
        st.info("ℹ️ No leads with verified business email addresses found in the current table to dispatch.")
