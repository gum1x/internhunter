"""Handshake — authenticated ingest with optional auto-login from edu pool."""
from __future__ import annotations

from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from loguru import logger

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import get_session, init_db, upsert_jobs
from internhunter.discovery.listing_common import ListingJob, board_refs, listing_to_job
from internhunter.discovery.merge import merge_boards
from internhunter.sessions.signup import ensure_handshake_session
from internhunter.sessions.store import resolve_handshake_session

_BASE = "https://app.joinhandshake.com"
_PAGE_SIZE = 25


def _page_url(page: int) -> str:
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


async def _render_pages(
    storage_state: str, max_pages: int, *, headless: bool = True
) -> list[ListingJob]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("handshake: playwright not installed; skipping")
        return []

    seen: set[str] = set()
    jobs: list[ListingJob] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
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
    if resolved.enable_handshake_auto:
        await ensure_handshake_session(resolved)
    session_path = resolve_handshake_session(resolved)
    if session_path is None:
        logger.info("handshake: no session available — skipping")
        return 0, 0, 0

    init_db(resolved.db_path)
    items = await _render_pages(
        str(session_path),
        max(1, resolved.handshake_max_pages),
        headless=resolved.browser_headless,
    )
    jobs = [job for item in items if (job := listing_to_job(item)) is not None]
    boards = merge_boards(board_refs(jobs))

    db = get_session()
    try:
        inserted, updated = upsert_jobs(db, jobs)
    finally:
        db.close()
    return len(items), inserted + updated, boards.new_boards