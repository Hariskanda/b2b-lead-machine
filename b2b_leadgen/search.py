import logging
import re
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Strict blacklist patterns: directories, aggregators, job boards, social networks, and review sites
BLACKLIST_DOMAINS = [
    'glassdoor', 'olx', 'jooble', 'linkedin', 'yelp', 'justdial',
    'indiamart', 'facebook', 'instagram', 'salaryexpert', 'indeed',
    'yellowpages', 'angi', 'angieslist', 'thumbtack', 'houzz', 'homeadvisor',
    'bbb', 'mapquest', 'superpages', 'expertise', 'nextdoor',
    'twitter', 'x', 'youtube', 'wikipedia', 'google', 'bing',
    'yahoo', 'tripadvisor', 'clutch', 'upcity', 'themanifest',
    'porch', 'homeguide', 'topratedlocal', 'birdeye', 'plumbersup',
    'chamberofcommerce', 'citysearch', 'manta', 'loc8nearme',
    'capterra', 'g2', 'trustpilot', 'craft', 'zoominfo',
    'bloomberg', 'pitchbook', 'reddit', 'github', 'medium'
]


def is_blacklisted_domain(url: str) -> bool:
    """
    Checks if a URL belongs to a blacklisted aggregator, social, job board, or directory site.
    Uses precise domain label matching to prevent false positive substring matches
    (e.g., radiantplumbing.com containing 'bing').
    """
    if not url or not isinstance(url, str):
        return True
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().split(":")[0]
        if not host:
            host = url.lower().split("/")[0].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return False

        host_parts = host.split(".")
        for b in BLACKLIST_DOMAINS:
            # Matches exact domain label (e.g., 'glassdoor' in ['glassdoor', 'com'])
            if b in host_parts:
                return True
            # Matches exact host or subdomains (e.g. 'in.jooble.org', 'dir.indiamart.com')
            if host == b or host.startswith(b + ".") or (f".{b}." in host):
                return True
        return False
    except Exception:
        return False


def is_valid_company_domain(url: str) -> bool:
    """Checks if a URL belongs to a potential company website and not an excluded directory/social site."""
    if is_blacklisted_domain(url):
        return False
    try:
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower().split(":")[0]
        return bool(netloc and "." in netloc)
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
        logger.warning(f"DuckDuckGo search failed for {clean_name}: {e}")

    # Step 2: Fallback Heuristic Domain Construction
    sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', clean_name).lower()
    if sanitized_name:
        fallback_url = f"https://www.{sanitized_name}.com"
        if is_valid_company_domain(fallback_url):
            return fallback_url

    return None
