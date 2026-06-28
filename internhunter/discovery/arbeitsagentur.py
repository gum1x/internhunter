"""Bundesagentur für Arbeit "Jobsuche" (Germany) — keyless.

No registration: the public client uses a hardcoded ``X-API-Key: jobboerse-jobsuche`` constant
(documented by the bundesAPI community). ``angebotsart=34`` natively filters to Praktikum/Trainee
(internships) and results carry a real apply URL. Endpoint verified live 2026-06.
"""
from __future__ import annotations

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # public constant, no registration
_DETAIL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"


def parse_results(data: object) -> list[ListingJob]:
    rows = data.get("ergebnisliste") if isinstance(data, dict) else None
    jobs: list[ListingJob] = []
    for j in rows or []:
        if not isinstance(j, dict):
            continue
        title = str(j.get("stellenangebotsTitel") or j.get("titel") or "").strip()
        ref = j.get("referenznummer") or j.get("refnr")
        url = j.get("externeURL") or (_DETAIL.format(ref=ref) if ref else None)
        if not title or not isinstance(url, str) or not url:
            continue
        loc = j.get("arbeitsort") if isinstance(j.get("arbeitsort"), dict) else {}
        posted = (
            j.get("datumErsteVeroeffentlichung")
            or j.get("aktuelleVeroeffentlichungsdatum")
        )
        jobs.append(
            ListingJob(
                title=title,
                company=j.get("firma") or j.get("arbeitgeber"),
                url=url,
                location=loc.get("ort") if isinstance(loc, dict) else None,
                posted=posted,
                source="arbeitsagentur",
            )
        )
    return jobs


async def fetch_arbeitsagentur(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    max_pages = max(1, settings.arbeitsagentur_max_pages)
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for page in range(1, max_pages + 1):
        try:
            data = await ctx.get_json(
                _URL,
                params={"angebotsart": "34", "size": 100, "page": page},
                headers=_HEADERS,
                respect_robots=False,
            )
        except Exception:
            ctx.logger.debug("arbeitsagentur fetch failed p={}", page)
            break
        page_jobs = parse_results(data)
        if not page_jobs:
            break
        for job in page_jobs:
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
    return jobs


async def ingest_arbeitsagentur(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_arbeitsagentur, settings)
