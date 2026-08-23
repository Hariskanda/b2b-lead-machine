import asyncio
import unittest
from b2b_leadgen.pipeline import load_input_csv, detect_company_column
from b2b_leadgen.models import CompanyExtractionResult, EnrichedLead
from b2b_leadgen.scraper import AsyncWebScraper, filter_valid_emails
from b2b_leadgen.search import is_valid_company_domain, search_company_website


class TestLeadGenComponents(unittest.TestCase):
    def test_csv_loader(self):
        leads = load_input_csv("data/sample_companies.csv")
        self.assertEqual(len(leads), 3)
        names = [l.company_name for l in leads]
        self.assertIn("Stripe", names)
        self.assertIn("Notion", names)
        self.assertIn("Figma", names)

    def test_domain_validator(self):
        self.assertFalse(is_valid_company_domain("https://www.linkedin.com/company/stripe"))
        self.assertFalse(is_valid_company_domain("https://en.wikipedia.org/wiki/Stripe_(company)"))
        self.assertTrue(is_valid_company_domain("https://stripe.com"))
        self.assertTrue(is_valid_company_domain("https://www.figma.com"))

    def test_email_filtering(self):
        raw = {"support@stripe.com", "hero-banner@2x.png", "test@example.com", "info@figma.com"}
        filtered = filter_valid_emails(raw)
        self.assertIn("support@stripe.com", filtered)
        self.assertIn("info@figma.com", filtered)
        self.assertNotIn("hero-banner@2x.png", filtered)
        self.assertNotIn("test@example.com", filtered)

    def test_model_validation(self):
        data = {
            "summary": "Stripe provides financial infrastructure and payment processing software for internet businesses.",
            "primary_email": "support@stripe.com",
            "personalized_pitch": "Hi Stripe team, I love your developer-first payment APIs. We build AI integrations that help automate billing workflows.",
            "confidence_score": 0.95,
            "email_source": "homepage"
        }
        res = CompanyExtractionResult.model_validate(data)
        self.assertEqual(res.primary_email, "support@stripe.com")
        self.assertEqual(res.confidence_score, 0.95)
        self.assertIn("billing workflows", res.personalized_pitch)

    def test_search_and_scrape(self):
        async def run_test():
            url = await search_company_website("Stripe")
            self.assertIsNotNone(url)
            self.assertTrue("stripe.com" in url)
            
            scraper = AsyncWebScraper()
            page = await scraper.scrape_company_site(url)
            self.assertIsNotNone(page)
            self.assertTrue(len(page.clean_text) > 50)
            
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
