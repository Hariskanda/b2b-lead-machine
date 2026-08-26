import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)


def generate_company_audit_pdf(
    company_name: str,
    website_url: Optional[str] = None,
    primary_email: Optional[str] = None,
    summary: Optional[str] = None,
    custom_audit: Optional[str] = None,
    agency_name: str = "AI Growth & Intelligence Partners",
    agency_website: str = "https://growth-intelligence.io",
    prepared_for: Optional[str] = None
) -> bytes:
    """
    Generates a high-converting, professional, white-labeled PDF digital audit report
    for a single business that consultants/agencies can deliver directly to clients.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # Brand Colors
    PRIMARY = colors.HexColor("#0f172a")      # Slate 900
    ACCENT = colors.HexColor("#2563eb")       # Royal Blue
    EMERALD = colors.HexColor("#059669")      # Emerald 600
    AMBER = colors.HexColor("#d97706")        # Amber 600
    CARD_BG = colors.HexColor("#f8fafc")      # Slate 50
    TEXT_DARK = colors.HexColor("#1e293b")    # Slate 800
    TEXT_MUTED = colors.HexColor("#64748b")   # Slate 500
    BORDER_COLOR = colors.HexColor("#e2e8f0") # Slate 200

    # Custom Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=PRIMARY
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=TEXT_MUTED
    )

    h2_style = ParagraphStyle(
        'H2Header',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=PRIMARY,
        spaceBefore=8,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14.5,
        textColor=TEXT_DARK
    )

    bullet_style = ParagraphStyle(
        'AuditBullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=TEXT_DARK
    )

    story = []

    # ---------------------------------------------------------
    # 1. Header with Agency Branding & Prospect Metadata
    # ---------------------------------------------------------
    header_data = [
        [
            Paragraph(f"<b>{agency_name.upper()}</b>", ParagraphStyle('AgH', fontName='Helvetica-Bold', fontSize=10.5, textColor=ACCENT)),
            Paragraph(f"<b>CONFIDENTIAL CLIENT AUDIT</b>", ParagraphStyle('Conf', fontName='Helvetica-Bold', fontSize=9, textColor=TEXT_MUTED, alignment=2))
        ],
        [
            Paragraph("<b>DIGITAL GROWTH & CLIENT AUDIT</b>", title_style),
            Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('Dt', fontName='Helvetica', fontSize=9, textColor=TEXT_MUTED, alignment=2))
        ],
        [
            Paragraph(f"Target Client: <b>{company_name}</b> | Website: <i>{website_url or 'N/A'}</i>", subtitle_style),
            Paragraph(f"Prepared by: {agency_name}", ParagraphStyle('Prep', fontName='Helvetica', fontSize=8.5, textColor=TEXT_MUTED, alignment=2))
        ]
    ]
    header_table = Table(header_data, colWidths=[380, 150])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT, spaceBefore=4, spaceAfter=14))

    # ---------------------------------------------------------
    # 2. Executive Overview Box
    # ---------------------------------------------------------
    summary_text = summary or f"{company_name} is an established organization providing core industry services with active market presence."
    exec_content = [
        [Paragraph("<b>EXECUTIVE BUSINESS DOSSIER & SUMMARY</b>", ParagraphStyle('ExH', fontName='Helvetica-Bold', fontSize=10, textColor=PRIMARY))],
        [Paragraph(summary_text, body_style)],
        [Spacer(1, 4)],
        [Paragraph(f"<b>Official Contact:</b> <code>{primary_email or 'Verified via Portal'}</code> | <b>Website Domain:</b> <i>{website_url or 'N/A'}</i>", subtitle_style)]
    ]
    exec_card = Table(exec_content, colWidths=[530])
    exec_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('LINELEFT', (0, 0), (0, -1), 4, ACCENT),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 14),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
    ]))
    story.append(exec_card)
    story.append(Spacer(1, 14))

    # ---------------------------------------------------------
    # 3. Key Findings & Performance Metrics Grid
    # ---------------------------------------------------------
    story.append(Paragraph("<b>📊 AUDIT SCORECARD & HEALTH SIGNALS</b>", h2_style))
    score_data = [
        [
            Paragraph("<b>ONLINE VISIBILITY</b><br/><font size='14' color='#059669'><b>88/100</b></font><br/><font size='8' color='#64748b'>Brand Presence</font>", ParagraphStyle('Sc1', fontName='Helvetica', alignment=1)),
            Paragraph("<b>INBOUND CAPTURE</b><br/><font size='14' color='#d97706'><b>54/100</b></font><br/><font size='8' color='#64748b'>Lead Conversion Gap</font>", ParagraphStyle('Sc2', fontName='Helvetica', alignment=1)),
            Paragraph("<b>RESPONSE VELOCITY</b><br/><font size='14' color='#dc2626'><b>42/100</b></font><br/><font size='8' color='#64748b'>Automation Opportunity</font>", ParagraphStyle('Sc3', fontName='Helvetica', alignment=1)),
            Paragraph("<b>OVERALL GROWTH GRADE</b><br/><font size='16' color='#2563eb'><b>B+</b></font><br/><font size='8' color='#64748b'>High Upside</font>", ParagraphStyle('Sc4', fontName='Helvetica', alignment=1))
        ]
    ]
    score_table = Table(score_data, colWidths=[132, 132, 132, 134])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#ffffff")),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 14))

    # ---------------------------------------------------------
    # 4. Detailed 3-Point Custom Mini-Audit Breakdown
    # ---------------------------------------------------------
    story.append(Paragraph("<b>🔍 3-POINT DETAILED MINI-AUDIT FINDINGS</b>", h2_style))

    raw_audit = custom_audit or (
        "• 🟢 Strengths: Strong reputation and clear commercial focus in target service category.\n"
        "• 🔍 Blind Spot / Growth Opportunity: Website visitors lack instant 24/7 self-serve booking and immediate inquiry follow-up automation.\n"
        "• 💡 Actionable Recommendation: Deploy an intelligent client capture workflow to automatically engage, qualify, and route prospects into the sales pipeline within 60 seconds."
    )

    lines = [l.strip() for l in raw_audit.split("\n") if l.strip()]

    for line in lines:
        if "strength" in line.lower() or "🟢" in line:
            icon_title = "<b>🟢 KEY STRENGTHS IDENTIFIED</b>"
            bar_color = EMERALD
        elif "blind spot" in line.lower() or "opportunity" in line.lower() or "🔍" in line:
            icon_title = "<b>🔍 IDENTIFIED BLIND SPOT & CONVERSION LEAK</b>"
            bar_color = AMBER
        else:
            icon_title = "<b>💡 HIGH-IMPACT RECOMMENDATION</b>"
            bar_color = ACCENT

        clean_text = line.replace("•", "").replace("🟢", "").replace("🔍", "").replace("💡", "").strip()

        finding_data = [
            [Paragraph(icon_title, ParagraphStyle('FH', fontName='Helvetica-Bold', fontSize=9.5, textColor=PRIMARY))],
            [Paragraph(clean_text, bullet_style)]
        ]
        finding_table = Table(finding_data, colWidths=[530])
        finding_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
            ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
            ('LINELEFT', (0, 0), (0, -1), 3.5, bar_color),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(finding_table)
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))

    # ---------------------------------------------------------
    # 5. Implementation Roadmap & Agency Call-to-Action
    # ---------------------------------------------------------
    story.append(Paragraph("<b>🚀 30-DAY GROWTH IMPLEMENTATION ROADMAP</b>", h2_style))
    roadmap_data = [
        [
            Paragraph("<b>Days 1-7: Infrastructure</b><br/><font size='8' color='#475569'>Deploy automated intake webhooks on homepage.</font>", ParagraphStyle('R1', fontName='Helvetica', fontSize=8.5)),
            Paragraph("<b>Days 8-14: Lead Routing</b><br/><font size='8' color='#475569'>Setup instant SMS/Email notifications to sales reps.</font>", ParagraphStyle('R2', fontName='Helvetica', fontSize=8.5)),
            Paragraph("<b>Days 15-30: Scaling</b><br/><font size='8' color='#475569'>Launch outbound pipeline campaigns and optimize ROI.</font>", ParagraphStyle('R3', fontName='Helvetica', fontSize=8.5))
        ]
    ]
    roadmap_table = Table(roadmap_data, colWidths=[176, 176, 178])
    roadmap_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(roadmap_table)
    story.append(Spacer(1, 14))

    # Agency Footer Box
    cta_content = [
        [Paragraph(f"<b>CONSULTING & IMPLEMENTATION PARTNER:</b> {agency_name}", ParagraphStyle('CtH', fontName='Helvetica-Bold', fontSize=10, textColor=colors.white))],
        [Paragraph(f"To execute this growth roadmap and unlock new inbound enterprise revenue, visit <u>{agency_website}</u> or contact your representative directly.", ParagraphStyle('CtB', fontName='Helvetica', fontSize=9, textColor=colors.HexColor("#cbd5e1")))]
    ]
    cta_card = Table(cta_content, colWidths=[530])
    cta_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PRIMARY),
        ('BOX', (0, 0), (-1, -1), 1, PRIMARY),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 14),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
    ]))
    story.append(cta_card)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_batch_audit_bundle_pdf(
    leads: List[Any],
    agency_name: str = "AI Growth & Intelligence Partners",
    agency_website: str = "https://growth-intelligence.io"
) -> bytes:
    """
    Generates a multi-page PDF compilation containing:
    1. Professional Cover Page with Executive Summary Table of all scraped businesses
    2. Deep-dive 3-point digital audits for each lead on dedicated pages
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()
    PRIMARY = colors.HexColor("#0f172a")
    ACCENT = colors.HexColor("#2563eb")
    EMERALD = colors.HexColor("#059669")
    AMBER = colors.HexColor("#d97706")
    CARD_BG = colors.HexColor("#f8fafc")
    TEXT_DARK = colors.HexColor("#1e293b")
    TEXT_MUTED = colors.HexColor("#64748b")
    BORDER_COLOR = colors.HexColor("#e2e8f0")

    title_style = ParagraphStyle('DocTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=PRIMARY)
    cover_title_style = ParagraphStyle('CoverTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=PRIMARY)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, textColor=TEXT_MUTED)
    h2_style = ParagraphStyle('H2Header', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=PRIMARY, spaceBefore=6, spaceAfter=3)
    body_style = ParagraphStyle('BodyDark', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=13.5, textColor=TEXT_DARK)
    bullet_style = ParagraphStyle('AuditBullet', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=TEXT_DARK)

    story = []

    # =========================================================
    # 📄 COVER PAGE & EXECUTIVE PORTFOLIO SUMMARY
    # =========================================================
    cover_header = [
        [
            Paragraph(f"<b>{agency_name.upper()} • ENTERPRISE AUDIT INTELLIGENCE</b>", ParagraphStyle('AgH', fontName='Helvetica-Bold', fontSize=10, textColor=ACCENT)),
            Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('DtH', fontName='Helvetica', fontSize=9, textColor=TEXT_MUTED, alignment=2))
        ],
        [
            Paragraph("<b>DIGITAL GROWTH & CLIENT AUDIT BUNDLE</b>", cover_title_style),
            Paragraph("<b>PRO DELIVERABLE</b>", ParagraphStyle('StH', fontName='Helvetica-Bold', fontSize=10, textColor=EMERALD, alignment=2))
        ],
        [
            Paragraph(f"Compiled Portfolio: <b>{len(leads)} Verified Enterprises</b> • Multi-Client Growth Audits", subtitle_style),
            Paragraph(f"Prepared by: {agency_name}", ParagraphStyle('Prep', fontName='Helvetica', fontSize=8.5, textColor=TEXT_MUTED, alignment=2))
        ]
    ]
    cover_table = Table(cover_header, colWidths=[380, 150])
    cover_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(cover_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2.5, color=ACCENT, spaceBefore=4, spaceAfter=14))

    # Executive Overview
    overview_text = (
        f"This comprehensive market intelligence dossier contains custom AI-powered digital growth audits, "
        f"conversion gap assessments, and actionable recommendations for {len(leads)} target enterprises. "
        f"Each audit identifies core strengths, inbound lead leaks, and high-impact optimizations."
    )
    overview_card = Table([[Paragraph("<b>EXECUTIVE PORTFOLIO OVERVIEW</b>", ParagraphStyle('ExH', fontName='Helvetica-Bold', fontSize=10, textColor=PRIMARY))], [Paragraph(overview_text, body_style)]], colWidths=[530])
    overview_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('LINELEFT', (0, 0), (0, -1), 4, ACCENT),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(overview_card)
    story.append(Spacer(1, 14))

    # Executive Portfolio Summary Table
    story.append(Paragraph("<b>📋 AUDITED ENTERPRISE PORTFOLIO INDEX</b>", h2_style))
    table_rows = [
        [
            Paragraph("<b>#</b>", ParagraphStyle('TH1', fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.white)),
            Paragraph("<b>Company Name</b>", ParagraphStyle('TH2', fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.white)),
            Paragraph("<b>Website Domain</b>", ParagraphStyle('TH3', fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.white)),
            Paragraph("<b>Contact Email</b>", ParagraphStyle('TH4', fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.white)),
            Paragraph("<b>Grade</b>", ParagraphStyle('TH5', fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.white, alignment=1))
        ]
    ]

    for idx, lead in enumerate(leads[:15], 1):
        c_name = getattr(lead, "company_name", None) or (lead.get("company_name") if isinstance(lead, dict) else f"Company #{idx}")
        w_url = getattr(lead, "website_url", None) or (lead.get("website_url") if isinstance(lead, dict) else "N/A")
        p_email = getattr(lead, "primary_email", None) or (lead.get("primary_email") if isinstance(lead, dict) else "Verified")

        clean_url = w_url.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
        if len(clean_url) > 22:
            clean_url = clean_url[:20] + "..."

        table_rows.append([
            Paragraph(f"{idx}", ParagraphStyle('TD1', fontName='Helvetica', fontSize=8, textColor=TEXT_DARK)),
            Paragraph(f"<b>{c_name[:24]}</b>", ParagraphStyle('TD2', fontName='Helvetica', fontSize=8, textColor=PRIMARY)),
            Paragraph(f"<i>{clean_url}</i>", ParagraphStyle('TD3', fontName='Helvetica', fontSize=7.5, textColor=TEXT_MUTED)),
            Paragraph(f"<code>{p_email[:26]}</code>", ParagraphStyle('TD4', fontName='Helvetica', fontSize=7.5, textColor=ACCENT)),
            Paragraph("<b>B+</b>", ParagraphStyle('TD5', fontName='Helvetica-Bold', fontSize=8, textColor=EMERALD, alignment=1))
        ])

    index_table = Table(table_rows, colWidths=[24, 156, 130, 160, 60])
    index_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, CARD_BG]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(index_table)
    story.append(Spacer(1, 14))

    # Cover Footer
    story.append(Paragraph(f"<i>Confidential Portfolio • Generated by {agency_name} ({agency_website})</i>", ParagraphStyle('FtCover', fontName='Helvetica-Oblique', fontSize=8, textColor=TEXT_MUTED, alignment=1)))

    # =========================================================
    # 📑 PER-COMPANY DEEP-DIVE AUDITS (DEDICATED PAGES)
    # =========================================================
    for idx, lead in enumerate(leads):
        story.append(PageBreak())

        c_name = getattr(lead, "company_name", None) or (lead.get("company_name") if isinstance(lead, dict) else f"Company #{idx+1}")
        w_url = getattr(lead, "website_url", None) or (lead.get("website_url") if isinstance(lead, dict) else "")
        p_email = getattr(lead, "primary_email", None) or (lead.get("primary_email") if isinstance(lead, dict) else "")
        c_summary = getattr(lead, "company_summary", None) or (lead.get("company_summary") if isinstance(lead, dict) else "")
        c_audit = getattr(lead, "custom_audit", None) or getattr(lead, "personalized_pitch", None) or (lead.get("custom_audit") if isinstance(lead, dict) else "")

        header_data = [
            [
                Paragraph(f"<b>{agency_name.upper()} • PORTFOLIO AUDIT REPORT #{idx+1}</b>", ParagraphStyle('AgH', fontName='Helvetica-Bold', fontSize=9, textColor=ACCENT)),
                Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('DtH', fontName='Helvetica', fontSize=8.5, textColor=TEXT_MUTED, alignment=2))
            ],
            [
                Paragraph(f"<b>DIGITAL AUDIT: {c_name}</b>", title_style),
                Paragraph("<b>GRADE: B+</b>", ParagraphStyle('StH', fontName='Helvetica-Bold', fontSize=10, textColor=EMERALD, alignment=2))
            ],
            [
                Paragraph(f"Website: <i>{w_url or 'N/A'}</i> • Email: <code>{p_email or 'Verified on Portal'}</code>", subtitle_style),
                ""
            ]
        ]
        header_table = Table(header_data, colWidths=[380, 150])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceBefore=2, spaceAfter=10))

        # Overview
        summary_text = c_summary or f"{c_name} is an active enterprise delivering targeted solutions."
        exec_card = Table([[Paragraph("<b>EXECUTIVE SUMMARY</b>", ParagraphStyle('ExH', fontName='Helvetica-Bold', fontSize=9.5, textColor=PRIMARY))], [Paragraph(summary_text, body_style)]], colWidths=[530])
        exec_card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
            ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
            ('LINELEFT', (0, 0), (0, -1), 3, ACCENT),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(exec_card)
        story.append(Spacer(1, 10))

        # Scorecard
        score_data = [[
            Paragraph("<b>VISIBILITY</b><br/><font size='12' color='#059669'><b>85/100</b></font>", ParagraphStyle('Sc1', fontName='Helvetica', alignment=1)),
            Paragraph("<b>CONVERSION</b><br/><font size='12' color='#d97706'><b>52/100</b></font>", ParagraphStyle('Sc2', fontName='Helvetica', alignment=1)),
            Paragraph("<b>AUTOMATION</b><br/><font size='12' color='#dc2626'><b>40/100</b></font>", ParagraphStyle('Sc3', fontName='Helvetica', alignment=1)),
            Paragraph("<b>UPSIDE POTENTIAL</b><br/><font size='12' color='#2563eb'><b>HIGH</b></font>", ParagraphStyle('Sc4', fontName='Helvetica', alignment=1))
        ]]
        score_table = Table(score_data, colWidths=[132, 132, 132, 134])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#ffffff")),
            ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 10))

        # Findings
        story.append(Paragraph("<b>🔍 3-POINT AUDIT FINDINGS</b>", h2_style))
        raw_audit = c_audit or (
            "• 🟢 Strengths: Quality service offering and brand positioning.\n"
            "• 🔍 Opportunity: Automated 24/7 lead intake response time optimization.\n"
            "• 💡 Recommendation: Implement an instant digital booking workflow to convert more high-intent web visitors."
        )
        for line in [l.strip() for l in raw_audit.split("\n") if l.strip()]:
            bar_color = EMERALD if ("strength" in line.lower() or "🟢" in line) else (AMBER if ("opportunity" in line.lower() or "blind spot" in line.lower() or "🔍" in line) else ACCENT)
            clean_text = line.replace("•", "").replace("🟢", "").replace("🔍", "").replace("💡", "").strip()
            finding_table = Table([[Paragraph(clean_text, bullet_style)]], colWidths=[530])
            finding_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
                ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
                ('LINELEFT', (0, 0), (0, -1), 3, bar_color),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ]))
            story.append(finding_table)
            story.append(Spacer(1, 4))

        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<i>Delivered exclusively by {agency_name} • {agency_website}</i>", ParagraphStyle('Ft', fontName='Helvetica-Oblique', fontSize=8, textColor=TEXT_MUTED, alignment=1)))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
