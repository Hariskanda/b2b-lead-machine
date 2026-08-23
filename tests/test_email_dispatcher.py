import unittest
from unittest.mock import MagicMock, patch
from b2b_leadgen.email_dispatcher import build_outreach_email, send_single_email, dispatch_campaign
from b2b_leadgen.models import EnrichedLead


class TestEmailDispatcher(unittest.TestCase):
    def setUp(self):
        self.sample_lead = EnrichedLead(
            company_name="Apex Plumbing Services",
            website_url="https://apexplumbing.com",
            primary_email="contact@apexplumbing.com",
            company_summary="Apex Plumbing provides commercial emergency plumbing in Austin.",
            personalized_pitch="Hi Apex team, love your 24/7 commercial plumbing focus. We build AI automation for contractor client intake.",
            confidence_score=0.9,
            email_source="homepage",
            status="success"
        )
        self.lead_without_email = EnrichedLead(
            company_name="No Email Plumbing",
            website_url="https://noemail.com",
            primary_email=None,
            company_summary="A plumbing company.",
            personalized_pitch="Hi team, nice website.",
            status="success"
        )

    def test_build_outreach_email(self):
        subject, html_body, plain_text = build_outreach_email(
            lead=self.sample_lead,
            app_url="http://localhost:8501",
            sender_name="B2B Lead Machine"
        )

        self.assertIn("Apex Plumbing Services", subject)
        self.assertIn("AI automation for contractor client intake", plain_text)
        self.assertIn("http://localhost:8501", plain_text)
        self.assertIn("₹499", plain_text)
        self.assertIn("http://localhost:8501", html_body)
        self.assertIn("AI automation for contractor client intake", html_body)

    def test_send_single_email(self):
        mock_server = MagicMock()
        success = send_single_email(
            server=mock_server,
            sender_email="sender@gmail.com",
            recipient_email="contact@apexplumbing.com",
            subject="Quick Question",
            html_body="<p>Hello</p>",
            plain_text="Hello",
            sender_name="B2B Machine"
        )
        self.assertTrue(success)
        mock_server.sendmail.assert_called_once()
        args, kwargs = mock_server.sendmail.call_args
        self.assertEqual(args[0], "sender@gmail.com")
        self.assertEqual(args[1], ["contact@apexplumbing.com"])

    @patch("smtplib.SMTP")
    def test_dispatch_campaign(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        leads = [self.sample_lead, self.lead_without_email]
        report = dispatch_campaign(
            leads=leads,
            sender_email="sender@gmail.com",
            app_password="mockapppassword123",
            app_url="http://localhost:8501",
            delay_seconds=0.0
        )

        self.assertTrue(report["success"])
        self.assertEqual(report["total_leads"], 2)
        self.assertEqual(report["eligible_leads"], 1)
        self.assertEqual(report["sent_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        mock_server.login.assert_called_once_with("sender@gmail.com", "mockapppassword123")
        mock_server.sendmail.assert_called_once()

    @patch("b2b_leadgen.email_dispatcher.settings")
    def test_dispatch_missing_credentials(self, mock_settings):
        mock_settings.effective_smtp_user = ""
        mock_settings.effective_smtp_password = ""
        report = dispatch_campaign(
            leads=[self.sample_lead],
            sender_email="",
            app_password=""
        )
        self.assertFalse(report["success"])
        self.assertIn("required", report["message"])


if __name__ == "__main__":
    unittest.main()
