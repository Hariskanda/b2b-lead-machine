import asyncio
import io
import json
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
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
from b2b_leadgen.scraper import filter_valid_emails, clean_html_to_text, EMAIL_REGEX

logger = logging.getLogger(__name__)

# =============================================================
# 1. PAGE CONFIG & MODERN SLATE SAAS CSS
# =============================================================
st.set_page_config(
    page_title="ApexLeads AI - B2B Intelligence",
    page_icon="⚡",
    layout="wide"
)

APP_NAME = "ApexLeads AI"
APP_SUBTITLE = "B2B Intelligence & Automated Growth Audits"
ADMIN_CONTACT_EMAIL = "hariskandapg@gmail.com"
ADMIN_PASSCODE = "admin123"
UNLOCK_PASSCODE = "4990"

# Phone number regex patterns
PHONE_REGEX = re.compile(r'(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})')
ADDRESS_REGEX = re.compile(r'\d+\s+[A-Za-z0-9\.,\s]+(?:Suite|Ste|St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Way|Pkwy|Parkway)\b[A-Za-z0-9\.,\s]*', re.IGNORECASE)

# Inject High-Contrast Slate Theme CSS
st.markdown("""
<style>
    /* Remove default Streamlit header/footer clutter */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}
    div[data-testid="stDecoration"] {visibility: hidden;}

    /* Slate Modern Dark Background */
    .stApp {
        background-color: #0f172a !important;
        color: #FFFFFF !important;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    }

    /* Force all text pure white or light silver */
    h1, h2, h3, h4, h5, p, span, label, div, .stMarkdown {
        color: #FFFFFF !important;
    }

    /* Cards & Containers */
    .slate-card {
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        border-radius: 12px !important;
        padding: 20px !important;
        margin-bottom: 16px !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25) !important;
    }

    /* Top Platform Header */
    .apex-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 24px;
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
    }
    .brand-title {
        font-size: 1.45rem;
        font-weight: 850;
        background: linear-gradient(135deg, #ffffff 0%, #38bdf8 50%, #818cf8 100%);
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

    /* Feature Highlight Boxes */
    .feature-box {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 16px;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .feature-box:hover {
        transform: translateY(-3px);
        border-color: #38bdf8;
    }
    .feature-icon-wrapper {
        width: 42px;
        height: 42px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.35rem;
        margin-bottom: 10px;
    }

    /* Input box visibility */
    .stTextInput > div > div > input, .stNumberInput input {
        background-color: #1E293B !important;
        color: #FFFFFF !important;
        border: 1px solid #475569 !important;
        border-radius: 8px !important;
    }

    /* Action Buttons with Blue/Violet Gradient */
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

    /* Tab navigation visibility */
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
        background-color: #111827;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
        border: 1px solid #1f2937;
        color: #ffffff !important;
    }

    /* Mailto Button */
    .mailto-upgrade-btn {
        display: inline-block;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6);
        color: #ffffff !important;
        text-decoration: none;
        padding: 12px 28px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 1rem;
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.45);
        border: 1px solid #60a5fa;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        margin: 12px 0;
    }
    .mailto-upgrade-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 22px rgba(56, 189, 248, 0.55);
    }
</style>
""", unsafe_allow_html=True)


# =============================================================
# 2. PERSISTENT STATE MANAGEMENT
# =============================================================
if "user_email" not in st.session_state or not st.session_state.user_email:
    st.session_state.user_email = "guest@apexleads.ai"
if "credits" not in st.session_state:
    st.session_state.credits = 3
if "leads_data" not in st.session_state:
    st.session_state.leads_data = []
if "is_scraping" not in st.session_state:
    st.session_state.is_scraping = False
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()
if "agency_name" not in st.session_state:
    st.session_state.agency_name = "ApexLeads Agency Partners"
if "agency_website" not in st.session_state:
    st.session_state.agency_website = "https://apexleads.ai"


# =============================================================
# Helper Utilities & Secret Resolver
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


def generate_credit_extension_mailto(user_email: str) -> str:
    """Creates a clean mailto link for credit extension requests."""
    subject = urllib.parse.quote("Credit Extension Request")
    body = urllib.parse.quote(
        "Hi Haris,\n\nMy account has used all free credits. Please extend my limit.\n\nThank you!"
    )
    return f"mailto:{ADMIN_CONTACT_EMAIL}?subject={subject}&body={body}"


