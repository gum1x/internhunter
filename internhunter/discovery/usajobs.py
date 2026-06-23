"""USAJobs (federal) — keyless. We deliberately skip the key-gated ``data.usajobs.gov`` API
and scrape the public, server-rendered search results HTML instead, so no API key is needed.

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
_HARD_PAGE_CAP = 200  # safety ceiling when max_pages=0 (full scrape); empty page stops earlier


def _page_url(query: dict[str, str], page: int) -> str:
    params = {**query, "p": str(page)}
    return f"{_RESULTS}?{urlencode(params)}"


def parse_results(markup: str) -> list[ListingJob]:
    soup = BeautifulSoup(markup or "", "lxml")
    jobs: list[ListingJob] = []
    for card in soup.select("div.usajobs-search-result--core, li.usajobs-search-result--core"):
        link = card.select_one("a.usajobs-search-result--core__title") or card.select_one(
            "a[href*='/job/']"
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
        jobs.append(
            ListingJob(
                title=link.get_text(strip=True),
                company=company,
                url=urljoin(_BASE, href.split("?")[0]),
                location=loc.get_text(strip=True) if loc is not None else None,
                source="usajobs",
            )
        )
    return jobs


async def fetch_usajobs(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    max_pages = settings.usajobs_max_pages if settings.usajobs_max_pages > 0 else _HARD_PAGE_CAP
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for query in _QUERIES:
        for page in range(1, max_pages + 1):
            try:
                markup = await ctx.get_text(_page_url(query, page), respect_robots=False)
            except Exception:
                ctx.logger.debug("usajobs fetch failed q={} p={}", query, page)
                break
            results = parse_results(markup)
            if not results:
                break
            for job in results:
                if job.url in seen:
                    continue
                seen.add(job.url)
                jobs.append(job)
    return jobs


async def ingest_usajobs(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_usajobs, settings)
