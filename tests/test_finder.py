import unittest
from unittest.mock import patch
from b2b_leadgen.finder import is_directory_domain, clean_company_name, discover_leads_by_keyword


class TestLeadFinder(unittest.TestCase):
    def test_directory_filter(self):
        self.assertTrue(is_directory_domain("https://www.yelp.com/biz/radiant-plumbing-austin"))
        self.assertTrue(is_directory_domain("https://www.yellowpages.com/austin-tx/plumbers"))
        self.assertTrue(is_directory_domain("https://www.angi.com/companylist/austin/plumbing.htm"))
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
            self.assertEqual(len(leads), 2)
            self.assertEqual(leads[0].company_name, "Radiant Plumbing & Air Conditioning")
            self.assertEqual(leads[1].company_name, "L & P Plumbing LLC")


if __name__ == "__main__":
    unittest.main()
