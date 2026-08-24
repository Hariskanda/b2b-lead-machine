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

from b2b_leadgen.config import settings
from b2b_leadgen.email_dispatcher import build_outreach_email, dispatch_campaign
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.history import sent_history
from b2b_leadgen.models import EnrichedLead, LeadInput
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
    "payment_verified": True,   # 100% Free Access Mode Active
    "paid": True,               # 100% Free Access Mode Active
    "admin_authenticated": False,
    "admin_logged_in": False,
    "campaign_results": None,
    "sync_status": None,
}

for state_key, state_default in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_default


# Custom CSS styling with Mobile Responsiveness & Free Tier Banner
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
        margin-bottom: 1.2rem;
    }
    .free-tier-banner {
        background: linear-gradient(135deg, #065f46 0%, #047857 100%);
        border: 2px solid #34d399;
        border-radius: 12px;
        padding: 14px 20px;
        color: #ffffff;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 14px rgba(4, 120, 87, 0.25);
    }
    .storefront-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: #ffffff;
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
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
    .outreach-box {
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        border: 2px solid #818cf8;
        border-radius: 16px;
        padding: 22px;
        color: #ffffff;
        margin: 20px 0;
        box-shadow: 0 6px 20px rgba(49, 46, 129, 0.25);
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
ADMIN_PASSWORD: str = str(get_secret("ADMIN_PASSWORD", getattr(settings, "admin_password", "admin123")))
SMTP_USER: str = str(get_secret("SMTP_USER", getattr(settings, "effective_smtp_user", "")))
SMTP_PASSWORD: str = str(get_secret("SMTP_PASSWORD", getattr(settings, "effective_smtp_password", "")))
SMTP_HOST: str = str(get_secret("SMTP_HOST", getattr(settings, "smtp_host", "smtp.gmail.com")))
SMTP_PORT: int = int(get_secret("SMTP_PORT", getattr(settings, "smtp_port", 587)))
SENDER_NAME: str = str(get_secret("SENDER_NAME", getattr(settings, "sender_name", "B2B Lead Machine")))
APP_URL: str = str(get_secret("APP_URL", getattr(settings, "effective_app_url", "http://localhost:8501")))


# State Accessors
is_admin_active = bool(st.session_state.get("admin_authenticated", False) or st.session_state.get("admin_logged_in", False))


# =============================================================
# 🛍️ Clean Public Sidebar Interface & Settings
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
        <span class="pill">📥 100% Free CSV Downloads</span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📦 Access Status")
    st.success("✅ FREE ACCESS ACTIVE — Full Dataset & CSV Export Unlocked")

    st.divider()

    # 📜 Persistent Sent History & Global Deduplication Metrics
    with st.expander("📜 Global Sent History & Memory", expanded=False):
        sent_count = sent_history.get_sent_count()
        used_topics = sent_history.get_used_topics()
        c_sh1, c_sh2 = st.columns(2)
        with c_sh1:
            st.metric("Total Emailed", sent_count)
        with c_sh2:
            st.metric("Topics Used", len(used_topics))

        all_records = sent_history.get_all_sent_records()
        if all_records:
            st.caption(f"🛡️ Strict deduplication active across {len(all_records)} contacts.")
            history_df = pd.DataFrame(all_records)[["email", "company_name", "topic", "sent_at"]]
            st.dataframe(history_df, use_container_width=True, hide_index=True)

            if st.button("🗑️ Clear / Reset Sent History", use_container_width=True):
                sent_history.clear_sent_history()
                st.toast("✅ Global sent history cleared!", icon="🗑️")
                st.rerun()
        else:
            st.caption("No outreach emails sent yet. Global deduplication database is clean.")

    st.divider()

    # 🔐 Admin Portal (Optional Engine Tuning & Google Sheets Sync)
    with st.expander("⚙️ Advanced Settings & Tuning", expanded=False):
        if not is_admin_active:
            admin_pwd_input = st.text_input("Admin Password (Optional)", type="password", key="admin_pwd_input")
            if st.button("Unlock Advanced Settings", use_container_width=True):
                if admin_pwd_input and admin_pwd_input == ADMIN_PASSWORD:
                    st.session_state["admin_authenticated"] = True
                    st.session_state["admin_logged_in"] = True
                    st.success("Advanced settings unlocked!")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid Admin Password.")
        else:
            st.markdown('<span style="color:#15803d; font-weight:700;">🔓 ADVANCED SETTINGS ACTIVE</span>', unsafe_allow_html=True)

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

            if st.button("Log Out of Settings", use_container_width=True):
                st.session_state["admin_authenticated"] = False
                st.session_state["admin_logged_in"] = False
                st.rerun()

    st.caption("⚡ **B2B Lead Machine** • Free Lead Discovery & Outreach Engine")


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

# 🎁 Free Tier Active Banner
st.markdown("""
<div class="free-tier-banner">
    <strong style="font-size:1.1rem;">🎉 Free Tier Active:</strong> Instant, unrestricted lead discovery with direct CSV/JSON download access. No paywall required!
</div>
""", unsafe_allow_html=True)

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
                    status_text.error(f"⚠️ Search discovery encountered a network issue: {disc_err}. Please retry in a few moments.")

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
# 📊 Generated Leads Display (100% Free & Full Access)
# =============================================================
if st.session_state["leads"]:
    df = st.session_state["df"]
    leads: list[EnrichedLead] = st.session_state["leads"]

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
        st.metric("Dataset Access", "✅ Unrestricted Free")

    # Full Interactive Table (Unrestricted for all users)
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

    # 📥 Instant Free CSV & JSON Download Actions
    st.markdown("### 📥 Instant Free CSV / JSON Export")
    c_dl1, c_dl2 = st.columns([1, 1])
    with c_dl1:
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Download Full CSV (Free)",
            data=csv_buffer.getvalue(),
            file_name=f"enriched_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True
        )
    with c_dl2:
        json_str = json.dumps([l.model_dump() for l in leads], indent=2)
        st.download_button(
            label="📥 Download Full JSON (Free)",
            data=json_str,
            file_name=f"enriched_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True
        )

    st.markdown("---")

    # =========================================================
    # 📨 Explicit Manual Outreach Campaign Launcher (Anti-Spam Deduplicated)
    # =========================================================
    st.markdown("### 📨 Manual Outbound Campaign Launcher")
    st.markdown("Dispatches personalized cold email pitches from your configured Gmail account with **strict global deduplication** to ensure no contact ever receives duplicate emails.")

    eligible_leads = [l for l in leads if getattr(l, "primary_email", None) and "@" in str(getattr(l, "primary_email", ""))]
    unsent_leads, skipped_leads = sent_history.filter_leads_for_dispatch(eligible_leads)

    if eligible_leads:
        sample_lead = eligible_leads[0]
        subj, html_prev, txt_prev = build_outreach_email(sample_lead, app_url=APP_URL, sender_name=SENDER_NAME)

        col_adm_info, col_adm_prev = st.columns([1, 1])
        with col_adm_info:
            st.info(f"• **Fresh Unsent Contacts:** {len(unsent_leads)}\n• **Already Contacted (Globally Skipped):** {len(skipped_leads)}\n• **Sender:** `{SMTP_USER}`\n• **App URL:** `{APP_URL}`")
        with col_adm_prev:
            with st.expander(f"👁️ Preview Email to {sample_lead.company_name}", expanded=False):
                st.markdown(f"**Subject:** `{subj}`")
                st.text(txt_prev)

        send_delay = st.slider("Safety Delay Between Outgoing Emails (Sec)", min_value=3, max_value=15, value=5, step=1, help="5-10s delay prevents triggering Gmail anti-spam sending blocks.", key="batch_delay_slider")

        if len(unsent_leads) == 0:
            st.warning("🛡️ All eligible leads in this dataset have already been contacted in past runs. Global deduplication filter has protected them from receiving duplicate emails.")
        else:
            if st.button("🚀 Launch Outreach Campaign (Manual Trigger Only)", type="primary", use_container_width=True):
                if not SMTP_USER or not SMTP_PASSWORD:
                    st.warning("⚠️ SMTP credentials (SMTP_USER, SMTP_PASSWORD) not set in secrets.")
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
                                topic=st.session_state.get("last_query", "Manual Batch Outreach"),
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
    else:
        st.info("ℹ️ No leads with verified email addresses found in the current table to dispatch.")
