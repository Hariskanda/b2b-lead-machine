import unittest
from b2b_leadgen.pdf_generator import (
    generate_company_audit_pdf,
    generate_batch_audit_bundle_pdf
)


class TestPDFGenerator(unittest.TestCase):
    def test_generate_single_company_audit_pdf(self):
        pdf_bytes = generate_company_audit_pdf(
            company_name="Apex Plumbing Services",
            website_url="https://apexplumbing.com",
            primary_email="contact@apexplumbing.com",
            summary="Apex Plumbing is a premier commercial contractor in Austin, TX.",
            custom_audit="• 🟢 Strengths: Rapid emergency dispatch.\n• 🔍 Opportunity: Online intake gaps.\n• 💡 Recommendation: Deploy instant web capture.",
            agency_name="Test Agency",
            agency_website="https://testagency.com"
        )
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        # PDF magic header check
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_generate_batch_audit_bundle_pdf(self):
        leads = [
            {
                "company_name": "Apex Plumbing",
                "website_url": "https://apex.com",
                "primary_email": "contact@apex.com",
                "company_summary": "Commercial Plumbing",
                "custom_audit": "• 🟢 Strengths: Good brand."
            },
            {
                "company_name": "Beta Electric",
                "website_url": "https://beta.com",
                "primary_email": "info@beta.com",
                "company_summary": "Commercial Electrical",
                "custom_audit": "• 🟢 Strengths: Fast dispatch."
            }
        ]
        bundle_bytes = generate_batch_audit_bundle_pdf(
            leads=leads,
            agency_name="Test Agency",
            agency_website="https://testagency.com"
        )
        self.assertIsInstance(bundle_bytes, bytes)
        self.assertGreater(len(bundle_bytes), 1000)
        self.assertTrue(bundle_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
