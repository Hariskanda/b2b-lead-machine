import asyncio
import io
import json
import pandas as pd
import streamlit as st
from datetime import datetime

from b2b_leadgen.config import settings
from b2b_leadgen.email_dispatcher import build_outreach_email, dispatch_campaign
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column
from b2b_leadgen.sheets_exporter import export_leads_to_google_sheet
from b2b_leadgen.upi_checkout import generate_upi_qr_code, validate_utr

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
        font-size: 2.3rem;
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
    .upi-card {
        background: #ffffff;
        border: 2px solid #6366f1;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        margin: 20px auto;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.12);
    }
    .email-card {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-radius: 12px;
        padding: 20px;
        margin: 15px 0;
    }
    .unlocked-box {
        background-color: #f0fdf4;
        border: 2px solid #22c55e;
        border-radius: 12px;
        padding: 18px;
        text-align: center;
        margin: 20px 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session State
if "leads" not in st.session_state:
    st.session_state["leads"] = []
if "df" not in st.session_state:
    st.session_state["df"] = pd.DataFrame()
if "last_query" not in st.session_state:
    st.session_state["last_query"] = ""
if "upi_payment_verified" not in st.session_state:
    st.session_state["upi_payment_verified"] = False
if "verified_utr" not in st.session_state:
    st.session_state["verified_utr"] = None
if "campaign_results" not in st.session_state:
    st.session_state["campaign_results"] = None


# =============================================================
# ⚙️ Sidebar Controls
# =============================================================
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/lightning-bolt.png", width=60)
    st.title("Settings & Config")

    api_key_input = st.text_input(
        "Gemini API Key",
        value=settings.effective_api_key or "",
        type="password",
        help="Optional: Provide your Google Gemini API Key."
    )

    model_option = st.selectbox(
        "Gemini Model",
        options=["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
        index=0,
        help="Google Gemini model for summary & pitch generation."
    )

    concurrency = st.slider(
        "Max Concurrency",
        min_value=1,
        max_value=8,
        value=settings.max_concurrent_requests,
        help="Concurrent web scraping and extraction requests."
    )

    follow_subpages = st.checkbox(
        "Follow Contact/About Pages",
        value=settings.follow_contact_pages,
        help="If enabled, crawls internal /contact or /about pages to locate hidden email addresses."
    )

    st.divider()
    st.subheader("📧 Gmail SMTP Outbound")
    smtp_sender = st.text_input(
        "Sender Gmail Address",
        value=getattr(settings, "effective_smtp_user", "") or "",
        placeholder="you@gmail.com",
        help="Your Gmail address for sending cold email outreach."
    )
    smtp_pass = st.text_input(
        "Gmail App Password (16-char)",
        value=getattr(settings, "effective_smtp_password", "") or "",
        type="password",
        help="Generate a 16-character App Password in Google Account > Security > 2-Step Verification > App Passwords."
    )
    app_public_url = st.text_input(
        "App Public URL (CTA link)",
        value=getattr(settings, "effective_app_url", "http://localhost:8501") or "http://localhost:8501",
        help="The link included in cold emails pointing leads to your payment portal."
    )

    st.divider()
    st.subheader("📲 UPI Payment Gateway")
    custom_upi_id = st.text_input("Merchant UPI ID", value=getattr(settings, "upi_id", "9019525230@fam"))
    custom_payee = st.text_input("Payee Name", value=getattr(settings, "upi_payee_name", "B2B Lead Machine"))
    custom_upi_amount = st.number_input("Lead Download Price (₹)", value=int(getattr(settings, "upi_amount_inr", 499.0)), min_value=1, step=50)

    if st.session_state["upi_payment_verified"]:
        st.success(f"✅ Verified UTR: `{st.session_state['verified_utr']}`")
    else:
        st.info(f"🔒 Download Status: ₹{custom_upi_amount} Required")

    st.divider()
    st.subheader("📊 Google Sheets Live Sync")
    gsheet_target = st.text_input(
        "Sheet Name or URL",
        placeholder="e.g. B2B Leads 2026 or full URL",
        help="Enter the title or URL of your Google Sheet."
    )
    worksheet_name = st.text_input("Worksheet Name", value="Leads")
    auto_sync_sheets = st.checkbox("Auto-sync new leads to Sheet", value=False)

    with st.expander("Service Account JSON (Optional)"):
        custom_sa_json = st.text_area(
            "Paste Service Account JSON",
            help="Optional if configured via st.secrets in Streamlit Cloud.",
            height=100
        )

    st.divider()
    st.caption("⚡ **Automated B2B Lead Machine**\nAutopilot Outbound Engine with UPI Paywall.")


# =============================================================
# 🚀 Main Application Header & Tabs
# =============================================================
st.markdown('<div class="main-header">⚡ Automated B2B Lead Machine</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Autonomous Lead Discovery, AI Cold Pitch Generation & Autopilot Email Dispatcher</div>', unsafe_allow_html=True)

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
                        api_key=api_key_input or None,
                        model=model_option,
                        max_concurrency=int(concurrency),
                        use_checkpoint=False
                    )

                    total = len(discovered_inputs)
                    results = []

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

                    if auto_sync_sheets and gsheet_target:
                        try:
                            sync_res = export_leads_to_google_sheet(
                                leads=results,
                                sheet_name_or_url=gsheet_target,
                                worksheet_title=worksheet_name or "Leads",
                                credentials_info=custom_sa_json or None
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
                            api_key=api_key_input or None,
                            model=model_option,
                            max_concurrency=int(concurrency),
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

                        if auto_sync_sheets and gsheet_target:
                            try:
                                sync_res = export_leads_to_google_sheet(
                                    leads=results,
                                    sheet_name_or_url=gsheet_target,
                                    worksheet_title=worksheet_name or "Leads",
                                    credentials_info=custom_sa_json or None
                                )
                                if sync_res.get("success"):
                                    st.toast(f"✅ Synced {sync_res.get('rows_appended')} leads to Google Sheet!", icon="📊")
                            except Exception as e:
                                st.warning(f"Google Sheets auto-sync failed: {e}")

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")


# =============================================================
# 📊 Generated Leads Table & Autopilot Dispatcher
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
    # 🚀 Autopilot Gmail Cold Email Dispatcher
    # =========================================================
    st.markdown("### 📨 Autopilot Cold Outreach Campaign")
    st.markdown("Automatically email these verified prospects their customized pitch with a link to your UPI payment portal.")

    eligible_count = sum(1 for l in leads if l.primary_email and "@" in l.primary_email)

    c_em1, c_em2 = st.columns([1, 1])
    with c_em1:
        st.markdown(f"""
        <div class="email-card">
            <h4 style="margin-top:0;">⚡ Campaign Overview</h4>
            <p>• <strong>Eligible Contacts:</strong> {eligible_count} verified email addresses</p>
            <p>• <strong>Sender:</strong> <code>{smtp_sender or 'Not configured (set in sidebar)'}</code></p>
            <p>• <strong>CTA Target Link:</strong> <a href="{app_public_url}" target="_blank">{app_public_url}</a></p>
            <p>• <strong>Payment Option:</strong> Informs lead of instant ₹499 UPI dataset download</p>
        </div>
        """, unsafe_allow_html=True)

    with c_em2:
        if eligible_count > 0:
            sample_lead = next(l for l in leads if l.primary_email)
            subj, html_prev, txt_prev = build_outreach_email(sample_lead, app_url=app_public_url, sender_name=settings.sender_name)
            with st.expander(f"👁️ Preview Outbound Email to {sample_lead.company_name}", expanded=False):
                st.markdown(f"**Subject:** `{subj}`")
                st.markdown(f"**To:** `{sample_lead.primary_email}`")
                st.markdown("**Email Body:**")
                st.text(txt_prev)
        else:
            st.info("No leads with verified email addresses available for outbound campaign.")

    if eligible_count > 0:
        if st.button("🚀 Launch Autopilot Email Campaign", type="primary", use_container_width=True):
            if not smtp_sender or not smtp_pass:
                st.warning("⚠️ Please enter your Sender Gmail Address and 16-character App Password in the sidebar.")
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
                            sender_email=smtp_sender,
                            app_password=smtp_pass,
                            app_url=app_public_url,
                            sender_name=settings.sender_name,
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
        st.markdown("#### 📊 Campaign Dispatch Results")
        if rep.get("results"):
            rep_df = pd.DataFrame(rep.get("results", []))
            st.dataframe(rep_df, use_container_width=True, hide_index=True)
        elif rep.get("message"):
            st.info(rep.get("message"))

    st.markdown("---")

    # =========================================================
    # 📲 Custom UPI QR Code Payment Wall (₹499)
    # =========================================================
    st.markdown("### 📥 Download Lead Dataset")

    is_upi_paid = st.session_state["upi_payment_verified"]

    if not is_upi_paid:
        qr_img, qr_buf, upi_uri = generate_upi_qr_code(
            upi_id=custom_upi_id,
            payee_name=custom_payee,
            amount_inr=float(custom_upi_amount),
            transaction_note="B2B Leads Dataset Export"
        )

        col_qr, col_verify = st.columns([1, 1])

        with col_qr:
            st.markdown(f"""
            <div class="upi-card">
                <h3 style="margin-top: 0; color: #1e293b;">📲 Scan to Pay ₹{int(custom_upi_amount)}</h3>
                <p style="color: #64748b; font-size: 0.95rem; margin-bottom: 12px;">
                    Scan using Google Pay, PhonePe, Paytm, BHIM, or any UPI App to unlock your verified CSV download.
                </p>
            </div>
            """, unsafe_allow_html=True)
            st.image(qr_buf, caption=f"Pay ₹{int(custom_upi_amount)} to {custom_upi_id}", use_container_width=True)
            st.link_button("📱 Pay via UPI App (Mobile Direct)", upi_uri, use_container_width=True)

        with col_verify:
            st.markdown("### 🔐 Enter 12-Digit UTR to Unlock")
            st.markdown(f"""
            **Payment Details:**
            - **Amount:** ₹{int(custom_upi_amount)}.00
            - **Payee Name:** `{custom_payee}`
            - **UPI ID:** `{custom_upi_id}`
            - **Note:** `B2B Leads Dataset Export`
            
            After completing payment in your UPI app, enter your **12-digit UTR Transaction ID** below:
            """)

            utr_input = st.text_input(
                "12-digit UTR Transaction ID",
                placeholder="e.g. 423589123456",
                max_chars=12,
                help="You can find the 12-digit UTR / Reference number in your UPI transaction receipt."
            )

            if st.button("✅ Verify Transaction & Unlock CSV", type="primary", use_container_width=True):
                if validate_utr(utr_input):
                    st.session_state["upi_payment_verified"] = True
                    st.session_state["verified_utr"] = utr_input.strip()
                    st.toast("🎉 Transaction verified! CSV Download Unlocked.", icon="✅")
                    st.rerun()
                else:
                    st.error("⚠️ Invalid UTR Number! Please enter a valid 12-digit numeric Transaction ID (UTR).")

            st.warning("⚠️ **Download CSV is hidden until ₹499 UPI payment is verified via 12-digit UTR.**")

    else:
        # Payment Verified -> Reveal Download CSV and JSON buttons!
        verified_utr_num = st.session_state.get("verified_utr", "Verified")
        st.markdown(f"""
        <div class="unlocked-box">
            <h3 style="color: #15803d; margin-bottom: 4px;">🎉 Payment Verified! (UTR: {verified_utr_num})</h3>
            <p style="color: #166534; margin: 0;">Your ₹{int(custom_upi_amount)} transfer is confirmed. Download your verified lead dataset below!</p>
        </div>
        """, unsafe_allow_html=True)

        c_dl1, c_dl2, c_sync = st.columns([1, 1, 2])
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
        with c_sync:
            if gsheet_target:
                if st.button("📊 Sync to Google Sheet Now", use_container_width=True):
                    with st.spinner("Connecting to Google Sheets and appending rows..."):
                        try:
                            sync_res = export_leads_to_google_sheet(
                                leads=leads,
                                sheet_name_or_url=gsheet_target,
                                worksheet_title=worksheet_name or "Leads",
                                credentials_info=custom_sa_json or None
                            )
                            st.success(f"✅ Appended {sync_res.get('rows_appended')} rows to [{sync_res.get('spreadsheet_title')}]({sync_res.get('spreadsheet_url')})!")
                        except Exception as e:
                            st.error(f"Failed to sync to Google Sheet: {e}")
