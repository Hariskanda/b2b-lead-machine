# Streamlit Community Cloud Deployment Guide

This guide details how to deploy **B2B Lead Machine** to **Streamlit Community Cloud** for free 24/7 hosting.

---

## 1. Push to GitHub

The remote origin is linked to:
`https://github.com/Hariskanda/b2b-lead-machine.git`

To push your committed code from your terminal, run:

```bash
git push -u origin main
```

*(If prompted for credentials, enter your GitHub Username and a [GitHub Personal Access Token](https://github.com/settings/tokens) as your password).*

---

## 2. 1-Click Deploy on Streamlit Community Cloud

1. Go to **[share.streamlit.io](https://share.streamlit.io/)** and sign in with your GitHub account.
2. Click **"New app"** (or **"Create app"**).
3. Select your repository:
   - **Repository:** `Hariskanda/b2b-lead-machine`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **"Advanced settings..."** ➔ **"Secrets"**.
5. Paste your production secrets into the Secrets text area (see below).
6. Click **"Save"** and **"Deploy!"**.

---

## 3. Production Secrets Template for Streamlit Cloud

Paste this configuration into the **Secrets** box on Streamlit Cloud (replace with your actual keys):

```toml
# Google Gemini API Key
GEMINI_API_KEY = "your_gemini_api_key_here"

# App Public URL on Streamlit Cloud
APP_URL = "https://your-app-name.streamlit.app"

# Gmail SMTP Configuration for Autopilot Outbound
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your_email@gmail.com"
SMTP_PASSWORD = "your_16_digit_gmail_app_password"
SENDER_NAME = "B2B Lead Machine"

# UPI Payment Gateway (₹499)
UPI_ID = "9019525230@fam"
UPI_PAYEE_NAME = "B2B Lead Machine"
UPI_AMOUNT_INR = 499
```

---

## 4. Live Features Active in Production

- **Autonomous Keyword Discovery**: Discover verified business leads by niche and location.
- **Gemini 1.5 Flash Enrichment**: Scrapes homepage and contact pages, extracts contact emails, generates summaries, and writes personalized 2-sentence cold outreach pitches.
- **Autopilot Email Dispatcher**: Dispatches outreach campaigns with a call-to-action link back to the cloud app.
- **₹499 Dynamic UPI QR Code**: Renders your custom FamPay QR code (`9019525230@fam`) and unlocks the CSV download upon entering a 12-digit UTR transaction ID.
- **Google Sheets Sync**: Real-time export to Google Sheets.
