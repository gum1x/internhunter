"""YC Work at a Startup — intern-filtered listings."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from internhunter.config.settings import Settings, get_settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_BASE = "https://www.workatastartup.com"
_LIST_URL = f"{_BASE}/jobs?role=intern"


def parse_listings(markup: str) -> list[ListingJob]:
    soup = BeautifulSoup(markup or "", "lxml")
    jobs: list[ListingJob] = []
    for card in soup.select("a[href*='/jobs/'], a[href*='/companies/']"):
        href = card.get("href")
        if not isinstance(href, str):
            continue
        title = card.get_text(" ", strip=True)
        if not title or len(title) < 4:
            continue
        url = urljoin(_BASE, href.split("?")[0])
        if not re.search(r"intern|co-?op", title, re.IGNORECASE):
            continue
        jobs.append(ListingJob(title=title, company=None, url=url, source="workatastartup"))
    return jobs


async def fetch_workatastartup(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    try:
        if ctx.browser is not None:
            markup = await ctx.browser.render(_LIST_URL)
        else:
            markup = await ctx.get_text(_LIST_URL, respect_robots=False)
    except Exception:
        ctx.logger.debug("workatastartup fetch failed")
        return []
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for job in parse_listings(markup):
        if job.url in seen:
            continue
        seen.add(job.url)
        jobs.append(job)
    return jobs


async def ingest_workatastartup(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_workatastartup, settings, need_browser=True)