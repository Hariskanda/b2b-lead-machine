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
DISALLOWED_EMAIL_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js'}
DISALLOWED_DOMAINS = {'example.com', 'domain.com', 'yourcompany.com', 'email.com', 'test.com', 'sentry.io'}


def filter_valid_emails(raw_emails: Set[str]) -> List[str]:
    """Filters out image filenames, dummy emails, and invalid formats."""
    valid = []
    for email in raw_emails:
        email = email.strip().lower().rstrip('.,;')
        if not email or '@' not in email:
            continue
        # Check extensions
        if any(email.endswith(ext) for ext in DISALLOWED_EMAIL_EXTS):
            continue
        domain = email.split('@')[-1]
        if domain in DISALLOWED_DOMAINS:
            continue
        if len(email) < 6 or len(email) > 80:
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

    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if desc_tag and desc_tag.get("content"):
        meta_desc = desc_tag["content"].strip()

    return title, meta_desc


def find_contact_links(base_url: str, soup: BeautifulSoup) -> List[str]:
    """Finds internal contact, about, or support page URLs from homepage navigation."""
    contact_keywords = ["contact", "about", "team", "support", "touch", "reach", "company"]
    discovered_urls = []
    base_domain = urlparse(base_url).netloc.lower()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        link_text = (a_tag.get_text() or "").lower()

        # Check mailto: links separately
        if href.startswith("mailto:"):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Ensure link stays on the same domain
        if parsed.netloc.lower() != base_domain:
            continue

        url_path = parsed.path.lower()
        if any(keyword in url_path or keyword in link_text for keyword in contact_keywords):
            if full_url not in discovered_urls and full_url != base_url:
                discovered_urls.append(full_url)
                if len(discovered_urls) >= 3:
                    break

    return discovered_urls


class AsyncWebScraper:
    def __init__(
        self,
        timeout: int = settings.request_timeout_seconds,
        user_agent: str = settings.user_agent,
        follow_contact_pages: bool = settings.follow_contact_pages
    ):
        self.timeout = timeout
        self.follow_contact_pages = follow_contact_pages
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1"
        }

    async def fetch_page(self, client: httpx.AsyncClient, url: str) -> Optional[ScrapedPage]:
        """Fetches and parses a single webpage."""
        try:
            response = await client.get(url, headers=self.headers, timeout=self.timeout, follow_redirects=True)
            if response.status_code >= 400:
                logger.warning(f"HTTP {response.status_code} fetching {url}")
                return None

            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")

            # Extract raw mailto: emails
            raw_emails = set()
            for mailto in soup.select('a[href^="mailto:"]'):
                href = mailto.get("href", "")
                email = href.replace("mailto:", "").split("?")[0].strip()
                if email:
                    raw_emails.add(email)

            # Extract regex emails from text
            regex_matches = EMAIL_REGEX.findall(html_content)
            raw_emails.update(regex_matches)

            valid_emails = filter_valid_emails(raw_emails)
            clean_text = clean_html_to_text(soup)
            title, meta_desc = extract_metadata(soup)
            contact_links = find_contact_links(url, soup)

            return ScrapedPage(
                url=str(response.url),
                status_code=response.status_code,
                title=title,
                meta_description=meta_desc,
                clean_text=clean_text,
                discovered_emails=valid_emails,
                contact_links=contact_links
            )
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return None

    async def scrape_company_site(self, base_url: str) -> Optional[ScrapedPage]:
        """
        Scrapes the company homepage, and if no contact email is found,
        crawls discovered contact/about subpages.
        """
        async with httpx.AsyncClient(verify=False) as client:
            homepage_data = await self.fetch_page(client, base_url)
            if not homepage_data:
                return None

            # If emails found or subpage following disabled, return homepage data
            if homepage_data.discovered_emails or not self.follow_contact_pages:
                return homepage_data

            # Follow top contact/about page to search for emails
            for contact_url in homepage_data.contact_links:
                logger.info(f"Checking subpage for contact details: {contact_url}")
                subpage_data = await self.fetch_page(client, contact_url)
                if subpage_data:
                    # Merge discovered emails and append text
                    if subpage_data.discovered_emails:
                        homepage_data.discovered_emails.extend(subpage_data.discovered_emails)
                    homepage_data.clean_text += f"\n--- Contact Page ({contact_url}) ---\n" + subpage_data.clean_text[:4000]
                    if homepage_data.discovered_emails:
                        break  # Found email, no need to crawl more

            # Deduplicate emails
            homepage_data.discovered_emails = list(dict.fromkeys(homepage_data.discovered_emails))
            return homepage_data
