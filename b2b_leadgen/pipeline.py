import asyncio
import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from b2b_leadgen.config import settings
from b2b_leadgen.extractor import GeminiLeadExtractor
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.scraper import AsyncWebScraper
from b2b_leadgen.search import search_company_website

logger = logging.getLogger(__name__)


def detect_company_column(header: List[str]) -> str:
    """Auto-detects the company name column from common naming patterns."""
    if not header:
        return ""
    candidates = ["company_name", "company", "company name", "name", "business", "business_name", "organization"]
    normalized_headers = {str(h).strip().lower(): str(h) for h in header}

    for candidate in candidates:
        if candidate in normalized_headers:
            return normalized_headers[candidate]

    # Default to first column if no exact match found
    return header[0]


def load_input_csv(file_path: str) -> List[LeadInput]:
    """Reads input CSV file and parses company names."""
    leads = []
    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return leads

        company_col = detect_company_column(reader.fieldnames)
        url_col = None
        for col in reader.fieldnames:
            if str(col).strip().lower() in ["website", "url", "website_url", "domain"]:
                url_col = col
                break

        for row in reader:
            company_name = str(row.get(company_col, "")).strip()
            if company_name and company_name.lower() != "nan":
                url = str(row.get(url_col, "")).strip() if url_col else None
                leads.append(LeadInput(company_name=company_name, website_url=url or None))
    return leads


def save_leads_to_csv(leads: List[EnrichedLead], output_path: str) -> None:
    """Exports enriched leads to CSV."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "company_name",
        "website_url",
        "primary_email",
        "company_summary",
        "personalized_pitch",
        "confidence_score",
        "email_source",
        "status",
        "error_message"
    ]
    with open(output_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.model_dump())


class CheckpointManager:
    """Manages persistent checkpointing to resume runs if interrupted."""
    def __init__(self, checkpoint_file: str):
        self.checkpoint_file = Path(checkpoint_file)
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

    def load_checkpoint(self) -> Dict[str, EnrichedLead]:
        if not self.checkpoint_file.exists():
            return {}
        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {name: EnrichedLead.model_validate(item) for name, item in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load checkpoint file: {e}")
            return {}

    def save_checkpoint(self, cache: Dict[str, EnrichedLead]) -> None:
        try:
            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump({k: v.model_dump() for k, v in cache.items()}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write checkpoint file: {e}")


class LeadGenPipeline:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_concurrency: Optional[int] = None,
        follow_contact_pages: Optional[bool] = None,
        use_checkpoint: bool = True,
        timeout: Optional[float] = None,
        user_agent: Optional[str] = None,
        **kwargs: Any
    ):
        concurrency = int(max_concurrency or getattr(settings, "max_concurrent_requests", 3) or 3)
        follow = bool(follow_contact_pages if follow_contact_pages is not None else getattr(settings, "follow_contact_pages", True))
        t_out = float(timeout or getattr(settings, "request_timeout_seconds", 15.0) or 15.0)
        ua = user_agent or getattr(settings, "user_agent", None)

        self.scraper = AsyncWebScraper(
            timeout=t_out,
            user_agent=ua,
            follow_contact_pages=follow,
            **kwargs
        )
        self.extractor = GeminiLeadExtractor(api_key=api_key, model=model)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.follow_contact_pages = follow
        self.use_checkpoint = use_checkpoint

    async def process_single_company(self, item: LeadInput) -> EnrichedLead:
        """Processes a single company: search URL -> scrape website -> extract via Gemini."""
        async with self.semaphore:
            company_name = item.company_name or "Unknown Company"
            url = item.website_url

            # 1. Search for website URL if not provided
            if not url:
                try:
                    url = await search_company_website(company_name)
                except Exception as e:
                    logger.error(f"Search failed for {company_name}: {e}")
                    return EnrichedLead(
                        company_name=company_name,
                        status="search_failed",
                        error_message=str(e)
                    )

            if not url:
                return EnrichedLead(
                    company_name=company_name,
                    status="no_website",
                    error_message="Could not discover official website URL"
                )

            # 2. Scrape website content
            scraped_page = None
            try:
                scraped_page = await self.scraper.scrape_url(url)
            except Exception as e:
                logger.error(f"Scraping failed for {url}: {e}")
                return EnrichedLead(
                    company_name=company_name,
                    website_url=url,
                    status="scraping_failed",
                    error_message=str(e)
                )

            if not scraped_page or not scraped_page.clean_text:
                return EnrichedLead(
                    company_name=company_name,
                    website_url=url,
                    status="empty_content",
                    error_message="Homepage returned no readable content"
                )

            # 3. Extract structured summary & email using Gemini
            try:
                extraction = await asyncio.to_thread(
                    self.extractor.extract_company_info,
                    company_name=company_name,
                    scraped_page=scraped_page
                )

                return EnrichedLead(
                    company_name=company_name,
                    website_url=url,
                    primary_email=extraction.primary_email,
                    company_summary=extraction.summary,
                    personalized_pitch=extraction.personalized_pitch,
                    confidence_score=extraction.confidence_score,
                    email_source=extraction.email_source,
                    status="success"
                )
            except Exception as e:
                logger.error(f"Extraction failed for {company_name}: {e}")
                fallback_email = scraped_page.discovered_emails[0] if scraped_page.discovered_emails else None
                return EnrichedLead(
                    company_name=company_name,
                    website_url=url,
                    primary_email=fallback_email,
                    company_summary=scraped_page.meta_description or f"{company_name} provides professional services.",
                    personalized_pitch=f"Hi {company_name} team, loved checking out your website. We help businesses in your space automate outreach and acquisition.",
                    status="success" if fallback_email else "extraction_failed",
                    error_message=str(e)
                )

    async def run_batch(
        self,
        inputs: List[LeadInput],
        output_csv_path: Optional[str] = None,
        progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
    ) -> List[EnrichedLead]:
        """Runs the enrichment pipeline over a batch of companies."""
        if not inputs:
            return []

        checkpoint_file = str(Path(output_csv_path).with_suffix(".checkpoint.json")) if output_csv_path else None
        cp_mgr = CheckpointManager(checkpoint_file) if (self.use_checkpoint and checkpoint_file) else None
        cached_results = cp_mgr.load_checkpoint() if cp_mgr else {}

        results: List[EnrichedLead] = []
        to_process: List[LeadInput] = []

        for item in inputs:
            if item.company_name in cached_results:
                results.append(cached_results[item.company_name])
            else:
                to_process.append(item)

        total_count = len(inputs)
        processed_count = len(results)

        if results and progress_callback:
            for r in results:
                try:
                    progress_callback(r, processed_count, total_count)
                except Exception:
                    pass

        if not to_process:
            return results

        # Process remaining items concurrently
        tasks = [self.process_single_company(item) for item in to_process]

        for future in asyncio.as_completed(tasks):
            try:
                lead = await future
            except Exception as e:
                logger.error(f"Unexpected task exception in pipeline batch: {e}")
                lead = EnrichedLead(company_name="Unknown Lead", status="failed", error_message=str(e))

            results.append(lead)
            processed_count += 1

            if cp_mgr:
                cached_results[lead.company_name] = lead
                cp_mgr.save_checkpoint(cached_results)

            if progress_callback:
                try:
                    progress_callback(lead, processed_count, total_count)
                except Exception:
                    pass

        if output_csv_path:
            try:
                save_leads_to_csv(results, output_csv_path)
            except Exception as e:
                logger.error(f"Failed to write output CSV {output_csv_path}: {e}")

        return results
