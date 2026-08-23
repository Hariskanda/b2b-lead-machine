import unittest
from b2b_leadgen.upi_checkout import generate_upi_uri, generate_upi_qr_code, validate_utr


class TestUPICheckout(unittest.TestCase):
    def test_upi_uri_generation(self):
        uri = generate_upi_uri(
            upi_id="9019525230@fam",
            payee_name="B2BLeadMachine",
            amount_inr=499,
            transaction_note="LeadExport499"
        )
        self.assertTrue(uri.startswith("upi://pay?"))
        self.assertIn("pa=9019525230%40fam", uri)
        self.assertIn("pn=B2BLeadMachine", uri)
        self.assertIn("am=499", uri)
        self.assertIn("cu=INR", uri)
        self.assertIn("tn=LeadExport499", uri)

    def test_upi_qr_code_generation(self):
        img, buf, uri = generate_upi_qr_code(
            upi_id="9019525230@fam",
            payee_name="B2BLeadMachine",
            amount_inr=499
        )
        self.assertIsNotNone(img)
        self.assertGreater(buf.getbuffer().nbytes, 100)
        self.assertTrue(uri.startswith("upi://pay?"))
        self.assertIn("pa=9019525230%40fam", uri)

    def test_utr_validation(self):
        # Valid 12-digit UTRs
        self.assertTrue(validate_utr("423589123456"))
        self.assertTrue(validate_utr("100000000000"))
        self.assertTrue(validate_utr(" 987654321012 "))

        # Invalid UTRs
        self.assertFalse(validate_utr(""))
        self.assertFalse(validate_utr("12345"))  # Too short
        self.assertFalse(validate_utr("1234567890123"))  # Too long (13 digits)
        self.assertFalse(validate_utr("12345678901A"))  # Contains character
        self.assertFalse(validate_utr("abcdefghijkl"))  # All letters


if __name__ == "__main__":
    unittest.main()
