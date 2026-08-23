import os
import tempfile
import unittest
from b2b_leadgen.history import SentHistoryManager
from b2b_leadgen.models import EnrichedLead


class TestSentHistory(unittest.TestCase):
    def setUp(self):
        self.tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp_file.close()
        self.manager = SentHistoryManager(file_path=self.tmp_file.name)
        self.manager.clear_sent_history()

    def tearDown(self):
        if os.path.exists(self.tmp_file.name):
            os.remove(self.tmp_file.name)

    def test_record_and_check_sent_email(self):
        self.assertFalse(self.manager.is_email_sent("john@example.com"))

        self.manager.record_sent_email(
            email="John@Example.com",
            company_name="Acme Corp",
            topic="Plumbing in Austin",
            pitch="Great service."
        )

        self.assertTrue(self.manager.is_email_sent("john@example.com"))
        self.assertTrue(self.manager.is_email_sent("JOHN@EXAMPLE.COM "))
        self.assertEqual(self.manager.get_sent_count(), 1)

        records = self.manager.get_all_sent_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["email"], "john@example.com")
        self.assertEqual(records[0]["company_name"], "Acme Corp")
        self.assertEqual(records[0]["topic"], "Plumbing in Austin")

    def test_filter_leads_for_dispatch(self):
        self.manager.record_sent_email("contact@used.com", company_name="Used Inc", topic="Roofing")

        lead1 = EnrichedLead(company_name="Fresh Co", primary_email="fresh@new.com", status="success")
        lead2 = EnrichedLead(company_name="Used Co", primary_email="contact@used.com", status="success")
        lead3 = EnrichedLead(company_name="No Email Co", primary_email=None, status="success")

        unsent, duplicate = self.manager.filter_leads_for_dispatch([lead1, lead2, lead3])
        self.assertEqual(len(unsent), 2)
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0].primary_email, "contact@used.com")

    def test_topic_rotation_and_record(self):
        custom = ["Niche A", "Niche B"]
        first = self.manager.get_next_rotating_niche(custom_niches=custom)
        self.assertIn(first, custom)
        self.assertTrue(self.manager.is_topic_used(first))

        second = self.manager.get_next_rotating_niche(custom_niches=custom)
        self.assertIn(second, custom)
        # Should pick the other unused niche
        self.assertNotEqual(first, second)

    def test_clear_sent_history(self):
        self.manager.record_sent_email("test@example.com", "Test Co")
        self.assertEqual(self.manager.get_sent_count(), 1)

        success = self.manager.clear_sent_history()
        self.assertTrue(success)
        self.assertEqual(self.manager.get_sent_count(), 0)
        self.assertFalse(self.manager.is_email_sent("test@example.com"))


if __name__ == "__main__":
    unittest.main()
