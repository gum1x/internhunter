"""Public Telegram channel scrape — no API, no login."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from internhunter.config.settings import Settings, get_settings
from internhunter.discovery.listing_common import ListingJob, ingest_listings
from internhunter.core.fetch import FetchContext

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_INTERNSHIP_RE = re.compile(r"\bintern\b|co-?op|apprentice", re.IGNORECASE)


def _channel_slugs(settings: Settings) -> list[str]:
    return [s.strip() for s in (settings.telegram_channels or "").split(",") if s.strip()]


def _extract_jobs(html: str, channel: str) -> list[ListingJob]:
    soup = BeautifulSoup(html or "", "lxml")
    jobs: list[ListingJob] = []
    seen: set[str] = set()
    for block in soup.select(".tgme_widget_message_text, .message"):
        text = block.get_text(" ", strip=True)
        if not text or not _INTERNSHIP_RE.search(text):
            continue
        for url in _URL_RE.findall(str(block)):
            clean = url.rstrip(".,)")
            if clean in seen or "t.me/" in clean:
                continue
            seen.add(clean)
            title = text[:120].strip()
            jobs.append(
                ListingJob(
                    title=title,
                    company=None,
                    url=clean,
                    source=f"telegram:{channel}",
                )
            )
    return jobs


async def fetch_telegram(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    slugs = _channel_slugs(settings)
    if not slugs:
        return []
    jobs: list[ListingJob] = []
    seen: set[str] = set()
    for slug in slugs:
        url = urljoin("https://t.me/s/", slug)
        try:
            html = await ctx.get_text(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("telegram fetch failed for {}", slug)
            continue
        for job in _extract_jobs(html, slug):
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
    return jobs


async def ingest_telegram(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_telegram, settings)