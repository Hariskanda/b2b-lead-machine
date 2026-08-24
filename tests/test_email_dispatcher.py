import unittest
from unittest.mock import MagicMock, patch
from b2b_leadgen.email_dispatcher import (
    build_outreach_email,
    send_single_email,
    dispatch_campaign,
    is_valid_business_email
)
from b2b_leadgen.history import sent_history
from b2b_leadgen.models import EnrichedLead


class TestEmailDispatcher(unittest.TestCase):
    def setUp(self):
        sent_history.clear_sent_history()
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
        self.invalid_artifact_lead = EnrichedLead(
            company_name="Bootstrap Lib",
            website_url="https://lib.com",
            primary_email="bootstrap@4.6.0",
            company_summary="A JS library.",
            personalized_pitch="Hi bootstrap team.",
            status="success"
        )

    def test_is_valid_business_email(self):
        valid, reason = is_valid_business_email("contact@apexplumbing.com")
        self.assertTrue(valid)

        valid, reason = is_valid_business_email("sales.dept@company.co.uk")
        self.assertTrue(valid)

        # Invalid library version artifacts and package strings
        valid, reason = is_valid_business_email("bootstrap@5.3.8")
        self.assertFalse(valid)

        valid, reason = is_valid_business_email("consent-manager@5.0.0")
        self.assertFalse(valid)

        valid, reason = is_valid_business_email("none")
        self.assertFalse(valid)

        valid, reason = is_valid_business_email("pkg@3.12.5")
        self.assertFalse(valid)
        self.assertIn("version", reason.lower())

        valid, reason = is_valid_business_email("splide@4.1.4")
        self.assertFalse(valid)

        valid, reason = is_valid_business_email("icon@2x.png")
        self.assertFalse(valid)

        valid, reason = is_valid_business_email("user@example.com")
        self.assertFalse(valid)

        valid, reason = is_valid_business_email("test@domain.com")
        self.assertFalse(valid)

    def test_build_outreach_email(self):
        subject, html_body, plain_text = build_outreach_email(
            lead=self.sample_lead,
            app_url="http://localhost:8501",
            sender_name="AI Audit & Lead Closer",
            extra_param_ignored="test"
        )

        self.assertIn("Apex Plumbing Services", subject)
        self.assertIn("complimentary", subject.lower())
        self.assertIn("Apex Plumbing Services", plain_text)
        self.assertIn("http://localhost:8501", plain_text)
        self.assertIn("http://localhost:8501", html_body)

    def test_send_single_email(self):
        mock_server = MagicMock()
        success = send_single_email(
            server=mock_server,
            sender_email="sender@gmail.com",
            recipient_email="contact@apexplumbing.com",
            subject="Quick Question",
            html_body="<p>Hello</p>",
            plain_text="Hello",
            sender_name="B2B Machine",
            extra_kwarg="ignored"
        )
        self.assertTrue(success)
        mock_server.sendmail.assert_called_once()
        args, kwargs = mock_server.sendmail.call_args
        self.assertEqual(args[0], "sender@gmail.com")
        self.assertEqual(args[1], ["contact@apexplumbing.com"])

    @patch("smtplib.SMTP")
    def test_dispatch_campaign_with_kwargs_and_callbacks(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        progress_calls = []
        def mock_progress(lead, success, msg, idx, tot):
            progress_calls.append((lead, success, msg, idx, tot))

        leads = [self.sample_lead, self.lead_without_email, self.invalid_artifact_lead]
        report = dispatch_campaign(
            leads=leads,
            sender_email="sender@gmail.com",
            app_password="mockapppassword123",
            app_url="http://localhost:8501",
            sender_name="B2B Lead Machine",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            price_usd=6.0,
            topic="Plumbing in Austin",
            delay_seconds=0.0,
            progress_callback=mock_progress,
            extra_unexpected_param="safe"
        )

        self.assertTrue(report["success"])
        self.assertEqual(report["total_leads"], 3)
        self.assertEqual(report["eligible_leads"], 2)
        self.assertEqual(report["sent_count"], 1)
        self.assertEqual(report["skipped_invalid"], 1)
        self.assertEqual(report["failed_count"], 0)
        mock_server.login.assert_called_once_with("sender@gmail.com", "mockapppassword123")
        mock_server.sendmail.assert_called_once()
        self.assertTrue(sent_history.is_email_sent("contact@apexplumbing.com"))

    @patch("smtplib.SMTP")
    def test_dispatch_campaign_deduplication(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        # Pre-record email as sent
        sent_history.record_sent_email("contact@apexplumbing.com", "Apex Plumbing", "Prior Topic")

        leads = [self.sample_lead]
        report = dispatch_campaign(
            leads=leads,
            sender_email="sender@gmail.com",
            app_password="mockapppassword123",
            delay_seconds=0.0
        )

        self.assertTrue(report["success"])
        self.assertEqual(report["sent_count"], 0)
        self.assertEqual(report["skipped_duplicates"], 1)
        mock_server.sendmail.assert_not_called()

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
