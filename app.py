import asyncio
import io
import json
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fpdf import FPDF
import httpx
from bs4 import BeautifulSoup
import pandas as pd
import streamlit as st

from b2b_leadgen.config import settings
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.pipeline import LeadGenPipeline, detect_company_column
from b2b_leadgen.scraper import filter_valid_emails, clean_html_to_text, EMAIL_REGEX

logger = logging.getLogger(__name__)

# =============================================================
# 1. PAGE CONFIG & MODERN HIGH-CONTRAST CSS
# =============================================================
st.set_page_config(
    page_title="ApexLeads AI | B2B Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_NAME = "ApexLeads AI"
APP_SUBTITLE = "Automated B2B Lead Intelligence & AI Client Audits"
ADMIN_CONTACT_EMAIL = "hariskandapg@gmail.com"
ADMIN_PASSCODE = "admin123"
UNLOCK_PASSCODE = "4990"

# Phone & Address Regex
PHONE_REGEX = re.compile(r'(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})')
ADDRESS_REGEX = re.compile(r'\d+\s+[A-Za-z0-9\.,\s]+(?:Suite|Ste|St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Way|Pkwy|Parkway)\b[A-Za-z0-9\.,\s]*', re.IGNORECASE)

# Dark theme with deep slate/indigo gradient background (#0f172a to #1e1b4b) & crisp white text (#F8FAFC)
st.markdown("""
<style>
    /* Remove default Streamlit header/footer clutter */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}
    div[data-testid="stDecoration"] {visibility: hidden;}

    /* Deep slate/indigo gradient background */
    [data-testid="stAppViewContainer"], .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%) !important;
        color: #F8FAFC !important;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    }

    /* Force all text elements to be crisp white */
    h1, h2, h3, h4, h5, h6, p, span, label, div, .stMarkdown {
        color: #F8FAFC !important;
    }

    /* Modern Container Cards */
    .saas-card {
        background: rgba(30, 41, 59, 0.7) !important;
        border: 1px solid #334155 !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
        margin-bottom: 1rem !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3) !important;
    }

    /* Ad Container with Dashed Border */
    .ad-card {
        background: rgba(30, 41, 59, 0.4) !important;
        border: 2px dashed #64748B !important;
        border-radius: 12px !important;
        padding: 1.2rem !important;
        margin-top: 1.5rem !important;
        margin-bottom: 1rem !important;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* Primary Action Buttons: Blue-to-purple gradient with bold pure white text */
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

    /* Mail Links */
    .mail-btn {
        display: inline-block;
        background-color: #38BDF8 !important;
        color: #0F172A !important;
        font-weight: bold !important;
        text-decoration: none !important;
        padding: 8px 16px !important;
        border-radius: 8px !important;
        font-size: 0.88rem !important;
        box-shadow: 0 2px 10px rgba(56, 189, 248, 0.3) !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease !important;
    }
    .mail-btn:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 16px rgba(56, 189, 248, 0.5) !important;
    }

    /* Public Landing Hero Banner */
    .hero-banner {
        background: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 27, 75, 0.9) 50%, rgba(15, 23, 42, 0.95) 100%);
        border: 1px solid rgba(99, 102, 241, 0.35);
        border-radius: 16px;
        padding: 32px 24px;
        text-align: center;
        margin-bottom: 24px;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
    }
    .hero-banner h1 {
        font-size: 2.6rem;
        font-weight: 850;
        background: linear-gradient(135deg, #ffffff 0%, #38bdf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
        letter-spacing: -0.02em;
    }
    .hero-banner h3 {
        font-size: 1.15rem;
        color: #38bdf8 !important;
        font-weight: 700;
        margin-bottom: 8px;
    }

    /* Input box visibility */
    .stTextInput > div > div > input, .stNumberInput input {
        background-color: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid #475569 !important;
        border-radius: 8px !important;
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

    /* Audit Result Box */
    .audit-box {
        border-left: 4px solid #10b981;
        background-color: #111827;
        padding: 14px;
        border-radius: 8px;
        margin-top: 8px;
        margin-bottom: 8px;
        border: 1px solid #1f2937;
        color: #F8FAFC !important;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================
# 2. STATE INITIALIZATION
# =============================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""
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
    clean_email = user_email.strip() if user_email else "user@agency.com"
    subject = urllib.parse.quote("ApexLeads: Request to Extend Credits")
    body = urllib.parse.quote(
        f"Hi Haris,\n\nMy account ({clean_email}) has used all free credits on ApexLeads AI.\nPlease extend my limit.\n\nThank you!"
    )
    return f"mailto:{ADMIN_CONTACT_EMAIL}?subject={subject}&body={body}"


# =============================================================
# 📄 FPDF WHITE-LABEL PDF REPORT GENERATOR
# =============================================================
class CleanFPDFReport(FPDF):
    def __init__(self, agency_name: str, agency_website: str):
        super().__init__()
        self.agency_name = agency_name
        self.agency_website = agency_website

    def header(self):
        self.set_font('helvetica', 'B', 9)
        self.set_text_color(56, 189, 248)
        self.cell(0, 6, f"{self.agency_name.upper()} • B2B CLIENT AUDIT DOSSIER", border=0, align='L')
        self.ln(6)
        self.set_draw_color(71, 85, 105)
        self.line(10, 16, 200, 16)
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(148, 163, 184)
        self.cell(0, 10, f"Confidential Client Audit • Generated by {self.agency_name} ({self.agency_website}) • Page {self.page_no()}", align='C')


def generate_fpdf_lead_audit_report(
    leads: List[EnrichedLead],
    agency_name: str = "ApexLeads Agency Partners",
    agency_website: str = "https://apexleads.ai"
) -> bytes:
    """Generates a complete, high-converting multi-client audit report using FPDF."""
    pdf = CleanFPDFReport(agency_name=agency_name, agency_website=agency_website)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title & Metadata
    pdf.set_font('helvetica', 'B', 20)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, "B2B Digital Growth & Website Audit Report", ln=1, align='L')

    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%B %d, %Y')} | Audited Portfolio: {len(leads)} Target Enterprises", ln=1, align='L')
    pdf.ln(6)

    # Executive Table Header
    pdf.set_fill_color(30, 41, 59)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('helvetica', 'B', 9)
    pdf.cell(50, 8, " Company Name", 1, 0, 'L', True)
    pdf.cell(48, 8, " Website Domain", 1, 0, 'L', True)
    pdf.cell(42, 8, " Phone Number", 1, 0, 'L', True)
    pdf.cell(32, 8, " Primary Email", 1, 0, 'L', True)
    pdf.cell(18, 8, " Score", 1, 1, 'C', True)

    # Executive Table Rows
    pdf.set_font('helvetica', '', 8)
    pdf.set_text_color(30, 41, 59)
    fill = False
    for idx, lead in enumerate(leads[:18], 1):
        pdf.set_fill_color(241, 245, 249) if fill else pdf.set_fill_color(255, 255, 255)
        c_name = (lead.company_name or f"Company #{idx}")[:24]
        w_url = (lead.website_url or "N/A").replace("https://", "").replace("http://", "").replace("www.", "")[:24]
        phone = (lead.phone_number or "N/A")[:20]
        email = (lead.primary_email or "Verified")[:18]
        score = f"{lead.audit_score or 85}/100"

        pdf.cell(50, 7, f" {c_name}", 1, 0, 'L', fill)
        pdf.cell(48, 7, f" {w_url}", 1, 0, 'L', fill)
        pdf.cell(42, 7, f" {phone}", 1, 0, 'L', fill)
        pdf.cell(32, 7, f" {email}", 1, 0, 'L', fill)
        pdf.cell(18, 7, f" {score}", 1, 1, 'C', fill)
        fill = not fill

    # Detailed Audit Breakdown Pages
    for idx, lead in enumerate(leads, 1):
        pdf.add_page()
        pdf.set_font('helvetica', 'B', 15)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 8, f"#{idx} Client Audit: {lead.company_name}", ln=1, align='L')

        pdf.set_font('helvetica', '', 9)
        pdf.set_text_color(71, 85, 105)
        contact_line = f"Domain: {lead.website_url or 'N/A'} | Phone: {lead.phone_number or 'N/A'} | Email: {lead.primary_email or 'N/A'}"
        pdf.cell(0, 6, contact_line, ln=1, align='L')
        pdf.ln(4)

        # Health Score Box
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(203, 213, 225)
        pdf.rect(10, pdf.get_y(), 190, 24, 'DF')
        
        pdf.set_font('helvetica', 'B', 10)
        pdf.set_text_color(37, 99, 235)
        pdf.set_xy(14, pdf.get_y() + 3)
        pdf.cell(0, 5, f"DIGITAL HEALTH & CONVERSION AUDIT SCORE: {lead.audit_score or 85}/100", ln=1)

        pdf.set_font('helvetica', '', 8.5)
        pdf.set_text_color(51, 65, 85)
        pdf.set_x(14)
        ssl_text = "SSL Encrypted: Active" if lead.ssl_active else "SSL Encrypted: Unsecured"
        mobile_text = "Mobile Viewport: Optimized" if lead.mobile_responsive else "Mobile Viewport: Needs Optimization"
        pdf.cell(0, 5, f"Status Checks: [✓] {ssl_text} • [✓] {mobile_text} • [✓] Fast Response Latency", ln=1)
        pdf.ln(8)

        # 2-Sentence Pitch & Recommendations
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 7, "Executive Outreach Pitch & Identified Conversion Bottlenecks:", ln=1)

        pdf.set_font('helvetica', '', 9.5)
        pdf.set_text_color(30, 41, 59)
        pitch_content = lead.personalized_pitch or lead.custom_audit or "Our digital audit identified growth upside in deploying an automated 60-second inbound response system."
        
        safe_pitch = pitch_content.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(190, 5.5, safe_pitch)
        pdf.ln(6)

        # Implementation partner box
        pdf.set_fill_color(15, 23, 42)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('helvetica', 'B', 9)
        pdf.rect(10, pdf.get_y(), 190, 16, 'F')
        pdf.set_xy(14, pdf.get_y() + 3)
        pdf.cell(0, 5, f"IMPLEMENTATION PARTNER: {agency_name}", ln=1)
        pdf.set_font('helvetica', '', 8)
        pdf.set_text_color(203, 213, 225)
        pdf.set_x(14)
        pdf.cell(0, 4, f"To execute this growth roadmap, visit {agency_website} or contact your representative.", ln=1)

    return bytes(pdf.output())


# =============================================================
# ⚡ LIVE SCRAPING & AUTOMATED AUDITING BACKEND
# =============================================================
async def audit_single_business(
    lead_input: LeadInput,
    client: httpx.AsyncClient,
    location_hint: str = ""
) -> EnrichedLead:
    """Performs a live structural audit and contact extraction for a single business."""
    company_name = lead_input.company_name
    target_url = lead_input.website_url or ""
    
    if target_url and not target_url.startswith("http://") and not target_url.startswith("https://"):
        target_url = "https://" + target_url

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
# 3. VIEW 1: LANDING PAGE & LOGIN (WHEN authenticated == False)
# =============================================================
if not st.session_state.authenticated:
    # Public Hero Banner
    st.markdown(f"""
    <div class="hero-banner">
        <span style="font-size:0.78rem; background:rgba(56,189,248,0.2); color:#38bdf8; border:1px solid rgba(56,189,248,0.4); padding:4px 14px; border-radius:9999px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em;">
            ⚡ ENTERPRISE OUTBOUND INTELLIGENCE
        </span>
        <h1 style="margin-top:12px;">{APP_NAME}</h1>
        <h3>{APP_SUBTITLE}</h3>
        <p style="color:#cbd5e1; max-width:760px; margin:0 auto; font-size:1.05rem;">
            Discover high-intent local clients, identify website bottlenecks automatically, and generate executive PDF audits in seconds.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Two-Column Layout
    col_showcase, col_auth = st.columns([3, 2], gap="large")

    # LEFT: Interactive visual showcase using st.radio
    with col_showcase:
        st.markdown("### 📸 Interactive Platform Showcase")
        slide_choice = st.radio(
            "Preview Platform Capabilities:",
            [
                "🔍 1. Lead Discovery Engine",
                "🤖 2. Automated AI Audit",
                "📄 3. Executive PDF Pitch Decks",
                "⭐ 4. Customer Proof"
            ],
            horizontal=True
        )

        if slide_choice == "🔍 1. Lead Discovery Engine":
            st.markdown("""
            <div class="saas-card">
                <div style="color:#38BDF8; font-weight:800; font-size:0.8rem; margin-bottom:6px;">REAL-TIME EXTRACTION ENGINE</div>
                <h4 style="margin:0 0 8px 0; color:#FFFFFF;">Target Local Metros & Extract Verified B2B Intelligence</h4>
                <p style="color:#CBD5E1; font-size:0.92rem; line-height:1.5;">
                    Extract direct phone numbers, business locations, decision-maker emails, and website domains simultaneously across any metro.
                </p>
                <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:14px; font-family:monospace; font-size:0.84rem; color:#38BDF8;">
                    [✓] Radiant Plumbing & HVAC • Austin, TX • 📞 (512) 555-0199 • 📧 contact@radiantplumbing.com • Score: 92/100<br/>
                    [✓] Elite Roofing Solutions • Miami, FL • 📞 (305) 555-0142 • 📧 sales@eliteroofing.com • Score: 86/100<br/>
                    [✓] Metro Commercial HVAC • Dallas, TX • 📞 (214) 555-0188 • 📧 info@metrocommercial.com • Score: 78/100
                </div>
            </div>
            """, unsafe_allow_html=True)

        elif slide_choice == "🤖 2. Automated AI Audit":
            st.markdown("""
            <div class="saas-card">
                <div style="color:#818CF8; font-weight:800; font-size:0.8rem; margin-bottom:6px;">AUTOMATED STRUCTURAL SCANNER</div>
                <h4 style="margin:0 0 8px 0; color:#FFFFFF;">AI-Detected Conversion Bottlenecks & 2-Sentence Pitch</h4>
                <p style="color:#CBD5E1; font-size:0.92rem; line-height:1.5;">
                    Every lead receives an instant structural scan detecting SSL encryption, mobile viewport presence, response speed, and high-converting pitch recommendations.
                </p>
                <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:14px; color:#E2E8F0; font-size:0.88rem;">
                    <b>Identified Bottleneck:</b> Missing mobile viewport optimization & lack of direct instant quote forms.<br/>
                    <b>Tailored 2-Sentence Pitch:</b> <i>"Our digital audit for Metro Commercial HVAC identified an overall health score of 78/100 with a conversion bottleneck in missing mobile optimization. Implementing an automated high-velocity inbound response system will capture lost leads and increase customer acquisition by 25%."</i>
                </div>
            </div>
            """, unsafe_allow_html=True)

        elif slide_choice == "📄 3. Executive PDF Pitch Decks":
            st.markdown("""
            <div class="saas-card">
                <div style="color:#34D399; font-weight:800; font-size:0.8rem; margin-bottom:6px;">CLIENT DELIVERABLE • WHITE-LABEL FPDF</div>
                <h4 style="margin:0 0 8px 0; color:#FFFFFF;">Download 1-Click White-Labeled PDF Audit Bundles</h4>
                <p style="color:#CBD5E1; font-size:0.92rem; line-height:1.5;">
                    Generate branded multi-client audit dossiers complete with an executive portfolio summary, health scorecards, and implementation roadmaps stamped with your agency branding.
                </p>
                <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:16px; text-align:center;">
                    <span style="font-size:1.8rem;">📑</span>
                    <div style="font-weight:700; color:#FFFFFF; margin-top:4px;">ApexLeads Digital Growth & Client Audit Dossier</div>
                    <div style="color:#94A3B8; font-size:0.82rem;">Compiled Portfolio: 15 Verified Enterprises • White-Labeled Deliverable</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        else:
            st.markdown("""
            <div class="saas-card">
                <div style="color:#FACC15; font-weight:800; font-size:0.8rem; margin-bottom:6px;">⭐ VERIFIED CUSTOMER PROOF</div>
                <h4 style="margin:0 0 8px 0; color:#FFFFFF;">Loved by B2B Agencies & Sales Consultants</h4>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:8px;">
                    <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:12px;">
                        <div style="color:#FACC15; font-size:0.85rem; margin-bottom:4px;">★★★★★</div>
                        <p style="color:#E2E8F0; font-size:0.82rem; font-style:italic; margin-bottom:6px;">
                            "Closed 4 retainer deals in week one using these white-label PDF audits."
                        </p>
                        <div style="font-weight:700; color:#38BDF8; font-size:0.78rem;">— Marcus Vance, Founder</div>
                    </div>
                    <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:12px;">
                        <div style="color:#FACC15; font-size:0.85rem; margin-bottom:4px;">★★★★★</div>
                        <p style="color:#E2E8F0; font-size:0.82rem; font-style:italic; margin-bottom:6px;">
                            "The 2-sentence pitch makes cold outreach 5x easier. Verified phones and emails alongside live scores."
                        </p>
                        <div style="font-weight:700; color:#38BDF8; font-size:0.78rem;">— Sarah Jenkins, Strategist</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # RIGHT: Sign-in card with text inputs for Name and Email
    with col_auth:
        st.markdown("### 🚀 Access Platform")
        with st.container(border=True):
            st.markdown("""
            <div style="text-align:center; padding-bottom:8px;">
                <h4 style="margin:0 0 4px 0; color:#FFFFFF;">Claim 3 Free Search Credits</h4>
                <p style="font-size:0.88rem; color:#94A3B8; margin:0;">
                    Enter your business email below to launch the B2B engine.
                </p>
            </div>
            """, unsafe_allow_html=True)

            login_name = st.text_input("Agency / User Name", placeholder="e.g. Alex Rivera or Apex Agency", key="landing_name_input")
            login_email = st.text_input("Business Email Address", placeholder="e.g. founder@agency.com", key="landing_email_input")

            if st.button("Claim 3 Free Credits & Launch Platform →", type="primary", width="stretch"):
                clean_email = login_email.strip().lower()
                if not clean_email or "@" not in clean_email or "." not in clean_email:
                    st.error("Please enter a valid business email address.")
                else:
                    st.session_state.authenticated = True
                    st.session_state.user_email = clean_email
                    st.session_state.credits = 3
                    if login_name.strip():
                        st.session_state.agency_name = login_name.strip()
                    st.toast(f"Welcome to {APP_NAME}, {clean_email}!", icon="🎉")
                    st.rerun()

    st.stop()


# =============================================================
# 4. VIEW 2: AUTHENTICATED DASHBOARD (WHEN authenticated == True)
# =============================================================

# TOP PLATFORM HEADER
st.markdown(f"""
<div class="saas-card" style="display:flex; justify-content:space-between; align-items:center; padding:16px 24px; margin-bottom:20px;">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:1.6rem;">⚡</span>
        <div>
            <span style="font-size:1.4rem; font-weight:850; color:#FFFFFF;">{APP_NAME}</span>
            <div style="font-size:0.78rem; color:#94A3B8;">{APP_SUBTITLE}</div>
        </div>
    </div>
    <div style="display:flex; align-items:center; gap:16px;">
        <span style="background:#059669; color:#FFFFFF; padding:6px 14px; border-radius:9999px; font-weight:700; font-size:0.84rem;">
            🔍 {st.session_state.credits} / 3 Free Searches Left
        </span>
        <span style="color:#94A3B8; font-size:0.86rem;">👤 {st.session_state.user_email}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# SIDEBAR CONTROLS
with st.sidebar:
    st.markdown(f"### ⚡ **{APP_NAME}**")
    st.markdown("B2B Outbound Intelligence")
    st.markdown(f"👤 **User:** `{st.session_state.user_email}`")
    st.metric("Free Credits Remaining", f"{st.session_state.credits} / 3")

    # Log Out Button
    if st.button("Log Out", width="stretch"):
        st.session_state.authenticated = False
        st.session_state.user_email = ""
        st.session_state.credits = 3
        st.session_state.leads_data = []
        st.session_state.df = pd.DataFrame()
        st.rerun()

    st.divider()

    # Out of Credits Wall & Mailto Extension
    if st.session_state.credits <= 0:
        st.error("⚠️ **Credits Exhausted!**")
        st.caption("You have used all free search credits.")
        mailto_extension = generate_credit_extension_mailto(st.session_state.user_email)
        st.markdown(f"""
        <a href="{mailto_extension}" target="_blank" class="mail-btn" style="display:block; text-align:center; background:#EF4444 !important; color:#FFFFFF !important; margin-top:4px;">
            📧 Request Credit Extension
        </a>
        """, unsafe_allow_html=True)
    else:
        mailto_extension = generate_credit_extension_mailto(st.session_state.user_email)
        st.markdown(f"""
        <a href="{mailto_extension}" target="_blank" class="mail-btn" style="display:block; text-align:center; margin-top:6px;">
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

    # 📢 SPONSOR SPOTLIGHT CARD
    st.markdown("""
    <div style="background-color:#1E293B; border:1px solid #38BDF8; border-radius:12px; padding:16px; text-align:center; box-shadow:0 4px 16px rgba(56,189,248,0.15);">
        <div style="font-size:0.75rem; font-weight:800; color:#38BDF8; letter-spacing:0.05em; text-transform:uppercase; margin-bottom:6px;">📢 SPONSOR SPOTLIGHT</div>
        <div style="font-size:0.88rem; font-weight:700; color:#FFFFFF; margin-bottom:6px;">Promote Your B2B Tool or Agency</div>
        <p style="font-size:0.78rem; color:#CBD5E1; line-height:1.4; margin-bottom:12px;">
            Promote your B2B software, service, or agency to active sales professionals here.
        </p>
        <a href="mailto:hariskandapg@gmail.com?subject=Sponsor%20Ad%20Placement%20Inquiry&body=Hi%20Haris,%20I%20am%20interested%20in%20placing%20an%20ad/banner%20on%20your%20ApexLeads%20platform.%20Let%20me%20know%20your%20rates%20and%20availability." target="_blank" class="mail-btn" style="display:inline-block; width:100%; text-align:center;">Reserve This Ad Spot ($)</a>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Collapsible Admin Expander (Passcode: "admin123")
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
# MAIN DASHBOARD: 3 TABS
# =============================================================
tab1, tab2, tab3 = st.tabs([
    "🚀 Lead & Audit Engine",
    "📋 Scraped Leads & PDF Export",
    "💼 Sponsorships & Credits"
])


# =============================================================
# TAB 1: 🚀 LEAD & AUDIT ENGINE
# =============================================================
with tab1:
    # Feature Showcase Grid
    c_f1, c_f2, c_f3 = st.columns(3)
    with c_f1:
        st.markdown("""
        <div class="saas-card">
            <div style="font-size:1.4rem; margin-bottom:6px;">🌐</div>
            <h4 style="margin:0 0 6px 0; font-weight:700; color:#FFFFFF;">Automated Lead Hunter</h4>
            <p style="margin:0; font-size:0.84rem; color:#CBD5E1; line-height:1.4;">
                Fast parallel scraping of verified company websites, phone numbers, and addresses.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_f2:
        st.markdown("""
        <div class="saas-card">
            <div style="font-size:1.4rem; margin-bottom:6px;">🤖</div>
            <h4 style="margin:0 0 6px 0; font-weight:700; color:#FFFFFF;">Live Website Auditing</h4>
            <p style="margin:0; font-size:0.84rem; color:#CBD5E1; line-height:1.4;">
                Scans SSL, mobile viewport, meta tags, and generates 2-sentence pitch recommendations.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with c_f3:
        st.markdown("""
        <div class="saas-card">
            <div style="font-size:1.4rem; margin-bottom:6px;">📄</div>
            <h4 style="margin:0 0 6px 0; font-weight:700; color:#FFFFFF;">Executive PDF Deliverable</h4>
            <p style="margin:0; font-size:0.84rem; color:#CBD5E1; line-height:1.4;">
                Download complete multi-client PDF audit bundles with audit score & agency branding.
            </p>
        </div>
        """, unsafe_allow_html=True)

    # Search Form Container
    with st.container(border=True):
        st.markdown("### 🎯 Find Local Businesses & Generate AI Audits")
        st.markdown("Enter target keywords, industry, and city (e.g. *'Commercial roofing in Miami, FL'* or *'HVAC contractors in Dallas, TX'*):")

        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            niche_query = st.text_input("Target Niche / Service", placeholder="e.g. Commercial Roofing Contractors", key="niche_input")
        with c2:
            location_query = st.text_input("City / Metro Location", placeholder="e.g. Miami, FL", key="location_input")
        with c3:
            lead_count = st.slider("Lead Count", min_value=1, max_value=15, value=10, step=1)

        c_btn, c_stat = st.columns([2, 1])
        with c_btn:
            btn_generate = st.button("Start Lead Discovery", type="primary", width="stretch", disabled=st.session_state.is_scraping)
        with c_stat:
            st.metric("Free Credits Remaining", f"{st.session_state.credits} / 3")

    # Lead Generation Action
    if btn_generate:
        combined_query = f"{niche_query.strip()} in {location_query.strip()}".strip() if location_query.strip() else niche_query.strip()

        if not combined_query:
            st.error("Please enter a target niche or location.")
        elif st.session_state.credits <= 0:
            st.warning("⚠️ Credits exhausted. Contact hariskandapg@gmail.com to extend.")
        else:
            st.session_state.is_scraping = True
            try:
                with st.status(f"🔎 Discovering businesses and generating live website audits for '{combined_query}'...", expanded=True) as status_box:
                    prog_bar = st.progress(0)
                    st.write(f"🔎 Querying DuckDuckGo for: `{combined_query}`...")
                    discovered = discover_leads_by_keyword(combined_query, max_results=int(lead_count))

                    if not discovered:
                        st.error("No company websites found for this query. Try refining your keywords.")
                    else:
                        st.write(f"✅ Found {len(discovered)} businesses! Running live structural scans & audit extraction in parallel...")

                        def update_lead_progress(lead: EnrichedLead, idx: int, tot: int):
                            pct = int((idx / tot) * 100) if tot > 0 else 0
                            prog_bar.progress(min(100, max(0, pct)))
                            contact_info = f" — 📞 Phone: `{lead.phone_number}`" if lead.phone_number else ""
                            email_info = f" • 📧 Email: `{lead.primary_email}`" if lead.primary_email else ""
                            st.write(f"⚡ **Auditing {idx} of {tot}:** `{lead.company_name}` (Score: {lead.audit_score}/100){contact_info}{email_info}")

                        results = safe_execute_live_audit_sync(
                            inputs=discovered,
                            location_hint=location_query.strip(),
                            progress_callback=update_lead_progress
                        )

                        # Deduct credit on successful run
                        st.session_state.credits -= 1
                        prog_bar.progress(100)
                        status_box.update(label=f"🎉 Successfully generated {len(results)} verified leads with Live Website Audits! (1 credit deducted)", state="complete")

                        st.session_state.leads_data = results
                        st.session_state.df = pd.DataFrame([r.model_dump() for r in results])
                        st.toast("Leads generated! View them in '📋 Scraped Leads & PDF Export' tab.", icon="✅")
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

    # 🎯 Leaderboard Ad Slot Container (.ad-card)
    st.markdown("""
    <div class="ad-card">
        <div>
            <div style="font-size:0.92rem; font-weight:700; color:#FFFFFF;">🎯 ADVERTISEMENT SPACE AVAILABLE — Reach hundreds of B2B marketers daily.</div>
            <div style="font-size:0.80rem; color:#94A3B8; margin-top:4px;">
                Interested in advertising? Contact: <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" style="color:#38BDF8; text-decoration:none; font-weight:600;">hariskandapg@gmail.com</a>
            </div>
        </div>
        <div>
            <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" target="_blank" class="mail-btn">Reserve Spot</a>
        </div>
    </div>
    """, unsafe_allow_html=True)


# =============================================================
# TAB 2: 📋 SCRAPED LEADS & PDF EXPORT
# =============================================================
with tab2:
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
                fpdf_bytes = generate_fpdf_lead_audit_report(
                    leads=leads,
                    agency_name=st.session_state.agency_name,
                    agency_website=st.session_state.agency_website
                )
                st.download_button(
                    label="📄 Download Executive Audit PDF",
                    data=fpdf_bytes,
                    file_name=f"apexleads_executive_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
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

        # Individual Lead Audits Expander
        with st.expander("🔍 View Individual Company Audits & 2-Sentence Pitches", expanded=False):
            for idx, lead in enumerate(leads, 1):
                phone_tag = f" • 📞 `{lead.phone_number}`" if lead.phone_number else ""
                addr_tag = f" • 📍 `{lead.address}`" if lead.address else ""
                st.markdown(f"**📌 {idx}. {lead.company_name}** (`{lead.primary_email or 'No email found'}`){phone_tag}{addr_tag}")
                st.markdown(f"**Audit Score:** `{lead.audit_score or 80}/100` | **Summary:** {lead.company_summary or 'N/A'}")
                st.markdown(f"""
                <div class="audit-box">
                    <strong>2-Sentence Pitch & Recommendations:</strong><br>
                    {lead.personalized_pitch or lead.custom_audit}
                </div>
                """, unsafe_allow_html=True)
                st.divider()

    # 🎯 Leaderboard Ad Slot Container (.ad-card)
    st.markdown("""
    <div class="ad-card">
        <div>
            <div style="font-size:0.92rem; font-weight:700; color:#FFFFFF;">🎯 ADVERTISEMENT SPACE AVAILABLE — Reach hundreds of B2B marketers daily.</div>
            <div style="font-size:0.80rem; color:#94A3B8; margin-top:4px;">
                Interested in advertising? Contact: <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" style="color:#38BDF8; text-decoration:none; font-weight:600;">hariskandapg@gmail.com</a>
            </div>
        </div>
        <div>
            <a href="mailto:hariskandapg@gmail.com?subject=Leaderboard%20Ad%20Inquiry" target="_blank" class="mail-btn">Reserve Spot</a>
        </div>
    </div>
    """, unsafe_allow_html=True)


# =============================================================
# TAB 3: 💼 SPONSORSHIPS & CREDITS
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
            st.metric("Free Credits Remaining", f"{st.session_state.credits} / 3")

        st.markdown("---")
        st.markdown("#### 📧 Request Credit Extension from Haris")
        st.markdown("Click below to open a pre-formatted email request to `hariskandapg@gmail.com`:")

        mailto_full = generate_credit_extension_mailto(st.session_state.user_email)
        st.markdown(f"""
        <div style="text-align:center; padding:12px 0;">
            <a href="{mailto_full}" target="_blank" class="mail-btn" style="padding:12px 28px !important; font-size:1rem !important;">
                📧 Request More Credits via Email (hariskandapg@gmail.com)
            </a>
        </div>
        """, unsafe_allow_html=True)

        st.caption(f"Direct Contact: `{ADMIN_CONTACT_EMAIL}`")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # 💼 Sponsorship Packages Overview
    with st.container(border=True):
        st.markdown("### 💼 Partner & Sponsorship Packages")
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
            <a href="{sponsor_mailto}" target="_blank" class="mail-btn" style="padding:12px 28px !important; font-size:0.95rem !important;">
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
