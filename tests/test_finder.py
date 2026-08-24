import unittest
from unittest.mock import patch
from b2b_leadgen.finder import is_directory_domain, clean_company_name, discover_leads_by_keyword


class TestLeadFinder(unittest.TestCase):
    def test_directory_filter(self):
        self.assertTrue(is_directory_domain("https://www.yelp.com/biz/radiant-plumbing-austin"))
        self.assertTrue(is_directory_domain("https://www.yellowpages.com/austin-tx/plumbers"))
        self.assertTrue(is_directory_domain("https://www.angi.com/companylist/austin/plumbing.htm"))
        # Test required blacklist domains
        self.assertTrue(is_directory_domain("https://www.glassdoor.com/Reviews/company-reviews.htm"))
        self.assertTrue(is_directory_domain("https://www.olx.in/services/plumber"))
        self.assertTrue(is_directory_domain("https://in.jooble.org/jobs-plumbing"))
        self.assertTrue(is_directory_domain("https://www.linkedin.com/company/apex-plumbing"))
        self.assertTrue(is_directory_domain("https://www.justdial.com/Austin/Plumbers"))
        self.assertTrue(is_directory_domain("https://dir.indiamart.com/contractor.html"))
        self.assertTrue(is_directory_domain("https://www.facebook.com/pages/plumbing"))
        self.assertTrue(is_directory_domain("https://www.instagram.com/plumbingco"))
        self.assertTrue(is_directory_domain("https://www.salaryexpert.com/salary/plumber"))
        self.assertFalse(is_directory_domain("https://radiantplumbing.com"))
        self.assertFalse(is_directory_domain("https://www.clarkekentplumbing.com"))

    def test_clean_company_name(self):
        title = "Radiant Plumbing & Air Conditioning | Austin HVAC & Plumber"
        url = "https://radiantplumbing.com"
        name = clean_company_name(title, url)
        self.assertEqual(name, "Radiant Plumbing & Air Conditioning")

    def test_clean_company_name_seo_headline(self):
        title = "Plumbers Near Me | L & P Plumbing LLC | Trusted Plumbers Serving Austin, TX"
        url = "https://lnpplumbing.com"
        name = clean_company_name(title, url)
        self.assertEqual(name, "L & P Plumbing LLC")

    def test_keyword_discovery_mocked(self):
        mock_results = [
            {"href": "https://www.yelp.com/biz/plumber", "title": "Top 10 Plumbers - Yelp"},
            {"href": "https://radiantplumbing.com", "title": "Radiant Plumbing & Air Conditioning"},
            {"href": "https://lnpplumbing.com", "title": "Plumbers Near Me | L & P Plumbing LLC"}
        ]
        with patch("ddgs.DDGS.text", return_value=mock_results):
            leads = discover_leads_by_keyword("Plumbing in Austin", max_results=5)
            self.assertGreater(len(leads), 0)
            self.assertLessEqual(len(leads), 5)
            for lead in leads:
                self.assertFalse("yelp.com" in lead.website_url)


if __name__ == "__main__":
    unittest.main()
