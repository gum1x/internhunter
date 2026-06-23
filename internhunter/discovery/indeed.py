"""Indeed — best-effort, stealth-browser, opt-in.

Indeed is aggressively bot-walled (Cloudflare), so there's no keyless JSON path; we render the
public search results with the stealth browser and parse job cards. This is **fragile** (CSS
churn + frequent blocks) and **off by default** (``settings.enable_indeed``). Everything fails
soft — a block or markup change logs and returns nothing, never raising into the pipeline.

Gray-area vs. Indeed ToS; intended for personal single-user use and isolated from the keyless core.
"""
from __future__ import annotations

from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_BASE = "https://www.indeed.com"
_PAGE_SIZE = 10
_HARD_PAGE_CAP = 100  # safety ceiling when max_pages=0 (full scrape); empty page stops earlier


def _page_url(location: str, start: int) -> str:
    params = {"q": "intern", "l": location, "start": str(start)}
    return f"{_BASE}/jobs?{urlencode(params)}"


def parse_cards(markup: str) -> list[ListingJob]:
    soup = BeautifulSoup(markup or "", "lxml")
    jobs: list[ListingJob] = []
    for card in soup.select("div.job_seen_beacon, div.cardOutline"):
        link = card.select_one("a.jcs-JobTitle") or card.select_one("h2.jobTitle a")
        if link is None:
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        title = link.get_text(strip=True)
        company = card.select_one('[data-testid="company-name"]') or card.select_one(
            "span.companyName"
        )
        loc = card.select_one('[data-testid="text-location"]') or card.select_one(
            "div.companyLocation"
        )
        jobs.append(
            ListingJob(
                title=title,
                company=company.get_text(strip=True) if company is not None else None,
                url=urljoin(_BASE, href.split("?")[0]) if href.startswith("/") else href,
                location=loc.get_text(strip=True) if loc is not None else None,
                source="indeed",
            )
        )
    return jobs


async def fetch_indeed(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    if ctx.browser is None:
        ctx.logger.debug("indeed skipped: browser not enabled")
        return []
    locations = [
        loc.strip() for loc in (settings.indeed_locations or "").split(",") if loc.strip()
    ] or [""]
    max_pages = settings.indeed_max_pages if settings.indeed_max_pages > 0 else _HARD_PAGE_CAP

    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for location in locations:
        for page in range(max_pages):
            url = _page_url(location, page * _PAGE_SIZE)
            try:
                markup = await ctx.browser.render(url, wait_for="a.jcs-JobTitle", timeout=30.0)
            except Exception:
                ctx.logger.debug("indeed render failed for {} start={}", location, page)
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


async def ingest_indeed(settings: Settings | None = None) -> tuple[int, int, int]:
    from internhunter.config.settings import get_settings

    resolved = settings or get_settings()
    if not resolved.enable_indeed:
        return 0, 0, 0
    return await ingest_listings(fetch_indeed, resolved, need_browser=True)
