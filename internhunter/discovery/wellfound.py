"""Wellfound (ex-AngelList Talent) — OPT-IN startup-job harvest.

Wellfound publishes no official feed or API, fronts the site with a DataDome bot-wall,
and its ToS restricts automated crawling — so this channel is OFF by default
(``INTERNHUNTER_ENABLE_WELLFOUND=true`` to opt in) and deliberately narrow: it fetches
only the robots-ALLOWED ``/company/<slug>/jobs`` pages for companies you explicitly list
in ``INTERNHUNTER_WELLFOUND_COMPANIES``, reads their schema.org JobPosting JSON-LD, and
never crawls search/browse pages. One request per company per run, through the shared
rate-limited, robots-gated fetcher. Expect it to stay inert if the bot-wall blocks the
fetch (the curl_cffi fallback sometimes clears it); startup coverage does not depend on
it — YC / Work-at-a-Startup / VC-portfolio / HN channels are on by default.
"""

from __future__ import annotations

from typing import Any

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.jsonld import extract_jobpostings
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_SITE = "https://wellfound.com"


def _org_name(posting: dict[str, Any], fallback: str) -> str:
    org = posting.get("hiringOrganization")
    if isinstance(org, dict):
        name = org.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return fallback


def _location(posting: dict[str, Any]) -> str | None:
    if str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return "Remote"
    locations = posting.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    for loc in locations if isinstance(locations, list) else []:
        if not isinstance(loc, dict):
            continue
        address = loc.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            joined = ", ".join(str(p) for p in parts if p)
            if joined:
                return joined
    return None


def postings_to_listings(html: str, company: str, page_url: str) -> list[ListingJob]:
    jobs: list[ListingJob] = []
    for posting in extract_jobpostings(html):
        title = str(posting.get("title") or "").strip()
        url = posting.get("url") or posting.get("applyUrl") or page_url
        if not title or not isinstance(url, str):
            continue
        jobs.append(
            ListingJob(
                title=title,
                company=_org_name(posting, company),
                url=url,
                location=_location(posting),
                posted=posting.get("datePosted"),
                source="wellfound",
                description=str(posting.get("description") or ""),
                extra={"wellfound_company": company},
            )
        )
    return jobs


async def fetch_wellfound(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    if not settings.enable_wellfound:
        return []
    slugs = [s.strip() for s in settings.wellfound_companies.split(",") if s.strip()]
    if not slugs:
        ctx.logger.info("wellfound: enabled but INTERNHUNTER_WELLFOUND_COMPANIES is empty")
        return []
    jobs: list[ListingJob] = []
    for slug in slugs:
        page_url = f"{_SITE}/company/{slug}/jobs"
        try:
            html = await ctx.get_text(page_url)
        except Exception:
            ctx.logger.debug("wellfound: fetch failed/blocked for {}", slug)
            continue
        jobs.extend(postings_to_listings(html, slug, page_url))
    return jobs


async def ingest_wellfound(settings: Settings | None = None) -> tuple[int, int, int]:
    # keep_early: founding/first-hire roles are the point of startup boards
    return await ingest_listings(fetch_wellfound, settings, keep_early=True)
