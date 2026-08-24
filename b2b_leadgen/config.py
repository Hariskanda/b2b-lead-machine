import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Admin Portal & Download Unlock Security
    admin_password: str = Field(
        default="admin123",
        validation_alias="ADMIN_PASSWORD"
    )
    unlock_code: str = Field(
        default="4990",
        validation_alias="UNLOCK_CODE"
    )
    whatsapp_number: str = Field(
        default="919019525230",
        validation_alias="WHATSAPP_NUMBER"
    )

    # NOWPayments Crypto Gateway Configuration ($6 USD)
    nowpayments_api_key: Optional[str] = Field(
        default=None,
        validation_alias="NOWPAYMENTS_API_KEY"
    )
    crypto_price_usd: float = Field(
        default=6.0,
        validation_alias="CRYPTO_PRICE_USD"
    )

    # API Keys (Supports GEMINI_API_KEY or fallback GOOGLE_API_KEY)
    gemini_api_key: Optional[str] = Field(
        default=None,
        validation_alias="GEMINI_API_KEY"
    )
    google_api_key_fallback: Optional[str] = Field(
        default=None,
        validation_alias="GOOGLE_API_KEY"
    )

    # App URL (default: http://localhost:8501)
    app_url: str = Field(
        default="http://localhost:8501",
        validation_alias="APP_URL"
    )

    # Gmail SMTP Configuration for Autopilot Email Dispatcher
    smtp_host: str = Field(
        default="smtp.gmail.com",
        validation_alias="SMTP_HOST"
    )
    smtp_port: int = Field(
        default=587,
        validation_alias="SMTP_PORT"
    )
    smtp_user: str = Field(
        default="",
        validation_alias="SMTP_USER"
    )
    smtp_password: str = Field(
        default="",
        validation_alias="SMTP_PASSWORD"
    )
    smtp_app_password: str = Field(
        default="",
        validation_alias="SMTP_APP_PASSWORD"
    )
    sender_name: str = Field(
        default="B2B Lead Machine",
        validation_alias="SENDER_NAME"
    )

    # Stripe Payment Configuration
    stripe_secret_key: Optional[str] = Field(
        default=None,
        validation_alias="STRIPE_SECRET_KEY"
    )
    lead_package_price_usd: int = Field(
        default=300,
        validation_alias="LEAD_PACKAGE_PRICE_USD"
    )

    # UPI Payment Configuration (₹499)
    upi_id: str = Field(
        default="9019525230@fam",
        validation_alias="UPI_ID"
    )
    upi_payee_name: str = Field(
        default="B2BLeadMachine",
        validation_alias="UPI_PAYEE_NAME"
    )
    upi_amount_inr: float = Field(
        default=499.0,
        validation_alias="UPI_AMOUNT_INR"
    )

    # Gemini Model configuration (2026 Standards with auto-fallback)
    gemini_model: str = Field(
        default="gemini-3.5-flash",
        validation_alias="GEMINI_MODEL"
    )

    # Concurrency and Rate Limiting
    max_concurrent_requests: int = Field(
        default=3,
        validation_alias="MAX_CONCURRENT_REQUESTS"
    )
    request_timeout_seconds: int = Field(
        default=15,
        validation_alias="REQUEST_TIMEOUT_SECONDS"
    )

    # Scraping Options
    follow_contact_pages: bool = Field(
        default=True,
        validation_alias="FOLLOW_CONTACT_PAGES"
    )
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        validation_alias="USER_AGENT"
    )

    @property
    def effective_nowpayments_key(self) -> Optional[str]:
        return self.nowpayments_api_key or os.environ.get("NOWPAYMENTS_API_KEY")

    @property
    def effective_api_key(self) -> Optional[str]:
        return self.gemini_api_key or self.google_api_key_fallback or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    @property
    def effective_app_url(self) -> str:
        return self.app_url or os.environ.get("APP_URL") or "http://localhost:8501"

    @property
    def effective_stripe_key(self) -> Optional[str]:
        return self.stripe_secret_key or os.environ.get("STRIPE_SECRET_KEY")

    @property
    def effective_smtp_user(self) -> str:
        return self.smtp_user or os.environ.get("SMTP_USER") or os.environ.get("GMAIL_ADDRESS") or ""

    @property
    def effective_smtp_password(self) -> str:
        return self.smtp_password or self.smtp_app_password or os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_APP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD") or ""


# Global singleton settings instance
settings = Settings()
