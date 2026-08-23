import logging
import re
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Common directory, social, and aggregator domains to filter out when seeking official company websites
EXCLUDED_DOMAINS = {
    "linkedin.com", "www.linkedin.com",
    "crunchbase.com", "www.crunchbase.com",
    "wikipedia.org", "en.wikipedia.org", "www.wikipedia.org",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "youtube.com", "www.youtube.com",
    "glassdoor.com", "www.glassdoor.com",
    "zoominfo.com", "www.zoominfo.com",
    "bloomberg.com", "www.bloomberg.com",
    "pitchbook.com", "www.pitchbook.com",
    "yelp.com", "www.yelp.com",
    "reddit.com", "www.reddit.com",
    "github.com", "www.github.com",
    "medium.com", "www.medium.com",
    "g2.com", "www.g2.com",
    "capterra.com", "www.capterra.com",
    "trustpilot.com", "www.trustpilot.com",
    "craft.co", "www.craft.co"
}


def is_valid_company_domain(url: str) -> bool:
    """Checks if a URL belongs to a potential company website and not an excluded directory/social site."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc:
            return False
        # Remove port if present
        host = netloc.split(":")[0]
        # Check against excluded domains or subdomains of excluded domains
        for excluded in EXCLUDED_DOMAINS:
            if host == excluded or host.endswith(f".{excluded}"):
                return False
        return True
    except Exception:
        return False


def clean_base_url(url: str) -> str:
    """Returns the base domain URL (scheme + netloc)."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    except Exception:
        return url


async def search_company_website(company_name: str) -> Optional[str]:
    """
    Finds the official website URL for a given company name using DuckDuckGo search
    with fallback heuristic domain discovery.
    """
    clean_name = company_name.strip()
    if not clean_name:
        return None

    # Step 1: DuckDuckGo Search via ddgs / duckduckgo_search library
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        try:
            ddgs = DDGS(verify=False)
        except TypeError:
            ddgs = DDGS()
        query = f'"{clean_name}" official website'
        results = list(ddgs.text(query, max_results=6))
        for res in results:
            link = res.get("href") or res.get("link") or res.get("url")
            if link and is_valid_company_domain(link):
                return clean_base_url(link)
    except Exception as e:
        logger.warning(f"DuckDuckGo search error for '{clean_name}': {e}. Trying fallback search...")

    # Step 2: Fallback query without quotes
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        try:
            ddgs = DDGS(verify=False)
        except TypeError:
            ddgs = DDGS()
        query = f'{clean_name} software company homepage'
        results = list(ddgs.text(query, max_results=6))
        for res in results:
            link = res.get("href") or res.get("link") or res.get("url")
            if link and is_valid_company_domain(link):
                return clean_base_url(link)
    except Exception as e:
        logger.warning(f"Fallback search error for '{clean_name}': {e}")

    # Step 3: Heuristic direct domain guess (e.g. Stripe -> https://stripe.com)
    sanitized_slug = re.sub(r'[^a-zA-Z0-9]', '', clean_name.lower())
    if sanitized_slug:
        return f"https://www.{sanitized_slug}.com"

    return None