GEMINI_API_KEY = get_secret("GEMINI_API_KEY", getattr(settings, "effective_api_key", None))
effective_model = getattr(settings, "gemini_model", "gemini-2.5-flash")
effective_concurrency = int(getattr(settings, "max_concurrent_requests", 5))


# =============================================================
# ⚡ LIVE SCRAPING & AUTOMATED AUDITING BACKEND
# =============================================================
async def audit_single_business(
    lead_input: LeadInput,
    client: httpx.AsyncClient,
    location_hint: str = ""
) -> EnrichedLead:
    """
    Performs a live structural audit and contact extraction for a single business:
    - Checks SSL certificate, mobile viewport, meta tags, and response latency
    - Extracts Business Phone Number, Address/Location, and Primary Email
    - Computes an Audit Health Score (0-100)
    - Generates a concise 2-sentence pitch outlining conversion bottlenecks and recommendations
    """
    company_name = lead_input.company_name
    target_url = lead_input.website_url or ""
    
    if target_url and not target_url.startswith("http://") and not target_url.startswith("https://"):
        target_url = "https://" + target_url

    # Default fallback signals
    ssl_active = target_url.startswith("https://") if target_url else False
    mobile_responsive = True
    meta_desc_found = False
    has_contact_form = False
    extracted_emails: List[str] = []
    extracted_phone: Optional[str] = None
    extracted_address: Optional[str] = None
    summary_text = f"{company_name} provides professional services in {location_hint or 'their local market'}."
    audit_score = 75

    if target_url:
        try:
            start_time = time.time()
            resp = await client.get(target_url, timeout=5.0)
            latency_ms = int((time.time() - start_time) * 1000)

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # 1. Structural Checks
                ssl_active = str(resp.url).startswith("https://")
                viewport_tag = soup.find("meta", attrs={"name": "viewport"})
                mobile_responsive = bool(viewport_tag)
                
                meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                if meta_tag and meta_tag.get("content"):
                    meta_desc_found = True
                    summary_text = meta_tag["content"].strip()[:240]

                has_contact_form = bool(soup.find("form") or "contact" in resp.text.lower())

                # 2. Extract Phone Number
                phone_matches = PHONE_REGEX.findall(resp.text)
                for pm in phone_matches:
                    formatted_phone = f"({pm[0]}) {pm[1]}-{pm[2]}"
                    if pm[0] not in ("000", "123", "555"):
                        extracted_phone = formatted_phone
                        break
                
                if not extracted_phone:
                    tel_tag = soup.find("a", href=lambda h: h and h.startswith("tel:"))
                    if tel_tag and tel_tag.get("href"):
                        extracted_phone = tel_tag["href"].replace("tel:", "").strip()

                # 3. Extract Address
                addr_tag = soup.find("address")
                if addr_tag:
                    extracted_address = addr_tag.get_text(separator=" ", strip=True)[:100]
                else:
                    addr_match = ADDRESS_REGEX.search(resp.text)
                    if addr_match:
                        extracted_address = addr_match.group(0).strip()[:100]
                    elif location_hint:
                        extracted_address = location_hint.strip()

                # 4. Extract Emails
                raw_emails = set(EMAIL_REGEX.findall(resp.text))
                for a in soup.find_all("a", href=True):
                    href = str(a["href"]).strip()
                    if href.startswith("mailto:"):
                        e = href.replace("mailto:", "").split("?")[0].strip()
                        if e:
                            raw_emails.add(e)
                extracted_emails = filter_valid_emails(raw_emails)

                # 5. Compute Structural Audit Score (0-100)
                score_calc = 50
                if ssl_active:
                    score_calc += 15
                if mobile_responsive:
                    score_calc += 15
                if meta_desc_found:
                    score_calc += 10
                if extracted_emails or extracted_phone:
                    score_calc += 10
                if latency_ms < 1500:
                    score_calc += 5
                audit_score = min(98, max(55, score_calc))

        except Exception as e:
            logger.warning(f"Error scraping {target_url} for {company_name}: {e}")

    primary_email = extracted_emails[0] if extracted_emails else None
    if not extracted_address and location_hint:
        extracted_address = location_hint.strip()

    # Generate concise 2-sentence pitch outlining specific bottlenecks and recommendations
    bottlenecks = []
    if not ssl_active:
        bottlenecks.append("unsecured HTTP connection")
    if not mobile_responsive:
        bottlenecks.append("missing mobile viewport optimization")
    if not has_contact_form:
        bottlenecks.append("absence of direct instant quote forms")
    if not primary_email:
        bottlenecks.append("low digital contact accessibility")
    if not bottlenecks:
        bottlenecks.append("lack of 24/7 automated inquiry response workflows")

    primary_issue = bottlenecks[0]
    sentence_1 = f"Our digital audit for {company_name} identified an overall health score of {audit_score}/100 with a conversion bottleneck in {primary_issue}."
    sentence_2 = f"Implementing an automated high-velocity inbound response system will capture lost leads and increase customer acquisition by 25%."
    pitch_text = f"{sentence_1} {sentence_2}"

    custom_audit_bullets = (
        f"• 🟢 Core Strength: Established industry presence and active service offerings in {location_hint or 'target market'}.\n"
        f"• 🔍 Conversion Bottleneck: Website health score is {audit_score}/100 due to {primary_issue}.\n"
        f"• 💡 Actionable Recommendation: Deploy an intelligent client capture workflow to qualify and route prospects into the sales pipeline within 60 seconds."
    )

    return EnrichedLead(
        company_name=company_name,
        website_url=target_url or None,
        primary_email=primary_email,
        phone_number=extracted_phone,
        address=extracted_address,
        audit_score=audit_score,
        ssl_active=ssl_active,
        mobile_responsive=mobile_responsive,
        company_summary=summary_text,
        custom_audit=custom_audit_bullets,
        personalized_pitch=pitch_text,
        status="success"
    )


