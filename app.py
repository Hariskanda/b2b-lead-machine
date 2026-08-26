import asyncio
import io
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

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
# 1. GLOBAL PAGE CONFIG & MODERN SAAS CSS
# =============================================================
st.set_page_config(
    page_title="ApexLeads AI",
    page_icon="⚡",
    layout="wide"
)

APP_NAME = "ApexLeads AI"
ADMIN_CONTACT_EMAIL = "hariskandapg@gmail.com"
ADMIN_PASSCODE = "admin123"
UNLOCK_PASSCODE = "4990"

# Inject modern dark-mode SaaS CSS
st.markdown("""
<style>
    /* Remove default Streamlit header/footer clutter */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}
    div[data-testid="stDecoration"] {visibility: hidden;}

    /* Modern Dark Theme */
    .stApp {
        background-color: #0b0f17;
        color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    }

    /* Top Platform Header */
    .apex-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 24px;
        background: linear-gradient(180deg, rgba(17, 24, 39, 0.95) 0%, rgba(15, 23, 42, 0.85) 100%);
        backdrop-filter: blur(16px);
        border: 1px solid #1e293b;
        border-radius: 14px;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
    }
    .brand-title {
        font-size: 1.35rem;
        font-weight: 850;
        background: linear-gradient(135deg, #ffffff 0%, #38bdf8 60%, #818cf8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.02em;
    }

    /* Rounded Container Cards */
    .saas-card {
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 22px;
        background-color: #111827;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
        margin-bottom: 20px;
    }

    /* Hero Sign-In Card */
    .hero-sign-card {
        border: 1px solid #3b82f6;
        border-radius: 18px;
        padding: 40px 32px;
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #0f172a 100%);
        text-align: center;
        box-shadow: 0 12px 36px rgba(59, 130, 246, 0.25);
        max-width: 680px;
        margin: 40px auto 20px auto;
    }
    .hero-sign-card h1 {
        font-size: 2.3rem;
        font-weight: 850;
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 12px;
    }
    .hero-sign-card p {
        color: #cbd5e1;
        font-size: 1.05rem;
        line-height: 1.5;
        margin-bottom: 24px;
    }

    /* Audit Display Card */
    .audit-card {
        border-left: 4px solid #10b981;
        background: #111827;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
        border: 1px solid #1f2937;
        color: #e2e8f0;
    }

    /* Badges & Pills */
    .pill-badge {
        display: inline-block;
        background: #1e293b;
        color: #93c5fd;
        border: 1px solid #334155;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
    }
    .pill-credit {
        display: inline-block;
        background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        color: #ffffff;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 700;
    }

    /* Large Mailto Upgrade Button */
    .mailto-upgrade-btn {
        display: inline-block;
        background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
        color: #ffffff !important;
        text-decoration: none;
        padding: 14px 32px;
        border-radius: 10px;
        font-weight: 700;
        font-size: 1.05rem;
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4);
        border: 1px solid #60a5fa;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        margin: 16px 0;
    }
    .mailto-upgrade-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 22px rgba(56, 189, 248, 0.5);
    }

    /* Styled Action Buttons */
    div.stButton > button:first-child {
        border-radius: 8px;
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
# Helper Utilities & Pipeline Execution
# =============================================================
def get_secret(key: str, default: Any = None) -> Any:
    """Safely retrieves secret configuration."""
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
    except Exception:
        pass

    return default


def safe_execute_pipeline_sync(
    pipeline: LeadGenPipeline,
    inputs: List[LeadInput],
    progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
) -> List[EnrichedLead]:
    """Executes the lead pipeline synchronously in the main Streamlit thread."""
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


def generate_mailto_url(user_email: str) -> str:
    """Creates a clean mailto link for credit extension requests."""
    clean_email = user_email.strip() if user_email else "user@agency.com"
    subject = urllib.parse.quote("Credit Extension Request")
    body = urllib.parse.quote(
        f"Hi Haris,\n\nMy account ({clean_email}) has exhausted its search credits on ApexLeads AI.\nI would like to request more credits.\n\nThank you!"
    )
    return f"mailto:{ADMIN_CONTACT_EMAIL}?subject={subject}&body={body}"


# Initialize Core Session State
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "credits" not in st.session_state:
    st.session_state.credits = 3
if "leads_data" not in st.session_state:
    st.session_state.leads_data = []
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()
if "agency_name" not in st.session_state:
    st.session_state.agency_name = "ApexLeads Agency Partners"
if "agency_website" not in st.session_state:
    st.session_state.agency_website = "https://apexleads.ai"
if "running" not in st.session_state:
    st.session_state.running = False


GEMINI_API_KEY = get_secret("GEMINI_API_KEY", getattr(settings, "effective_api_key", None))
effective_model = getattr(settings, "gemini_model", "gemini-2.5-flash")
effective_concurrency = int(getattr(settings, "max_concurrent_requests", 5))


# =============================================================
# 2. SIMPLE, WORKING SIGN-IN GATE (NO OAUTH BUGS)
# =============================================================
if "user_email" not in st.session_state or not st.session_state.user_email:
    st.markdown(f"""
    <div class="hero-sign-card">
        <span class="pill-badge" style="margin-bottom:12px;">⚡ THE NEW STANDARD IN HIGH-TICKET OUTBOUND</span>
        <h1>⚡ ApexLeads AI</h1>
        <p>
            Find high-converting local leads, generate instant AI website audits, and scale client outreach.
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        with st.container(border=True):
            st.markdown("### 🚀 Get Started with 3 Free Credits")
            email_in = st.text_input("Enter your business email to get 3 free search credits:", placeholder="e.g. founder@growthagency.com")
            
            if st.button("Launch Platform →", type="primary", width="stretch"):
                clean_email = email_in.strip().lower()
                if not clean_email or "@" not in clean_email or "." not in clean_email:
                    st.error("Please enter a valid email address.")
                else:
                    st.session_state.user_email = clean_email
                    st.session_state.credits = 3
                    st.toast(f"Welcome, {clean_email}!", icon="👋")
                    st.rerun()

    st.stop()


# =============================================================
# TOP NAVIGATION HEADER & SIDEBAR
# =============================================================
st.markdown(f"""
<div class="apex-header">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:1.4rem;">⚡</span>
        <span class="brand-title">{APP_NAME}</span>
        <span class="pill-badge" style="color:#34d399; border-color:rgba(16, 185, 129, 0.3);">● Online</span>
    </div>
    <div style="display:flex; align-items:center; gap:14px;">
        <span class="pill-credit">🔍 {st.session_state.credits} Search Credits Left</span>
        <span style="color:#94a3b8; font-size:0.88rem;">👤 {st.session_state.user_email}</span>
    </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown(f"### ⚡ **{APP_NAME}**")
    st.markdown(f"👤 **Account:** `{st.session_state.user_email}`")
    
    st.metric("Remaining Credits", st.session_state.credits)

    if st.button("Sign Out", width="stretch"):
        st.session_state.user_email = None
        st.session_state.credits = 3
        st.session_state.leads_data = []
        st.session_state.df = pd.DataFrame()
        st.rerun()

    st.divider()

    # White-label report branding
    with st.expander("🏢 White-Label Report Branding", expanded=False):
        agency_name = st.text_input("Agency / Company Name", value=st.session_state.agency_name)
        st.session_state.agency_name = agency_name
        agency_web = st.text_input("Agency Website URL", value=st.session_state.agency_website)
        st.session_state.agency_website = agency_web
        st.caption("Custom branding stamped onto all generated PDF audits.")

    st.divider()

    # Quick mailto extension
    st.markdown("#### 💎 Need More Credits?")
    mailto_quick = generate_mailto_url(st.session_state.user_email)
    st.markdown(f"""
    <a href="{mailto_quick}" target="_blank" style="display:block; text-align:center; background:#1e293b; color:#38bdf8; border:1px solid #334155; padding:8px 12px; border-radius:8px; text-decoration:none; font-weight:600; font-size:0.84rem;">
        📧 Email Haris for More
    </a>
    """, unsafe_allow_html=True)

    st.divider()

    # Admin Passcode Field
    with st.expander("🔑 Admin Passcode Unlock", expanded=False):
        passcode_in = st.text_input("Enter Passcode to reset to 10 credits", type="password")
        if st.button("Apply Passcode", width="stretch"):
            if passcode_in.strip() in [ADMIN_PASSCODE, UNLOCK_PASSCODE]:
                st.session_state.credits = 10
                st.toast("Credits reset to 10!", icon="🎉")
                st.rerun()
            else:
                st.error("Invalid passcode.")


# =============================================================
# 3. TAB-BASED VISIBLE NAVIGATION
# =============================================================
tab_dash, tab_leads, tab_upgrade = st.tabs([
    "📊 Lead Engine & Audit",
    "📁 Saved Results & PDF",
    "💎 Search Credits & Support"
])


# =============================================================
# 4. TAB 1: LEAD ENGINE & SEARCH LIMIT LOGIC
# =============================================================
with tab_dash:
    with st.container(border=True):
        st.markdown("### 🎯 Find Local Businesses & Generate AI Audits")
        st.markdown("Enter target keywords, industry, and city (e.g. *'Commercial roofing in Miami, FL'* or *'HVAC contractors in Dallas, TX'*):")

        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            niche_query = st.text_input("Target Niche / Service", placeholder="e.g. Commercial Roofing Contractors", key="niche_input")
        with c2:
            location_query = st.text_input("City / Metro Location", placeholder="e.g. Miami, FL", key="location_input")
        with c3:
            lead_count = st.number_input("Lead Count", min_value=3, max_value=30, value=10, step=1)

        c_btn, c_stat = st.columns([2, 1])
        with c_btn:
            btn_generate = st.button("🚀 Generate Leads & Mini-Audits", type="primary", width="stretch", disabled=st.session_state.running)
        with c_stat:
            st.metric("Remaining Search Credits", st.session_state.credits)

    # Lead Generation Action
    if btn_generate:
        combined_query = f"{niche_query.strip()} in {location_query.strip()}".strip() if location_query.strip() else niche_query.strip()

        if not combined_query:
            st.error("Please enter a target niche or location.")
        elif st.session_state.credits <= 0:
            st.error("⚠️ You have exhausted your free search credits. Please visit the **💎 Search Credits & Support** tab to request more credits from Haris.")
        else:
            st.session_state.running = True
            try:
                with st.spinner(f"🔎 Discovering businesses and generating AI audits for '{combined_query}'..."):
                    progress_box = st.container(border=True)
                    with progress_box:
                        status_text = st.empty()
                        prog_bar = st.progress(0)

                        status_text.info(f"🔎 Searching DuckDuckGo for '{combined_query}'...")
                        discovered = discover_leads_by_keyword(combined_query, max_results=int(lead_count))

                        if not discovered:
                            status_text.error("No company websites found for this query. Try refining your keywords.")
                        else:
                            status_text.success(f"✅ Found {len(discovered)} businesses! Running Gemini 2026 AI Audits in parallel...")

                            pipeline = LeadGenPipeline(
                                api_key=GEMINI_API_KEY,
                                model=effective_model,
                                max_concurrency=effective_concurrency,
                                follow_contact_pages=True,
                                use_checkpoint=False
                            )

                            def update_lead_progress(lead: EnrichedLead, idx: int, tot: int):
                                pct = int((idx / tot) * 100) if tot > 0 else 0
                                prog_bar.progress(min(100, max(0, pct)))
                                email_tag = f" — 📧 Found: `{lead.primary_email}`" if lead.primary_email else ""
                                status_text.markdown(f"⚡ **Auditing {idx} of {tot}:** `{lead.company_name}`...{email_tag}")

                            results = safe_execute_pipeline_sync(
                                pipeline=pipeline,
                                inputs=discovered,
                                progress_callback=update_lead_progress
                            )

                            # Deduct credit on successful run
                            st.session_state.credits -= 1
                            prog_bar.progress(100)
                            status_text.success(f"🎉 Successfully generated {len(results)} verified leads with AI Audits! (1 credit deducted)")

                            st.session_state.leads_data = results
                            st.session_state.df = pd.DataFrame([r.model_dump() for r in results])
                            st.rerun()

            except Exception as e:
                st.error(f"Error during lead generation: {e}")
            finally:
                st.session_state.running = False

    # Optional CSV Upload section
    with st.expander("📁 Or Enrich an Existing CSV File", expanded=False):
        uploaded_file = st.file_uploader("Upload CSV with company names", type=["csv"])
        if uploaded_file is not None:
            try:
                uploaded_df = pd.read_csv(uploaded_file)
                st.dataframe(uploaded_df.head(4), width="stretch", hide_index=True)
                col_name_detect = detect_company_column(list(uploaded_df.columns))
                selected_col = st.selectbox(
                    "Company Name Column",
                    options=list(uploaded_df.columns),
                    index=list(uploaded_df.columns).index(col_name_detect) if col_name_detect in uploaded_df.columns else 0
                )

                if st.button("⚡ Enrich Uploaded CSV", type="primary", disabled=st.session_state.running):
                    if st.session_state.credits <= 0:
                        st.error("⚠️ You have exhausted your free search credits. Please request more in the Upgrade tab.")
                    else:
                        csv_inputs = []
                        for _, row in uploaded_df.iterrows():
                            cn = str(row.get(selected_col, "")).strip()
                            if cn and cn.lower() != "nan":
                                csv_inputs.append(LeadInput(company_name=cn))

                        if not csv_inputs:
                            st.error("No valid company names found.")
                        else:
                            st.session_state.running = True
                            try:
                                with st.spinner("Enriching CSV accounts with AI audits..."):
                                    pipeline = LeadGenPipeline(
                                        api_key=GEMINI_API_KEY,
                                        model=effective_model,
                                        max_concurrency=effective_concurrency,
                                        follow_contact_pages=True,
                                        use_checkpoint=False
                                    )
                                    csv_results = safe_execute_pipeline_sync(pipeline=pipeline, inputs=csv_inputs)
                                    st.session_state.credits -= 1
                                    st.session_state.leads_data = csv_results
                                    st.session_state.df = pd.DataFrame([r.model_dump() for r in csv_results])
                                    st.success(f"Enriched {len(csv_results)} companies from CSV! (1 credit deducted)")
                                    st.rerun()
                            finally:
                                st.session_state.running = False
            except Exception as ex:
                st.error(f"Error reading CSV: {ex}")


# =============================================================
# 5. TAB 2: AUDIT RESULTS & EXPORT
# =============================================================
with tab_leads:
    if not st.session_state.leads_data:
        st.info("No leads generated yet. Run a search in the **📊 Lead Engine & Audit** tab to see results and download PDFs.")
    else:
        leads: List[EnrichedLead] = st.session_state.leads_data
        df = st.session_state.df

        st.markdown("### 📋 Generated Leads & AI Digital Growth Audits")
        
        # Summary Metrics
        tot = len(leads)
        emails_found = sum(1 for l in leads if l.primary_email)
        rate = f"{(emails_found / tot * 100):.1f}%" if tot else "0%"

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Total Companies Audited", tot)
        with m2:
            st.metric("Verified Emails Discovered", emails_found)
        with m3:
            st.metric("Email Discovery Rate", rate)

        # Full Dataframe Table
        st.dataframe(
            df[["company_name", "website_url", "primary_email", "company_summary", "custom_audit", "status"]],
            column_config={
                "website_url": st.column_config.LinkColumn("Website URL"),
                "primary_email": st.column_config.TextColumn("Contact Email"),
                "custom_audit": st.column_config.TextColumn("3-Point AI Mini-Audit", width="large")
            },
            width="stretch",
            hide_index=True
        )

        st.markdown("---")
        st.markdown("#### 📥 Export & PDF Reports")
        st.caption(f"Branded for: **{st.session_state.agency_name}** ({st.session_state.agency_website})")

        c_dl1, c_dl2 = st.columns(2)
        with c_dl1:
            try:
                bundle_bytes = generate_batch_audit_bundle_pdf(
                    leads=leads,
                    agency_name=st.session_state.agency_name,
                    agency_website=st.session_state.agency_website
                )
                st.download_button(
                    label="📑 Download Complete Multi-Client PDF Audit Bundle",
                    data=bundle_bytes,
                    file_name=f"apexleads_audit_bundle_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    width="stretch"
                )
            except Exception as err:
                st.error(f"Error generating PDF bundle: {err}")

        with c_dl2:
            csv_buf = io.StringIO()
            df.to_csv(csv_buf, index=False)
            st.download_button(
                label="📥 Download Full Leads CSV",
                data=csv_buf.getvalue(),
                file_name=f"apexleads_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                width="stretch"
            )

        # Individual PDF Cards
        with st.expander("🔍 View Individual Company Audits & 1-Click Single PDFs", expanded=False):
            for idx, lead in enumerate(leads, 1):
                col_a1, col_a2 = st.columns([4, 1])
                with col_a1:
                    st.markdown(f"**📌 {idx}. {lead.company_name}** (`{lead.primary_email or 'No email found'}`)")
                    st.markdown(f"**Summary:** {lead.company_summary or 'N/A'}")
                    st.markdown(f"""
                    <div class="audit-card">
                        <strong>3-Point AI Growth Audit:</strong><br>
                        {lead.custom_audit or lead.personalized_pitch or 'Audit generated by Gemini'}
                    </div>
                    """, unsafe_allow_html=True)
                with col_a2:
                    try:
                        single_pdf = generate_company_audit_pdf(
                            company_name=lead.company_name,
                            website_url=lead.website_url,
                            primary_email=lead.primary_email,
                            summary=lead.company_summary,
                            custom_audit=lead.custom_audit or lead.personalized_pitch,
                            agency_name=st.session_state.agency_name,
                            agency_website=st.session_state.agency_website
                        )
                        st.download_button(
                            label="📄 Download PDF",
                            data=single_pdf,
                            file_name=f"audit_{re.sub(r'[^a-zA-Z0-9]', '_', lead.company_name).lower()}.pdf",
                            mime="application/pdf",
                            key=f"single_pdf_btn_{idx}",
                            width="stretch"
                        )
                    except Exception as e:
                        st.caption(f"PDF gen error: {e}")
                st.divider()


# =============================================================
# 6. TAB 3: UPGRADE & CONTACT (HARISKANDAPG@GMAIL.COM)
# =============================================================
with tab_upgrade:
    with st.container(border=True):
        st.markdown("### 💎 Need More Search Credits?")
        st.markdown(f"Your logged-in email: **`{st.session_state.user_email}`**")
        st.markdown(f"Current Credit Balance: **`{st.session_state.credits} Searches Remaining`**")

        st.markdown("""
        To extend your search credits, request unlimited agency access, or ask for custom industry scraping pools, click the button below to send a direct message to Haris.
        """)

        mailto_full = generate_mailto_url(st.session_state.user_email)
        st.markdown(f"""
        <div style="text-align:center; padding:16px 0;">
            <a href="{mailto_full}" target="_blank" class="mailto-upgrade-btn">
                📧 Request More Credits via Email (hariskandapg@gmail.com)
            </a>
        </div>
        """, unsafe_allow_html=True)

        st.caption(f"Creator & Admin Email: `{ADMIN_CONTACT_EMAIL}`")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("### 🔑 Admin Passcode Manual Override")
        st.caption("Enter the testing passcode to instantly replenish 10 search credits.")
        passcode_input_tab = st.text_input("Enter Passcode", type="password", key="passcode_tab_in")
        if st.button("Reset to 10 Credits", type="primary"):
            if passcode_input_tab.strip() in [ADMIN_PASSCODE, UNLOCK_PASSCODE]:
                st.session_state.credits = 10
                st.toast("🎉 Credits replenished to 10!", icon="⚡")
                st.rerun()
            else:
                st.error("Invalid passcode.")
