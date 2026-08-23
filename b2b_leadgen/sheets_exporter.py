import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import gspread
from google.oauth2.service_account import Credentials

from b2b_leadgen.models import EnrichedLead

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_HEADERS = [
    "Company Name",
    "Website URL",
    "Primary Email",
    "Company Summary",
    "Personalized Cold Pitch",
    "Confidence Score",
    "Email Source",
    "Status",
    "Synced At"
]


def get_gspread_client(credentials_info: Optional[Union[Dict[str, Any], str]] = None) -> gspread.Client:
    """
    Authenticates and returns a gspread Client using Streamlit secrets,
    a service account dictionary, a JSON string, or a local credentials file path.
    """
    creds_dict = None

    # 1. Check if direct dictionary passed
    if isinstance(credentials_info, dict):
        creds_dict = credentials_info

    # 2. Check if JSON string passed
    elif isinstance(credentials_info, str) and credentials_info.strip().startswith("{"):
        try:
            creds_dict = json.loads(credentials_info)
        except Exception as e:
            raise ValueError(f"Invalid JSON string provided for credentials: {e}")

    # 3. Check if file path passed
    elif isinstance(credentials_info, str) and os.path.exists(credentials_info):
        creds = Credentials.from_service_account_file(credentials_info, scopes=SCOPES)
        return gspread.authorize(creds)

    # 4. Check Streamlit secrets if running inside Streamlit
    if not creds_dict:
        try:
            import streamlit as st
            if "gcp_service_account" in st.secrets:
                creds_dict = dict(st.secrets["gcp_service_account"])
            elif "connections" in st.secrets and "gsheets" in st.secrets.connections:
                creds_dict = dict(st.secrets.connections.gsheets)
        except Exception:
            pass

    # 5. Check GOOGLE_APPLICATION_CREDENTIALS environment variable
    if not creds_dict and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if os.path.exists(env_path):
            creds = Credentials.from_service_account_file(env_path, scopes=SCOPES)
            return gspread.authorize(creds)

    # 6. Check GCP_SERVICE_ACCOUNT_JSON env var (raw JSON string)
    if not creds_dict and os.environ.get("GCP_SERVICE_ACCOUNT_JSON"):
        try:
            creds_dict = json.loads(os.environ.get("GCP_SERVICE_ACCOUNT_JSON"))
        except Exception:
            pass

    if creds_dict:
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return gspread.authorize(creds)

    raise ValueError(
        "No Google Service Account credentials found. Please provide a service account JSON "
        "or configure st.secrets['gcp_service_account']."
    )


def export_leads_to_google_sheet(
    leads: List[EnrichedLead],
    sheet_name_or_url: str,
    worksheet_title: str = "Leads",
    credentials_info: Optional[Union[Dict[str, Any], str]] = None
) -> Dict[str, Any]:
    """
    Appends a list of EnrichedLead objects into a Google Sheet in real time.
    Creates header row if the worksheet is newly created or empty.
    """
    if not leads:
        return {"success": False, "message": "No leads to export."}

    client = get_gspread_client(credentials_info)

    # Open Spreadsheet by URL or Title
    if sheet_name_or_url.startswith("http://") or sheet_name_or_url.startswith("https://"):
        spreadsheet = client.open_by_url(sheet_name_or_url)
    else:
        spreadsheet = client.open(sheet_name_or_url)

    # Get or create worksheet
    try:
        worksheet = spreadsheet.worksheet(worksheet_title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_title, rows=100, cols=len(SHEET_HEADERS))

    # Check existing data & headers
    existing_values = worksheet.get_all_values()
    if not existing_values:
        worksheet.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")

    # Format rows to append
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_to_append = []
    for lead in leads:
        rows_to_append.append([
            lead.company_name,
            lead.website_url or "",
            lead.primary_email or "",
            lead.company_summary or "",
            lead.personalized_pitch or "",
            str(lead.confidence_score or ""),
            lead.email_source or "",
            lead.status,
            current_time
        ])

    worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    return {
        "success": True,
        "spreadsheet_title": spreadsheet.title,
        "spreadsheet_url": spreadsheet.url,
        "worksheet_title": worksheet_title,
        "rows_appended": len(rows_to_append)
    }
