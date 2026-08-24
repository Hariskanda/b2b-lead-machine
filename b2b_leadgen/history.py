import json
import logging
import os
import random
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Persistent global sent history database in project root
DEFAULT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sent_emails_global.json")
LEGACY_HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sent_history.json")

# 30+ High-intent B2B service industries
INDUSTRIES = [
    "HVAC and air conditioning contractors",
    "Commercial roofing companies",
    "Plumbing and emergency drain services",
    "Commercial cleaning and janitorial services",
    "Solar panel installation and energy solutions",
    "Electrical contractors and engineering",
    "Dental clinics and orthodontic practices",
    "Accounting and certified CPA firms",
    "Landscaping and commercial grounds maintenance",
    "General construction and remodeling contractors",
    "IT support and managed IT service providers",
    "Auto repair and fleet maintenance centers",
    "Real estate agencies and property management",
    "Corporate law and legal practices",
    "Commercial pest control exterminators",
    "Corporate catering and event planners",
    "Painting and commercial drywall contractors",
    "Commercial flooring and tile installation",
    "Security systems and commercial access control",
    "Moving and commercial storage companies",
    "Pool construction and commercial maintenance",
    "Chiropractic and physical therapy clinics",
    "Veterinary clinics and animal hospitals",
    "Architecture and structural design firms",
    "Digital marketing and SEO agencies",
    "Commercial insurance brokerages",
    "Concrete and paving contractors",
    "Commercial fencing and gate installers",
    "Commercial locksmiths and master key specialists",
    "Waste management and dumpster rental services"
]

# 30+ Major Metros
METROS = [
    "Dallas, TX", "Austin, TX", "Houston, TX", "San Antonio, TX",
    "Miami, FL", "Orlando, FL", "Tampa, FL", "Jacksonville, FL",
    "Atlanta, GA", "Phoenix, AZ", "Chicago, IL", "San Diego, CA",
    "Los Angeles, CA", "San Francisco, CA", "Seattle, WA", "Denver, CO",
    "Boston, MA", "Charlotte, NC", "Raleigh, NC", "Philadelphia, PA",
    "Nashville, TN", "Las Vegas, NV", "Portland, OR", "Indianapolis, IN",
    "Columbus, OH", "Minneapolis, MN", "Detroit, MI", "Salt Lake City, UT",
    "Kansas City, MO", "Baltimore, MD"
]

# Curated evergreen starter niches
CURATED_NICHES = [
    "HVAC contractors in Dallas, TX",
    "Commercial roofing companies in Miami, FL",
    "Plumbing contractors in Austin, TX",
    "Digital marketing agencies in Atlanta, GA",
    "Dental clinics in Phoenix, AZ",
    "Commercial cleaning services in Chicago, IL",
    "Solar panel installation in San Diego, CA",
    "Electrical contractors in Seattle, WA",
    "Accounting firms in Denver, CO",
    "Landscaping companies in Orlando, FL",
    "General contractors in Houston, TX",
    "IT support and managed service providers in Boston, MA",
    "Auto repair and detailing in Charlotte, NC",
    "Real estate brokerages in Tampa, FL",
    "Legal and law firms in Philadelphia, PA",
    "Catering and event planning in Nashville, TN"
]


def _extract_email_from_obj(lead: Any) -> Optional[str]:
    """Helper to extract primary_email from either EnrichedLead object or dictionary."""
    if lead is None:
        return None
    if isinstance(lead, dict):
        return lead.get("primary_email")
    return getattr(lead, "primary_email", None)


