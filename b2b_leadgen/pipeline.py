import asyncio
import csv
import json
import logging
import os
from pathlib import Path
from typing import Callable, List, Optional

from b2b_leadgen.config import settings
from b2b_leadgen.extractor import GeminiLeadExtractor
from b2b_leadgen.models import EnrichedLead, LeadInput
from b2b_leadgen.scraper import AsyncWebScraper
from b2b_leadgen.search import search_company_website

logger = logging.getLogger(__name__)


def detect_company_column(header: List[str]) -> str:
    """Auto-detects the company name column from common naming patterns."""
    candidates = ["company_name", "company", "company name", "name", "business", "business_name", "organization"]
    normalized_headers = {h.strip().lower(): h for h in header}

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
            if col.strip().lower() in ["website", "url", "website_url", "domain"]:
                url_col = col
                break

        for row in reader:
            company_name = row.get(company_col, "").strip()
            if company_name:
                url = row.get(url_col, "").strip() if url_col else None
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

    def load_checkpoint(self) -> dict[str, EnrichedLead]:
        if not self.checkpoint_file.exists():
            return {}
        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {name: EnrichedLead.model_validate(item) for name, item in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load checkpoint file: {e}")
            return {}

    def save_checkpoint(self, cache: dict[str, EnrichedLead]) -> None:
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
        max_concurrency: int = settings.max_concurrent_requests,
        use_checkpoint: bool = True
    ):
        self.scraper = AsyncWebScraper()
        self.extractor = GeminiLeadExtractor(api_key=api_key, model=model)
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.use_checkpoint = use_checkpoint

    async def process_single_company(self, item: LeadInput) -> EnrichedLead:
        """Processes a single company: search URL -> scrape website -> extract via Gemini."""
        async with self.semaphore:
            company_name = item.company_name
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
            try:
                scraped_page = await self.scraper.scrape_company_site(url)
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
                # Run synchronous SDK call in thread pool to avoid blocking async loop
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
                return EnrichedLead(
                    company_name=company_name,
                    website_url=url,
                    status="extraction_failed",
                    error_message=str(e)
                )

    async def run_batch(
        self,
        inputs: List[LeadInput],
        output_csv_path: Optional[str] = None,
        progress_callback: Optional[Callable[[EnrichedLead, int, int], None]] = None
    ) -> List[EnrichedLead]:
        """Runs the enrichment pipeline over a batch of companies."""
        checkpoint_file = str(Path(output_csv_path).with_suffix(".checkpoint.json")) if output_csv_path else None
        cp_mgr = CheckpointManager(checkpoint_file) if (self.use_checkpoint and checkpoint_file) else None
        cached_results = cp_mgr.load_checkpoint() if cp_mgr else {}

        results: List[EnrichedLead] = []
        tasks = []
        total = len(inputs)

        for idx, item in enumerate(inputs, start=1):
            if item.company_name in cached_results:
                lead = cached_results[item.company_name]
                results.append(lead)
                if progress_callback:
                    progress_callback(lead, idx, total)
                continue

            async def process_and_track(input_item: LeadInput, current_idx: int):
                lead_result = await self.process_single_company(input_item)
                if cp_mgr:
                    cached_results[input_item.company_name] = lead_result
                    cp_mgr.save_checkpoint(cached_results)
                if progress_callback:
                    progress_callback(lead_result, current_idx, total)
                return lead_result

            tasks.append(process_and_track(item, idx))

        if tasks:
            new_results = await asyncio.gather(*tasks)
            results.extend(new_results)

        # Save final output if path specified
        if output_csv_path:
            save_leads_to_csv(results, output_csv_path)

        return results
