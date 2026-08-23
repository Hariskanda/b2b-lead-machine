import asyncio
import unittest
from bs4 import BeautifulSoup
from b2b_leadgen.models import CompanyExtractionResult, ScrapedPage
from b2b_leadgen.scraper import filter_valid_emails, clean_html_to_text, AsyncWebScraper
from b2b_leadgen.search import is_valid_company_domain, clean_base_url, search_company_website


class TestLeadGenComponents(unittest.TestCase):
    def test_domain_filtering(self):
        self.assertFalse(is_valid_company_domain("https://www.linkedin.com/company/stripe"))
        self.assertFalse(is_valid_company_domain("https://twitter.com/stripe"))
        self.assertFalse(is_valid_company_domain("https://en.wikipedia.org/wiki/Stripe"))
        self.assertTrue(is_valid_company_domain("https://stripe.com"))
        self.assertTrue(is_valid_company_domain("https://www.shopify.com"))

    def test_clean_base_url(self):
        self.assertEqual(clean_base_url("https://stripe.com/docs/api?ref=google"), "https://stripe.com")
        self.assertEqual(clean_base_url("https://www.shopify.com/pricing#plans"), "https://www.shopify.com")

    def test_email_filtering(self):
        raw_emails = {"support@stripe.com", "logo@company.png", "test@example.com", "sales@shop.com."}
        filtered = filter_valid_emails(raw_emails)
        self.assertIn("support@stripe.com", filtered)
        self.assertIn("sales@shop.com", filtered)
        self.assertNotIn("logo@company.png", filtered)
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

    def test_scraper_clean_html(self):
        html = "<html><head><title>Test</title></head><body><h1>Welcome</h1><p>Contact us at info@testbiz.com</p><script>var x = 1;</script></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        text = clean_html_to_text(soup)
        self.assertIn("Welcome", text)
        self.assertIn("Contact us at info@testbiz.com", text)
        self.assertNotIn("var x = 1", text)


if __name__ == "__main__":
    unittest.main()