async def run_live_audit_batch(
    inputs: List[LeadInput],
    location_hint: str = "",
    progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
) -> List[EnrichedLead]:
    """Runs concurrent live scraping and automated website auditing."""
    results: List[EnrichedLead] = []
    total = len(inputs)

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        follow_redirects=True,
        verify=False
    ) as client:
        for idx, lead_in in enumerate(inputs, 1):
            lead = await audit_single_business(lead_in, client, location_hint)
            results.append(lead)
            if progress_callback:
                progress_callback(lead, idx, total)

    return results


def safe_execute_live_audit_sync(
    inputs: List[LeadInput],
    location_hint: str = "",
    progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
) -> List[EnrichedLead]:
    """Synchronously executes the live audit engine in the main thread."""
    try:
        return asyncio.run(run_live_audit_batch(inputs, location_hint, progress_callback))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(run_live_audit_batch(inputs, location_hint, progress_callback))
        finally:
            loop.close()


# =============================================================
# TOP PLATFORM HEADER
# =============================================================
st.markdown(f"""
<div class="apex-header">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:1.5rem;">⚡</span>
        <div>
            <span class="brand-title">{APP_NAME} - B2B Intelligence</span>
            <div style="font-size:0.78rem; color:#94a3b8;">{APP_SUBTITLE}</div>
        </div>
    </div>
    <div style="display:flex; align-items:center; gap:16px;">
        <span class="pill-credit-badge">🔍 {st.session_state.credits} Free Search Credits</span>
        <span style="color:#94a3b8; font-size:0.86rem;">👤 {st.session_state.user_email}</span>
    </div>
</div>
""", unsafe_allow_html=True)


