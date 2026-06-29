"""LinkedIn authenticated search — deeper than guest API when a session exists."""
from __future__ import annotations

from urllib.parse import urlencode

from loguru import logger

from internhunter.config.settings import Settings, get_settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.linkedin import parse_cards
from internhunter.discovery.listing_common import ListingJob, ingest_listings
from internhunter.sessions.signup import ensure_linkedin_session
from internhunter.sessions.store import load_storage_state

_SEARCH = "https://www.linkedin.com/jobs/search/"
_PAGE_SIZE = 25


def _search_url(keyword: str, location: str, start: int) -> str:
    params = {
        "keywords": keyword,
        "location": location,
        "f_E": "1",  # Internship
        "start": str(start),
    }
    return f"{_SEARCH}?{urlencode(params)}"


async def fetch_linkedin_auth(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    if not settings.enable_linkedin_auth:
        return []
    session_path = load_storage_state(settings, "linkedin")
    if session_path is None:
        created = await ensure_linkedin_session(settings)
        if not created:
            return []
        session_path = load_storage_state(settings, "linkedin")
    if session_path is None:
        return []

    keywords = [
        kw.strip()
        for kw in (settings.linkedin_keywords or "intern").split(",")
        if kw.strip()
    ]
    locations = [
        loc.strip()
        for loc in (settings.linkedin_locations or "").split(",")
        if loc.strip()
    ] or ["United States"]
    max_pages = settings.linkedin_max_pages if settings.linkedin_max_pages > 0 else 50

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("linkedin_auth: playwright not installed")
        return []

    seen: set[str] = set()
    jobs: list[ListingJob] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=settings.browser_headless)
        try:
            context = await browser.new_context(storage_state=str(session_path))
            page = await context.new_page()
            for keyword in keywords:
                for location in locations:
                    for page_idx in range(max_pages):
                        url = _search_url(keyword, location, page_idx * _PAGE_SIZE)
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                            cards = parse_cards(await page.content())
                        except Exception:
                            break
                        if not cards:
                            break
                        for card in cards:
                            if card.url in seen:
                                continue
                            seen.add(card.url)
                            card = ListingJob(
                                title=card.title,
                                company=card.company,
                                url=card.url,
                                location=card.location,
                                posted=card.posted,
                                source="linkedin_auth",
                            )
                            jobs.append(card)
        finally:
            await browser.close()
    return jobs


async def ingest_linkedin_auth(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_linkedin_auth, settings, need_browser=True)