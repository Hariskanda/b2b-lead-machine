from typing import Optional, List
from pydantic import BaseModel, Field


class LeadInput(BaseModel):
    """Input record representing a target company."""
    company_name: str
    website_url: Optional[str] = None


class CompanyExtractionResult(BaseModel):
    """
    Schema passed directly to Google GenAI for structured JSON extraction.
    """
    summary: str = Field(
        description="A strictly 1-sentence concise summary explaining what the company does and its core value proposition."
    )
    primary_email: Optional[str] = Field(
        default=None,
        description="The primary contact, sales, support, or general inquiry email address found. Set to null if no valid email is present."
    )
    personalized_pitch: str = Field(
        description="A personalized, high-converting 2-sentence icebreaker cold email tailored specifically to this company, referencing their service offering and offering a value-add collaboration or efficiency boost."
    )
    confidence_score: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0 regarding extraction accuracy."
    )
    email_source: Optional[str] = Field(
        default=None,
        description="The origin of the extracted email ('homepage', 'contact_page', 'mailto', 'inferred', or 'none')."
    )


class ScrapedPage(BaseModel):
    """Internal model for scraped webpage content and extracted signals."""
    url: str
    status_code: int
    title: Optional[str] = None
    meta_description: Optional[str] = None
    clean_text: str = ""
    discovered_emails: List[str] = Field(default_factory=list)
    contact_links: List[str] = Field(default_factory=list)


class EnrichedLead(BaseModel):
    """Final enriched lead representation exported to CSV/JSON."""
    company_name: str
    website_url: Optional[str] = None
    primary_email: Optional[str] = None
    company_summary: Optional[str] = None
    personalized_pitch: Optional[str] = None
    confidence_score: Optional[float] = None
    email_source: Optional[str] = None
    status: str = "success"  # success, no_website, scraping_failed, extraction_failed
    error_message: Optional[str] = None