class SentHistoryManager:
    _instance: Optional["SentHistoryManager"] = None
    _lock = threading.Lock()

    def __new__(cls, file_path: Optional[str] = None) -> "SentHistoryManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SentHistoryManager, cls).__new__(cls)
                cls._instance._init_manager(file_path or DEFAULT_HISTORY_FILE)
            return cls._instance

    def _init_manager(self, file_path: str) -> None:
        self.file_path = file_path
        self._rw_lock = threading.Lock()
        self._sent_emails: Dict[str, Dict[str, Any]] = {}
        self._used_topics: Set[str] = set()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        self._sent_emails = {}
        self._used_topics = set()

        files_to_check = [self.file_path, LEGACY_HISTORY_FILE]
        for fp in files_to_check:
            if os.path.exists(fp):
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for k, v in data.get("sent_emails", {}).items():
                            clean_k = str(k).lower().strip()
                            if clean_k and clean_k not in self._sent_emails:
                                self._sent_emails[clean_k] = v
                        for t in data.get("used_topics", []):
                            if t:
                                self._used_topics.add(str(t).strip())
                except Exception as e:
                    logger.error(f"Error loading sent history from {fp}: {e}")

    def _save_to_disk(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            data = {
                "sent_emails": self._sent_emails,
                "used_topics": list(self._used_topics),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            tmp_path = f"{self.file_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.file_path)
        except Exception as e:
            logger.error(f"Error saving sent history to {self.file_path}: {e}")

    def is_email_sent(self, email: Optional[str]) -> bool:
        """Returns True if the email has already been dispatched to in past cycles."""
        if not email or not isinstance(email, str) or "@" not in email:
            return False
        clean_email = email.lower().strip()
        with self._rw_lock:
            return clean_email in self._sent_emails

    def record_sent_email(
        self,
        email: str,
        company_name: str = "",
        topic: str = "",
        pitch: str = ""
    ) -> None:
        """Records a successfully dispatched email into the persistent database."""
        if not email or not isinstance(email, str) or "@" not in email:
            return
        clean_email = email.lower().strip()
        with self._rw_lock:
            self._sent_emails[clean_email] = {
                "email": clean_email,
                "company_name": str(company_name or "Unknown"),
                "topic": str(topic or "General Outreach"),
                "pitch": str(pitch or ""),
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if topic:
                self._used_topics.add(str(topic).strip())
            self._save_to_disk()

    def record_used_topic(self, topic: str) -> None:
        """Marks a topic / niche as used so it is not immediately repeated."""
        if not topic:
            return
        with self._rw_lock:
            self._used_topics.add(str(topic).strip())
            self._save_to_disk()

    def is_topic_used(self, topic: str) -> bool:
        """Checks if a topic has been used."""
        if not topic:
            return False
        with self._rw_lock:
            return str(topic).strip() in self._used_topics

    def get_all_sent_records(self) -> List[Dict[str, Any]]:
        """Returns all recorded sent emails sorted by latest date."""
        with self._rw_lock:
            records = list(self._sent_emails.values())
            records.sort(key=lambda r: r.get("sent_at", ""), reverse=True)
            return records

    def get_sent_count(self) -> int:
        """Returns count of unique emails sent."""
        with self._rw_lock:
            return len(self._sent_emails)

    def get_used_topics(self) -> List[str]:
        """Returns list of used topics."""
        with self._rw_lock:
            return list(self._used_topics)

    def remove_sent_email(self, email: str) -> bool:
        """Removes a single email from the sent history / do-not-contact list."""
        if not email:
            return False
        clean_email = email.lower().strip()
        with self._rw_lock:
            if clean_email in self._sent_emails:
                del self._sent_emails[clean_email]
                self._save_to_disk()
                return True
            return False

    def add_to_do_not_contact(self, email: str, company_name: str = "Manual Block", reason: str = "Admin Added") -> bool:
        """Manually adds an email to the permanent do-not-contact list."""
        if not email or "@" not in email:
            return False
        clean_email = email.lower().strip()
        with self._rw_lock:
            self._sent_emails[clean_email] = {
                "email": clean_email,
                "company_name": str(company_name),
                "topic": f"Do-Not-Contact ({reason})",
                "pitch": "Blocked by Admin",
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._save_to_disk()
            return True

    def clear_sent_history(self) -> bool:
        """Resets the sent history database and wipes persistent storage."""
        with self._rw_lock:
            self._sent_emails = {}
            self._used_topics = set()
            try:
                if os.path.exists(self.file_path):
                    os.remove(self.file_path)
                if os.path.exists(LEGACY_HISTORY_FILE):
                    os.remove(LEGACY_HISTORY_FILE)
                return True
            except Exception as e:
                logger.error(f"Error removing history file {self.file_path}: {e}")
                return False

    def filter_leads_for_dispatch(
        self,
        leads: List[Any]
    ) -> Tuple[List[Any], List[Any]]:
        """
        Splits leads into (unsent_leads, already_sent_leads) based on email history.
        Safely supports EnrichedLead instances, dataclasses, or dicts.
        """
        unsent: List[Any] = []
        already_sent: List[Any] = []

        with self._rw_lock:
            for lead in leads:
                raw_email = _extract_email_from_obj(lead)
                email = str(raw_email).lower().strip() if raw_email else ""
                if email and email in self._sent_emails:
                    already_sent.append(lead)
                else:
                    unsent.append(lead)

        return unsent, already_sent

    def get_next_rotating_niche(self, custom_niches: Optional[List[str]] = None) -> str:
        """
        Selects a fresh, unused niche from custom niches or 900+ industry x metro combinations.
        Marks it as used in history.
        """
        with self._rw_lock:
            # 1. Custom niches priority
            if custom_niches:
                unused_custom = [n for n in custom_niches if str(n).strip() not in self._used_topics]
                if unused_custom:
                    chosen = str(random.choice(unused_custom)).strip()
                    self._used_topics.add(chosen)
                    self._save_to_disk()
                    return chosen
                # If all custom niches used, pick random custom
                chosen = str(random.choice(custom_niches)).strip()
                return chosen

            # 2. Build full matrix of 900+ combinations
            all_combinations = [f"{ind} in {metro}" for ind in INDUSTRIES for metro in METROS]
            unused_combinations = [c for c in all_combinations if c not in self._used_topics]

            if unused_combinations:
                chosen = random.choice(unused_combinations)
                self._used_topics.add(chosen)
                self._save_to_disk()
                return chosen

            # 3. If all 900+ combinations exhausted, reset topics and pick fresh
            logger.info("All 900+ niches exhausted! Resetting used topics cycle.")
            self._used_topics.clear()
            chosen = random.choice(all_combinations)
            self._used_topics.add(chosen)
            self._save_to_disk()
            return chosen


# Global singleton instance
sent_history = SentHistoryManager()
