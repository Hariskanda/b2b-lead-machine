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
from b2b_leadgen.pdf_generator import (
    generate_batch_audit_bundle_pdf,
    generate_company_audit_pdf
)
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column

logger = logging.getLogger(__name__)

# =============================================================
# 📱 Page Configuration & Brand Constants
# =============================================================
st.set_page_config(
    page_title="ApexLeads AI | B2B Intelligence & Growth Audits",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_NAME = "ApexLeads AI"
APP_SUBTITLE = "B2B Intelligence & Automated Growth Audits"
MAX_FREE_SEARCHES = 3
ADMIN_CONTACT_EMAIL = "hariskandapg@gmail.com"
USER_USAGE_FILE = "user_usage.json"
CLERK_SIGN_IN_URL = "https://internal-chamois-9541.clerk.accounts.dev/sign-in"
CLERK_SIGN_UP_URL = "https://internal-chamois-9541.clerk.accounts.dev/sign-up"
CLERK_USER_PROFILE_URL = "https://internal-chamois-9541.clerk.accounts.dev/user"


# =============================================================
# 💾 Persistent Per-User Search Limit Storage Helper
# =============================================================
def load_all_user_usage() -> Dict[str, Dict[str, Any]]:
    """Loads all user profile usage records from JSON storage."""
    if os.path.exists(USER_USAGE_FILE):
        try:
            with open(USER_USAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading user usage: {e}")
            return {}
    return {}


def save_all_user_usage(data: Dict[str, Dict[str, Any]]) -> None:
    """Saves user profile usage records to JSON storage."""
    try:
        with open(USER_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving user usage: {e}")


def get_user_usage(email: str) -> Dict[str, Any]:
    """Retrieves usage statistics for a specific user email."""
    if not email:
        return {"search_count": 0, "is_unlimited": False}
    norm = email.strip().lower()
    data = load_all_user_usage()
    if norm == ADMIN_CONTACT_EMAIL.lower():
        return {"search_count": 0, "is_unlimited": True}
    return data.get(norm, {"search_count": 0, "is_unlimited": False})


def record_user_search(email: str) -> int:
    """Increments and persists search count for the given user."""
    if not email:
        return 0
    norm = email.strip().lower()
    data = load_all_user_usage()
    if norm not in data:
        data[norm] = {"search_count": 0, "is_unlimited": False, "created_at": datetime.now().isoformat()}
    data[norm]["search_count"] = data[norm].get("search_count", 0) + 1
    data[norm]["updated_at"] = datetime.now().isoformat()
    save_all_user_usage(data)
    return data[norm]["search_count"]


def admin_reset_user_limit(email: str, grant_unlimited: bool = False) -> None:
    """Resets user search count to 0 and optionally grants unlimited access."""
    if not email:
        return
    norm = email.strip().lower()
    data = load_all_user_usage()
    if norm not in data:
        data[norm] = {"created_at": datetime.now().isoformat()}
    data[norm]["search_count"] = 0
    if grant_unlimited:
        data[norm]["is_unlimited"] = True
    data[norm]["updated_at"] = datetime.now().isoformat()
    save_all_user_usage(data)


SESSION_DEFAULTS: Dict[str, Any] = {
    "user_email": None,           # Logged-in user email
    "user_name": None,
    "admin_authenticated": False, # Admin login state
    "leads": [],
    "df": pd.DataFrame(),
    "last_query": "",
    "running": False,
    "activity_logs": [],
    "agency_name": "ApexLeads Agency Partners",
    "agency_website": "https://apexleads.ai"
}

for state_key, state_default in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_default


# 1. Detect Native Streamlit Authentication (st.user)
if hasattr(st, "user") and getattr(st.user, "is_logged_in", False) and getattr(st.user, "email", None):
    st.session_state["user_email"] = str(st.user.email).strip().lower()

# 2. Detect query parameters (e.g. redirected from Clerk Auth / SSO)
query_params = st.query_params
if "email" in query_params and query_params["email"] and not st.session_state["user_email"]:
    st.session_state["user_email"] = query_params["email"].strip().lower()


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
# 🎨 Modern Dark-Mode SaaS CSS (Polished UI & Typography)
# =============================================================
st.markdown("""
<style>
    /* Hide Default Streamlit Header & Footer */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}
    div[data-testid="stDecoration"] {visibility: hidden;}

    /* Modern Dark-Mode SaaS Theme */
    .stApp {
        background-color: #0b0f17;
        color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    }

    /* Top Platform Header */
    .apex-navbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 26px;
        background: linear-gradient(180deg, rgba(17, 24, 39, 0.95) 0%, rgba(15, 23, 42, 0.85) 100%);
        backdrop-filter: blur(16px);
        border: 1px solid #1e293b;
        border-radius: 16px;
        margin-bottom: 22px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }
    .brand-container {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .brand-icon-box {
        width: 40px;
        height: 40px;
        background: linear-gradient(135deg, #38bdf8 0%, #6366f1 100%);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.3rem;
        box-shadow: 0 0 16px rgba(56, 189, 248, 0.4);
    }
    .brand-title {
        font-size: 1.35rem;
        font-weight: 850;
        background: linear-gradient(135deg, #ffffff 0%, #38bdf8 60%, #818cf8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.02em;
    }
    .brand-status-badge {
        font-size: 0.72rem;
        background: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
        padding: 2px 8px;
        border-radius: 9999px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }

    /* Hero Banner */
    .hero-banner {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 20px;
        padding: 36px 28px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 24px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
    }
    .hero-banner h1 {
        font-size: 2.45rem;
        font-weight: 850;
        margin-bottom: 0.5rem;
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.02em;
    }
    .hero-banner p {
        font-size: 1.05rem;
        color: #cbd5e1;
        max-width: 780px;
        margin: 0 auto 16px auto;
        line-height: 1.5;
    }

    /* Containers & Cards */
    .metric-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 18px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    .audit-card {
        border-left: 4px solid #10b981;
        background: #111827;
        padding: 16px;
        border-radius: 10px;
        margin-bottom: 12px;
        border: 1px solid #1f2937;
        color: #e2e8f0;
    }
    .sponsor-box {
        background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
        border: 1px dashed #475569;
        border-radius: 14px;
        padding: 16px;
        text-align: center;
        margin-top: 14px;
    }

    /* Limit Warning Box */
    .limit-warning-box {
        background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
        border: 2px solid #818cf8;
        border-radius: 18px;
        padding: 28px;
        text-align: center;
        margin: 20px 0;
        box-shadow: 0 8px 30px rgba(129, 140, 248, 0.25);
    }
    .mailto-btn {
        display: inline-block;
        background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
        color: #ffffff !important;
        text-decoration: none;
        padding: 12px 28px;
        border-radius: 10px;
        font-weight: 700;
        font-size: 1.02rem;
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4);
        border: 1px solid #60a5fa;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .mailto-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 22px rgba(56, 189, 248, 0.5);
    }

    .mailto-sidebar-btn {
        display: block;
        background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
        color: #ffffff !important;
        text-decoration: none;
        padding: 10px 14px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 0.85rem;
        text-align: center;
        box-shadow: 0 2px 10px rgba(37, 99, 235, 0.35);
        border: 1px solid #60a5fa;
        margin-top: 10px;
    }

    /* Badges & Pills */
    .pill {
        display: inline-block;
        background: #1e293b;
        color: #93c5fd;
        border: 1px solid #334155;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.76rem;
        font-weight: 600;
    }
    .pill-free {
        display: inline-block;
        background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        color: #ffffff;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 700;
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

    /* Streamlit Button Styling */
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


def generate_mailto_url(user_email: Optional[str]) -> str:
    """Generates the dynamic one-click mailto URL addressed to Haris."""
    clean_email = user_email.strip() if user_email else "user@agency.com"
    subject_encoded = urllib.parse.quote("Request to Extend App Limit")
    body_text = f"Hi Haris, my account ({clean_email}) has reached its search limit. Please extend my access!"
    body_encoded = urllib.parse.quote(body_text)
    return f"mailto:{ADMIN_CONTACT_EMAIL}?subject={subject_encoded}&body={body_encoded}"


def render_user_limit_reached_card(user_email: str) -> None:
    """Renders the professional limit-reached message and one-click mailto upgrade button."""
    clean_email = user_email.strip() if user_email else "user@agency.com"
    mailto_url = generate_mailto_url(user_email)

    st.markdown(f"""
    <div class="limit-warning-box">
        <span class="pill" style="background:#312e81; color:#c7d2fe; border-color:#6366f1;">⚠️ USAGE LIMIT REACHED</span>
        <h2 style="color:#ffffff; margin: 12px 0 8px 0; font-weight: 800;">You have exhausted your free searches.</h2>
        <p style="color:#cbd5e1; font-size: 1.02rem; max-width: 680px; margin: 0 auto 18px auto; line-height: 1.5;">
            Your account (<b>{clean_email}</b>) has used all <b>{MAX_FREE_SEARCHES} of {MAX_FREE_SEARCHES}</b> free lead searches. Click below to request more limit from Haris via email.
        </p>
        <div style="margin: 20px 0;">
            <a href="{mailto_url}" target="_blank" class="mailto-btn">
                📧 Request More Limit via Email
            </a>
        </div>
        <p style="color:#94a3b8; font-size: 0.88rem; margin-top: 14px; margin-bottom: 0;">
            Direct Contact: <a href="mailto:{ADMIN_CONTACT_EMAIL}" style="color:#38bdf8; text-decoration:none;"><b>{ADMIN_CONTACT_EMAIL}</b></a>
        </p>
    </div>
    """, unsafe_allow_html=True)


# Read Core Secrets
GEMINI_API_KEY: Optional[str] = get_secret("GEMINI_API_KEY", getattr(settings, "effective_api_key", None))
ADMIN_PASSWORD: str = str(get_secret("ADMIN_PASSWORD", getattr(settings, "admin_password", "admin123")))
UNLOCK_CODE: str = str(get_secret("UNLOCK_CODE", getattr(settings, "unlock_code", "4990")))

# Authentication & State
current_user_email: Optional[str] = st.session_state.get("user_email")
is_admin_active = bool(
    st.session_state.get("admin_authenticated", False) or 
    (current_user_email and current_user_email.lower() == ADMIN_CONTACT_EMAIL.lower())
)

# Per-User Usage Statistics
user_stats = get_user_usage(current_user_email or "")
user_searches_used = int(user_stats.get("search_count", 0))
user_is_unlimited = bool(user_stats.get("is_unlimited", False) or is_admin_active)
user_searches_remaining = max(0, MAX_FREE_SEARCHES - user_searches_used)
has_user_hit_limit = (user_searches_used >= MAX_FREE_SEARCHES) and not user_is_unlimited
is_engine_running = bool(st.session_state.get("running", False))


# =============================================================
# 🛍️ PILLAR 1: EXPLICIT SIDEBAR NAVIGATION & CONTROLS
# =============================================================
with st.sidebar:
    # Sleek Logo & Brand Identity
    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">
        <div class="brand-icon-box">⚡</div>
        <div>
            <div style="font-size:1.25rem; font-weight:850; color:#ffffff; line-height:1.1;">{APP_NAME}</div>
            <div style="font-size:0.75rem; color:#94a3b8;">B2B Intelligence Platform</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Clean Radio Button Navigation at the top
    st.markdown("#### 🧭 Navigation")
    selected_page = st.radio(
        "Navigation",
        options=["📊 Dashboard & Tool", "🏠 Home / Landing", "💎 Extend Limit"],
        index=0,
        label_visibility="collapsed"
    )

    st.divider()

    # User Account Status Card
    if current_user_email:
        st.markdown("#### 👤 Account Profile")
        st.markdown(f"""
        <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:12px; margin-bottom:12px;">
            <div style="font-size:0.8rem; color:#94a3b8;">Signed in as:</div>
            <div style="font-size:0.88rem; font-weight:700; color:#f8fafc; word-break:break-all; margin-bottom:6px;">{current_user_email}</div>
            <a href="{CLERK_USER_PROFILE_URL}" target="_blank" style="color:#38bdf8; font-size:0.78rem; text-decoration:none;">⚙️ Manage Profile</a>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Log Out", width="stretch"):
            try:
                if hasattr(st, "logout") and hasattr(st, "user") and getattr(st.user, "is_logged_in", False):
                    st.logout()
            except Exception:
                pass
            st.session_state["user_email"] = None
            st.session_state["user_name"] = None
            st.session_state["admin_authenticated"] = False
            st.rerun()

        st.divider()

        # Permanent Search Limit Tracker & Mailto Upgrade
        st.markdown("#### 📊 Search Balance")
        if user_is_unlimited:
            st.markdown("""
            <div style="background:#064e3b; border:1px solid #34d399; border-radius:12px; padding:14px; margin-bottom:14px;">
                <span class="pill-free">⭐ UNLIMITED SEARCHES</span>
                <p style="font-size:0.82rem; color:#e2e8f0; margin-top:6px; margin-bottom:0;">
                    Unlimited lead generation and audit queries active.
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:14px; margin-bottom:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:0.82rem; font-weight:700; color:#f8fafc;">Searches Remaining:</span>
                    <span class="pill" style="color:{'#ef4444' if user_searches_remaining == 0 else '#38bdf8'}; font-weight:700;">
                        {user_searches_remaining} / {MAX_FREE_SEARCHES} Left
                    </span>
                </div>
                <div style="background:#1f2937; border-radius:9999px; height:7px; width:100%; overflow:hidden; margin-top:8px;">
                    <div style="background:{'#ef4444' if user_searches_remaining == 0 else '#38bdf8'}; height:100%; width:{(user_searches_remaining / MAX_FREE_SEARCHES) * 100}%;"></div>
                </div>
                <p style="font-size:0.78rem; color:#94a3b8; margin-top:8px; margin-bottom:0;">
                    Used <b>{user_searches_used} of {MAX_FREE_SEARCHES}</b> free searches.
                </p>
            </div>
            """, unsafe_allow_html=True)

            # Permanent pinned mailto button in sidebar
            sidebar_mailto = generate_mailto_url(current_user_email)
            st.markdown(f"""
            <a href="{sidebar_mailto}" target="_blank" class="mailto-sidebar-btn">
                📧 Request More Limit via Email
            </a>
            """, unsafe_allow_html=True)

        st.divider()

        # White-Label Customization for PDF Export
        with st.expander("🏢 White-Label Report Branding", expanded=False):
            agency_name_in = st.text_input("Agency / Company Name", value=st.session_state.get("agency_name", "ApexLeads Agency Partners"))
            st.session_state["agency_name"] = agency_name_in
            agency_web_in = st.text_input("Agency Website URL", value=st.session_state.get("agency_website", "https://apexleads.ai"))
            st.session_state["agency_website"] = agency_web_in
            st.caption("Stamped onto all generated White-Labeled PDF Audit Reports.")

        st.divider()

    # 📢 Sponsored Partner / Ad Slot Space
    st.markdown("""
    <div class="sponsor-box">
        <span style="font-size:0.68rem; color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; font-weight:700;">⭐ SPONSORED PARTNER</span>
        <div style="font-size:0.86rem; font-weight:700; color:#f8fafc; margin-top:6px;">Cold Email Infrastructure</div>
        <p style="font-size:0.78rem; color:#94a3b8; margin-top:4px; margin-bottom:8px; line-height:1.4;">
            Scale deliverability with dedicated sending pools & automated domain warm-up.
        </p>
        <span class="pill" style="font-size:0.72rem; border-color:#475569;">Sponsored Ad Slot</span>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # 🔑 Admin Override Panel
    if is_admin_active:
        with st.expander("👑 Admin Control Panel (Haris)", expanded=True):
            st.success("👑 Admin Mode Active (`hariskandapg@gmail.com`)")
            all_users = list(load_all_user_usage().keys())
            
            target_override_email = st.text_input("Target User Email to Replenish", value=current_user_email or "", key="admin_target_email_in")
            col_ad1, col_ad2 = st.columns(2)
            with col_ad1:
                if st.button("🔄 Reset to 3", width="stretch"):
                    if target_override_email:
                        admin_reset_user_limit(target_override_email, grant_unlimited=False)
                        add_activity_log(f"Admin reset limit for {target_override_email} to 3 searches.", "INFO")
                        st.toast(f"Limit replenished for {target_override_email}!", icon="🔄")
                        st.rerun()
            with col_ad2:
                if st.button("⭐ Unlimited", width="stretch"):
                    if target_override_email:
                        admin_reset_user_limit(target_override_email, grant_unlimited=True)
                        add_activity_log(f"Admin granted unlimited access to {target_override_email}.", "INFO")
                        st.toast(f"Unlimited granted for {target_override_email}!", icon="⭐")
                        st.rerun()

            if all_users:
                st.caption(f"Registered User Profiles ({len(all_users)}):")
                for u in all_users[:6]:
                    u_stat = get_user_usage(u)
                    st.text(f"• {u}: {u_stat.get('search_count', 0)} used {'(Unlimited)' if u_stat.get('is_unlimited') else ''}")
    else:
        with st.expander("🔐 Admin Access", expanded=False):
            admin_pwd = st.text_input("Admin Password", type="password", key="admin_pwd_field")
            if st.button("Authenticate Admin", width="stretch"):
                if admin_pwd and (admin_pwd == ADMIN_PASSWORD or admin_pwd == UNLOCK_CODE):
                    st.session_state["admin_authenticated"] = True
                    add_activity_log("Admin authenticated via password.", "INFO")
                    st.toast("🔓 Admin mode unlocked!", icon="👑")
                    st.rerun()
                else:
                    st.error("Invalid admin password.")

    st.caption(f"⚡ **{APP_NAME}** • Support: `{ADMIN_CONTACT_EMAIL}`")


effective_model = getattr(settings, "gemini_model", "gemini-2.5-flash")
effective_concurrency = int(getattr(settings, "max_concurrent_requests", 5))
effective_follow_subpages = bool(getattr(settings, "follow_contact_pages", True))
effective_agency_name = str(st.session_state.get("agency_name", "ApexLeads Agency Partners"))
effective_agency_website = str(st.session_state.get("agency_website", "https://apexleads.ai"))


# =============================================================
# 🔒 MANDATORY AUTH WALL (WHEN LOGGED OUT)
# =============================================================
if not current_user_email:
    # Modern Top Header
    st.markdown(f"""
    <div class="apex-navbar">
        <div class="brand-container">
            <div class="brand-icon-box">⚡</div>
            <div>
                <span class="brand-title">{APP_NAME}</span>
                <span class="brand-status-badge">● Operational</span>
            </div>
        </div>
        <div style="display:flex; gap:10px;">
            <a href="{CLERK_SIGN_IN_URL}" target="_blank" style="background:#4f46e5; color:#ffffff; text-decoration:none; padding:8px 18px; border-radius:8px; font-weight:600; font-size:0.85rem;">🔑 Sign In</a>
            <a href="{CLERK_SIGN_UP_URL}" target="_blank" style="border:1px solid #475569; color:#cbd5e1; text-decoration:none; padding:8px 18px; border-radius:8px; font-weight:600; font-size:0.85rem;">✨ Sign Up</a>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Hero Banner
    st.markdown(f"""
    <div class="hero-banner">
        <span class="pill-free" style="margin-bottom: 12px;">⚡ THE NEW STANDARD IN HIGH-TICKET CLIENT ACQUISITION</span>
        <h1>{APP_NAME} - B2B Intelligence</h1>
        <p>
            Instant AI-Powered Prospect Intelligence, Verified Contact Extraction & 3-Point Digital Growth Audits with Gemini AI.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Auth Sign-in Card
    col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
    with col_c2:
        with st.container(border=True):
            st.markdown(f"""
            <div style="text-align:center; padding:10px 0 16px 0;">
                <span class="pill" style="background:#312e81; color:#c7d2fe; border-color:#6366f1; margin-bottom:8px;">🔒 SIGN-IN REQUIRED</span>
                <h3 style="color:#ffffff; margin:8px 0 4px 0;">Access {APP_NAME} Platform</h3>
                <p style="color:#94a3b8; font-size:0.88rem; margin-bottom:0;">
                    Sign in to claim your <b>3 free lead generation searches</b> and client audit deliverables.
                </p>
            </div>
            """, unsafe_allow_html=True)

            if hasattr(st, "login"):
                try:
                    if st.button("🔑 Sign in with Streamlit SSO", type="primary", width="stretch", key="st_sso_login_btn"):
                        st.login()
                except Exception:
                    pass

            sign_in_email = st.text_input("Work / Agency Email Address", placeholder="e.g. founder@growthagency.com", key="auth_wall_email")
            sign_in_name = st.text_input("Your Name / Company Name (Optional)", placeholder="e.g. Alex Rivera", key="auth_wall_name")

            c_auth1, c_auth2 = st.columns(2)
            with c_auth1:
                if st.button("🚀 Access Platform", type="primary", width="stretch"):
                    clean_e = sign_in_email.strip().lower()
                    if not clean_e or "@" not in clean_e or "." not in clean_e:
                        st.error("Please enter a valid email address.")
                    else:
                        st.session_state["user_email"] = clean_e
                        st.session_state["user_name"] = sign_in_name.strip() if sign_in_name else clean_e.split("@")[0]
                        get_user_usage(clean_e)
                        add_activity_log(f"User signed in: {clean_e}", "INFO")
                        st.toast(f"Welcome to {APP_NAME}, {clean_e}!", icon="👋")
                        st.rerun()
            with c_auth2:
                st.link_button("🔐 Sign in via Clerk Portal", url=CLERK_SIGN_IN_URL, width="stretch")

    st.stop()


# =============================================================
# 🚀 PILLAR 2: PROFESSIONAL HEADER & BRANDING
# =============================================================
st.markdown(f"""
<div class="apex-navbar">
    <div class="brand-container">
        <div class="brand-icon-box">⚡</div>
        <div>
            <span class="brand-title">{APP_NAME}</span>
            <span class="brand-status-badge">● Engine Online</span>
        </div>
    </div>
    <div style="display:flex; align-items:center; gap:16px;">
        {'<span class="pill-pro">⭐ Unlimited Searches</span>' if user_is_unlimited else f'<span class="pill" style="color:{"#ef4444" if user_searches_remaining == 0 else "#38bdf8"}; font-weight:700;">🔍 {user_searches_remaining} / {MAX_FREE_SEARCHES} Free Searches Left</span>'}
        <div style="display:flex; align-items:center; gap:8px;">
            <span style="color:#94a3b8; font-size:0.86rem;">👤 {current_user_email}</span>
            <a href="{CLERK_USER_PROFILE_URL}" target="_blank" style="background:#1e293b; border:1px solid #334155; color:#93c5fd; text-decoration:none; padding:4px 10px; border-radius:6px; font-size:0.78rem; font-weight:600;">Profile</a>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# =============================================================
# 📱 PAGE ROUTING: HOME vs DASHBOARD vs EXTEND LIMIT
# =============================================================

# VIEW 1: HOME / LANDING VIEW
if selected_page == "🏠 Home / Landing":
    st.markdown(f"""
    <div class="hero-banner">
        <span class="pill-free" style="margin-bottom: 12px;">⚡ THE NEW STANDARD IN HIGH-TICKET CLIENT ACQUISITION</span>
        <h1>{APP_NAME} - B2B Intelligence</h1>
        <p>
            Instant AI-Powered Prospect Intelligence, Verified Contact Extraction & 3-Point Digital Growth Audits with Gemini AI.
        </p>
    </div>
    """, unsafe_allow_html=True)

    c_s1, c_s2, c_s3 = st.columns(3)
    with c_s1:
        with st.container(border=True):
            st.markdown("""
            <div style="font-size:2rem; margin-bottom:8px;">🎯</div>
            <h4 style="color:#ffffff; margin-top:0;">1. Target Any Metro & Niche</h4>
            <p style="color:#94a3b8; font-size:0.88rem; line-height:1.5;">
                Enter local keywords (e.g. <i>"Commercial HVAC in Dallas, TX"</i>) or upload an existing account list.
            </p>
            """, unsafe_allow_html=True)

    with c_s2:
        with st.container(border=True):
            st.markdown("""
            <div style="font-size:2rem; margin-bottom:8px;">🤖</div>
            <h4 style="color:#ffffff; margin-top:0;">2. Gemini 2026 AI Audits</h4>
            <p style="color:#94a3b8; font-size:0.88rem; line-height:1.5;">
                Extract verified emails and identify strengths, conversion blind spots, and high-impact growth levers.
            </p>
            """, unsafe_allow_html=True)

    with c_s3:
        with st.container(border=True):
            st.markdown("""
            <div style="font-size:2rem; margin-bottom:8px;">📄</div>
            <h4 style="color:#ffffff; margin-top:0;">3. Deliver White-Labeled PDFs</h4>
            <p style="color:#94a3b8; font-size:0.88rem; line-height:1.5;">
                Download ready-to-present PDF audit reports branded with your agency name to close high-ticket clients.
            </p>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("### 🚀 Ready to Generate Leads?")
        st.markdown("Switch directly to the **📊 Dashboard & Tool** in the sidebar to start finding clients and downloading white-labeled PDF audits.")


# VIEW 2: EXTEND LIMIT VIEW
elif selected_page == "💎 Extend Limit":
    st.markdown("""
    <div class="hero-banner">
        <span class="pill-pro" style="margin-bottom: 12px;">💎 EXTEND YOUR SEARCH LIMIT</span>
        <h1>Account Balance & Search Allowance</h1>
        <p>
            Request extended lead searches, custom enterprise enrichment pools, or unlimited platform access directly from Haris.
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_ex1, col_ex2 = st.columns([2, 1])
    with col_ex1:
        with st.container(border=True):
            st.markdown("### 📊 Your Current Account Balance")
            st.markdown(f"**Account Email:** `{current_user_email}`")
            st.markdown(f"**Searches Used:** `{user_searches_used} of {MAX_FREE_SEARCHES}`")
            st.markdown(f"**Searches Remaining:** `{user_searches_remaining} Left`")
            st.markdown(f"**Access Tier:** `{'⭐ Unlimited Pro' if user_is_unlimited else 'Free Allowance (3 Searches)'}`")
            
            st.divider()
            mailto_url = generate_mailto_url(current_user_email)
            st.markdown(f"""
            <div style="text-align:center; padding: 12px 0;">
                <p style="color:#cbd5e1; font-size:0.95rem;">Click the button below to send a pre-formatted request directly to Haris:</p>
                <a href="{mailto_url}" target="_blank" class="mailto-btn">
                    📧 Request Limit Extension via Email
                </a>
            </div>
            """, unsafe_allow_html=True)

    with col_ex2:
        with st.container(border=True):
            st.markdown("### 📩 Direct Admin Contact")
            st.markdown(f"**Creator Email:** `{ADMIN_CONTACT_EMAIL}`")
            st.caption("Emails are typically reviewed and limits extended within a few hours.")


# VIEW 3: CORE DASHBOARD & TOOL (DEFAULT VIEW)
else:
    # Show Limit Reached Warning if user hit limit
    if has_user_hit_limit:
        render_user_limit_reached_card(current_user_email)

    tab_search, tab_csv = st.tabs(["🔍 Search & Generate Client Audits", "📁 Upload Existing CSV"])

    # -------------------------------------------------------------
    # TAB 1: Autonomous Keyword Discovery & Audit Generator
    # -------------------------------------------------------------
    with tab_search:
        with st.container(border=True):
            st.markdown("### 🎯 Discover Real Companies & Generate Mini-Audits")
            st.markdown("Enter a target search phrase (e.g. *'Commercial roofing in Miami, FL'* or *'Plumbing contractors in Austin, TX'*):")

            col1, col2 = st.columns([3, 1])
            with col1:
                search_query = st.text_input(
                    "Search Query / Niche + Location",
                    placeholder="e.g. Commercial HVAC contractors in Dallas, TX",
                    key="keyword_search_input",
                    disabled=has_user_hit_limit
                )
            with col2:
                num_leads = st.number_input(
                    "Target Lead Count",
                    min_value=3,
                    max_value=30,
                    value=10,
                    step=1,
                    disabled=has_user_hit_limit
                )

            btn_discover = st.button("🚀 Generate Leads & Mini-Audits", type="primary", width="stretch", disabled=is_engine_running or has_user_hit_limit)

        if btn_discover:
            if has_user_hit_limit:
                st.warning("⚠️ You have exhausted your free searches.")
            else:
                target_q = search_query.strip()
                target_n = int(num_leads)

                if not target_q:
                    st.error("Please enter a valid search query.")
                else:
                    st.session_state["running"] = True
                    try:
                        with st.spinner(f"🔎 Discovering and auditing businesses for '{target_q}' in parallel..."):
                            progress_container = st.container(border=True)
                            with progress_container:
                                status_text = st.empty()
                                prog_bar = st.progress(0)

                                add_activity_log(f"Starting discovery for '{target_q}' (User: {current_user_email})...", "INFO")
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

                                        prog_bar.progress(100)
                                        add_activity_log(f"Generated mini-audits for {len(results)} leads.", "INFO")
                                        status_text.success(f"🎉 Successfully generated {len(results)} leads with Custom Mini-Audits!")

                                        st.session_state["leads"] = results
                                        df_data = [r.model_dump() for r in results]
                                        st.session_state["df"] = pd.DataFrame(df_data)
                                        st.session_state["last_query"] = target_q

                                        # Record per-user search count in persistent storage
                                        if not user_is_unlimited and current_user_email:
                                            record_user_search(current_user_email)
                                            st.rerun()

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
        with st.container(border=True):
            st.markdown("### 📁 Upload Existing CSV for Mini-Audits")
            st.markdown("Upload a CSV containing company names to enrich them with verified contact emails and AI digital audits.")

            uploaded_file = st.file_uploader("Upload CSV file", type=["csv"], disabled=has_user_hit_limit)

            if uploaded_file is not None:
                try:
                    uploaded_df = pd.read_csv(uploaded_file)
                    st.dataframe(uploaded_df.head(5), width="stretch", hide_index=True)

                    company_col_detected = detect_company_column(list(uploaded_df.columns))
                    selected_col = st.selectbox(
                        "Select Company Name Column",
                        options=list(uploaded_df.columns),
                        index=list(uploaded_df.columns).index(company_col_detected) if company_col_detected in uploaded_df.columns else 0,
                        disabled=has_user_hit_limit
                    )

                    btn_enrich_csv = st.button("⚡ Generate Mini-Audits from Uploaded CSV", type="primary", disabled=is_engine_running or has_user_hit_limit)

                    if btn_enrich_csv:
                        if has_user_hit_limit:
                            st.warning("⚠️ You have exhausted your free searches.")
                        else:
                            input_leads = []
                            for _, row in uploaded_df.iterrows():
                                c_name = str(row.get(selected_col, "")).strip()
                                if c_name and c_name.lower() != "nan":
                                    input_leads.append(LeadInput(company_name=c_name))

                            if not input_leads:
                                st.error("No valid company names found in selected column.")
                            else:
                                st.session_state["running"] = True
                                try:
                                    with st.spinner("Enriching uploaded CSV in parallel..."):
                                        progress_container = st.container(border=True)
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

                                                prog_bar.progress(100)
                                                add_activity_log(f"Enriched {len(results)} leads from CSV.", "INFO")
                                                status_text.success(f"🎉 Successfully enriched {len(results)} leads from CSV with Custom Mini-Audits!")

                                                st.session_state["leads"] = results
                                                st.session_state["df"] = pd.DataFrame([r.model_dump() for r in results])
                                                st.session_state["last_query"] = f"CSV: {uploaded_file.name}"

                                                # Record per-user search count in persistent storage
                                                if not user_is_unlimited and current_user_email:
                                                    record_user_search(current_user_email)
                                                    st.rerun()

                                            except Exception as csv_pipe_err:
                                                logger.error(f"CSV enrichment error: {csv_pipe_err}")
                                                add_activity_log(f"CSV enrichment error: {csv_pipe_err}", "ERROR")
                                                status_text.error(f"⚠️ CSV enrichment error: {csv_pipe_err}")

                                finally:
                                    st.session_state["running"] = False

                except Exception as e:
                    st.error(f"Error reading CSV file: {e}")

    # =============================================================
    # 📊 LEADS DISPLAY & UNRESTRICTED 1-CLICK EXPORTS
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
            st.metric("Export Deliverables", "✅ 1-Click Ready")

        # Full Interactive Data Table
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

        # 1-Click Multi-Client PDF Audit Bundle & Full CSV Download
        st.markdown("#### 📄 1-Click Client Deliverables & PDF Reports")
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
