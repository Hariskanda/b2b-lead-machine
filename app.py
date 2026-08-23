import asyncio
import io
import json
import os
import urllib.parse
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import streamlit as st

from b2b_leadgen.config import settings
from b2b_leadgen.email_dispatcher import build_outreach_email, dispatch_campaign
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column
from b2b_leadgen.sheets_exporter import export_leads_to_google_sheet
from b2b_leadgen.upi_checkout import generate_upi_qr_code, generate_upi_uri, validate_utr

# Page Configuration
st.set_page_config(
    page_title="B2B Lead Machine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS styling
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
    .upi-hero-box {
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        border: 2px solid #6366f1;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        margin: 15px auto;
        box-shadow: 0 6px 18px rgba(99, 102, 241, 0.12);
    }
    .whatsapp-box {
        background: #f0fdf4;
        border: 2px solid #22c55e;
        border-radius: 14px;
        padding: 18px;
        text-align: center;
        margin-top: 15px;
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
</style>
""", unsafe_allow_html=True)


# =============================================================
# 🔐 Secure Secret Resolution Helper with Robust Fallbacks
# =============================================================
def get_secret(key: str, default: Any = None) -> Any:
    """
    Reads a configuration secret with robust fallbacks:
    1. st.secrets[key] / st.secrets[key.lower()] / st.secrets[key.upper()]
    2. os.environ[key] / os.environ[key.lower()] / os.environ[key.upper()]
    3. settings attribute or default value
    """
    try:
        if hasattr(st, "secrets") and st.secrets is not None:
            if key in st.secrets:
                return st.secrets[key]
            if key.lower() in st.secrets:
                return st.secrets[key.lower()]
            if key.upper() in st.secrets:
                return st.secrets[key.upper()]
    except Exception:
        pass

    for env_key in [key, key.lower(), key.upper()]:
        env_val = os.environ.get(env_key)
        if env_val is not None and str(env_val).strip():
            return env_val

    settings_val = getattr(settings, key.lower(), None)
    if settings_val is not None and str(settings_val).strip():
        return settings_val

    return default


# Read Core Secrets Securely from st.secrets / backend
GEMINI_API_KEY: Optional[str] = get_secret("GEMINI_API_KEY", settings.effective_api_key)
ADMIN_PASSWORD: str = str(get_secret("ADMIN_PASSWORD", settings.admin_password or "admin123"))
UNLOCK_CODE: str = str(get_secret("UNLOCK_CODE", settings.unlock_code or "4990"))
WHATSAPP_NUMBER: str = str(get_secret("WHATSAPP_NUMBER", settings.whatsapp_number or "919019525230"))
SMTP_USER: str = str(get_secret("SMTP_USER", settings.effective_smtp_user or ""))
SMTP_PASSWORD: str = str(get_secret("SMTP_PASSWORD", settings.effective_smtp_password or ""))
SMTP_HOST: str = str(get_secret("SMTP_HOST", settings.smtp_host or "smtp.gmail.com"))
SMTP_PORT: int = int(get_secret("SMTP_PORT", settings.smtp_port or 587))
SENDER_NAME: str = str(get_secret("SENDER_NAME", settings.sender_name or "B2B Lead Machine"))
APP_URL: str = str(get_secret("APP_URL", settings.effective_app_url or "http://localhost:8501"))
UPI_ID: str = str(get_secret("UPI_ID", settings.upi_id or "9019525230@fam"))
UPI_PAYEE_NAME: str = str(get_secret("UPI_PAYEE_NAME", "B2BLeadMachine"))
UPI_AMOUNT_INR: int = int(get_secret("UPI_AMOUNT_INR", 499))
UPI_NOTE: str = "LeadExport499"

# Universal UPI Deep Link Intent URI (Pre-filled ₹499)
UNIVERSAL_UPI_URI = generate_upi_uri(
    upi_id=UPI_ID,
    payee_name=UPI_PAYEE_NAME,
    amount_inr=UPI_AMOUNT_INR,
    transaction_note=UPI_NOTE
)


# Initialize Session State
if "leads" not in st.session_state:
    st.session_state["leads"] = []
if "df" not in st.session_state:
    st.session_state["df"] = pd.DataFrame()
if "last_query" not in st.session_state:
    st.session_state["last_query"] = ""
if "upi_payment_verified" not in st.session_state:
    st.session_state["upi_payment_verified"] = False
if "submitted_utr" not in st.session_state:
    st.session_state["submitted_utr"] = ""
if "campaign_results" not in st.session_state:
    st.session_state["campaign_results"] = None
if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False


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
        <span class="pill">📲 Verified ₹499 UPI Export</span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📦 Order Status")
    if st.session_state["upi_payment_verified"]:
        st.success("✅ FULL CSV EXPORT UNLOCKED")
    else:
        st.info(f"🔒 Full CSV Export: ₹{UPI_AMOUNT_INR} Verification Required")

    st.divider()

    # 🔐 Secure Admin Configuration Portal (Password Protected)
    with st.expander("🔐 Admin Portal", expanded=False):
        if not st.session_state["admin_authenticated"]:
            st.markdown("##### Admin Authentication")
            admin_pwd_input = st.text_input("Enter Admin Password", type="password", key="admin_pwd_input")
            if st.button("Unlock Admin Panel", use_container_width=True):
                if admin_pwd_input and admin_pwd_input == ADMIN_PASSWORD:
                    st.session_state["admin_authenticated"] = True
                    st.success("Admin mode unlocked!")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid Admin Password.")
        else:
            st.markdown('<span style="color:#15803d; font-weight:700;">🔓 ADMIN MODE ACTIVE</span>', unsafe_allow_html=True)

            if not st.session_state["upi_payment_verified"]:
                if st.button("⚡ Admin Instant Unlock Dataset", type="primary", use_container_width=True):
                    st.session_state["upi_payment_verified"] = True
                    st.toast("🎉 Dataset unlocked by Admin!", icon="🔓")
                    st.rerun()

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
                value=int(settings.max_concurrent_requests),
                key="admin_concurrency_slider"
            )

            admin_follow_subpages = st.checkbox(
                "Follow Contact/About Pages",
                value=settings.follow_contact_pages,
                key="admin_follow_subpages_cb"
            )

            st.markdown("##### Google Sheets Sync")
            admin_gsheet_target = st.text_input("Sheet Name or URL", placeholder="e.g. B2B Leads 2026", key="admin_gsheet_target")
            admin_auto_sync = st.checkbox("Auto-sync to Google Sheet", value=False, key="admin_auto_sync_cb")

            if st.button("Log Out of Admin", use_container_width=True):
                st.session_state["admin_authenticated"] = False
                st.rerun()

    st.caption("⚡ **B2B Lead Machine** • Secure UPI Payment Gateway")


# Set runtime parameters (Admin overrides if logged in, otherwise default)
effective_model = st.session_state.get("admin_model_select", settings.gemini_model or "gemini-1.5-flash")
effective_concurrency = int(st.session_state.get("admin_concurrency_slider", settings.max_concurrent_requests or 3))
effective_follow_subpages = bool(st.session_state.get("admin_follow_subpages_cb", settings.follow_contact_pages))
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
    st.markdown("Enter a target search phrase (e.g. *'Plumbing contractors in Austin, TX'* or *'Digital marketing agencies in Bangalore'*) to autonomously discover official company websites and enrich them.")

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
                discovered_inputs = discover_leads_by_keyword(search_query.strip(), max_results=int(num_leads))

                if not discovered_inputs:
                    status_text.error("No companies could be discovered. Try refining your search query.")
                else:
                    status_text.success(f"✅ Discovered {len(discovered_inputs)} businesses! Starting AI scraping and cold pitch generation...")

                    pipeline = LeadGenPipeline(
                        api_key=GEMINI_API_KEY,
                        model=effective_model,
                        max_concurrency=effective_concurrency,
                        follow_contact_pages=effective_follow_subpages,
                        use_checkpoint=False
                    )

                    total = len(discovered_inputs)

                    def update_ui_progress(lead: EnrichedLead, idx: int, tot: int):
                        pct = int((idx / tot) * 100)
                        prog_bar.progress(pct)
                        email_tag = f" — Found email: {lead.primary_email}" if lead.primary_email else ""
                        status_text.text(f"Processing ({idx}/{tot}): {lead.company_name}{email_tag}")

                    results = asyncio.run(
                        pipeline.run_batch(
                            inputs=discovered_inputs,
                            output_csv_path=None,
                            progress_callback=update_ui_progress
                        )
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

                        pipeline = LeadGenPipeline(
                            api_key=GEMINI_API_KEY,
                            model=effective_model,
                            max_concurrency=effective_concurrency,
                            follow_contact_pages=effective_follow_subpages,
                            use_checkpoint=False
                        )

                        def update_csv_progress(lead: EnrichedLead, idx: int, tot: int):
                            pct = int((idx / tot) * 100)
                            prog_bar.progress(pct)
                            status_text.text(f"Enriching ({idx}/{tot}): {lead.company_name}")

                        results = asyncio.run(
                            pipeline.run_batch(
                                inputs=input_leads,
                                output_csv_path=None,
                                progress_callback=update_csv_progress
                            )
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

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")


# =============================================================
# 📊 Generated Leads Table & Secure UPI WhatsApp Verification
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
        st.metric("Total Leads", total_leads)
    with m2:
        st.metric("Verified Emails Found", emails_found)
    with m3:
        st.metric("Email Discovery Rate", email_rate)
    with m4:
        st.metric("Successful Scrapes", success_count)

    # Interactive Table
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

    # Cold Outreach Pitch Cards
    with st.expander("✉️ View Personalized Cold Email Pitches for All Leads", expanded=False):
        for lead in leads:
            st.markdown(f"**📌 {lead.company_name}** (`{lead.primary_email or 'No email found'}`)")
            st.markdown(f"**Summary:** {lead.company_summary or 'N/A'}")
            st.info(lead.personalized_pitch or "N/A")
            st.divider()

    st.markdown("---")

    # =========================================================
    # 🚀 Admin Autopilot Outbound Launcher (Gated to Admin)
    # =========================================================
    if st.session_state["admin_authenticated"]:
        st.markdown("### 📨 Admin Autopilot Email Campaign")
        st.markdown("Dispatches personalized cold email pitches from your configured Gmail account with your CTA link.")

        eligible_count = sum(1 for l in leads if l.primary_email and "@" in l.primary_email)

        if eligible_count > 0:
            sample_lead = next(l for l in leads if l.primary_email)
            subj, html_prev, txt_prev = build_outreach_email(sample_lead, app_url=APP_URL, sender_name=SENDER_NAME)

            col_adm_info, col_adm_prev = st.columns([1, 1])
            with col_adm_info:
                st.info(f"• **Eligible Contacts:** {eligible_count}\n• **Sender:** `{SMTP_USER}`\n• **CTA Link:** `{APP_URL}`")
            with col_adm_prev:
                with st.expander(f"👁️ Preview Email to {sample_lead.company_name}", expanded=False):
                    st.markdown(f"**Subject:** `{subj}`")
                    st.text(txt_prev)

            if st.button("🚀 Launch Autopilot Email Campaign (Admin)", type="primary", use_container_width=True):
                if not SMTP_USER or not SMTP_PASSWORD:
                    st.warning("⚠️ SMTP credentials not set in secrets.")
                else:
                    progress_container = st.container()
                    with progress_container:
                        dispatch_status = st.empty()
                        dispatch_bar = st.progress(0)

                        def on_email_progress(lead: EnrichedLead, success: bool, msg: str, idx: int, tot: int):
                            pct = int((idx / tot) * 100)
                            dispatch_bar.progress(pct)
                            icon = "✅" if success else "❌"
                            dispatch_status.text(f"Sending ({idx}/{tot}) {icon} -> {lead.company_name} ({lead.primary_email})")

                        with st.spinner("Dispatching cold email pitches via Gmail SMTP..."):
                            report = dispatch_campaign(
                                leads=leads,
                                sender_email=SMTP_USER,
                                app_password=SMTP_PASSWORD,
                                app_url=APP_URL,
                                sender_name=SENDER_NAME,
                                smtp_host=SMTP_HOST,
                                smtp_port=SMTP_PORT,
                                delay_seconds=1.0,
                                progress_callback=on_email_progress
                            )

                        dispatch_bar.progress(100)
                        st.session_state["campaign_results"] = report
                        if report.get("success"):
                            st.success(f"🎉 Campaign Finished! Successfully sent {report.get('sent_count')} out of {report.get('eligible_leads')} emails.")
                        else:
                            st.warning(f"⚠️ {report.get('message')}")

            if st.session_state["campaign_results"]:
                rep = st.session_state["campaign_results"]
                if rep.get("results"):
                    st.dataframe(pd.DataFrame(rep.get("results", [])), use_container_width=True, hide_index=True)

        st.markdown("---")

    # =========================================================
    # 📲 Secure UPI Payment & WhatsApp Verification Flow
    # =========================================================
    st.markdown("### 📥 Download Lead Dataset")

    is_upi_paid = st.session_state["upi_payment_verified"]

    if not is_upi_paid:
        qr_img, qr_buf, upi_uri = generate_upi_qr_code(
            upi_id=UPI_ID,
            payee_name=UPI_PAYEE_NAME,
            amount_inr=UPI_AMOUNT_INR,
            transaction_note=UPI_NOTE
        )

        col_checkout, col_qr = st.columns([3, 2])

        with col_checkout:
            st.markdown(f"""
            <div class="upi-hero-box">
                <h2 style="color: #1e293b; margin-top: 0; font-weight: 800;">⚡ Step 1: Pay ₹{UPI_AMOUNT_INR} via UPI</h2>
                <p style="color: #475569; font-size: 1.0rem; margin-bottom: 16px;">
                    Scan the QR code or tap the button below to launch Google Pay, PhonePe, Paytm, or BHIM.
                </p>
                <div style="background: #eef2ff; border-radius: 10px; padding: 12px; margin-bottom: 16px; text-align: left;">
                    <span style="font-size: 0.88rem; color: #3730a3;">
                        <strong>• Payee:</strong> <code>{UPI_PAYEE_NAME}</code><br>
                        <strong>• UPI ID:</strong> <code>{UPI_ID}</code><br>
                        <strong>• Amount:</strong> <code>₹{UPI_AMOUNT_INR}.00</code> (Pre-filled)<br>
                        <strong>• Reference Note:</strong> <code>{UPI_NOTE}</code>
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Prominent Clickable UPI Intent Deep Link
            st.link_button(
                label=f"🚀 Launch UPI App to Pay ₹{UPI_AMOUNT_INR} (GPay / PhonePe / Paytm)",
                url=UNIVERSAL_UPI_URI,
                type="primary",
                use_container_width=True
            )

            st.markdown("---")

            st.markdown(f"""
            <div class="whatsapp-box">
                <h3 style="color: #166534; margin-top: 0; font-weight: 700;">📲 Step 2: Send Payment Proof</h3>
                <p style="color: #15803d; font-size: 0.95rem; margin-bottom: 12px;">
                    After completing the transfer, enter your 12-digit UTR and send payment proof on WhatsApp to receive your instant Unlock Code.
                </p>
            </div>
            """, unsafe_allow_html=True)

            utr_input = st.text_input(
                "Enter 12-digit UTR / UPI Transaction Reference",
                value=st.session_state["submitted_utr"],
                placeholder="e.g. 423589123456",
                max_chars=12,
                help="You can find your 12-digit UTR number in your UPI payment receipt."
            )

            # Build pre-filled WhatsApp link with submitted UTR
            utr_text_part = f"My UTR reference is: {utr_input.strip()}" if utr_input.strip() else "My UTR reference is: [Enter UTR]"
            wa_message = f"Hi, I just paid ₹{UPI_AMOUNT_INR} for my B2B Leads. {utr_text_part}"
            wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={urllib.parse.quote(wa_message)}"

            st.link_button(
                label="📲 Send Payment Proof on WhatsApp to Unlock",
                url=wa_url,
                type="primary",
                use_container_width=True
            )

            st.markdown("---")

            st.markdown("#### 🔑 Step 3: Enter Unlock Code")
            st.caption("Enter the 4-digit Unlock Code received on WhatsApp (or Admin Authorization) to download the CSV.")

            c_code1, c_code2 = st.columns([3, 1])
            with c_code1:
                entered_code = st.text_input("Enter Unlock Code", type="password", placeholder="Enter code here...", label_visibility="collapsed")
            with c_code2:
                if st.button("Unlock CSV", type="primary", use_container_width=True):
                    clean_code = entered_code.strip()
                    if clean_code and (clean_code == UNLOCK_CODE or clean_code == ADMIN_PASSWORD):
                        st.session_state["upi_payment_verified"] = True
                        st.session_state["submitted_utr"] = utr_input.strip()
                        st.toast("🎉 Code verified! Full CSV download unlocked.", icon="✅")
                        st.rerun()
                    else:
                        st.error("⚠️ Invalid Unlock Code. Please send proof on WhatsApp to receive your code.")

        with col_qr:
            st.markdown("""
            <div style="text-align:center; padding: 10px;">
                <p style="font-weight: 700; color: #1e293b; margin-bottom: 8px;">Scan with any UPI App</p>
            </div>
            """, unsafe_allow_html=True)
            st.image(qr_buf, caption=f"Scan to Pay ₹{UPI_AMOUNT_INR} ({UPI_ID})", use_container_width=True)

    else:
        # Payment Verified -> Reveal Download CSV and JSON buttons!
        st.markdown(f"""
        <div class="unlocked-box">
            <h3 style="color: #15803d; margin-bottom: 4px;">🎉 Full Lead Dataset Unlocked!</h3>
            <p style="color: #166534; margin: 0;">Payment of ₹{UPI_AMOUNT_INR} confirmed. Download your verified lead dataset below!</p>
        </div>
        """, unsafe_allow_html=True)

        c_dl1, c_dl2 = st.columns([1, 1])
        with c_dl1:
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv_buffer.getvalue(),
                file_name=f"enriched_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )
        with c_dl2:
            json_str = json.dumps([l.model_dump() for l in leads], indent=2)
            st.download_button(
                label="📥 Download JSON",
                data=json_str,
                file_name=f"enriched_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True
            )