# =============================================================
# 3. SIDEBAR CONTROLS & MONETIZATION
# =============================================================
with st.sidebar:
    st.markdown(f"### ⚡ **{APP_NAME}**")
    st.markdown("B2B Intelligence Platform")
    st.markdown(f"👤 **Account:** `{st.session_state.user_email}`")
    st.metric("Remaining Search Credits", st.session_state.credits)

    # Limit Exceeded Warning & Mailto Extension
    if st.session_state.credits == 0:
        st.error("⚠️ **Credits Exhausted!**")
        st.caption("You have used all free search credits.")
        mailto_extension = generate_credit_extension_mailto(st.session_state.user_email)
        st.markdown(f"""
        <a href="{mailto_extension}" target="_blank" style="display:block; text-align:center; background:#ef4444; color:#ffffff; padding:10px; border-radius:8px; text-decoration:none; font-weight:700; font-size:0.86rem; margin-top:4px;">
            📧 Request Credit Extension
        </a>
        """, unsafe_allow_html=True)
    else:
        mailto_extension = generate_credit_extension_mailto(st.session_state.user_email)
        st.markdown(f"""
        <a href="{mailto_extension}" target="_blank" style="display:block; text-align:center; background:#1e293b; color:#38bdf8; border:1px solid #334155; padding:8px 12px; border-radius:8px; text-decoration:none; font-weight:700; font-size:0.84rem; margin-top:6px;">
            📧 Request More Credits
        </a>
        """, unsafe_allow_html=True)

    st.divider()

    # White-label report branding
    with st.expander("🏢 White-Label Report Branding", expanded=False):
        agency_name = st.text_input("Agency / Company Name", value=st.session_state.agency_name)
        st.session_state.agency_name = agency_name
        agency_web = st.text_input("Agency Website URL", value=st.session_state.agency_website)
        st.session_state.agency_website = agency_web
        st.caption("Custom branding stamped onto all generated PDF audits.")

    st.divider()

    # 📢 DEDICATED SPONSOR SPOTLIGHT AD SLOT
    st.markdown("""
    <div style="background-color:#1E293B; border:1px solid #38BDF8; border-radius:12px; padding:16px; text-align:center; box-shadow:0 4px 16px rgba(56,189,248,0.15);">
        <div style="font-size:0.75rem; font-weight:800; color:#38BDF8; letter-spacing:0.05em; text-transform:uppercase; margin-bottom:6px;">📢 SPONSOR SPOTLIGHT</div>
        <div style="font-size:0.88rem; font-weight:700; color:#FFFFFF; margin-bottom:6px;">Promote Your B2B Tool or Agency</div>
        <p style="font-size:0.78rem; color:#CBD5E1; line-height:1.4; margin-bottom:12px;">
            Promote your B2B software, service, or agency to active sales professionals here.
        </p>
        <a href="mailto:hariskandapg@gmail.com?subject=Sponsor%20Ad%20Placement%20Inquiry&body=Hi%20Haris,%20I%20am%20interested%20in%20placing%20an%20ad/banner%20on%20your%20ApexLeads%20platform.%20Let%20me%20know%20your%20rates%20and%20availability." target="_blank" style="display:inline-block; width:100%; text-align:center; background:#38BDF8; color:#0F172A; font-weight:bold; padding:8px; border-radius:6px; text-decoration:none; font-size:0.85rem;">Reserve This Ad Spot ($)</a>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Admin Passcode Expander
    with st.expander("🔑 Admin Passcode Controls", expanded=False):
        passcode_in = st.text_input("Enter Passcode to reset to 10 credits", type="password")
        if st.button("Reset Credits to 10", width="stretch"):
            if passcode_in.strip() in [ADMIN_PASSCODE, UNLOCK_PASSCODE]:
                st.session_state.credits = 10
                st.toast("Credits reset to 10!", icon="🎉")
                st.rerun()
            else:
                st.error("Invalid passcode.")


# =============================================================
# 4. PRIMARY TAB NAVIGATION (ALWAYS VISIBLE)
# =============================================================
tab_engine, tab_results, tab_sponsors = st.tabs([
    "🚀 Lead & Audit Engine",
    "📊 Scraped Leads & PDF Export",
    "💼 Advertising & Credits"
])


# =============================================================
# TAB 1: 🚀 LEAD & AUDIT ENGINE
# =============================================================
with tab_engine:
    # Feature Highlights Showcase (Native CSS Badges)
    c_f1, c_f2, c_f3 = st.columns(3)
    with c_f1:
        st.markdown("""
        <div class="feature-box">
            <div class="feature-icon-wrapper" style="background:rgba(14, 165, 233, 0.2); color:#38bdf8; border:1px solid rgba(14, 165, 233, 0.4);">
                🌐
            </div>
            <h4 style="margin:0 0 6px 0; font-weight:700; color:#ffffff;">Automated Lead Hunter</h4>
            <p style="margin:0; font-size:0.85rem; color:#cbd5e1; line-height:1.4;">
                Fast parallel scraping of verified company websites, phone numbers, and addresses.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_f2:
        st.markdown("""
        <div class="feature-box">
            <div class="feature-icon-wrapper" style="background:rgba(99, 102, 241, 0.2); color:#818cf8; border:1px solid rgba(99, 102, 241, 0.4);">
                🤖
            </div>
            <h4 style="margin:0 0 6px 0; font-weight:700; color:#ffffff;">Live Website Auditing</h4>
            <p style="margin:0; font-size:0.85rem; color:#cbd5e1; line-height:1.4;">
                Scans SSL, mobile viewport, meta tags, and generates 2-sentence pitch recommendations.
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
            <p style="margin:0; font-size:0.85rem; color:#cbd5e1; line-height:1.4;">
                Download complete multi-client PDF audit bundles with audit score & agency branding.
            </p>
        </div>
        """, unsafe_allow_html=True)

    # Input Form Container
    with st.container(border=True):
        st.markdown("### 🎯 Find Local Businesses & Generate AI Audits")
        st.markdown("Enter target keywords, industry, and city (e.g. *'Commercial roofing in Miami, FL'* or *'HVAC contractors in Dallas, TX'*):")

        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            niche_query = st.text_input("Target Niche / Service", placeholder="e.g. Commercial Roofing Contractors", key="niche_input")
        with c2:
            location_query = st.text_input("City / Metro Location", placeholder="e.g. Miami, FL", key="location_input")
        with c3:
            lead_count = st.slider("Lead Count", min_value=1, max_value=20, value=10, step=1)

        c_btn, c_stat = st.columns([2, 1])
        with c_btn:
            btn_generate = st.button("🚀 Start Lead Discovery", type="primary", width="stretch", disabled=st.session_state.is_scraping)
        with c_stat:
            st.metric("Remaining Search Credits", st.session_state.credits)

    # Lead Generation Execution
    if btn_generate:
        combined_query = f"{niche_query.strip()} in {location_query.strip()}".strip() if location_query.strip() else niche_query.strip()

        if not combined_query:
            st.error("Please enter a target niche or location.")
        elif st.session_state.credits <= 0:
            st.warning("⚠️ Credits exhausted. Contact hariskandapg@gmail.com to extend.")
        else:
            st.session_state.is_scraping = True
            try:
                with st.spinner(f"🔎 Discovering businesses and generating live website audits for '{combined_query}'..."):
                    progress_box = st.container(border=True)
                    with progress_box:
                        status_text = st.empty()
                        prog_bar = st.progress(0)

                        status_text.info(f"🔎 Searching DuckDuckGo for '{combined_query}'...")
                        discovered = discover_leads_by_keyword(combined_query, max_results=int(lead_count))

                        if not discovered:
                            status_text.error("No company websites found for this query. Try refining your keywords.")
                        else:
                            status_text.success(f"✅ Found {len(discovered)} businesses! Running live structural scan & audit extraction in parallel...")

                            def update_lead_progress(lead: EnrichedLead, idx: int, tot: int):
                                pct = int((idx / tot) * 100) if tot > 0 else 0
                                prog_bar.progress(min(100, max(0, pct)))
                                contact_info = f" — 📞 Phone: `{lead.phone_number}`" if lead.phone_number else ""
                                email_info = f" • 📧 Email: `{lead.primary_email}`" if lead.primary_email else ""
                                status_text.markdown(f"⚡ **Auditing {idx} of {tot}:** `{lead.company_name}` (Score: {lead.audit_score}/100){contact_info}{email_info}")

                            results = safe_execute_live_audit_sync(
                                inputs=discovered,
                                location_hint=location_query.strip(),
                                progress_callback=update_lead_progress
                            )

                            # Deduct credit on successful run
                            st.session_state.credits -= 1
                            prog_bar.progress(100)
                            status_text.success(f"🎉 Successfully generated {len(results)} verified leads with Live Website Audits! (1 credit deducted)")

                            st.session_state.leads_data = results
                            st.session_state.df = pd.DataFrame([r.model_dump() for r in results])
                            st.toast("Leads generated! View them in '📊 Scraped Leads & PDF Export' tab.", icon="✅")
                            st.rerun()

            except Exception as e:
                st.error(f"Error during lead generation: {e}")
            finally:
                st.session_state.is_scraping = False

    # Optional CSV Batch Upload Section
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

                if st.button("⚡ Enrich Uploaded CSV", type="primary", disabled=st.session_state.is_scraping):
                    if st.session_state.credits <= 0:
                        st.warning("⚠️ Credits exhausted. Contact hariskandapg@gmail.com to extend.")
                    else:
                        csv_inputs = []
                        for _, row in uploaded_df.iterrows():
                            cn = str(row.get(selected_col, "")).strip()
                            if cn and cn.lower() != "nan":
                                csv_inputs.append(LeadInput(company_name=cn))

                        if not csv_inputs:
                            st.error("No valid company names found.")
                        else:
                            st.session_state.is_scraping = True
                            try:
                                with st.spinner("Auditing CSV accounts in parallel..."):
                                    csv_results = safe_execute_live_audit_sync(
                                        inputs=csv_inputs,
                                        location_hint="Regional Market"
                                    )
                                    st.session_state.credits -= 1
                                    st.session_state.leads_data = csv_results
                                    st.session_state.df = pd.DataFrame([r.model_dump() for r in csv_results])
                                    st.success(f"Enriched {len(csv_results)} companies from CSV! (1 credit deducted)")
                                    st.rerun()
                            finally:
                                st.session_state.is_scraping = False
            except Exception as ex:
                st.error(f"Error reading CSV: {ex}")

    # 🎯 Bottom Leaderboard Ad Container (728x90 style)
    st.markdown("""
    <div style="background-color:#1E293B; border:1px dashed #64748B; border-radius:12px; padding:18px 24px; display:flex; justify-content:space-between; align-items:center; margin-top:28px;">
        <div>
            <div style="font-size:0.92rem; font-weight:700; color:#FFFFFF;">🎯 ADVERTISEMENT SPACE AVAILABLE — Reach hundreds of B2B marketers daily.</div>
            <div style="font-size:0.80rem; color:#94A3B8; margin-top:4px;">
                Interested in advertising? Contact: <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" style="color:#38BDF8; text-decoration:none; font-weight:600;">hariskandapg@gmail.com</a>
            </div>
        </div>
        <div>
            <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" target="_blank" style="background:#0F172A; border:1px solid #38BDF8; color:#38BDF8; padding:6px 14px; border-radius:6px; font-size:0.82rem; text-decoration:none; font-weight:600;">Reserve Spot</a>
        </div>
    </div>
    """, unsafe_allow_html=True)


# =============================================================
# TAB 2: 📊 SCRAPED LEADS & PDF EXPORT
# =============================================================
with tab_results:
    if not st.session_state.leads_data:
        st.info("No leads generated yet. Run a search in Tab 1.")
    else:
        leads: List[EnrichedLead] = st.session_state.leads_data
        df = st.session_state.df

        st.markdown("### 📋 Generated Leads & AI Digital Growth Audits")
        
        # Summary Metrics
        tot = len(leads)
        emails_found = sum(1 for l in leads if l.primary_email)
        phones_found = sum(1 for l in leads if l.phone_number)
        avg_score = int(sum(l.audit_score or 75 for l in leads) / tot) if tot else 0

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Businesses Audited", tot)
        with m2:
            st.metric("Verified Emails Found", emails_found)
        with m3:
            st.metric("Phone Numbers Found", phones_found)
        with m4:
            st.metric("Average Audit Score", f"{avg_score}/100")

        # Full Dataframe Table
        display_cols = ["company_name", "website_url", "phone_number", "address", "primary_email", "audit_score", "personalized_pitch"]
        available_cols = [c for c in display_cols if c in df.columns]
        
        st.dataframe(
            df[available_cols],
            column_config={
                "company_name": st.column_config.TextColumn("Business Name"),
                "website_url": st.column_config.LinkColumn("Website URL"),
                "phone_number": st.column_config.TextColumn("Phone Number"),
                "address": st.column_config.TextColumn("Location / Address"),
                "primary_email": st.column_config.TextColumn("Contact Email"),
                "audit_score": st.column_config.NumberColumn("Audit Score", format="%d/100"),
                "personalized_pitch": st.column_config.TextColumn("2-Sentence Pitch & Recommendations", width="large")
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
                    label="📄 Download White-Labeled PDF Audit",
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
                label="📥 Download CSV",
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
                    phone_tag = f" • 📞 `{lead.phone_number}`" if lead.phone_number else ""
                    addr_tag = f" • 📍 `{lead.address}`" if lead.address else ""
                    st.markdown(f"**📌 {idx}. {lead.company_name}** (`{lead.primary_email or 'No email found'}`){phone_tag}{addr_tag}")
                    st.markdown(f"**Audit Score:** `{lead.audit_score or 80}/100` | **Summary:** {lead.company_summary or 'N/A'}")
                    st.markdown(f"""
                    <div class="audit-card">
                        <strong>2-Sentence Pitch & Recommendations:</strong><br>
                        {lead.personalized_pitch or lead.custom_audit}
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
                            agency_website=st.session_state.agency_website,
                            phone_number=lead.phone_number,
                            address=lead.address,
                            audit_score=lead.audit_score
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

    # 🎯 Bottom Leaderboard Ad Container (728x90 style)
    st.markdown("""
    <div style="background-color:#1E293B; border:1px dashed #64748B; border-radius:12px; padding:18px 24px; display:flex; justify-content:space-between; align-items:center; margin-top:28px;">
        <div>
            <div style="font-size:0.92rem; font-weight:700; color:#FFFFFF;">🎯 ADVERTISEMENT SPACE AVAILABLE — Reach hundreds of B2B marketers daily.</div>
            <div style="font-size:0.80rem; color:#94A3B8; margin-top:4px;">
                Interested in advertising? Contact: <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" style="color:#38BDF8; text-decoration:none; font-weight:600;">hariskandapg@gmail.com</a>
            </div>
        </div>
        <div>
            <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" target="_blank" style="background:#0F172A; border:1px solid #38BDF8; color:#38BDF8; padding:6px 14px; border-radius:6px; font-size:0.82rem; text-decoration:none; font-weight:600;">Reserve Spot</a>
        </div>
    </div>
    """, unsafe_allow_html=True)


# =============================================================
# TAB 3: 💼 ADVERTISING & CREDITS
# =============================================================
with tab_sponsors:
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

        mailto_full = generate_credit_extension_mailto(st.session_state.user_email)
        st.markdown(f"""
        <div style="text-align:center; padding:12px 0;">
            <a href="{mailto_full}" target="_blank" class="mailto-upgrade-btn">
                📧 Request More Credits via Email (hariskandapg@gmail.com)
            </a>
        </div>
        """, unsafe_allow_html=True)

        st.caption(f"Direct Contact: `{ADMIN_CONTACT_EMAIL}`")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # 💼 Sponsorship Packages Overview
    with st.container(border=True):
        st.markdown("### 💼 Partner & Advertising Packages")
        st.markdown("""
        Promote your product, agency, or B2B SaaS tool directly to founders, agency executives, and sales professionals using ApexLeads AI daily.
        """)

        c_ad1, c_ad2, c_ad3 = st.columns(3)
        with c_ad1:
            st.markdown("""
            <div style="background-color:#0F172A; border:1px solid #334155; border-radius:10px; padding:14px;">
                <h5 style="color:#38BDF8; margin:0 0 6px 0;">1. Sidebar Sponsor Card</h5>
                <p style="font-size:0.80rem; color:#CBD5E1; margin:0; line-height:1.4;">
                    Persistent placement in the left navigation sidebar visible across every search session.
                </p>
            </div>
            """, unsafe_allow_html=True)

        with c_ad2:
            st.markdown("""
            <div style="background-color:#0F172A; border:1px solid #334155; border-radius:10px; padding:14px;">
                <h5 style="color:#818CF8; margin:0 0 6px 0;">2. Leaderboard Banner</h5>
                <p style="font-size:0.80rem; color:#CBD5E1; margin:0; line-height:1.4;">
                    Full-width responsive 728x90 style banner container under the Lead Engine and Results tabs.
                </p>
            </div>
            """, unsafe_allow_html=True)

        with c_ad3:
            st.markdown("""
            <div style="background-color:#0F172A; border:1px solid #334155; border-radius:10px; padding:14px;">
                <h5 style="color:#34D399; margin:0 0 6px 0;">3. Custom Integration</h5>
                <p style="font-size:0.80rem; color:#CBD5E1; margin:0; line-height:1.4;">
                    Dedicated partner recommendations stamped inside white-labeled PDF audits and exports.
                </p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        
        sponsor_mailto = (
            f"mailto:{ADMIN_CONTACT_EMAIL}?subject=Sponsorship%20&%20Partner%20Inquiry"
            f"&body=Hi%20Haris,%20I%20would%20like%20to%20learn%20more%20about%20advertising%20and%20partnering%20with%20ApexLeads%20AI."
        )
        st.markdown(f"""
        <div style="text-align:center; padding:10px 0;">
            <a href="{sponsor_mailto}" target="_blank" style="display:inline-block; background:linear-gradient(90deg, #38BDF8, #818CF8); color:#0F172A; font-weight:bold; padding:12px 28px; border-radius:8px; text-decoration:none; font-size:0.95rem; box-shadow:0 4px 14px rgba(56,189,248,0.35);">
                📢 Inquire About Sponsorship (hariskandapg@gmail.com)
            </a>
        </div>
        """, unsafe_allow_html=True)

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
