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
# 1. GLOBAL PAGE CONFIG & PURE CSS RADIAL GRADIENT THEME
# =============================================================
st.set_page_config(
    page_title="ApexLeads AI | B2B Lead Intelligence",
    page_icon="⚡",
    layout="wide"
)

APP_NAME = "ApexLeads AI"
APP_TAGLINE = "B2B Outbound Intelligence & Automated Growth Audits"
ADMIN_CONTACT_EMAIL = "hariskandapg@gmail.com"
ADMIN_PASSCODE = "admin123"
UNLOCK_PASSCODE = "4990"

# Inject High-Performance Pure CSS (Zero External Image Dependencies)
st.markdown("""
<style>
    /* Remove default Streamlit header/footer clutter */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}
    div[data-testid="stDecoration"] {visibility: hidden;}

    /* Radial gradient background */
    .stApp {
        background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #0f172a 50%, #020617 100%) !important;
        color: #F8FAFC !important;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    }

    /* Force all text pure white & readable */
    h1, h2, h3, h4, p, span, label, .stMarkdown {
        color: #F8FAFC !important;
    }

    /* Card Containers */
    .saas-card {
        background: rgba(30, 41, 59, 0.7) !important;
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
        border-radius: 12px !important;
        padding: 20px !important;
        margin-bottom: 16px !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3) !important;
    }

    /* Native CSS Feature Showcase Cards */
    .feature-box {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
        border: 1px solid rgba(99, 102, 241, 0.25);
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 16px;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .feature-box:hover {
        transform: translateY(-3px);
        border-color: #38bdf8;
    }
    .feature-icon-wrapper {
        width: 44px;
        height: 44px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.4rem;
        margin-bottom: 12px;
    }

    /* Top Header Bar */
    .apex-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 24px;
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 14px;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
    }
    .brand-title {
        font-size: 1.45rem;
        font-weight: 850;
        background: linear-gradient(135deg, #ffffff 0%, #38bdf8 50%, #a855f7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.02em;
    }
    .pill-credit-badge {
        display: inline-block;
        background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        color: #ffffff !important;
        padding: 6px 14px;
        border-radius: 9999px;
        font-size: 0.84rem;
        font-weight: 700;
        box-shadow: 0 2px 10px rgba(16, 185, 129, 0.35);
    }

    /* Input box visibility */
    .stTextInput > div > div > input, .stNumberInput input {
        background-color: #1E293B !important;
        color: #FFFFFF !important;
        border: 1px solid #475569 !important;
        border-radius: 8px !important;
    }

    /* Primary Action Buttons */
    .stButton > button {
        background: linear-gradient(90deg, #3B82F6, #8B5CF6) !important;
        color: #FFFFFF !important;
        font-weight: bold !important;
        border: none !important;
        padding: 10px 24px !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 14px rgba(59, 130, 246, 0.35) !important;
        transition: all 0.2s ease-in-out !important;
    }
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 20px rgba(56, 189, 248, 0.5) !important;
    }

    /* Tab navigation high visibility */
    button[data-baseweb="tab"] {
        color: #94A3B8 !important;
        font-size: 16px !important;
        font-weight: 700 !important;
        padding: 10px 20px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #38BDF8 !important;
        border-bottom: 3px solid #38BDF8 !important;
    }

    /* Audit Display Card */
    .audit-card {
        border-left: 4px solid #10b981;
        background: #111827;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
        border: 1px solid #1f2937;
        color: #f8fafc !important;
    }

    /* Large Mailto Button */
    .mailto-upgrade-btn {
        display: inline-block;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6);
        color: #ffffff !important;
        text-decoration: none;
        padding: 14px 32px;
        border-radius: 10px;
        font-weight: 700;
        font-size: 1.05rem;
        box-shadow: 0 4px 18px rgba(37, 99, 235, 0.45);
        border: 1px solid #60a5fa;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        margin: 16px 0;
    }
    .mailto-upgrade-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 24px rgba(56, 189, 248, 0.55);
    }
</style>
""", unsafe_allow_html=True)


