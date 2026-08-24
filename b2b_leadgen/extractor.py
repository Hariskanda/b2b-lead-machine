import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from b2b_leadgen.config import settings
from b2b_leadgen.models import CompanyExtractionResult, ScrapedPage

logger = logging.getLogger(__name__)


def build_extraction_prompt(company_name: str, scraped_page: ScrapedPage) -> str:
    """Builds the structured extraction prompt for Google Gemini to produce a high-value Custom Mini-Audit."""
    discovered_emails_str = (
        ", ".join(scraped_page.discovered_emails)
        if scraped_page.discovered_emails
        else "None detected automatically"
    )

    prompt = f"""
You are an expert digital growth auditor and B2B research consultant. Analyze the scraped website data for "{company_name}" and provide an actionable, value-first Custom Mini-Audit rather than a generic sales pitch.

Output the following structured JSON fields:
1. summary: A concise, strictly 1-sentence description of what the company does and its core value proposition.
2. primary_email: The primary contact, sales, support, or general inquiry email address found. Set to null if no valid email is found.
3. custom_audit: A structured 3-bullet mini-audit formatted as:
   • 🟢 Strengths: [1 concise sentence on what they do well based on website text]
   • 🔍 Blind Spot / Growth Opportunity: [1 concise sentence on a potential missed opportunity, e.g., missing automated lead capture, SEO meta gaps, or mobile booking]
   • 💡 Recommendation: [1 polite, actionable suggestion on how to fix it and capture more qualified clients]
4. personalized_pitch: The formatted mini-audit text above combined with a warm, polite closing offering a free digital consultation.
5. confidence_score: Confidence score between 0.0 and 1.0.
6. email_source: Origin of the email ('homepage', 'contact_page', 'mailto', 'inferred', or 'none').

### Company Information
- Name: {company_name}
- URL: {scraped_page.url}
- Title: {scraped_page.title or 'N/A'}
- Meta Description: {scraped_page.meta_description or 'N/A'}
- Heuristically Discovered Emails: {discovered_emails_str}

### Scraped Website Content
{scraped_page.clean_text}
"""
    return prompt.strip()


class GeminiLeadExtractor:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.effective_api_key
        self.model = model or settings.gemini_model
        self.client = None

        if self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Google GenAI client with key: {e}")
        else:
            try:
                # Fall back to default environment detection in Google GenAI client
                self.client = genai.Client()
            except Exception as e:
                logger.warning(f"No Google GenAI API key found: {e}")
                self.client = None

    def extract_company_info(self, company_name: str, scraped_page: ScrapedPage) -> CompanyExtractionResult:
        """
        Calls Gemini using Google GenAI SDK with structured output validation for a Custom Mini-Audit.
        """
        if not self.client:
            logger.warning(f"Google GenAI client unavailable for {company_name}. Using fallback heuristic extraction.")
            fallback_email = scraped_page.discovered_emails[0] if scraped_page.discovered_emails else None
            fallback_summary = (
                scraped_page.meta_description
                or f"{company_name} provides specialized services and solutions."
            )
            fallback_audit = (
                f"• 🟢 Strengths: Strong service focus in {scraped_page.title or company_name}.\n"
                f"• 🔍 Opportunity: Enhancing real-time digital lead intake and automated follow-ups.\n"
                f"• 💡 Recommendation: Implement an instant digital inquiry workflow to capture website visitors 24/7."
            )
            return CompanyExtractionResult(
                summary=fallback_summary,
                primary_email=fallback_email,
                custom_audit=fallback_audit,
                personalized_pitch=fallback_audit,
                confidence_score=0.6 if fallback_email else 0.4,
                email_source="heuristic_dom" if fallback_email else "none"
            )

        prompt = build_extraction_prompt(company_name, scraped_page)

        # Build 2026 Gemini model fallback chain
        candidate_models = []
        if self.model:
            candidate_models.append(self.model)
        for m in ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            if m not in candidate_models:
                candidate_models.append(m)

        for candidate_model in candidate_models:
            try:
                response = self.client.models.generate_content(
                    model=candidate_model,
                    contents=prompt,
                    config={
                        'response_mime_type': 'application/json',
                        'response_schema': CompanyExtractionResult,
                    }
                )

                # Check for parsed object or parse response text
                if hasattr(response, "parsed") and response.parsed is not None:
                    if isinstance(response.parsed, CompanyExtractionResult):
                        return response.parsed
                    elif isinstance(response.parsed, dict):
                        return CompanyExtractionResult.model_validate(response.parsed)

                if response.text:
                    return CompanyExtractionResult.model_validate_json(response.text)

            except Exception as e:
                err_msg = str(e).lower()
                logger.warning(f"Model '{candidate_model}' extraction failed for {company_name}: {e}")
                # If 404/not found or unsupported, continue to next candidate in fallback chain
                if "404" in err_msg or "not found" in err_msg or "invalid" in err_msg:
                    continue
                # For other errors, try fallback model as well
                continue

        logger.error(f"All Gemini model candidates exhausted for {company_name}. Using fallback heuristic extraction.")
        fallback_email = scraped_page.discovered_emails[0] if scraped_page.discovered_emails else None
        fallback_summary = (
            scraped_page.meta_description
            or f"{company_name} provides specialized professional services."
        )
        fallback_audit = (
            f"• 🟢 Strengths: Established brand presence and customer offerings.\n"
            f"• 🔍 Opportunity: Streamlining inbound client conversion and response velocity.\n"
            f"• 💡 Recommendation: Deploy automated client intake workflows to boost conversion rates."
        )
        return CompanyExtractionResult(
            summary=fallback_summary,
            primary_email=fallback_email,
            custom_audit=fallback_audit,
            personalized_pitch=fallback_audit,
            confidence_score=0.3,
            email_source="heuristic_fallback" if fallback_email else "none"
        )
