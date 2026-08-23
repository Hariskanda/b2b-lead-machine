import time
import unittest
from unittest.mock import patch, MagicMock
from b2b_leadgen.autopilot import AutopilotEngine, CURATED_NICHES


class TestAutopilotEngine(unittest.TestCase):
    def setUp(self):
        self.engine = AutopilotEngine()
        self.engine.stop()

    def tearDown(self):
        self.engine.stop()

    def test_singleton_instance(self):
        engine2 = AutopilotEngine()
        self.assertIs(self.engine, engine2)

    def test_curated_niches_populated(self):
        self.assertGreater(len(CURATED_NICHES), 5)
        self.assertTrue(any("Dallas" in n for n in CURATED_NICHES))

    def test_start_and_stop(self):
        status_before = self.engine.get_status()
        self.assertFalse(status_before["is_running"])

        with patch("b2b_leadgen.autopilot.AutopilotEngine._run_loop"):
            self.engine.start(
                gemini_api_key=None,
                smtp_user="test@gmail.com",
                smtp_password="app_password",
                app_url="http://localhost:8501",
                batch_size=3,
                interval_seconds=30,
                run_continuously=True
            )
            status_running = self.engine.get_status()
            self.assertTrue(status_running["is_running"])
            self.assertEqual(status_running["batch_size"], 3)

            self.engine.stop()
            status_stopped = self.engine.get_status()
            self.assertFalse(status_stopped["is_running"])


if __name__ == "__main__":
    unittest.main()
