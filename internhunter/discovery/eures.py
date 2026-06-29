"""EURES (EU public job-vacancy search) — keyless.

The search SPA is backed by ``POST /eures/api/jv-searchengine/public/jv-search/search`` whose
OpenAPI declares ``security: []`` (no API key); the old ``eures-apps/searchengine`` path now
404s. Results carry no apply URL, so we build the public portal detail URL from the vacancy id.
Multiple TITLE keyword passes give multilingual intern coverage; ``classify_internship`` (in
``listing_to_job``) still filters. Endpoint verified live 2026-06.
"""
from __future__ import annotations

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_URL = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
_DETAIL = "https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=en"
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
# Multilingual title passes: EN/intern, FR/stage, DE/Praktikum, CZ/stáž, ES/becario.
_KEYWORDS = ("internship", "trainee", "stage", "Praktikum", "stáž", "becario")
_PER_PAGE = 50  # API max; 100 -> HTTP 400


def _location(location_map: object) -> str | None:
    if isinstance(location_map, dict) and location_map:
        return ", ".join(sorted(str(k) for k in location_map))  # country codes
    return None


def parse_vacancies(data: object, source: str = "eures") -> list[ListingJob]:
    jvs = data.get("jvs") if isinstance(data, dict) else None
    jobs: list[ListingJob] = []
    for jv in jvs or []:
        if not isinstance(jv, dict):
            continue
        jid, title = jv.get("id"), jv.get("title")
        if not isinstance(jid, str) or not isinstance(title, str) or not title:
            continue
        employer = jv.get("employer")
        company = employer.get("name") if isinstance(employer, dict) else None
        jobs.append(
            ListingJob(
                title=title,
                company=company if isinstance(company, str) else None,
                url=_DETAIL.format(id=jid),
                location=_location(jv.get("locationMap")),
                posted=jv.get("creationDate"),  # unix ms; parse_datetime handles it
                source=source,
                description=str(jv.get("description") or ""),
            )
        )
    return jobs


async def fetch_eures(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    max_pages = max(1, settings.eures_max_pages)
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for keyword in _KEYWORDS:
        for page in range(1, max_pages + 1):
            body = {
                "resultsPerPage": _PER_PAGE,
                "page": page,
                "sortSearch": "MOST_RECENT",
                "keywords": [{"keyword": keyword, "specificSearchCode": "TITLE"}],
            }
            try:
                data = await ctx.post_json(
                    _URL, json_body=body, headers=_HEADERS, respect_robots=False
                )
            except Exception:
                ctx.logger.debug("eures fetch failed kw={} p={}", keyword, page)
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
