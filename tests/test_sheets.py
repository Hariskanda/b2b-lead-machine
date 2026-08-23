import unittest
from unittest.mock import MagicMock, patch
from b2b_leadgen.models import EnrichedLead
from b2b_leadgen.sheets_exporter import export_leads_to_google_sheet, SHEET_HEADERS


class TestGoogleSheetsExporter(unittest.TestCase):
    def setUp(self):
        self.sample_leads = [
            EnrichedLead(
                company_name="Austin Radiant Plumbing",
                website_url="https://radiantplumbing.com",
                primary_email="contact@radiantplumbing.com",
                company_summary="Top rated Austin plumbing and HVAC service contractor.",
                personalized_pitch="Hi team, love your HVAC services. We automate local contractor lead intake.",
                confidence_score=0.9,
                email_source="homepage",
                status="success"
            )
        ]

    def test_empty_leads(self):
        res = export_leads_to_google_sheet([], "My Sheet")
        self.assertFalse(res["success"])

    @patch("b2b_leadgen.sheets_exporter.get_gspread_client")
    def test_successful_export(self, mock_get_client):
        mock_client = MagicMock()
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.title = "B2B Leads Test"
        mock_spreadsheet.url = "https://docs.google.com/spreadsheets/d/test-id/edit"
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = []  # simulate empty worksheet

        mock_spreadsheet.worksheet.return_value = mock_worksheet
        mock_client.open.return_value = mock_spreadsheet
        mock_get_client.return_value = mock_client

        res = export_leads_to_google_sheet(
            leads=self.sample_leads,
            sheet_name_or_url="B2B Leads Test",
            worksheet_title="Leads",
            credentials_info={"type": "service_account"}
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["rows_appended"], 1)
        mock_worksheet.append_row.assert_called_once_with(SHEET_HEADERS, value_input_option="USER_ENTERED")
        mock_worksheet.append_rows.assert_called_once()


if __name__ == "__main__":
    unittest.main()
