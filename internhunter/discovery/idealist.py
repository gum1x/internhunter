"""Idealist — mission-driven / nonprofit internships (a segment the ATS+startup sources miss).
Keyless: fetch the public internship search page(s) and read schema.org JobPosting JSON-LD.
Best-effort + fail-soft; endpoint markup is verified during rollout."""
from __future__ import annotations

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.jsonld_listings import listings_from_html
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_PAGES = (
    "https://www.idealist.org/en/internships?q=intern",
    "https://www.idealist.org/en/internships",
)


async def fetch_idealist(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for url in _PAGES:
        try:
            markup = await ctx.get_text(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("idealist fetch failed for {}", url)
            continue
        for job in listings_from_html(markup, "idealist"):
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
    return jobs


async def ingest_idealist(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_idealist, settings)
