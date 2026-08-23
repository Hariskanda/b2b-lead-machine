import unittest
from unittest.mock import patch, MagicMock
from b2b_leadgen.nowpayments import (
    create_nowpayments_invoice,
    check_nowpayments_payment_status,
    check_nowpayments_invoice_status,
    get_nowpayments_headers
)


class TestNOWPayments(unittest.TestCase):
    def test_get_nowpayments_headers(self):
        headers = get_nowpayments_headers("test_key_123")
        self.assertEqual(headers["x-api-key"], "test_key_123")
        self.assertEqual(headers["Content-Type"], "application/json")

    @patch("httpx.Client.post")
    def test_create_nowpayments_invoice_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "5000000000",
            "invoice_url": "https://nowpayments.io/payment/?iid=5000000000",
            "price_amount": 6.0,
            "price_currency": "usd"
        }
        mock_post.return_value = mock_resp

        result = create_nowpayments_invoice(
            api_key="test_api_key",
            price_amount=6.0,
            price_currency="usd",
            order_description="B2B Leads Dataset Export"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["invoice_id"], "5000000000")
        self.assertEqual(result["invoice_url"], "https://nowpayments.io/payment/?iid=5000000000")

    @patch("httpx.Client.get")
    def test_check_nowpayments_invoice_status_finished(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "5527915624",
            "payment_status": "finished"
        }
        mock_get.return_value = mock_resp

        result = check_nowpayments_invoice_status(
            api_key="test_api_key",
            invoice_id="5527915624"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "finished")
        self.assertTrue(result["is_completed"])

    @patch("httpx.Client.get")
    def test_check_nowpayments_invoice_status_confirmed(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "5527915624",
            "status": "confirmed"
        }
        mock_get.return_value = mock_resp

        result = check_nowpayments_invoice_status(
            api_key="test_api_key",
            invoice_id="5527915624"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(result["is_completed"])

    def test_create_nowpayments_invoice_missing_key(self):
        result = create_nowpayments_invoice(api_key="")
        self.assertFalse(result["success"])
        self.assertIn("not configured", result["error"])


if __name__ == "__main__":
    unittest.main()
