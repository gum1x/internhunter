"""Idealist (nonprofit / mission-driven internships) — keyless.

Idealist's jobs page is a React SPA with no JobPosting JSON-LD (the old harvester got 0). Its
search is Algolia-backed and the search-only key is public (shipped in the page bundle). We query
that index directly, filtered to JOB/INTERNSHIP records; ``classify_internship`` (in
``listing_to_job``) drops non-interns. Creds are re-read from the page at runtime (self-healing)
with a verified fallback. Endpoint verified live 2026-06.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_SITE = "https://www.idealist.org"
_JOBS_PAGE = f"{_SITE}/en/jobs"
_INDEX = "idealist7-production"
_FALLBACK_APP_ID = "NSV3AUESS7"
_FALLBACK_KEY = "c2730ea10ab82787f2f3cc961e8c1e06"  # public search-only key
_HARD_PAGE_CAP = 12  # Algolia caps reachable offset ~1000; 100/page -> ~10 pages

_APP_RE = re.compile(r'"appId":"([A-Z0-9]+)"')
_KEY_RE = re.compile(r'"searchApiKey":"([a-f0-9]+)"')


async def _resolve_creds(ctx: FetchContext) -> tuple[str, str]:
    try:
        html = await ctx.get_text(_JOBS_PAGE, respect_robots=False)
        app, key = _APP_RE.search(html), _KEY_RE.search(html)
        if app and key:
            return app.group(1), key.group(1)
    except Exception:
        ctx.logger.debug("idealist: cred re-discovery failed, using fallback")
    return _FALLBACK_APP_ID, _FALLBACK_KEY


def _location(hit: dict[str, Any]) -> str | None:
    if hit.get("remoteOk") or hit.get("locationType") == "REMOTE":
        return "Remote"
    parts = [hit.get("city"), hit.get("stateStr"), hit.get("country")]
    return ", ".join(p for p in parts if p) or None


def parse_hits(data: object) -> list[ListingJob]:
    hits = data.get("hits") if isinstance(data, dict) else None
    jobs: list[ListingJob] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("name") or "").strip()
        url_field = hit.get("url")
        rel = url_field.get("en") if isinstance(url_field, dict) else None
        if not title or not isinstance(rel, str):
            continue
        jobs.append(
            ListingJob(
                title=title,
                company=hit.get("orgName"),
                url=urljoin(_SITE, rel.split("?")[0]),
                location=_location(hit),
                posted=hit.get("published"),  # unix epoch seconds
                source="idealist",
                description=str(hit.get("description") or ""),
                extra={"idealist_type": hit.get("type"), "object_id": hit.get("objectID")},
            )
        )
    return jobs


async def fetch_idealist(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    app_id, api_key = await _resolve_creds(ctx)
    url = f"https://{app_id}-dsn.algolia.net/1/indexes/{_INDEX}/query"
    headers = {
        "X-Algolia-API-Key": api_key,
        "X-Algolia-Application-Id": app_id,
        "Content-Type": "application/json",
    }
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for page in range(_HARD_PAGE_CAP):
        body = {
            "query": "intern",
            "hitsPerPage": 100,
            "page": page,
            "facetFilters": [["type:INTERNSHIP", "type:JOB"]],
        }
        try:
            data = await ctx.post_json(url, json_body=body, headers=headers, respect_robots=False)
        except Exception:
            ctx.logger.debug("idealist fetch failed page={}", page)
            break
        page_jobs = parse_hits(data)
        if not page_jobs:
            break
        for job in page_jobs:
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
        if isinstance(data, dict) and page + 1 >= int(data.get("nbPages") or 0):
            break
    return jobs


async def ingest_idealist(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_idealist, settings)
