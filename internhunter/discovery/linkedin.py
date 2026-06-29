"""LinkedIn jobs via the public, keyless *guest* endpoint.

``/jobs-guest/jobs/api/seeMoreJobPostings/search`` returns an HTML fragment of job cards with
no auth — the same data the public (logged-out) jobs pages render. We parse the cards, classify
internships, and store them as listings (``ats="listing"``, ``raw["source"]="linkedin"``);
``reresolve`` later upgrades any whose apply URL redirects to a real ATS board.

Gray-area vs. LinkedIn ToS — kept rate-limited (the shared HostLimiter applies) and intended
for personal single-user use. Fails soft so it can never destabilize the keyless core.
"""
from __future__ import annotations

from urllib.parse import urlencode

from bs4 import BeautifulSoup

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_PAGE_SIZE = 25
_HARD_PAGE_CAP = 200  # safety ceiling when max_pages=0 (full scrape); empty page stops earlier


def _keywords(settings: Settings) -> list[str]:
    raw = (settings.linkedin_keywords or "intern").split(",")
    return [kw.strip() for kw in raw if kw.strip()] or ["intern"]


def _page_url(keyword: str, location: str, start: int) -> str:
    params = urlencode({"keywords": keyword, "location": location, "start": start})
    return f"{_SEARCH}?{params}"


def parse_cards(markup: str) -> list[ListingJob]:
    """Parse the guest-API HTML fragment into ListingJob rows."""
    soup = BeautifulSoup(markup or "", "lxml")
    jobs: list[ListingJob] = []
    for card in soup.select("li"):
        link = card.select_one("a.base-card__full-link") or card.select_one("a[href]")
        title_el = card.select_one(".base-search-card__title") or card.select_one("h3")
        if link is None or title_el is None:
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.startswith("http"):
            continue
        company_el = card.select_one(".base-search-card__subtitle")
        loc_el = card.select_one(".job-search-card__location")
        time_el = card.select_one("time")
        posted = time_el.get("datetime") if time_el is not None else None
        jobs.append(
            ListingJob(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el is not None else None,
                url=href.split("?")[0],
                location=loc_el.get_text(strip=True) if loc_el is not None else None,
                posted=posted if isinstance(posted, str) else None,
                source="linkedin",
            )
        )
    return jobs


async def fetch_linkedin(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    locations = [
        loc.strip() for loc in (settings.linkedin_locations or "").split(",") if loc.strip()
    ] or ["United States"]
    max_pages = settings.linkedin_max_pages if settings.linkedin_max_pages > 0 else _HARD_PAGE_CAP

    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for keyword in _keywords(settings):
        for location in locations:
            for page in range(max_pages):
                url = _page_url(keyword, location, page * _PAGE_SIZE)
                try:
                    markup = await ctx.get_text(url, respect_robots=False)
                except Exception:
                    ctx.logger.debug(
                        "linkedin fetch failed for {} {} start={}", keyword, location, page
                    )
                    break
                cards = parse_cards(markup)
                if not cards:
                    break
                for card in cards:
                    if card.url in seen:
                        continue
                    seen.add(card.url)
                    jobs.append(card)
    return jobs


async def ingest_linkedin(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_linkedin, settings)
