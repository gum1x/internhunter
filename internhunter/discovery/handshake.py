"""Handshake — authenticated, opt-in, best-effort.

Handshake postings require a logged-in *university* session, so there is no keyless path. We
mirror the existing ``staffspy_session`` cookie pattern: the user supplies a saved Playwright
storage-state JSON at ``settings.handshake_session``. If that file is missing the module is
**inert** (returns ``(0, 0, 0)``, logged once). If present we drive a browser context with that
session, scrape the student postings list, and ingest the cards.

This is fragile (Handshake markup churns) and depends entirely on the user providing their own
session; it is never part of the automatic pipeline.
"""
from __future__ import annotations

from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from loguru import logger

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import get_session, init_db, upsert_jobs
from internhunter.discovery.listing_common import ListingJob, board_refs, listing_to_job
from internhunter.discovery.merge import merge_boards

_BASE = "https://app.joinhandshake.com"
_PAGE_SIZE = 25


def _page_url(page: int) -> str:
    # employmentTypeIds=internship-equivalent filter; page is 1-indexed in Handshake.
    params = {"page": str(page), "per_page": str(_PAGE_SIZE), "query": "intern"}
    return f"{_BASE}/stu/postings?{urlencode(params)}"


def parse_cards(markup: str) -> list[ListingJob]:
    soup = BeautifulSoup(markup or "", "lxml")
    jobs: list[ListingJob] = []
    for card in soup.select('a[href*="/stu/jobs/"], a[href*="/jobs/"]'):
        href = card.get("href")
        if not isinstance(href, str) or "job" not in href:
            continue
        title_el = card.select_one('[class*="title"]') or card
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue
        company_el = card.select_one('[class*="employer"], [class*="company"]')
        loc_el = card.select_one('[class*="location"]')
        jobs.append(
            ListingJob(
                title=title,
                company=company_el.get_text(strip=True) if company_el is not None else None,
                url=urljoin(_BASE, href.split("?")[0]),
                location=loc_el.get_text(strip=True) if loc_el is not None else None,
                source="handshake",
            )
        )
    return jobs


async def _render_pages(storage_state: str, max_pages: int) -> list[ListingJob]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("handshake: playwright not installed; skipping")
        return []

    seen: set[str] = set()
    jobs: list[ListingJob] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            for n in range(1, max_pages + 1):
                try:
                    await page.goto(_page_url(n), wait_until="domcontentloaded", timeout=30000)
                    markup = await page.content()
                except Exception:
                    logger.debug("handshake render failed page={}", n)
                    break
                cards = parse_cards(markup)
                if not cards:
                    break
                for card in cards:
                    if card.url in seen:
                        continue
                    seen.add(card.url)
                    jobs.append(card)
        finally:
            await browser.close()
    return jobs


async def ingest_handshake(settings: Settings | None = None) -> tuple[int, int, int]:
    resolved = settings or get_settings()
    session_path = resolved.handshake_session
    if not session_path or not session_path.exists():
        logger.info("handshake: no session at {} — skipping (opt-in)", session_path)
        return 0, 0, 0

    init_db(resolved.db_path)
    items = await _render_pages(str(session_path), max(1, resolved.handshake_max_pages))
    jobs = [job for item in items if (job := listing_to_job(item)) is not None]
    boards = merge_boards(board_refs(jobs))

    db = get_session()
    try:
        inserted, updated = upsert_jobs(db, jobs)
    finally:
        db.close()
    return len(items), inserted + updated, boards.new_boards