# =============================================================
# 2. SAFE SESSION STATE INITIALIZATION (NO LOCKOUTS)
# =============================================================
if "user_email" not in st.session_state or not st.session_state.user_email:
    st.session_state.user_email = "guest@apexleads.ai"
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


# =============================================================
# Helper Utilities & Execution Engine
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


GEMINI_API_KEY = get_secret("GEMINI_API_KEY", getattr(settings, "effective_api_key", None))
effective_model = getattr(settings, "gemini_model", "gemini-2.5-flash")
effective_concurrency = int(getattr(settings, "max_concurrent_requests", 5))


# =============================================================
# TOP HEADER BAR & SIDEBAR
# =============================================================
st.markdown(f"""
<div class="apex-header">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:1.5rem;">⚡</span>
        <div>
            <span class="brand-title">{APP_NAME}</span>
            <div style="font-size:0.75rem; color:#94a3b8;">{APP_TAGLINE}</div>
        </div>
    </div>
    <div style="display:flex; align-items:center; gap:16px;">
        <span class="pill-credit-badge">🔍 {st.session_state.credits} Free Search Credits</span>
        <span style="color:#94a3b8; font-size:0.86rem;">👤 {st.session_state.user_email}</span>
    </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown(f"### ⚡ **{APP_NAME}**")
    st.markdown(f"👤 **Account:** `{st.session_state.user_email}`")
    st.metric("Remaining Search Credits", st.session_state.credits)

    st.divider()

    # White-label report branding
    with st.expander("🏢 White-Label Report Branding", expanded=False):
        agency_name = st.text_input("Agency / Company Name", value=st.session_state.agency_name)
        st.session_state.agency_name = agency_name
        agency_web = st.text_input("Agency Website URL", value=st.session_state.agency_website)
        st.session_state.agency_website = agency_web
        st.caption("Custom branding stamped onto all generated PDF audits.")

    st.divider()

    # Quick Email Request link
    st.markdown("#### 💎 Need More Credits?")
    mailto_sidebar = generate_mailto_url(st.session_state.user_email)
    st.markdown(f"""
    <a href="{mailto_sidebar}" target="_blank" style="display:block; text-align:center; background:#1e293b; color:#38bdf8; border:1px solid #334155; padding:10px; border-radius:8px; text-decoration:none; font-weight:700; font-size:0.86rem;">
        📧 Email Haris for More Credits
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
# NATIVE CSS FEATURE SHOWCASE (100% RELIABLE, ZERO EXTERNAL IMAGES)
# =============================================================
c_f1, c_f2, c_f3 = st.columns(3)
with c_f1:
    st.markdown("""
    <div class="feature-box">
        <div class="feature-icon-wrapper" style="background:rgba(14, 165, 233, 0.2); color:#38bdf8; border:1px solid rgba(14, 165, 233, 0.4);">
            🌐
        </div>
        <h4 style="margin:0 0 6px 0; font-weight:700; color:#ffffff;">10x Lead Discovery</h4>
        <p style="margin:0; font-size:0.85rem; color:#94a3b8; line-height:1.4;">
            Extract verified company contacts & decision-maker emails across any metro.
        </p>
    </div>
    """, unsafe_allow_html=True)

with c_f2:
    st.markdown("""
    <div class="feature-box">
        <div class="feature-icon-wrapper" style="background:rgba(99, 102, 241, 0.2); color:#818cf8; border:1px solid rgba(99, 102, 241, 0.4);">
            🤖
        </div>
        <h4 style="margin:0 0 6px 0; font-weight:700; color:#ffffff;">Gemini 2026 AI Audits</h4>
        <p style="margin:0; font-size:0.85rem; color:#94a3b8; line-height:1.4;">
            Identifies conversion leaks, website blind spots, and 3 actionable growth levers.
        </p>
    </div>
    """, unsafe_allow_html=True)

with c_f3:
    st.markdown("""
    <div class="feature-box">
        <div class="feature-icon-wrapper" style="background:rgba(16, 185, 129, 0.2); color:#34d399; border:1px solid rgba(16, 185, 129, 0.4);">
            📄
        </div>
        <h4 style="margin:0 0 6px 0; font-weight:700; color:#ffffff;">Executive PDF Deliverable</h4>
        <p style="margin:0; font-size:0.85rem; color:#94a3b8; line-height:1.4;">
            1-Click downloadable PDF audit reports stamped with your agency branding.
        </p>
    </div>
    """, unsafe_allow_html=True)


# =============================================================
# 3. PERSISTENT PRIMARY TABS & DASHBOARD
# =============================================================
tab1, tab2, tab3 = st.tabs([
    "🚀 Lead Engine",
    "📊 Scraped Results & PDF",
    "💎 Account & Credits"
])


# =============================================================
# TAB 1: 🚀 LEAD ENGINE
# =============================================================
with tab1:
    with st.container(border=True):
        st.markdown("### 🎯 Discover Real Companies & Generate AI Mini-Audits")
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
            btn_generate = st.button("🚀 Start Discovery", type="primary", width="stretch", disabled=st.session_state.running)
        with c_stat:
            st.metric("Remaining Search Credits", st.session_state.credits)

    # Lead Generation Action
    if btn_generate:
        combined_query = f"{niche_query.strip()} in {location_query.strip()}".strip() if location_query.strip() else niche_query.strip()

        if not combined_query:
            st.error("Please enter a target niche or location.")
        elif st.session_state.credits <= 0:
            st.error("⚠️ You have exhausted your free search credits. Please visit the **💎 Account & Credits** tab to request more credits from Haris.")
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
                            st.toast("Leads generated! View them in '📊 Scraped Results & PDF' tab.", icon="✅")
                            st.rerun()

            except Exception as e:
                st.error(f"Error during lead generation: {e}")
            finally:
                st.session_state.running = False

    # Optional CSV Upload Section
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
                        st.error("⚠️ You have exhausted your free search credits. Please request more in the Credits tab.")
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
# TAB 2: 📊 SCRAPED RESULTS & PDF
# =============================================================
with tab2:
    if not st.session_state.leads_data:
        st.info("No leads generated yet. Enter your search query in **🚀 Lead Engine** and click 'Start Discovery'.")
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
# TAB 3: 💎 ACCOUNT & CREDITS
# =============================================================
with tab3:
    with st.container(border=True):
        st.markdown("### 💎 Search Credit Status & Account")
        
        c_em1, c_em2 = st.columns([2, 1])
        with c_em1:
            user_email_input = st.text_input("Your Account Email", value=st.session_state.user_email)
            if user_email_input != st.session_state.user_email:
                st.session_state.user_email = user_email_input.strip().lower()
        with c_em2:
            st.metric("Current Search Credits", st.session_state.credits)

        st.markdown("---")
        st.markdown("#### 📧 Request Credit Extension from Haris")
        st.markdown("Click below to open a pre-formatted email request to `hariskandapg@gmail.com`:")

        mailto_full = generate_mailto_url(st.session_state.user_email)
        st.markdown(f"""
        <div style="text-align:center; padding:12px 0;">
            <a href="{mailto_full}" target="_blank" class="mailto-upgrade-btn">
                📧 Request More Credits via Email (hariskandapg@gmail.com)
            </a>
        </div>
        """, unsafe_allow_html=True)

        st.caption(f"Direct Contact: `{ADMIN_CONTACT_EMAIL}`")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("### 🔑 Admin Passcode Manual Override")
        st.caption("Enter the testing passcode (`admin123` or `4990`) to instantly replenish 10 search credits.")
        passcode_input_tab = st.text_input("Enter Passcode", type="password", key="passcode_tab_in")
        if st.button("Reset to 10 Credits", type="primary"):
            if passcode_input_tab.strip() in [ADMIN_PASSCODE, UNLOCK_PASSCODE]:
                st.session_state.credits = 10
                st.toast("🎉 Credits replenished to 10!", icon="⚡")
                st.rerun()
            else:
                st.error("Invalid passcode.")
