"""USAJobs (federal) — keyless, via the stealth browser.

The public usajobs.gov search page is JS-rendered: the server HTML has no result cards, so a
plain HTTP scrape returns nothing, and the structured ``data.usajobs.gov`` API needs a key
(against the keyless ethos). So we render the public search page with the same stealth browser
Indeed uses and parse the cards — no API key, no login. Off unless the browser is enabled;
fails soft if a render is blocked or the markup changes.

Federal postings rarely map to a commercial ATS, so these stay ``ats="listing"`` with
``raw["source"]="usajobs"`` — still real internships, surfaced like any other listing.
"""
from __future__ import annotations

from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_BASE = "https://www.usajobs.gov"
_RESULTS = f"{_BASE}/Search/Results"
# Two passes: a plain intern keyword search and the hiring-path slice for students/recent grads.
_QUERIES: tuple[dict[str, str], ...] = (
    {"k": "intern"},
    {"k": "intern", "hp": "student"},
)
_HARD_PAGE_CAP = 50  # safety ceiling when max_pages=0 (full scrape); empty page stops earlier
_JOB_LINK = "a[href*='/job/']"


def _page_url(query: dict[str, str], page: int) -> str:
    params = {**query, "p": str(page)}
    return f"{_RESULTS}?{urlencode(params)}"


def parse_results(markup: str) -> list[ListingJob]:
    soup = BeautifulSoup(markup or "", "lxml")
    jobs: list[ListingJob] = []
    seen: set[str] = set()
    cards = soup.select("div.usajobs-search-result--core, li.usajobs-search-result--core")
    for card in cards:
        link = card.select_one("a.usajobs-search-result--core__title") or card.select_one(
            _JOB_LINK
        )
        if link is None:
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        agency = card.select_one(".usajobs-search-result--core__agency")
        dept = card.select_one(".usajobs-search-result--core__department")
        company = None
        for el in (agency, dept):
            if el is not None and el.get_text(strip=True):
                company = el.get_text(strip=True)
                break
        loc = card.select_one(".usajobs-search-result--core__location")
        url = urljoin(_BASE, href.split("?")[0])
        seen.add(url)
        jobs.append(
            ListingJob(
                title=link.get_text(strip=True),
                company=company,
                url=url,
                location=loc.get_text(strip=True) if loc is not None else None,
                source="usajobs",
            )
        )
    # Fallback: class names churn — if the structured cards matched nothing, scan raw job links.
    if not jobs:
        for link in soup.select(_JOB_LINK):
            href = link.get("href")
            title = link.get_text(strip=True)
            if not isinstance(href, str) or not href or not title:
                continue
            url = urljoin(_BASE, href.split("?")[0])
            if url in seen:
                continue
            seen.add(url)
            jobs.append(ListingJob(title=title, company=None, url=url, source="usajobs"))
    return jobs


async def fetch_usajobs(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    if ctx.browser is None:
        ctx.logger.debug("usajobs skipped: browser not enabled (page is JS-rendered)")
        return []
    max_pages = settings.usajobs_max_pages if settings.usajobs_max_pages > 0 else _HARD_PAGE_CAP
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for query in _QUERIES:
        for page in range(1, max_pages + 1):
            try:
                markup = await ctx.browser.render(
                    _page_url(query, page), wait_for=_JOB_LINK, timeout=30.0
                )
            except Exception:
                ctx.logger.debug("usajobs render failed q={} p={}", query, page)
                break
            results = parse_results(markup)
            if not results:
                break
            new = False
            for job in results:
                if job.url in seen:
                    continue
                seen.add(job.url)
                jobs.append(job)
                new = True
            if not new:  # same page repeating -> stop paginating this query
                break
    return jobs


async def ingest_usajobs(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_usajobs, settings, need_browser=True)
