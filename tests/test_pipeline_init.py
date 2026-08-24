import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from b2b_leadgen.pipeline import LeadGenPipeline
from b2b_leadgen.scraper import AsyncWebScraper
from b2b_leadgen.models import LeadInput, EnrichedLead


class TestPipelineInitialization(unittest.TestCase):
    def test_scraper_init_with_kwargs(self):
        scraper = AsyncWebScraper(
            timeout=20.0,
            user_agent="CustomTestUA/1.0",
            follow_contact_pages=False,
            max_subpages=5,
            extra_unexpected_param="safe"
        )
        self.assertEqual(scraper.timeout, 20.0)
        self.assertEqual(scraper.headers["User-Agent"], "CustomTestUA/1.0")
        self.assertFalse(scraper.follow_contact_pages)
        self.assertEqual(scraper.max_subpages, 5)

    def test_pipeline_init_with_kwargs(self):
        pipeline = LeadGenPipeline(
            api_key="test_api_key",
            model="gemini-1.5-flash",
            max_concurrency=4,
            follow_contact_pages=False,
            use_checkpoint=False,
            timeout=25.0,
            user_agent="PipelineUA/2.0",
            extra_param="safe_to_ignore"
        )
        self.assertIsNotNone(pipeline.scraper)
        self.assertIsNotNone(pipeline.extractor)
        self.assertEqual(pipeline.use_checkpoint, False)
        self.assertFalse(pipeline.follow_contact_pages)

    @patch.object(AsyncWebScraper, "scrape_url", new_callable=AsyncMock)
    def test_scraper_alias(self, mock_scrape_url):
        mock_scrape_url.return_value = MagicMock(clean_text="test", discovered_emails=[])
        scraper = AsyncWebScraper()
        result = asyncio.run(scraper.scrape_company_site("https://example.com"))
        mock_scrape_url.assert_called_once_with("https://example.com")


if __name__ == "__main__":
    unittest.main()
