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
# 📱 Page Configuration & Constants
# =============================================================
st.set_page_config(
    page_title="B2B Lead Machine: Automate Your Lead Generation & Auditing",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
    "agency_name": "AI Growth & Intelligence Partners",
    "agency_website": "https://growth-intelligence.io"
}

for state_key, state_default in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_default


# Auto-detect email from query parameters (e.g. redirected from Clerk Auth)
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
# 🎨 Modern Dark-Mode SaaS CSS (Polished UI)
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
        font-size: 1.3rem;
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
        padding: 44px 32px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 28px;
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
        font-size: 1.15rem;
        color: #cbd5e1;
        max-width: 840px;
        margin: 0 auto 20px auto;
        line-height: 1.6;
    }

    /* Auth Sign-In Wall Box */
    .auth-wall-container {
        background: linear-gradient(135deg, #111827 0%, #1e1b4b 50%, #111827 100%);
        border: 2px solid #6366f1;
        border-radius: 24px;
        padding: 40px;
        max-width: 680px;
        margin: 30px auto;
        box-shadow: 0 16px 48px rgba(99, 102, 241, 0.2);
        text-align: center;
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
        font-size: 1.05rem;
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4);
        border: 1px solid #60a5fa;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .mailto-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 22px rgba(56, 189, 248, 0.5);
    }

    .clerk-btn {
        display: inline-block;
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
        color: #ffffff !important;
        text-decoration: none;
        padding: 10px 22px;
        border-radius: 10px;
        font-weight: 700;
        font-size: 0.95rem;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
        border: 1px solid #818cf8;
    }
    .clerk-btn-outline {
        display: inline-block;
        background: transparent;
        color: #cbd5e1 !important;
        text-decoration: none;
        padding: 10px 22px;
        border-radius: 10px;
        font-weight: 600;
        font-size: 0.95rem;
        border: 1px solid #475569;
    }

    /* Feature Badges & Pills */
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
    .pill-free {
        display: inline-block;
        background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        color: #ffffff;
        padding: 5px 14px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 700;
        box-shadow: 0 2px 10px rgba(16, 185, 129, 0.35);
    }
    .pill-pro {
        display: inline-block;
        background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
        color: #ffffff;
        padding: 5px 14px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 700;
    }

    /* Audit Cards */
    .audit-card {
        border-left: 4px solid #10b981;
        background: #111827;
        padding: 16px;
        border-radius: 10px;
        margin-bottom: 12px;
        border: 1px solid #1f2937;
        color: #e2e8f0;
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


def render_user_limit_reached_card(user_email: str) -> None:
    """Renders the professional limit-reached message and personalized mailto link."""
    clean_email = user_email.strip() if user_email else "user@agency.com"
    subject_encoded = urllib.parse.quote("Unlock More Searches")
    body_text = f"Hi Haris, my account ({clean_email}) has exhausted its free searches. Please extend my limit!"
    body_encoded = urllib.parse.quote(body_text)
    mailto_url = f"mailto:{ADMIN_CONTACT_EMAIL}?subject={subject_encoded}&body={body_encoded}"

    st.markdown(f"""
    <div class="limit-warning-box">
        <span class="pill" style="background:#312e81; color:#c7d2fe; border-color:#6366f1;">⚠️ USAGE LIMIT REACHED</span>
        <h2 style="color:#ffffff; margin: 12px 0 8px 0; font-weight: 800;">You have used all your free searches.</h2>
        <p style="color:#cbd5e1; font-size: 1.02rem; max-width: 680px; margin: 0 auto 18px auto; line-height: 1.5;">
            Your account (<b>{clean_email}</b>) has used all <b>{MAX_FREE_SEARCHES} of {MAX_FREE_SEARCHES}</b> complimentary lead generation searches. Click below to request more limit from Haris.
        </p>
        <div style="margin: 20px 0;">
            <a href="{mailto_url}" target="_blank" class="mailto-btn">
                📧 Request More Searches via Email
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
is_admin_active = bool(st.session_state.get("admin_authenticated", False) or (current_user_email and current_user_email.lower() == ADMIN_CONTACT_EMAIL.lower()))

# Per-User Usage Statistics
user_stats = get_user_usage(current_user_email or "")
user_searches_used = int(user_stats.get("search_count", 0))
user_is_unlimited = bool(user_stats.get("is_unlimited", False) or is_admin_active)
user_searches_remaining = max(0, MAX_FREE_SEARCHES - user_searches_used)
has_user_hit_limit = (user_searches_used >= MAX_FREE_SEARCHES) and not user_is_unlimited
is_engine_running = bool(st.session_state.get("running", False))


# =============================================================
# 🛍️ Sidebar: User Profile, Usage, Branding & Admin Panel
# =============================================================
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/lightning-bolt.png", width=55)
    st.title("B2B Lead Machine")

    if current_user_email:
        st.markdown("#### 👤 Active Account")
        st.markdown(f"""
        <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:12px; margin-bottom:12px;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                <span style="font-size:1.1rem;">👤</span>
                <strong style="color:#f8fafc; font-size:0.88rem; word-break:break-all;">{current_user_email}</strong>
            </div>
            <a href="{CLERK_USER_PROFILE_URL}" target="_blank" style="color:#38bdf8; font-size:0.8rem; text-decoration:none;">⚙️ Manage Clerk Profile</a>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Log Out", width="stretch"):
            st.session_state["user_email"] = None
            st.session_state["user_name"] = None
            st.session_state["admin_authenticated"] = False
            st.rerun()

        st.divider()

        # Per-User Search Limit Tracker
        st.markdown("#### 📊 Search Balance")
        if user_is_unlimited:
            st.markdown("""
            <div style="background:#064e3b; border:1px solid #34d399; border-radius:12px; padding:14px; margin-bottom:14px;">
                <span class="pill-free">⭐ UNLIMITED SEARCHES ACTIVE</span>
                <p style="font-size:0.84rem; color:#e2e8f0; margin-top:8px; margin-bottom:0;">
                    Unlimited lead generation and audit queries unlocked.
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:14px; margin-bottom:14px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:0.85rem; font-weight:700; color:#f8fafc;">Searches Remaining:</span>
                    <span class="pill" style="background:#1e293b; color:{'#ef4444' if user_searches_remaining == 0 else '#38bdf8'}; font-weight:700;">
                        {user_searches_remaining} / {MAX_FREE_SEARCHES} Left
                    </span>
                </div>
                <div style="background:#1f2937; border-radius:9999px; height:8px; width:100%; overflow:hidden; margin-top:8px;">
                    <div style="background:{'#ef4444' if user_searches_remaining == 0 else '#38bdf8'}; height:100%; width:{(user_searches_remaining / MAX_FREE_SEARCHES) * 100}%;"></div>
                </div>
                <p style="font-size:0.8rem; color:#94a3b8; margin-top:8px; margin-bottom:0;">
                    Used <b>{user_searches_used} of {MAX_FREE_SEARCHES}</b> free searches.
                </p>
            </div>
            """, unsafe_allow_html=True)

        st.divider()

        # White-Label Customization for PDF Export
        st.markdown("#### 🏢 White-Label Report Branding")
        agency_name_in = st.text_input("Agency / Company Name", value=st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
        st.session_state["agency_name"] = agency_name_in
        agency_web_in = st.text_input("Agency Website URL", value=st.session_state.get("agency_website", "https://growth-intelligence.io"))
        st.session_state["agency_website"] = agency_web_in
        st.caption("Your branding is automatically stamped onto all generated White-Labeled PDF Audit Reports.")

        st.divider()

    # 🔑 Admin Override Panel
    with st.expander("🔐 Admin Override Panel", expanded=False):
        if not is_admin_active:
            admin_pwd = st.text_input("Admin Password", type="password", key="admin_pwd_field")
            if st.button("Authenticate Admin", width="stretch"):
                if admin_pwd and (admin_pwd == ADMIN_PASSWORD or admin_pwd == UNLOCK_CODE):
                    st.session_state["admin_authenticated"] = True
                    add_activity_log("Admin authenticated successfully.", "INFO")
                    st.toast("🔓 Admin mode unlocked!", icon="👑")
                    st.rerun()
                else:
                    st.error("Invalid admin password.")
        else:
            st.success("👑 Admin Mode Active")
            all_users = list(load_all_user_usage().keys())
            
            target_override_email = st.text_input("Target User Email to Replenish", value=current_user_email or "", key="admin_target_email_in")
            col_ad1, col_ad2 = st.columns(2)
            with col_ad1:
                if st.button("🔄 Reset to 3 Searches", width="stretch"):
                    if target_override_email:
                        admin_reset_user_limit(target_override_email, grant_unlimited=False)
                        add_activity_log(f"Admin reset limit for {target_override_email} to 3 searches.", "INFO")
                        st.toast(f"Limit reset to 3 for {target_override_email}!", icon="🔄")
                        st.rerun()
            with col_ad2:
                if st.button("⭐ Grant Unlimited", width="stretch"):
                    if target_override_email:
                        admin_reset_user_limit(target_override_email, grant_unlimited=True)
                        add_activity_log(f"Admin granted unlimited access to {target_override_email}.", "INFO")
                        st.toast(f"Unlimited granted for {target_override_email}!", icon="⭐")
                        st.rerun()

            if all_users:
                st.caption(f"Registered User Profiles ({len(all_users)}):")
                for u in all_users[:8]:
                    u_stat = get_user_usage(u)
                    st.text(f"• {u}: {u_stat.get('search_count', 0)} used {'(Unlimited)' if u_stat.get('is_unlimited') else ''}")

            if st.button("Exit Admin Mode", width="stretch"):
                st.session_state["admin_authenticated"] = False
                st.rerun()

    st.caption(f"⚡ **B2B Lead Machine** • Support: `{ADMIN_CONTACT_EMAIL}`")


effective_model = getattr(settings, "gemini_model", "gemini-2.5-flash")
effective_concurrency = int(getattr(settings, "max_concurrent_requests", 5))
effective_follow_subpages = bool(getattr(settings, "follow_contact_pages", True))
effective_agency_name = str(st.session_state.get("agency_name", "AI Growth & Intelligence Partners"))
effective_agency_website = str(st.session_state.get("agency_website", "https://growth-intelligence.io"))


# =============================================================
# 🔒 PILLAR 1: MANDATORY SIGN-IN WALL (WHEN LOGGED OUT)
# =============================================================
if not current_user_email:
    # SaaS Navbar (Logged Out State)
    st.markdown(f"""
    <div class="saas-navbar">
        <div class="saas-logo">
            ⚡ <span>B2B Lead Machine</span>
        </div>
        <div style="display:flex; gap:10px;">
            <a href="{CLERK_SIGN_IN_URL}" target="_blank" class="clerk-btn" style="padding:8px 18px; font-size:0.85rem;">🔑 Sign In</a>
            <a href="{CLERK_SIGN_UP_URL}" target="_blank" class="clerk-btn-outline" style="padding:8px 18px; font-size:0.85rem;">✨ Sign Up</a>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Hero Section
    st.markdown("""
    <div class="hero-container">
        <span class="pill-free" style="margin-bottom: 12px;">⚡ THE NEW STANDARD IN HIGH-TICKET CLIENT ACQUISITION</span>
        <h1 class="hero-title">Automate Your Agency's Lead Generation & Auditing</h1>
        <p class="hero-subtitle">
            Discover high-intent local businesses, extract verified decision-maker emails, and generate client-ready <b>3-Point Digital Growth Audits</b> with Gemini AI.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Mandatory Auth Card
    st.markdown("""
    <div class="auth-wall-container">
        <span class="pill" style="background:#312e81; color:#c7d2fe; border-color:#6366f1; margin-bottom:12px;">🔒 SIGN-IN REQUIRED TO ACCESS ENGINE</span>
        <h2 style="color:#ffffff; margin: 12px 0 8px 0; font-weight: 800;">Sign in to Start Generating Leads & Audits</h2>
        <p style="color:#cbd5e1; font-size: 0.98rem; max-width: 540px; margin: 0 auto 24px auto; line-height: 1.5;">
            Create your account or sign in with your email to claim your <b>3 free lead generation searches</b> and white-labeled PDF deliverables.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Direct Sign-in Form
    col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
    with col_c2:
        st.markdown("#### ⚡ Quick Email Sign-In / Register")
        sign_in_email = st.text_input("Work / Agency Email Address", placeholder="e.g. founder@growthagency.com", key="auth_wall_email")
        sign_in_name = st.text_input("Your Name / Company Name (Optional)", placeholder="e.g. Alex Rivera", key="auth_wall_name")

        c_auth1, c_auth2 = st.columns(2)
        with c_auth1:
            if st.button("🚀 Access B2B Lead Machine", type="primary", width="stretch"):
                clean_e = sign_in_email.strip().lower()
                if not clean_e or "@" not in clean_e or "." not in clean_e:
                    st.error("Please enter a valid email address.")
                else:
                    st.session_state["user_email"] = clean_e
                    st.session_state["user_name"] = sign_in_name.strip() if sign_in_name else clean_e.split("@")[0]
                    # Ensure user profile exists in persistent storage
                    get_user_usage(clean_e)
                    add_activity_log(f"User signed in: {clean_e}", "INFO")
                    st.toast(f"Welcome to B2B Lead Machine, {clean_e}!", icon="👋")
                    st.rerun()
        with c_auth2:
            st.link_button("🔐 Sign in via Clerk Portal", url=CLERK_SIGN_IN_URL, width="stretch")

    st.stop()


# =============================================================
# 🚀 MAIN SAAS DASHBOARD (LOGGED IN STATE)
# =============================================================
st.markdown(f"""
<div class="saas-navbar">
    <div class="saas-logo">
        ⚡ <span>B2B Lead Machine</span>
    </div>
    <div style="display:flex; align-items:center; gap:16px;">
        {'<span class="pill-pro">⭐ Unlimited Searches</span>' if user_is_unlimited else f'<span class="pill" style="color:{"#ef4444" if user_searches_remaining == 0 else "#38bdf8"};">🔍 {user_searches_remaining} / {MAX_FREE_SEARCHES} Free Searches Left</span>'}
        <div style="display:flex; align-items:center; gap:8px;">
            <span style="color:#94a3b8; font-size:0.88rem;">👤 {current_user_email}</span>
            <a href="{CLERK_USER_PROFILE_URL}" target="_blank" class="clerk-btn" style="padding:6px 14px; font-size:0.8rem;">Profile</a>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Hero Section
st.markdown("""
<div class="hero-container">
    <span class="pill-free" style="margin-bottom: 12px;">⚡ THE NEW STANDARD IN HIGH-TICKET CLIENT ACQUISITION</span>
    <h1 class="hero-title">Automate Your Agency's Lead Generation & Auditing</h1>
    <p class="hero-subtitle">
        Discover high-intent local businesses, extract verified decision-maker emails, and generate client-ready <b>3-Point Digital Growth Audits</b> with Gemini AI.
    </p>
    <div style="display:flex; justify-content:center; gap:12px; flex-wrap:wrap;">
        <span class="pill">🤖 Gemini 2026 AI Engine</span>
        <span class="pill">📄 White-Labeled PDF Audits</span>
        <span class="pill">📥 Full CSV & JSON Exports</span>
        <span class="pill">⚡ Parallel Concurrency</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Show Limit Reached Warning if user hit limit
if has_user_hit_limit:
    render_user_limit_reached_card(current_user_email)

tab_search, tab_csv = st.tabs(["🔍 Search & Generate Client Audits", "📁 Upload Existing CSV"])


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
            st.warning("⚠️ You have used all your free searches.")
        else:
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
    st.markdown("### 📁 Upload Existing CSV for Mini-Audits")
    st.markdown("Upload a CSV containing company names to enrich them with verified contact emails and AI digital audits.")

    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"], disabled=has_user_hit_limit)

    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            st.dataframe(uploaded_df.head(5), width="stretch")

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
                    st.warning("⚠️ You have used all your free searches.")
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
        st.metric("Export Deliverables", "✅ 1-Click Downloads Ready")

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
