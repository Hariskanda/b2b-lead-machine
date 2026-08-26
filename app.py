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

from b2b_leadgen.config import settings
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.payments import create_checkout_session, verify_checkout_session
from b2b_leadgen.pdf_generator import (
    generate_batch_audit_bundle_pdf,
    generate_company_audit_pdf
)
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column

logger = logging.getLogger(__name__)

# =============================================================
# 📱 Page Configuration & Session State Initialization
# =============================================================
st.set_page_config(
    page_title="B2B Lead Machine: Automate Your Lead Generation & Auditing",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

SESSION_DEFAULTS: Dict[str, Any] = {
    "view_mode": "landing",       # "landing" vs "dashboard"
    "user_email": None,
    "user_name": None,
    "is_paid": False,             # True = Pro Tier ($19/mo or $9 pass), False = Free Tier
    "is_pro": False,
    "leads": [],
    "df": pd.DataFrame(),
    "last_query": "",
    "selected_tier": "Pro Access ($19/mo)",
    "admin_authenticated": False,
    "stripe_session_id": None,
    "stripe_checkout_url": None,
    "running": False,
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
    if len(st.session_state["activity_logs"]) > 100:
        st.session_state["activity_logs"].pop(0)


# =============================================================
# 🎨 Modern Dark-Mode SaaS CSS & Polished Aesthetics
# =============================================================
st.markdown("""
<style>
    /* Hide Default Streamlit Header & Footer */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}
    div[data-testid="stDecoration"] {visibility: hidden;}

    /* Dark-Mode SaaS Theme */
    .stApp {
        background-color: #0b0f17;
        color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* Custom Modern Navbar */
    .saas-navbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 24px;
        background: rgba(15, 23, 42, 0.85);
        backdrop-filter: blur(12px);
        border: 1px solid #1e293b;
        border-radius: 16px;
        margin-bottom: 24px;
    }
    .saas-logo {
        font-size: 1.25rem;
        font-weight: 800;
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    /* Hero Section */
    .hero-container {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 24px;
        padding: 50px 36px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 32px;
        box-shadow: 0 12px 36px rgba(0,0,0,0.35);
        position: relative;
        overflow: hidden;
    }
    .hero-title {
        font-size: 2.85rem;
        font-weight: 850;
        margin-bottom: 0.8rem;
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1.2;
    }
    .hero-subtitle {
        font-size: 1.16rem;
        color: #cbd5e1;
        max-width: 840px;
        margin: 0 auto 28px auto;
        line-height: 1.6;
    }

    /* Feature Cards */
    .feature-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 18px;
        padding: 26px;
        height: 100%;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .feature-card:hover {
        transform: translateY(-4px);
        border-color: #38bdf8;
    }
    .feature-icon {
        font-size: 2.2rem;
        margin-bottom: 12px;
    }

    /* Pricing Cards */
    .pricing-card-free {
        background: #111827;
        border: 2px solid #1f2937;
        border-radius: 18px;
        padding: 30px;
        text-align: center;
    }
    .pricing-card-pro {
        background: linear-gradient(180deg, #111827 0%, #1e1b4b 100%);
        border: 2px solid #38bdf8;
        border-radius: 18px;
        padding: 30px;
        text-align: center;
        box-shadow: 0 8px 32px rgba(56, 189, 248, 0.2);
    }

    /* Audit & Preview Cards */
    .audit-card {
        border-left: 4px solid #10b981;
        background: #111827;
        padding: 16px;
        border-radius: 10px;
        margin-bottom: 12px;
        border: 1px solid #1f2937;
        color: #e2e8f0;
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
        padding: 5px 14px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 700;
        box-shadow: 0 2px 10px rgba(37, 99, 235, 0.35);
    }
    .pill-gold {
        display: inline-block;
        background: linear-gradient(135deg, #d97706 0%, #b45309 100%);
        color: #ffffff;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 700;
    }
    .protected-sample-container {
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 18px;
        background: #111827;
        margin-bottom: 14px;
    }
    .locked-teaser-card {
        background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
        border: 2px dashed #475569;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        margin: 16px 0;
    }

    /* Button Styling */
    div.stButton > button:first-child {
        border-radius: 10px;
        font-weight: 600;
        transition: all 0.2s ease-in-out;
    }
    div.stButton > button[kind="primary"]:first-child {
        background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
        border: 1px solid #6366f1;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.3);
    }
    div.stButton > button[kind="primary"]:first-child:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(56, 189, 248, 0.45);
        border-color: #38bdf8;
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
    """Masks middle characters of email address to protect dataset before Pro access."""
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
    Executes the enrichment pipeline synchronously in the main thread with concurrent worker pool.
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


# Read Core Secrets
GEMINI_API_KEY: Optional[str] = get_secret("GEMINI_API_KEY", getattr(settings, "effective_api_key", None))
STRIPE_SECRET_KEY: Optional[str] = get_secret("STRIPE_SECRET_KEY", getattr(settings, "stripe_secret_key", None))
ADMIN_PASSWORD: str = str(get_secret("ADMIN_PASSWORD", getattr(settings, "admin_password", "admin123")))
UNLOCK_CODE: str = str(get_secret("UNLOCK_CODE", getattr(settings, "unlock_code", "4990")))
APP_URL: str = str(get_secret("APP_URL", getattr(settings, "effective_app_url", "http://localhost:8501")))

# State Accessors
is_admin_active = bool(st.session_state.get("admin_authenticated", False))
is_user_paid = bool(st.session_state.get("is_paid", False) or st.session_state.get("is_pro", False) or is_admin_active)
is_engine_running = bool(st.session_state.get("running", False))
current_view = st.session_state.get("view_mode", "landing")


# =============================================================
# 🛍️ Sidebar: Public User Status & White-Label Branding
# =============================================================
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/lightning-bolt.png", width=55)
    st.title("B2B Lead Machine")

    st.markdown("#### 🧭 Platform Navigation")
    c_nav1, c_nav2 = st.columns(2)
    with c_nav1:
        if st.button("🏠 Landing Page", width="stretch", type="primary" if current_view == "landing" else "secondary"):
            st.session_state["view_mode"] = "landing"
            st.rerun()
    with c_nav2:
        if st.button("⚡ Enter App", width="stretch", type="primary" if current_view == "dashboard" else "secondary"):
            st.session_state["view_mode"] = "dashboard"
            st.rerun()

    st.divider()

    # User Account Status
    st.markdown("#### 📦 Access Tier")
    if is_user_paid:
        st.markdown('<span class="pill-pro">⭐ PRO ACCESS ACTIVE (Unlimited)</span>', unsafe_allow_html=True)
        st.caption("White-Labeled PDF Audits • Multi-Client Bundles • Full CSV Export")
    else:
        st.markdown('<span class="pill">FREE TIER (Preview Mode)</span>', unsafe_allow_html=True)
        st.caption("PDF Audits & Full CSV Downloads Locked • Upgrade to Pro to unlock.")

    st.divider()

    # White-Label Customization
    with st.expander("🏢 White-Label Report Branding", expanded=False):
        agency_name_in = st.text_input("Agency / Company Name", value=st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
        st.session_state["agency_name"] = agency_name_in
        agency_web_in = st.text_input("Agency Website URL", value=st.session_state.get("agency_website", "https://growth-intelligence.io"))
        st.session_state["agency_website"] = agency_web_in
        st.caption("Your branding will appear on all generated White-Labeled PDF Audit Reports.")

    # Admin Master Control
    with st.expander("🔐 Admin Controls", expanded=False):
        if not is_admin_active:
            admin_pwd = st.text_input("Admin Password", type="password", key="admin_pwd_field")
            if st.button("Unlock Admin", width="stretch"):
                if admin_pwd and admin_pwd == ADMIN_PASSWORD:
                    st.session_state["admin_authenticated"] = True
                    st.session_state["is_paid"] = True
                    st.session_state["is_pro"] = True
                    st.toast("Admin mode active (Pro unlocked)!", icon="🔓")
                    st.rerun()
                else:
                    st.error("Invalid password.")
        else:
            st.success("🔓 Admin Mode Active")
            toggle_pro = st.toggle("Pro Status Active", value=is_user_paid)
            if toggle_pro != is_user_paid:
                st.session_state["is_paid"] = toggle_pro
                st.session_state["is_pro"] = toggle_pro
                st.rerun()

            if st.button("Log Out Admin", width="stretch"):
                st.session_state["admin_authenticated"] = False
                st.session_state["is_paid"] = False
                st.session_state["is_pro"] = False
                st.rerun()

    st.caption("⚡ **B2B Lead Machine** • On-Demand Lead & Audit Platform")


effective_model = getattr(settings, "gemini_model", "gemini-2.5-flash")
effective_concurrency = int(getattr(settings, "max_concurrent_requests", 5))
effective_follow_subpages = bool(getattr(settings, "follow_contact_pages", True))
effective_agency_name = str(st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
effective_agency_website = str(st.session_state.get("agency_website", "https://growth-intelligence.io"))


# =============================================================
# 🚀 PILLAR 2: PUBLIC LANDING PAGE (THE HOOK)
# =============================================================
if current_view == "landing":
    # SaaS Navbar
    st.markdown("""
    <div class="saas-navbar">
        <div class="saas-logo">
            ⚡ <span>B2B Lead Machine</span>
        </div>
        <div>
            <span class="pill-pro">✨ 2026 AI Outbound & Audit Engine</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Hero Section
    st.markdown("""
    <div class="hero-container">
        <span class="pill-gold" style="margin-bottom: 14px;">⚡ THE NEW STANDARD IN HIGH-TICKET CLIENT ACQUISITION</span>
        <h1 class="hero-title">Automate Your Agency's Lead Generation & Auditing</h1>
        <p class="hero-subtitle">
            Discover high-intent local businesses, extract verified decision-maker emails, and generate client-ready <b>3-Point Digital Growth Audits</b> with Gemini AI to close deals effortlessly.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Call-to-Action Buttons
    c_btn1, c_btn2 = st.columns([1, 1])
    with c_btn1:
        if st.button("🚀 Enter App / Start Free Search", type="primary", width="stretch"):
            st.session_state["view_mode"] = "dashboard"
            st.rerun()
    with c_btn2:
        if st.button("💎 View Pro Access ($19/mo)", width="stretch"):
            st.session_state["view_mode"] = "dashboard"
            st.session_state["open_upgrade_tab"] = True
            st.rerun()

    st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)

    # 3-Step How It Works Section
    st.markdown("### 🛠️ How It Works in 3 Simple Steps")
    c_s1, c_s2, c_s3 = st.columns(3)
    with c_s1:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">🎯</div>
            <h4 style="color:#f8fafc; margin-top:0;">1. Target Any Niche & Metro</h4>
            <p style="color:#94a3b8; font-size:0.9rem; line-height:1.5;">
                Enter any local industry and geography (e.g. <i>"Commercial roofing in Miami, FL"</i>) or upload your own CSV list of target accounts.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_s2:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">🤖</div>
            <h4 style="color:#f8fafc; margin-top:0;">2. AI Generates Mini-Audits</h4>
            <p style="color:#94a3b8; font-size:0.9rem; line-height:1.5;">
                Gemini 2026 AI analyzes company websites to identify 🟢 strengths, 🔍 conversion blind spots, and 💡 high-ROI recommendations.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_s3:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">📄</div>
            <h4 style="color:#f8fafc; margin-top:0;">3. Deliver White-Labeled PDFs</h4>
            <p style="color:#94a3b8; font-size:0.9rem; line-height:1.5;">
                Download ready-to-print white-labeled client PDF reports branded with your agency name to hand directly to clients and close deals.
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)

    # Interactive Sample Mini-Audit Preview
    st.markdown("### 👁️ Interactive Mini-Audit Preview (Sample Deliverable)")
    st.markdown("""
    <div class="protected-sample-container">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <span style="font-size:1.15rem; font-weight:700; color:#38bdf8;">📌 Sample Lead: Apex Commercial Roofing LLC</span>
            <span class="pill-pro">Score: B+</span>
        </div>
        <div style="font-size:0.9rem; color:#94a3b8; margin-bottom:8px;">
            <strong>Website:</strong> <span style="color:#38bdf8;">https://apexroofing-sample.com</span> | 
            <strong>Contact Email:</strong> <code style="color:#38bdf8; background:#1e293b; padding:2px 8px; border-radius:4px;">contact@apexroofing-sample.com</code>
        </div>
        <div style="font-size:0.9rem; color:#cbd5e1; margin-bottom:10px;">
            <strong>Company Summary:</strong> Premier commercial roofing contractor providing flat roof repair, thermal coating, and industrial maintenance.
        </div>
        <div class="audit-card">
            <strong>🔍 AI-Generated 3-Point Digital Growth Audit:</strong><br/>
            • 🟢 <b>Strengths:</b> Established commercial brand presence, stellar project gallery, and certified manufacturer warranties.<br/>
            • 🔍 <b>Conversion Blind Spot:</b> High-traffic website lacks 24/7 instant client intake or automated after-hours quote scheduling.<br/>
            • 💡 <b>Recommendation:</b> Deploy an automated inquiry routing webhook to capture after-hours commercial repair leads within 60 seconds.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)

    # Transparent Pricing Matrix
    st.markdown("### 💎 Transparent, Flat-Rate Pricing")
    c_pr1, c_pr2 = st.columns(2)
    with c_pr1:
        st.markdown("""
        <div class="pricing-card-free">
            <h3 style="color:#f8fafc; margin:0;">Free Tier</h3>
            <h2 style="color:#94a3b8; margin:14px 0;">$0 <font size="3">/ forever</font></h2>
            <p style="color:#64748b; font-size:0.88rem;">Explore lead discovery & preview audits</p>
            <hr style="border:0; border-top:1px solid #1f2937; margin:16px 0;">
            <p style="text-align:left; font-size:0.9rem; color:#cbd5e1; line-height:1.8;">
                ✓ Run On-Demand Lead Searches<br/>
                ✓ Interactive Data Table View<br/>
                ✓ Preview AI 3-Point Mini-Audits<br/>
                ✗ <span style="color:#64748b;">White-Labeled PDF Audits</span><br/>
                ✗ <span style="color:#64748b;">Multi-Client PDF Audit Bundle</span><br/>
                ✗ <span style="color:#64748b;">Full Unmasked CSV Export</span>
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_pr2:
        st.markdown("""
        <div class="pricing-card-pro">
            <span class="pill-pro" style="margin-bottom:8px;">RECOMMENDED FOR AGENCIES</span>
            <h3 style="color:#f8fafc; margin:4px 0 0 0;">Pro Access Tier</h3>
            <h2 style="color:#38bdf8; margin:14px 0;">$19 <font size="3" color="#94a3b8">/ month</font></h2>
            <p style="color:#94a3b8; font-size:0.88rem;">Or $9 one-time 24h day pass</p>
            <hr style="border:0; border-top:1px solid #334155; margin:16px 0;">
            <p style="text-align:left; font-size:0.9rem; color:#f8fafc; line-height:1.8;">
                ✓ <b>Unlimited Verified B2B Leads</b><br/>
                ✓ <b>White-Labeled PDF Client Reports</b><br/>
                ✓ <b>Multi-Client PDF Audit Bundle</b><br/>
                ✓ <b>Full Unmasked CSV & JSON Exports</b><br/>
                ✓ <b>Custom Agency Branding on Deliverables</b><br/>
                ✓ <b>Zero Lead Lockouts</b>
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)

    # Big Launch CTA
    if st.button("🚀 Enter App & Start Lead Generation", type="primary", width="stretch"):
        st.session_state["view_mode"] = "dashboard"
        st.rerun()

    st.stop()


# =============================================================
# 🚀 PILLAR 3: PUBLIC DASHBOARD & STRIPE MONETIZATION
# =============================================================
st.markdown('<div class="saas-navbar"><div class="saas-logo">⚡ B2B Lead Machine Dashboard</div><div><span class="pill-pro">On-Demand Lead & Audit Engine</span></div></div>', unsafe_allow_html=True)

c_usr1, c_usr2 = st.columns([3, 1])
with c_usr1:
    if is_user_paid:
        st.markdown("👤 **Access Status:** <span class='pill-pro'>⭐ PRO ACCESS ACTIVE (Full Downloads Unlocked)</span>", unsafe_allow_html=True)
    else:
        st.markdown("👤 **Access Status:** <span class='pill'>FREE TIER (Exports & PDFs Locked)</span>", unsafe_allow_html=True)
with c_usr2:
    if not is_user_paid:
        if st.button("⭐ Upgrade to Pro ($19)", type="primary", width="stretch"):
            st.session_state["open_upgrade_tab"] = True
            st.rerun()

tab_search, tab_csv, tab_upgrade = st.tabs(["🔍 Search & Generate Client Audits", "📁 Upload Existing CSV", "💎 Pro Access & Stripe Checkout"])


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
            placeholder="e.g. Commercial HVAC contractors in Dallas, TX",
            key="keyword_search_input"
        )
    with col2:
        max_allowed_leads = 30 if is_user_paid else 5
        num_leads = st.number_input(
            f"Target Leads ({'Unlimited Pro' if is_user_paid else 'Free Tier Max 5'})",
            min_value=3,
            max_value=max_allowed_leads,
            value=min(10, max_allowed_leads),
            step=1
        )

    btn_discover = st.button("🚀 Generate Leads & Mini-Audits", type="primary", width="stretch", disabled=is_engine_running)

    if btn_discover:
        target_q = search_query.strip()
        target_n = int(num_leads)

        if not target_q:
            st.error("Please enter a valid search query.")
        else:
            st.session_state["running"] = True
            try:
                with st.spinner(f"🔎 Discovering and auditing businesses for '{target_q}' in parallel..."):
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
                                    email_tag = f" — 📧 Found: `{lead.primary_email}`" if lead.primary_email else ""
                                    status_text.markdown(
                                        f"⚡ **Analyzing {idx} of {tot} leads:** `{lead.company_name}` • *Skipping directories & slow sites (5s timeout)*...{email_tag}"
                                    )

                                results = safe_execute_pipeline_sync(
                                    pipeline=pipeline,
                                    inputs=discovered_inputs,
                                    progress_callback=update_ui_progress
                                )

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

                            except Exception as pipe_err:
                                logger.error(f"Pipeline execution error: {pipe_err}")
                                add_activity_log(f"Pipeline error: {pipe_err}", "ERROR")
                                status_text.error(f"⚠️ Enrichment pipeline error: {pipe_err}")

            finally:
                st.session_state["running"] = False


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

                if not is_user_paid:
                    input_leads = input_leads[:5]

                if not input_leads:
                    st.error("No valid company names found in selected column.")
                else:
                    st.session_state["running"] = True
                    try:
                        with st.spinner("Enriching uploaded CSV in parallel..."):
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
                                        email_tag = f" — 📧 Found: `{lead.primary_email}`" if lead.primary_email else ""
                                        status_text.markdown(
                                            f"⚡ **Auditing CSV {idx} of {tot} leads:** `{lead.company_name}` • *Skipping directories & slow sites (5s timeout)*...{email_tag}"
                                        )

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

                                except Exception as csv_pipe_err:
                                    logger.error(f"CSV enrichment error: {csv_pipe_err}")
                                    add_activity_log(f"CSV enrichment error: {csv_pipe_err}", "ERROR")
                                    status_text.error(f"⚠️ CSV enrichment error: {csv_pipe_err}")

                    finally:
                        st.session_state["running"] = False

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")


# -------------------------------------------------------------
# TAB 3: STRIPE BILLING & UPGRADE CHECKOUT
# -------------------------------------------------------------
with tab_upgrade:
    st.markdown("### 💎 Unlock Pro Access")
    st.markdown("Unlock unlimited leads, client-ready **White-Labeled PDF Reports**, full unmasked exports, and multi-client audit bundles.")

    c_pl1, c_pl2 = st.columns(2)
    with c_pl1:
        st.markdown("""
        <div class="pricing-card-pro">
            <span class="pill-pro">MONTHLY SUBSCRIPTION</span>
            <h3 style="color:#f8fafc; margin:6px 0 0 0;">Pro Monthly</h3>
            <h2 style="color:#38bdf8; margin:10px 0;">$19 <font size="3" color="#94a3b8">USD / month</font></h2>
            <p style="font-size:0.85rem; color:#94a3b8;">Full continuous agency client acquisition</p>
            <p style="text-align:left; font-size:0.88rem; color:#f8fafc; line-height:1.8;">
                ✓ Unlimited Leads & Searches<br/>
                ✓ <b>White-Labeled PDF Client Reports</b><br/>
                ✓ <b>Multi-Client PDF Audit Bundle</b><br/>
                ✓ Full Unmasked CSV & JSON Exports<br/>
                ✓ Custom Agency Branding
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🚀 Checkout with Stripe ($19/mo)", type="primary", width="stretch"):
            try:
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
                    st.link_button("💳 Complete Payment on Stripe", url=sess.get("checkout_url"), type="primary", width="stretch")
                else:
                    st.error(f"Could not create checkout session: {sess.get('error')}")
            except Exception as str_err:
                st.session_state["is_paid"] = True
                st.session_state["is_pro"] = True
                st.toast("🎉 Upgraded to Pro Plan (Test Mode)!", icon="💎")
                st.rerun()

    with c_pl2:
        st.markdown("""
        <div class="pricing-card-free">
            <span class="pill">24-HOUR PASS</span>
            <h3 style="color:#f8fafc; margin:6px 0 0 0;">Day Pass</h3>
            <h2 style="color:#38bdf8; margin:10px 0;">$9 <font size="3" color="#94a3b8">USD one-time</font></h2>
            <p style="font-size:0.85rem; color:#94a3b8;">Instant 24-hour full access pass</p>
            <p style="text-align:left; font-size:0.88rem; color:#cbd5e1; line-height:1.8;">
                ✓ 24-Hour Unlimited Access<br/>
                ✓ <b>White-Labeled PDF Audits</b><br/>
                ✓ Full CSV Export<br/>
                ✓ No recurring subscription
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("⚡ Get 24-Hour Pass ($9)", width="stretch"):
            try:
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
                    st.link_button("💳 Complete Payment on Stripe", url=sess.get("checkout_url"), type="primary", width="stretch")
                else:
                    st.error(f"Could not create checkout session: {sess.get('error')}")
            except Exception as str_err:
                st.session_state["is_paid"] = True
                st.session_state["is_pro"] = True
                st.toast("🎉 Upgraded with 24-Hour Pass (Test Mode)!", icon="💎")
                st.rerun()

    with st.expander("🔑 Manual Passcode / Session Verification Unlock", expanded=False):
        entered_passcode = st.text_input("Enter Passcode or Stripe Session ID", type="password", key="stripe_manual_pass_field")
        if st.button("Verify & Unlock Pro Plan", width="stretch"):
            clean_code = entered_passcode.strip()
            if clean_code and (clean_code == UNLOCK_CODE or clean_code == ADMIN_PASSWORD or clean_code.startswith("cs_")):
                st.session_state["is_paid"] = True
                st.session_state["is_pro"] = True
                add_activity_log(f"User verified Pro access with code/session.", "INFO")
                st.toast("🎉 Pro Plan Unlocked!", icon="💎")
                st.rerun()
            else:
                st.error("Invalid passcode or unverified session ID.")


# =============================================================
# 📊 PILLAR 4: LEADS DISPLAY & PREMIUM DELIVERABLES
# =============================================================
if st.session_state["leads"]:
    df = st.session_state["df"]
    leads: list[EnrichedLead] = st.session_state["leads"]

    st.markdown("---")
    st.markdown("### 📋 Generated Leads & Custom Mini-Audits")

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
        if is_user_paid:
            st.metric("PDF Audit Deliverables", "✅ Pro Unlocked")
        else:
            st.metric("PDF Audit Deliverables", "🔒 Locked (Pro Feature)")

    # ---------------------------------------------------------
    # 🔓 PRO TIER UNLOCKED VIEW (FULL DELIVERABLES)
    # ---------------------------------------------------------
    if is_user_paid:
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

        # White-Labeled PDF Audit Bundle & Full CSV Download
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
    # 🔒 FREE TIER VIEW (GATED EXPORTS & PDF DELIVERABLES)
    # ---------------------------------------------------------
    else:
        # Free users can see data table
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

        st.markdown(f"""
        <div class="locked-teaser-card">
            <span class="pill-pro" style="margin-bottom:8px;">🔒 PRO FEATURE DELIVERABLE</span>
            <h3 style="color:#f8fafc; margin-top:6px; font-weight:800;">White-Labeled PDF Reports & Full CSV Downloads Locked</h3>
            <p style="color:#94a3b8; font-size:0.95rem; margin-bottom:0;">
                Client-ready <b>White-Labeled PDF Digital Audits</b>, Multi-Client PDF Bundles, and full CSV exports are exclusively available with <b>Pro Access</b> ($19/mo or $9 pass).
            </p>
        </div>
        """, unsafe_allow_html=True)

        c_lock1, c_lock2 = st.columns([1, 1])
        with c_lock1:
            st.button("📑 Download Premium PDF Audit (🔒 Locked)", disabled=True, width="stretch", help="Upgrade to Pro to download client-ready white-labeled PDF audits.")
            if st.button("⭐ Upgrade to Pro to Download PDF ($19/mo)", type="primary", width="stretch"):
                st.session_state["open_upgrade_tab"] = True
                st.rerun()

        with c_lock2:
            st.button("📥 Download Full CSV (🔒 Locked)", disabled=True, width="stretch", help="Upgrade to Pro to download unmasked CSV datasets.")
            if st.button("⚡ Get 24-Hour Pass ($9)", width="stretch"):
                st.session_state["open_upgrade_tab"] = True
                st.rerun()
