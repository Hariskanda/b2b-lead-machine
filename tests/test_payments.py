import unittest
from unittest.mock import MagicMock, patch
from b2b_leadgen.payments import create_checkout_session, verify_checkout_session, get_stripe_key


class TestStripePayments(unittest.TestCase):
    def test_missing_key(self):
        with self.assertRaises(ValueError):
            create_checkout_session("http://success", "http://cancel", api_key="")

    @patch("stripe.checkout.Session.create")
    def test_create_session(self, mock_stripe_create):
        mock_session = MagicMock()
        mock_session.id = "cs_test_12345"
        mock_session.url = "https://checkout.stripe.com/c/pay/cs_test_12345"
        mock_stripe_create.return_value = mock_session

        res = create_checkout_session(
            success_url="http://localhost:8501/?session_id={CHECKOUT_SESSION_ID}&payment_status=success",
            cancel_url="http://localhost:8501/?payment_status=cancelled",
            amount_usd=300,
            api_key="sk_test_mock_key_123"
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["session_id"], "cs_test_12345")
        self.assertEqual(res["checkout_url"], "https://checkout.stripe.com/c/pay/cs_test_12345")
        mock_stripe_create.assert_called_once()
        args, kwargs = mock_stripe_create.call_args
        self.assertEqual(kwargs["line_items"][0]["price_data"]["unit_amount"], 30000)

    @patch("stripe.checkout.Session.retrieve")
    def test_verify_session_paid(self, mock_stripe_retrieve):
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_stripe_retrieve.return_value = mock_session

        is_paid = verify_checkout_session("cs_test_12345", api_key="sk_test_mock_key_123")
        self.assertTrue(is_paid)

    @patch("stripe.checkout.Session.retrieve")
    def test_verify_session_unpaid(self, mock_stripe_retrieve):
        mock_session = MagicMock()
        mock_session.payment_status = "unpaid"
        mock_stripe_retrieve.return_value = mock_session

        is_paid = verify_checkout_session("cs_test_12345", api_key="sk_test_mock_key_123")
        self.assertFalse(is_paid)


if __name__ == "__main__":
    unittest.main()
