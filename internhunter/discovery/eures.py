"""EURES — the EU's public job-mobility portal. Keyless (no API key). EURES exposes a public
JSON search behind its SPA; we POST an intern keyword search and normalize the returned
vacancies into listings. The endpoint/payload shape is version-sensitive, so this parses
defensively and fails soft (returns nothing) on any drift rather than breaking the pipeline.
"""
from __future__ import annotations

from typing import Any

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_SEARCH = (
    "https://europa.eu/eures/eures-apps/searchengine/page/jv-search/search?lang=en"
)


def _body(page: int, per_page: int) -> dict[str, Any]:
    return {
        "resultsPerPage": per_page,
        "page": page,
        "sortSearch": "BEST_MATCH",
        "keywords": [{"keyword": "intern", "specificSearchCode": "EVERYWHERE"}],
        "locationCodes": [],
        "positionScheduleCodes": [],
        "smsErrorMessages": [],
        "euresFlagSearch": False,
    }


def _vacancies(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in ("jvs", "vacancies", "results", "content"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def parse_vacancies(data: Any) -> list[ListingJob]:
    jobs: list[ListingJob] = []
    for jv in _vacancies(data):
        title = str(jv.get("title") or jv.get("jvTitle") or "").strip()
        url = (
            jv.get("jvUrl") or jv.get("url") or jv.get("applyUrl")
            or jv.get("detailsUrl")
        )
        if not title or not isinstance(url, str) or not url.startswith("http"):
            continue
        employer = jv.get("employer") or jv.get("companyName") or jv.get("employerName")
        if isinstance(employer, dict):
            employer = employer.get("name")
        loc = jv.get("locationMap") or jv.get("location") or jv.get("locationName")
        if isinstance(loc, (dict, list)):
            loc = None
        jobs.append(
            ListingJob(
                title=title,
                company=employer if isinstance(employer, str) else None,
                url=url,
                location=loc if isinstance(loc, str) else None,
                posted=jv.get("creationDate") or jv.get("publicationDate"),
                source="eures",
            )
        )
    return jobs


async def fetch_eures(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    max_pages = max(1, settings.eures_max_pages)
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for page in range(1, max_pages + 1):
        try:
            data = await ctx.post_json(
                _SEARCH, json_body=_body(page, 50), respect_robots=False
            )
        except Exception:
            ctx.logger.debug("eures search failed page={}", page)
            break
        page_jobs = parse_vacancies(data)
        if not page_jobs:
            break
        for job in page_jobs:
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
    return jobs


async def ingest_eures(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_eures, settings)
