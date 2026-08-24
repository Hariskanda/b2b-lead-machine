import asyncio
import io
import json
import logging
import os
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st

from b2b_leadgen.autopilot import autopilot_engine
from b2b_leadgen.config import settings
from b2b_leadgen.email_dispatcher import build_outreach_email, dispatch_campaign
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.history import sent_history
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.nowpayments import (
    check_nowpayments_invoice_status,
    create_nowpayments_invoice
)
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column
from b2b_leadgen.sheets_exporter import export_leads_to_google_sheet

logger = logging.getLogger(__name__)

# =============================================================
# 📱 Page Configuration & Early Session State Initialization
# =============================================================
st.set_page_config(
    page_title="B2B Lead Machine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Comprehensive top-level state defaults to guarantee mobile/cross-browser uptime
SESSION_DEFAULTS: Dict[str, Any] = {
    "leads": [],
    "df": pd.DataFrame(),
    "last_query": "",
    "payment_verified": False,
    "paid": False,
    "admin_authenticated": False,
    "admin_logged_in": False,
    "crypto_invoice_url": None,
    "crypto_invoice_id": None,
    "campaign_results": None,
    "sync_status": None,
}

for state_key, state_default in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_default


# Custom CSS styling with Mobile Responsiveness & Copy Protection
st.markdown("""
<style>
    .main-header {
        font-size: 2.4rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
        background: linear-gradient(90deg, #4A90E2, #9013FE);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #6c757d;
        margin-bottom: 1.5rem;
    }
    .storefront-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: #ffffff;
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .crypto-hero-box {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        border: 2px solid #818cf8;
        border-radius: 16px;
        padding: 22px;
        color: #ffffff;
        text-align: center;
        margin: 15px auto;
        box-shadow: 0 6px 18px rgba(129, 140, 248, 0.18);
    }
    .unlocked-box {
        background-color: #f0fdf4;
        border: 2px solid #22c55e;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin: 20px 0;
    }
    .pill {
        display: inline-block;
        background: #334155;
        color: #93c5fd;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        margin: 2px 0;
    }
    /* 🛡️ Copy Protection & Scrape Deterrence for Public Preview */
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
        padding: 24px;
        text-align: center;
        margin: 16px 0;
    }
    .paywall-gate-card {
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        border: 2px solid #818cf8;
        border-radius: 16px;
        padding: 24px;
        color: #ffffff;
        text-align: center;
        margin: 20px 0;
        box-shadow: 0 8px 24px rgba(49, 46, 129, 0.25);
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


def safe_execute_pipeline(
    pipeline: LeadGenPipeline,
    inputs: List[LeadInput],
    progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
) -> List[EnrichedLead]:
    """Safely runs the async enrichment pipeline across any execution environment."""
    try:
        return asyncio.run(
            pipeline.run_batch(
                inputs=inputs,
                output_csv_path=None,
                progress_callback=progress_callback
            )
        )
    except RuntimeError:
        # If an event loop is already running in this thread
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
CRYPTO_PRICE_USD: float = float(get_secret("CRYPTO_PRICE_USD", getattr(settings, "crypto_price_usd", 6.0)))
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
is_paid_active = bool(st.session_state.get("payment_verified", False) or st.session_state.get("paid", False))


# =============================================================
# 🛍️ Clean Public Sidebar Interface & Gated Admin Portal
# =============================================================
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/lightning-bolt.png", width=60)
    st.title("B2B Lead Machine")

    st.markdown("""
    <div class="storefront-card">
        <h4 style="margin-top:0; color:#f8fafc; font-size:1.05rem;">⚡ Prospecting on Autopilot</h4>
        <p style="font-size:0.85rem; color:#cbd5e1; margin-bottom:10px;">
            Target real local businesses, extract verified contact emails, and generate customized AI sales pitches in seconds.
        </p>
        <span class="pill">🎯 Niche + Location Discovery</span><br>
        <span class="pill">📧 Decision-Maker Emails</span><br>
        <span class="pill">✍️ AI Cold Pitches</span><br>
        <span class="pill">🌐 Zero-KYC Crypto Checkout</span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📦 Order Status")
    if is_paid_active:
        st.success("✅ FULL CSV EXPORT UNLOCKED")
    else:
        st.info(f"🔒 Full CSV Export: ${CRYPTO_PRICE_USD:.2f} USD Crypto Required")

    st.divider()

    # 🔐 Secure Admin Configuration Portal (Password Protected)
    with st.expander("🔐 Admin Portal", expanded=False):
        if not is_admin_active:
            st.markdown("##### Admin Authentication")
            admin_pwd_input = st.text_input("Enter Admin Password", type="password", key="admin_pwd_input")
            if st.button("Unlock Admin Panel", use_container_width=True):
                if admin_pwd_input and admin_pwd_input == ADMIN_PASSWORD:
                    st.session_state["admin_authenticated"] = True
                    st.session_state["admin_logged_in"] = True
                    st.success("Admin mode unlocked!")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid Admin Password.")
        else:
            st.markdown('<span style="color:#15803d; font-weight:700;">🔓 ADMIN MODE ACTIVE</span>', unsafe_allow_html=True)

            if not is_paid_active:
                if st.button("⚡ Admin Instant Unlock Dataset", type="primary", use_container_width=True):
                    st.session_state["payment_verified"] = True
                    st.session_state["paid"] = True
                    st.toast("🎉 Dataset unlocked by Admin!", icon="🔓")
                    st.rerun()

            st.markdown("---")
            st.markdown("#### 🤖 24/7 Autopilot Background Engine")

            ap_status = autopilot_engine.get_status()
            if ap_status["is_running"]:
                st.success(f"🟢 ACTIVE: Sent {ap_status['total_emails_sent']} emails | Cycle #{ap_status['total_cycles']}")
                st.caption(f"Current Niche: `{ap_status['current_niche'] or 'Initializing...'}`")
                if ap_status.get("total_duplicates_skipped", 0) > 0:
                    st.caption(f"🛡️ Skipped Duplicates: `{ap_status['total_duplicates_skipped']}`")
                if st.button("🛑 Stop 24/7 Autopilot Engine", type="secondary", use_container_width=True):
                    autopilot_engine.stop()
                    st.warning("Autopilot stopped.")
                    st.rerun()
            else:
                st.info("⚪ STATUS: Autopilot Engine Idle")

                ap_batch_size = st.slider("Batch Size (Leads/cycle)", min_value=3, max_value=20, value=5, key="ap_batch_slider")
                ap_interval = st.slider("Interval Delay Between Batches (Sec)", min_value=30, max_value=600, value=120, step=30, key="ap_interval_slider")
                ap_continuous = st.checkbox("Run Continuously 24/7 (Non-Repeating Topic Rotation)", value=True, key="ap_continuous_cb")

                if st.button("🚀 Launch 24/7 Background Autopilot", type="primary", use_container_width=True):
                    if not SMTP_USER or not SMTP_PASSWORD:
                        st.warning("⚠️ SMTP credentials (SMTP_USER, SMTP_PASSWORD) not set in secrets.")
                    else:
                        autopilot_engine.start(
                            gemini_api_key=GEMINI_API_KEY,
                            smtp_user=SMTP_USER,
                            smtp_password=SMTP_PASSWORD,
                            app_url=APP_URL,
                            sender_name=SENDER_NAME,
                            smtp_host=SMTP_HOST,
                            smtp_port=SMTP_PORT,
                            price_usd=CRYPTO_PRICE_USD,
                            batch_size=ap_batch_size,
                            interval_seconds=ap_interval,
                            run_continuously=ap_continuous
                        )
                        st.success("🎉 24/7 Background Autopilot Worker Launched with Topic Rotation & Deduplication!")
                        st.rerun()

            with st.expander("📜 View Autopilot Activity Logs", expanded=False):
                logs = ap_status.get("logs", [])
                if logs:
                    for l in logs[:15]:
                        st.text(f"[{l['timestamp']}] {l['message']}")
                else:
                    st.caption("No logs recorded yet.")

            st.markdown("---")
            st.markdown("#### 📜 Sent History & Topic Database")
            sent_count = sent_history.get_sent_count()
            used_topics = sent_history.get_used_topics()
            c_sh1, c_sh2 = st.columns(2)
            with c_sh1:
                st.metric("Unique Leads Contacted", sent_count)
            with c_sh2:
                st.metric("Topics Explored", len(used_topics))

            all_records = sent_history.get_all_sent_records()
            if all_records:
                with st.expander(f"📋 View Sent History Log ({len(all_records)} emails)", expanded=False):
                    history_df = pd.DataFrame(all_records)[["email", "company_name", "topic", "sent_at"]]
                    st.dataframe(history_df, use_container_width=True, hide_index=True)

                with st.expander(f"🏷️ View Explored Topics ({len(used_topics)})", expanded=False):
                    for t in used_topics:
                        st.text(f"• {t}")

                if st.button("🗑️ Clear / Reset Sent History & Topics", use_container_width=True):
                    sent_history.clear_sent_history()
                    st.toast("✅ Sent history and topic memory reset!", icon="🗑️")
                    st.rerun()
            else:
                st.caption("No outreach emails sent yet. Sent history database is clean.")

            st.markdown("---")
            st.markdown("#### Engine Tuning")

            admin_model = st.selectbox(
                "Gemini Model",
                options=["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
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

            st.markdown("##### Google Sheets Sync")
            admin_gsheet_target = st.text_input("Sheet Name or URL", placeholder="e.g. B2B Leads 2026", key="admin_gsheet_target")
            admin_auto_sync = st.checkbox("Auto-sync to Google Sheet", value=False, key="admin_auto_sync_cb")

            if st.button("Log Out of Admin", use_container_width=True):
                st.session_state["admin_authenticated"] = False
                st.session_state["admin_logged_in"] = False
                st.rerun()

    st.caption("⚡ **B2B Lead Machine** • Automated NOWPayments Crypto Gateway")


# Set runtime parameters (Admin overrides if logged in, otherwise default)
effective_model = st.session_state.get("admin_model_select", getattr(settings, "gemini_model", "gemini-1.5-flash"))
effective_concurrency = int(st.session_state.get("admin_concurrency_slider", getattr(settings, "max_concurrent_requests", 3)))
effective_follow_subpages = bool(st.session_state.get("admin_follow_subpages_cb", getattr(settings, "follow_contact_pages", True)))
effective_gsheet_target = str(st.session_state.get("admin_gsheet_target", ""))
effective_auto_sync = bool(st.session_state.get("admin_auto_sync_cb", False))


# =============================================================
# 🚀 Main Storefront Header & Tabs
# =============================================================
st.markdown('<div class="main-header">⚡ Automated B2B Lead Machine</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Autonomous Lead Discovery, Verified Email Extraction & AI Cold Pitch Generator</div>', unsafe_allow_html=True)

tab_search, tab_csv = st.tabs(["🔍 Keyword Search & Lead Discovery", "📁 Upload Existing CSV"])


# -------------------------------------------------------------
# TAB 1: Autonomous Keyword Discovery
# -------------------------------------------------------------
with tab_search:
    st.markdown("### 🎯 Discover Real Companies by Niche & Location")
    st.markdown("Enter a target search phrase (e.g. *'Plumbing contractors in Austin, TX'* or *'Commercial roofing in Miami'*) to autonomously discover official company websites and enrich them.")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input(
            "Search Query / Niche + Location",
            placeholder="e.g. Plumbing contractors in Austin, TX",
            key="keyword_search_input"
        )
    with col2:
        num_leads = st.number_input("Target Lead Count", min_value=3, max_value=30, value=15, step=1)

    btn_discover = st.button("🚀 Generate Leads Table", type="primary", use_container_width=True)

    if btn_discover:
        if not search_query.strip():
            st.error("Please enter a valid search query.")
        else:
            progress_container = st.container()
            with progress_container:
                status_text = st.empty()
                prog_bar = st.progress(0)

                status_text.info(f"🔎 Discovering businesses matching '{search_query}' via DuckDuckGo...")
                try:
                    discovered_inputs = discover_leads_by_keyword(search_query.strip(), max_results=int(num_leads))
                except Exception as disc_err:
                    logger.error(f"Discovery error: {disc_err}")
                    discovered_inputs = []
                    status_text.error(f"⚠️ Search discovery encounter a network issue: {disc_err}. Please retry in a few seconds.")

                if not discovered_inputs:
                    status_text.error("No companies could be discovered for this query. Try refining your search keywords.")
                else:
                    status_text.success(f"✅ Discovered {len(discovered_inputs)} businesses! Starting AI scraping and cold pitch generation...")

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
                            status_text.text(f"Processing ({idx}/{tot}): {lead.company_name}{email_tag}")

                        results = safe_execute_pipeline(
                            pipeline=pipeline,
                            inputs=discovered_inputs,
                            progress_callback=update_ui_progress
                        )

                        prog_bar.progress(100)
                        status_text.success(f"🎉 Successfully enriched {len(results)} leads!")

                        st.session_state["leads"] = results
                        df_data = [r.model_dump() for r in results]
                        st.session_state["df"] = pd.DataFrame(df_data)
                        st.session_state["last_query"] = search_query
                        st.session_state["campaign_results"] = None
                        st.session_state["crypto_invoice_url"] = None
                        st.session_state["crypto_invoice_id"] = None

                        if effective_auto_sync and effective_gsheet_target:
                            try:
                                sync_res = export_leads_to_google_sheet(
                                    leads=results,
                                    sheet_name_or_url=effective_gsheet_target,
                                    worksheet_title="Leads"
                                )
                                if sync_res.get("success"):
                                    st.toast(f"✅ Synced {sync_res.get('rows_appended')} leads to Google Sheet!", icon="📊")
                            except Exception as e:
                                st.warning(f"Google Sheets auto-sync failed: {e}")

                    except Exception as pipe_err:
                        logger.error(f"Pipeline execution error: {pipe_err}")
                        status_text.error(f"⚠️ Enrichment pipeline error: {pipe_err}")


# -------------------------------------------------------------
# TAB 2: CSV Lead Enrichment
# -------------------------------------------------------------
with tab_csv:
    st.markdown("### 📁 Upload Existing CSV")
    st.markdown("Upload a CSV containing company names to enrich them with verified contact emails, summaries, and personalized cold pitches.")

    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            st.dataframe(uploaded_df.head(5), use_container_width=True)

            company_col_detected = detect_company_column(list(uploaded_df.columns))
            selected_col = st.selectbox(
                "Select Company Name Column",
                options=list(uploaded_df.columns),
                index=list(uploaded_df.columns).index(company_col_detected) if company_col_detected in uploaded_df.columns else 0
            )

            btn_enrich_csv = st.button("⚡ Enrich Uploaded CSV", type="primary")

            if btn_enrich_csv:
                input_leads = []
                for _, row in uploaded_df.iterrows():
                    c_name = str(row.get(selected_col, "")).strip()
                    if c_name and c_name.lower() != "nan":
                        input_leads.append(LeadInput(company_name=c_name))

                if not input_leads:
                    st.error("No valid company names found in selected column.")
                else:
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
                                status_text.text(f"Enriching ({idx}/{tot}): {lead.company_name}")

                            results = safe_execute_pipeline(
                                pipeline=pipeline,
                                inputs=input_leads,
                                progress_callback=update_csv_progress
                            )

                            prog_bar.progress(100)
                            status_text.success(f"🎉 Successfully enriched {len(results)} leads from CSV!")

                            st.session_state["leads"] = results
                            st.session_state["df"] = pd.DataFrame([r.model_dump() for r in results])
                            st.session_state["last_query"] = f"CSV: {uploaded_file.name}"
                            st.session_state["campaign_results"] = None
                            st.session_state["crypto_invoice_url"] = None
                            st.session_state["crypto_invoice_id"] = None

                            if effective_auto_sync and effective_gsheet_target:
                                try:
                                    sync_res = export_leads_to_google_sheet(
                                        leads=results,
                                        sheet_name_or_url=effective_gsheet_target,
                                        worksheet_title="Leads"
                                    )
                                    if sync_res.get("success"):
                                        st.toast(f"✅ Synced {sync_res.get('rows_appended')} leads to Google Sheet!", icon="📊")
                                except Exception as e:
                                    st.warning(f"Google Sheets auto-sync failed: {e}")

                        except Exception as csv_pipe_err:
                            logger.error(f"CSV enrichment error: {csv_pipe_err}")
                            status_text.error(f"⚠️ CSV enrichment error: {csv_pipe_err}")

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")


# =============================================================
# 📊 Generated Leads Display (Paywall Protected & Admin View)
# =============================================================
if st.session_state["leads"]:
    df = st.session_state["df"]
    leads: list[EnrichedLead] = st.session_state["leads"]

    is_admin = bool(st.session_state.get("admin_authenticated", False) or st.session_state.get("admin_logged_in", False))
    is_paid = bool(st.session_state.get("payment_verified", False) or st.session_state.get("paid", False))

    st.markdown("---")
    st.markdown("### 📋 Generated Leads Dataset")

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
        if is_admin:
            st.metric("Dataset Access", "🔓 Admin Mode")
        elif is_paid:
            st.metric("Dataset Access", "✅ Unlocked")
        else:
            st.metric("Dataset Access", "🔒 Sample Preview (2 of %d)" % total_leads)

    # ---------------------------------------------------------
    # 🔓 UNLOCKED / ADMIN FULL VIEW
    # ---------------------------------------------------------
    if is_admin or is_paid:
        if is_admin and not is_paid:
            st.info("🔓 **ADMIN MODE ACTIVE:** You are viewing the full, unrestricted leads dataset.")

        # Full Interactive Table
        st.dataframe(
            df[["company_name", "website_url", "primary_email", "company_summary", "personalized_pitch", "status"]],
            column_config={
                "website_url": st.column_config.LinkColumn("Website URL"),
                "primary_email": st.column_config.TextColumn("Contact Email"),
                "personalized_pitch": st.column_config.TextColumn("Cold Email Pitch", width="large")
            },
            use_container_width=True,
            hide_index=True
        )

        # Full Cold Outreach Pitch Cards
        with st.expander("✉️ View Personalized Cold Email Pitches for All Leads", expanded=False):
            for lead in leads:
                st.markdown(f"**📌 {lead.company_name}** (`{lead.primary_email or 'No email found'}`)")
                st.markdown(f"**Summary:** {lead.company_summary or 'N/A'}")
                st.info(lead.personalized_pitch or "N/A")
                st.divider()

    # ---------------------------------------------------------
    # 🔒 PUBLIC RESTRICTED SAMPLE PREVIEW (Max 2 Rows + Copy Protection)
    # ---------------------------------------------------------
    else:
        st.markdown("#### 👁️ Verified Sample Preview (Top 2 Leads)")
        st.caption("🛡️ *Data preview is copy-protected. Complete the $6.00 USD crypto payment below to unlock the full dataset & download CSV.*")

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
                <div style="background:#f8fafc; border-left:3px solid #3b82f6; padding:10px; border-radius:6px; font-size:0.86rem; color:#1e293b;">
                    <strong>AI Cold Pitch Preview:</strong> <em>"{lead.personalized_pitch or 'Custom pitch generated by Gemini'}"</em>
                </div>
            </div>
            """, unsafe_allow_html=True)

        if hidden_count > 0:
            st.markdown(f"""
            <div class="locked-teaser-card">
                <h3 style="color:#334155; margin-top:0; font-weight:800;">🔒 +{hidden_count} More Verified Leads & AI Pitches Locked</h3>
                <p style="color:#64748b; font-size:0.95rem; margin-bottom:0;">
                    Full unmasked contact emails, complete company dossiers, customized cold pitches, and the complete CSV/JSON export are protected behind the paywall.
                </p>
            </div>
            """, unsafe_allow_html=True)

        # High-Converting Paywall Gate Notice
        st.markdown(f"""
        <div class="paywall-gate-card">
            <h2 style="margin-top:0; font-weight:800; color:#ffffff;">🚀 Unlock All {total_leads} Leads & Download Full CSV</h2>
            <p style="font-size:1.05rem; color:#c7d2fe; margin-bottom:14px; max-width:680px; margin-left:auto; margin-right:auto;">
                Complete your checkout for <strong>${CRYPTO_PRICE_USD:.2f} USD</strong> via automated Zero-KYC NOWPayments Crypto Checkout (USDT, BTC, ETH, SOL, LTC) to unlock all unmasked leads immediately.
            </p>
            <span class="pill" style="background:#4338ca; color:#ffffff;">⚡ Instant On-Chain Blockchain Confirmation</span>
            <span class="pill" style="background:#4338ca; color:#ffffff;">📥 Immediate Full CSV Export</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # =========================================================
    # 🚀 Admin Autopilot Outbound Launcher (Gated to Admin)
    # =========================================================
    if is_admin:
        st.markdown("### 📨 Admin Single-Batch Outbound Launcher")
        st.markdown(f"Dispatches personalized cold email pitches from your configured Gmail account with CTA directing to your **${CRYPTO_PRICE_USD:.2f} USD Zero-KYC Crypto Checkout**.")

        eligible_leads = [l for l in leads if getattr(l, "primary_email", None) and "@" in str(getattr(l, "primary_email", ""))]
        unsent_leads, skipped_leads = sent_history.filter_leads_for_dispatch(eligible_leads)

        if eligible_leads:
            sample_lead = eligible_leads[0]
            subj, html_prev, txt_prev = build_outreach_email(sample_lead, app_url=APP_URL, sender_name=SENDER_NAME, price_usd=CRYPTO_PRICE_USD)

            col_adm_info, col_adm_prev = st.columns([1, 1])
            with col_adm_info:
                st.info(f"• **Fresh Unsent Contacts:** {len(unsent_leads)}\n• **Already Emailed (Skipped):** {len(skipped_leads)}\n• **Sender:** `{SMTP_USER}`\n• **CTA:** `${CRYPTO_PRICE_USD:.2f} USD Crypto Checkout`\n• **App URL:** `{APP_URL}`")
            with col_adm_prev:
                with st.expander(f"👁️ Preview Email to {sample_lead.company_name}", expanded=False):
                    st.markdown(f"**Subject:** `{subj}`")
                    st.text(txt_prev)

            send_delay = st.slider("Safety Delay Between Outgoing Emails (Sec)", min_value=3, max_value=15, value=5, step=1, help="5-10s delay prevents triggering Gmail anti-spam sending blocks.", key="batch_delay_slider")

            if len(unsent_leads) == 0:
                st.warning("⚠️ All eligible leads in this table have already been emailed previously. Deduplication filter active.")
            else:
                if st.button("🚀 Launch Single-Batch Outreach Campaign", type="primary", use_container_width=True):
                    if not SMTP_USER or not SMTP_PASSWORD:
                        st.warning("⚠️ SMTP credentials not set in secrets.")
                    else:
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

                            with st.spinner("Connecting to Gmail SMTP & dispatching cold email pitches..."):
                                report = dispatch_campaign(
                                    leads=unsent_leads,
                                    sender_email=SMTP_USER,
                                    app_password=SMTP_PASSWORD,
                                    app_url=APP_URL,
                                    sender_name=SENDER_NAME,
                                    smtp_host=SMTP_HOST,
                                    smtp_port=SMTP_PORT,
                                    price_usd=CRYPTO_PRICE_USD,
                                    topic=st.session_state.get("last_query", "Single Batch Outreach"),
                                    delay_seconds=float(send_delay),
                                    progress_callback=on_email_progress
                                )

                            dispatch_bar.progress(100)
                            st.session_state["campaign_results"] = report
                            if report.get("success"):
                                st.success(f"🎉 Campaign Finished! Successfully sent {report.get('sent_count')} emails ({report.get('skipped_duplicates', 0)} duplicates skipped, {report.get('skipped_invalid', 0)} invalid artifacts skipped).")
                            else:
                                st.warning(f"⚠️ {report.get('message')}")

            if st.session_state["campaign_results"]:
                rep = st.session_state["campaign_results"]
                if rep.get("results"):
                    st.dataframe(pd.DataFrame(rep.get("results", [])), use_container_width=True, hide_index=True)

        st.markdown("---")

    # =========================================================
    # 💳 Automated Zero-KYC Crypto Checkout (NOWPayments)
    # =========================================================
    st.markdown("### 📥 Download Lead Dataset")

    if not is_paid:
        st.markdown(f"""
        <div class="crypto-hero-box">
            <h2 style="color: #ffffff; margin-top: 0; font-weight: 800;">⚡ Instant Zero-KYC Crypto Checkout</h2>
            <p style="color: #cbd5e1; font-size: 1.0rem; margin-bottom: 12px;">
                Pay <strong>${CRYPTO_PRICE_USD:.2f} USD</strong> with <strong>Bitcoin (BTC), USDT (TRC20/ERC20), Ethereum (ETH), Solana (SOL), Litecoin (LTC)</strong> or 150+ cryptocurrencies.
            </p>
            <span class="pill">🔒 100% Automated On-Chain Verification</span>
            <span class="pill">⚡ Instant CSV Download Upon Confirmation</span>
        </div>
        """, unsafe_allow_html=True)

        c_cr1, c_cr2 = st.columns([1, 1])

        with c_cr1:
            st.markdown("#### 1. Generate Payment Invoice")
            if st.button("⚡ Generate Secure Crypto Invoice ($6 USD)", type="primary", use_container_width=True):
                if not NOWPAYMENTS_API_KEY or NOWPAYMENTS_API_KEY == "dummy_nowpayments_key":
                    st.warning("⚠️ NOWPAYMENTS_API_KEY is not configured in secrets. Please set your NOWPayments API Key in Streamlit Cloud Secrets.")
                else:
                    with st.spinner("Connecting to NOWPayments API..."):
                        inv = create_nowpayments_invoice(
                            api_key=NOWPAYMENTS_API_KEY,
                            price_amount=CRYPTO_PRICE_USD,
                            price_currency="usd",
                            order_description=f"B2B Leads Machine - {len(leads)} Verified Leads Export"
                        )
                        if inv.get("success"):
                            st.session_state["crypto_invoice_url"] = inv.get("invoice_url")
                            st.session_state["crypto_invoice_id"] = inv.get("invoice_id")
                            st.success("🎉 Crypto invoice generated successfully!")
                        else:
                            st.error(f"Failed to generate invoice: {inv.get('error')}")

            if st.session_state["crypto_invoice_url"]:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                st.link_button(
                    label=f"🚀 Pay ${CRYPTO_PRICE_USD:.2f} with Crypto on NOWPayments",
                    url=st.session_state["crypto_invoice_url"],
                    type="primary",
                    use_container_width=True
                )
                st.caption(f"Invoice ID: `{st.session_state['crypto_invoice_id']}`")

        with c_cr2:
            st.markdown("#### 2. Automatic Invoice Verification")
            st.markdown("Once you complete payment in your wallet, click below to verify invoice on-chain:")

            inv_id_input = st.text_input(
                "Invoice ID",
                value=st.session_state["crypto_invoice_id"] or "",
                placeholder="e.g. 5527915624",
                help="The Invoice ID generated by NOWPayments (auto-filled)."
            )

            if st.button("🔄 Check Payment Status & Unlock CSV", use_container_width=True):
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
                                st.toast("🎉 Crypto payment verified! Full CSV download unlocked.", icon="✅")
                                st.rerun()
                            else:
                                st.info(f"⏳ Current Invoice Status: `{status_name}`. Please complete the transfer on NOWPayments and re-check once confirmed on the blockchain.")
                        else:
                            st.error(f"Could not verify invoice: {stat.get('error')}")

            with st.expander("🔑 Manual Passcode / Admin Unlock", expanded=False):
                entered_passcode = st.text_input("Enter Passcode", type="password", placeholder="Enter unlock code...", key="manual_passcode_field")
                if st.button("Unlock with Code", use_container_width=True):
                    clean_code = entered_passcode.strip()
                    if clean_code and (clean_code == UNLOCK_CODE or clean_code == ADMIN_PASSWORD):
                        st.session_state["payment_verified"] = True
                        st.session_state["paid"] = True
                        st.toast("🎉 Passcode verified! Full CSV download unlocked.", icon="✅")
                        st.rerun()
                    else:
                        st.error("⚠️ Invalid code.")

    else:
        # Payment Verified -> Reveal Download CSV and JSON buttons!
        st.markdown(f"""
        <div class="unlocked-box">
            <h3 style="color: #15803d; margin-bottom: 4px;">🎉 Full Lead Dataset Unlocked!</h3>
            <p style="color: #166534; margin: 0;">Payment confirmed on-chain. Download your verified lead dataset below!</p>
        </div>
        """, unsafe_allow_html=True)

        c_dl1, c_dl2 = st.columns([1, 1])
        with c_dl1:
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            st.download_button(
                label="📥 Download Full CSV",
                data=csv_buffer.getvalue(),
                file_name=f"enriched_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )
        with c_dl2:
            json_str = json.dumps([l.model_dump() for l in leads], indent=2)
            st.download_button(
                label="📥 Download Full JSON",
                data=json_str,
                file_name=f"enriched_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True
            )
