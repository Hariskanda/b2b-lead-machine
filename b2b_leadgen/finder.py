import logging
import re
from typing import List, Set
from urllib.parse import urlparse

from b2b_leadgen.models import LeadInput
from b2b_leadgen.search import clean_base_url, is_valid_company_domain

logger = logging.getLogger(__name__)

# Extended list of local directories, lead aggregators, and non-company domains to skip
DIRECTORY_DOMAINS = {
    "yelp.com", "www.yelp.com",
    "yellowpages.com", "www.yellowpages.com",
    "angi.com", "www.angi.com",
    "angieslist.com", "www.angieslist.com",
    "thumbtack.com", "www.thumbtack.com",
    "houzz.com", "www.houzz.com",
    "homeadvisor.com", "www.homeadvisor.com",
    "bbb.org", "www.bbb.org",
    "mapquest.com", "www.mapquest.com",
    "superpages.com", "www.superpages.com",
    "expertise.com", "www.expertise.com",
    "nextdoor.com", "www.nextdoor.com",
    "indeed.com", "www.indeed.com",
    "glassdoor.com", "www.glassdoor.com",
    "linkedin.com", "www.linkedin.com",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "youtube.com", "www.youtube.com",
    "wikipedia.org", "www.wikipedia.org",
    "google.com", "www.google.com",
    "bing.com", "www.bing.com",
    "yahoo.com", "www.yahoo.com",
    "tripadvisor.com", "www.tripadvisor.com",
    "clutch.co", "www.clutch.co",
    "upcity.com", "www.upcity.com",
    "themanifest.com", "www.themanifest.com",
    "porch.com", "www.porch.com",
    "homeguide.com", "www.homeguide.com",
    "topratedlocal.com", "www.topratedlocal.com",
    "birdeye.com", "www.birdeye.com",
    "plumbersup.com", "www.plumbersup.com",
    "chamberofcommerce.com", "www.chamberofcommerce.com",
    "citysearch.com", "www.citysearch.com",
    "manta.com", "www.manta.com",
    "loc8nearme.com", "www.loc8nearme.com"
}

GENERIC_PHRASES = [
    r'^\d+\s+best\b.*',
    r'^top\s+\d+\b.*',
    r'^best\b.*',
    r'^plumbers\s+near\s+me\b.*',
    r'^emergency\s+plumber\b.*',
    r'^plumbing\s+repairs\b.*',
    r'^find\s+a\b.*',
    r'^hire\s+the\b.*',
    r'^affordable\b.*',
    r'^reliable\b.*'
]


def is_directory_domain(url: str) -> bool:
    """Checks if a URL belongs to a directory, aggregator, or non-business site."""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().split(":")[0]
        if not host:
            return True
        for d in DIRECTORY_DOMAINS:
            if host == d or host.endswith(f".{d}"):
                return True
        return not is_valid_company_domain(url)
    except Exception:
        return True


def is_generic_title(segment: str) -> bool:
    """Checks if a title segment is a generic SEO headline rather than a company name."""
    s = segment.strip().lower()
    for pattern in GENERIC_PHRASES:
        if re.search(pattern, s):
            return True
    return False


def clean_company_name(raw_title: str, url: str) -> str:
    """
    Cleans a search result title into a concise company name.
    """
    domain = urlparse(url).netloc.replace("www.", "").split(".")[0]
    domain_fallback = domain.capitalize()

    if not raw_title:
        return domain_fallback

    # Split by standard title separators
    parts = [p.strip() for p in re.split(r'\s+[|\-–—:•]\s+', raw_title) if p.strip()]

    candidate = None
    for part in parts:
        cleaned = re.sub(r'(?i)\b(official site|homepage|welcome to|reviews|services|contact us|24/7|free estimates)\b', '', part).strip(" .,-–|:")
        if len(cleaned) >= 3 and not is_generic_title(cleaned):
            candidate = cleaned
            break

    if not candidate:
        candidate = domain_fallback

    return candidate.strip(" .,-–|:")


def discover_leads_by_keyword(query: str, max_results: int = 20) -> List[LeadInput]:
    """
    Searches DuckDuckGo for businesses matching a query and extracts clean company names and URLs.
    Filters out directory and aggregator sites (Yelp, Angie, YellowPages, etc.).
    """
    leads: List[LeadInput] = []
    seen_domains: Set[str] = set()

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        try:
            ddgs = DDGS(verify=False)
        except TypeError:
            ddgs = DDGS()

        search_queries = [
            query,
            f"{query} contractors",
            f"{query} company website",
            f"{query} services"
        ]

        for q in search_queries:
            if len(leads) >= max_results:
                break

            try:
                results = list(ddgs.text(q, max_results=30))
                for item in results:
                    url = item.get("href") or item.get("link") or item.get("url")
                    title = item.get("title") or ""

                    if not url or is_directory_domain(url):
                        continue

                    base_url = clean_base_url(url)
                    parsed_domain = urlparse(base_url).netloc.lower()

                    if parsed_domain in seen_domains:
                        continue

                    company_name = clean_company_name(title, base_url)
                    if company_name and len(company_name) >= 2:
                        seen_domains.add(parsed_domain)
                        leads.append(LeadInput(
                            company_name=company_name,
                            website_url=base_url
                        ))

                    if len(leads) >= max_results:
                        break
            except Exception as e:
                logger.warning(f"Error executing sub-query '{q}': {e}")

    except Exception as e:
        logger.error(f"Error in discover_leads_by_keyword for '{query}': {e}")

    return leads
