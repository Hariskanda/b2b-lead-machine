import asyncio
from datetime import datetime, timedelta
import logging
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional

from b2b_leadgen.config import settings
from b2b_leadgen.email_dispatcher import dispatch_campaign
from b2b_leadgen.finder import discover_leads_by_keyword
from b2b_leadgen.history import sent_history, CURATED_NICHES
from b2b_leadgen.models import EnrichedLead
from b2b_leadgen.pipeline import LeadGenPipeline

logger = logging.getLogger(__name__)


class AutopilotEngine:
    _instance: Optional["AutopilotEngine"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "AutopilotEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AutopilotEngine, cls).__new__(cls)
                cls._instance._init_engine()
            return cls._instance

    def _init_engine(self) -> None:
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Engine Telemetry
        self.total_cycles: int = 0
        self.total_leads_discovered: int = 0
        self.total_emails_sent: int = 0
        self.total_duplicates_skipped: int = 0
        self.current_niche: str = ""
        self.started_at: Optional[datetime] = None
        self.last_cycle_at: Optional[datetime] = None
        self.logs: List[Dict[str, Any]] = []

        # Default Settings
        self.batch_size: int = 5
        self.interval_seconds: int = 120
        self.run_continuously: bool = True
        self.duration_hours: float = 24.0
        self.custom_niches: List[str] = []

    def log(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"timestamp": timestamp, "level": level, "message": message}
        self.logs.append(entry)
        if len(self.logs) > 200:
            self.logs.pop(0)
        logger.info(f"[AUTOPILOT] {message}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "total_cycles": self.total_cycles,
            "total_leads_discovered": self.total_leads_discovered,
            "total_emails_sent": self.total_emails_sent,
            "total_duplicates_skipped": self.total_duplicates_skipped,
            "current_niche": self.current_niche,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "last_cycle_at": self.last_cycle_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_cycle_at else None,
            "batch_size": self.batch_size,
            "interval_seconds": self.interval_seconds,
            "run_continuously": self.run_continuously,
            "logs": list(reversed(self.logs[-50:]))
        }

    def start(
        self,
        gemini_api_key: Optional[str],
        smtp_user: str,
        smtp_password: str,
        app_url: str,
        sender_name: str = "B2B Lead Machine",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        price_usd: float = 6.0,
        batch_size: int = 5,
        interval_seconds: int = 120,
        run_continuously: bool = True,
        duration_hours: float = 24.0,
        custom_niches: Optional[List[str]] = None
    ) -> bool:
        with self._lock:
            if self.is_running:
                return True

            self.batch_size = max(2, min(batch_size, 30))
            self.interval_seconds = max(15, interval_seconds)
            self.run_continuously = run_continuously
            self.duration_hours = max(0.1, duration_hours)
            self.custom_niches = custom_niches or []

            self._stop_event.clear()
            self.is_running = True
            self.started_at = datetime.now()

            self._thread = threading.Thread(
                target=self._run_loop,
                kwargs={
                    "gemini_api_key": gemini_api_key,
                    "smtp_user": smtp_user,
                    "smtp_password": smtp_password,
                    "app_url": app_url,
                    "sender_name": sender_name,
                    "smtp_host": smtp_host,
                    "smtp_port": smtp_port,
                    "price_usd": price_usd
                },
                daemon=True,
                name="AutopilotOutboundWorker"
            )
            self._thread.start()
            self.log(f"🚀 Autopilot Engine launched! Batch size: {self.batch_size}, Interval: {self.interval_seconds}s, Topic Rotation Active.")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self.is_running:
                return True

            self._stop_event.set()
            self.is_running = False
            self.log("🛑 Autopilot Engine received stop signal. Stopping...")
            return True

    def _run_loop(
        self,
        gemini_api_key: Optional[str],
        smtp_user: str,
        smtp_password: str,
        app_url: str,
        sender_name: str,
        smtp_host: str,
        smtp_port: int,
        price_usd: float = 6.0
    ) -> None:
        start_time = datetime.now()
        max_end_time = start_time + timedelta(hours=self.duration_hours) if not self.run_continuously else None

        while not self._stop_event.is_set():
            if max_end_time and datetime.now() >= max_end_time:
                self.log(f"⏰ Duration limit ({self.duration_hours}h) reached. Autopilot shutting down.")
                break

            self.total_cycles += 1
            self.last_cycle_at = datetime.now()

            # 🎯 1. Dynamic Topic Rotation: Pick fresh, non-repeating niche
            niche = sent_history.get_next_rotating_niche(self.custom_niches)
            self.current_niche = niche

            self.log(f"🔄 Cycle #{self.total_cycles} started: Fresh niche '{niche}' (target: {self.batch_size} leads)")

            try:
                # 2. Discover Leads
                discovered = discover_leads_by_keyword(niche, max_results=self.batch_size)
                if not discovered:
                    self.log(f"⚠️ No leads found for '{niche}'. Moving to next cycle.", level="WARNING")
                else:
                    self.total_leads_discovered += len(discovered)
                    self.log(f"✅ Discovered {len(discovered)} company domains. Running AI enrichment...")

                    # 3. Enrich Leads via Pipeline
                    effective_autopilot_model = getattr(settings, "gemini_model", "gemini-2.5-flash") or "gemini-2.5-flash"
                    pipeline = LeadGenPipeline(
                        api_key=gemini_api_key,
                        model=effective_autopilot_model,
                        max_concurrency=2,
                        follow_contact_pages=True,
                        use_checkpoint=False
                    )

                    enriched_leads: List[EnrichedLead] = asyncio.run(
                        pipeline.run_batch(inputs=discovered, output_csv_path=None)
                    )

                    emails_found = [l for l in enriched_leads if l.primary_email and "@" in l.primary_email]

                    # 4. Filter already-sent emails to prevent duplicates
                    unsent_leads, skipped_leads = sent_history.filter_leads_for_dispatch(emails_found)
                    if skipped_leads:
                        self.total_duplicates_skipped += len(skipped_leads)
                        self.log(f"🛡️ Deduplication filter: Skipped {len(skipped_leads)} already-contacted leads.")

                    self.log(f"🎯 AI Enrichment complete: Found {len(unsent_leads)} fresh new verified contacts.")

                    # 5. Dispatch Email Campaign with crypto/USD pricing CTA and record sent history
                    if unsent_leads and smtp_user and smtp_password:
                        self.log(f"📨 Dispatching value-first mini-audits to {len(unsent_leads)} recipients from {smtp_user} (Topic: '{niche}')...")
                        report = dispatch_campaign(
                            leads=unsent_leads,
                            sender_email=smtp_user,
                            app_password=smtp_password,
                            app_url=app_url,
                            sender_name=sender_name,
                            smtp_host=smtp_host,
                            smtp_port=smtp_port,
                            price_usd=price_usd,
                            topic=niche,
                            delay_seconds=5.0,
                            stop_event=self._stop_event
                        )
                        sent = report.get("sent_count", 0)
                        self.total_emails_sent += sent
                        self.log(f"🎉 Sent {sent}/{len(unsent_leads)} emails successfully in Cycle #{self.total_cycles}.")
                    elif not unsent_leads:
                        self.log("ℹ️ No new un-emailed contacts discovered for this niche batch.")
                    else:
                        self.log("⚠️ SMTP credentials not provided; skipped sending.", level="WARNING")

            except Exception as e:
                self.log(f"❌ Error during cycle execution: {e}", level="ERROR")

            # Interval delay check (responsive to stop event)
            self.log(f"⏳ Sleeping for {self.interval_seconds} seconds before next cycle...")
            for _ in range(int(self.interval_seconds)):
                if self._stop_event.is_set():
                    break
                time.sleep(1.0)

        self.is_running = False
        self.log("🏁 Autopilot Engine stopped.")


# Global engine instance
autopilot_engine = AutopilotEngine()
