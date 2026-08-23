import logging
import re
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from b2b_leadgen.config import settings
from b2b_leadgen.models import ScrapedPage

logger = logging.getLogger(__name__)

# Regex for detecting email addresses in HTML / text
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

# Common false positive patterns or dummy domains in emails
DISALLOWED_EMAIL_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.map', '.woff', '.ttf')
DISALLOWED_DOMAINS = {'example.com', 'domain.com', 'yourcompany.com', 'email.com', 'test.com', 'sentry.io', 'wixpress.com'}
JUNK_PREFIXES = {'bootstrap', 'splide', 'jquery', 'swiper', 'vue', 'react', 'core-js', 'lodash', 'popper', 'fontawesome', 'webpack', 'babel', 'angular', 'chartjs', 'select2', 'moment', 'axios', 'sentry', 'dummy', 'user', 'username', 'test'}


def filter_valid_emails(raw_emails: Set[str]) -> List[str]:
    """Filters out image filenames, library artifacts (bootstrap@4.6.0), dummy emails, and invalid formats."""
    valid = []
    for email in raw_emails:
        email = email.strip().lower().rstrip('.,;:/')
        if not email or '@' not in email or email.count('@') != 1:
            continue
        user, domain = email.split('@')
        if user in JUNK_PREFIXES:
            continue
        if re.match(r"^v?\d+(\.\d+)+$", domain):
            continue
        if any(email.endswith(ext) for ext in DISALLOWED_EMAIL_EXTS):
            continue
        if domain in DISALLOWED_DOMAINS:
            continue
        if len(email) < 6 or len(email) > 80:
            continue
        tld = domain.split('.')[-1]
        if not tld.isalpha() or len(tld) < 2:
            continue
        if email not in valid:
            valid.append(email)
    return valid


def clean_html_to_text(soup: BeautifulSoup) -> str:
    """Removes irrelevant tags (scripts, styles, etc.) and extracts readable text."""
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    # Get text with whitespace separator
    text = soup.get_text(separator=" ", strip=True)
    # Collapse multiple spaces and newlines
    text = re.sub(r'\s+', ' ', text)
    return text[:10000]  # Cap at 10k chars to maintain cost efficiency


def extract_metadata(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    """Extracts title and meta description from page HTML."""
    title = None
    meta_desc = None

    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    return title, meta_desc


class AsyncWebScraper:
    def __init__(
        self,
        timeout: Optional[float] = None,
        follow_contact_pages: bool = True,
        max_subpages: int = 2
    ):
        self.timeout = timeout or settings.scraping_timeout_seconds
        self.follow_contact_pages = follow_contact_pages
        self.max_subpages = max_subpages
        self.headers = {
            "User-Agent": settings.scraping_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def scrape_url(self, url: str) -> ScrapedPage:
        """Fetches and parses the given URL, optionally discovering contact subpages."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                verify=False
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code} when fetching {url}")
                    return ScrapedPage(url=url, status_code=resp.status_code)

                soup = BeautifulSoup(resp.text, "html.parser")
                title, meta_desc = extract_metadata(soup)
                clean_text = clean_html_to_text(soup)

                # Heuristic DOM Email Search
                discovered_emails = set(EMAIL_REGEX.findall(resp.text))
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("mailto:"):
                        raw_email = href.replace("mailto:", "").split("?")[0].strip()
                        if raw_email:
                            discovered_emails.add(raw_email)

                # Subpage crawling for Contact / About pages if requested
                if self.follow_contact_pages:
                    subpage_emails = await self._crawl_subpages(client, url, soup)
                    discovered_emails.update(subpage_emails)

                valid_emails = filter_valid_emails(discovered_emails)

                return ScrapedPage(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    title=title,
                    meta_description=meta_desc,
                    clean_text=clean_text,
                    discovered_emails=valid_emails
                )

        except Exception as e:
            logger.warning(f"Error scraping {url}: {e}")
            return ScrapedPage(url=url, status_code=0)

    async def _crawl_subpages(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        soup: BeautifulSoup
    ) -> Set[str]:
        """Finds contact/about links and fetches their content to discover more emails."""
        emails: Set[str] = set()
        subpage_urls: Set[str] = set()

        contact_keywords = ["contact", "about", "team", "reach", "support", "get-in-touch"]

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            link_text = a.get_text().lower()

            if any(k in href.lower() or k in link_text for k in contact_keywords):
                full_url = urljoin(base_url, href)
                # Ensure same origin
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    subpage_urls.add(full_url)
                    if len(subpage_urls) >= self.max_subpages:
                        break

        for sub_url in subpage_urls:
            try:
                resp = await client.get(sub_url)
                if resp.status_code == 200:
                    found = EMAIL_REGEX.findall(resp.text)
                    emails.update(found)
                    sub_soup = BeautifulSoup(resp.text, "html.parser")
                    for a in sub_soup.find_all("a", href=True):
                        if a["href"].startswith("mailto:"):
                            em = a["href"].replace("mailto:", "").split("?")[0].strip()
                            if em:
                                emails.add(em)
            except Exception as e:
                logger.debug(f"Could not scrape subpage {sub_url}: {e}")

        return emails
