from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import get_session, init_db, upsert_jobs
from internhunter.core.fetch import FetchContext, build_fetch_context
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_location,
    normalize_title,
    parse_datetime,
)
from internhunter.discovery.fingerprint import detect_from_url, detection_to_board_ref
from internhunter.discovery.merge import merge_boards
from internhunter.sources.base import BoardRef


@dataclass(frozen=True)
class ApiJob:
    title: str
    company: str | None
    url: str
    location: str | None
    posted: Any
    source: str


def _items(data: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows = data.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def _remotive(ctx: FetchContext) -> list[ApiJob]:
    data = await ctx.get_json(
        "https://remotive.com/api/remote-jobs?search=intern", respect_robots=False
    )
    return [
        ApiJob(
            str(j.get("title", "")),
            j.get("company_name"),
            str(j.get("url", "")),
            j.get("candidate_required_location"),
            j.get("publication_date"),
            "remotive",
        )
        for j in _items(data, "jobs")
    ]


async def _jobicy(ctx: FetchContext) -> list[ApiJob]:
    data = await ctx.get_json(
        "https://jobicy.com/api/v2/remote-jobs?count=100&tag=intern", respect_robots=False
    )
    return [
        ApiJob(
            str(j.get("jobTitle", "")),
            j.get("companyName"),
            str(j.get("url", "")),
            j.get("jobGeo"),
            j.get("pubDate"),
            "jobicy",
        )
        for j in _items(data, "jobs")
    ]


async def _arbeitnow(ctx: FetchContext, pages: int = 3) -> list[ApiJob]:
    jobs: list[ApiJob] = []
    url: str | None = "https://www.arbeitnow.com/api/job-board-api"
    for _ in range(pages):
        if not url:
            break
        data = await ctx.get_json(url, respect_robots=False)
        for j in _items(data, "data"):
            jobs.append(
                ApiJob(
                    str(j.get("title", "")),
                    j.get("company_name"),
                    str(j.get("url", "")),
                    j.get("location"),
                    j.get("created_at"),
                    "arbeitnow",
                )
            )
        links = data.get("links") if isinstance(data, dict) else None
        url = links.get("next") if isinstance(links, dict) else None
    return jobs


async def _themuse(ctx: FetchContext, pages: int = 5) -> list[ApiJob]:
    jobs: list[ApiJob] = []
    for page in range(pages):
        data = await ctx.get_json(
            f"https://www.themuse.com/api/public/jobs?level=Internship&page={page}",
            respect_robots=False,
        )
        results = _items(data, "results")
        if not results:
            break
        for j in results:
            company = j.get("company")
            refs = j.get("refs")
            locations = j.get("locations")
            loc = locations[0].get("name") if isinstance(locations, list) and locations else None
            jobs.append(
                ApiJob(
                    str(j.get("name", "")),
                    company.get("name") if isinstance(company, dict) else None,
                    str(refs.get("landing_page", "")) if isinstance(refs, dict) else "",
                    loc if isinstance(loc, str) else None,
                    j.get("publication_date"),
                    "themuse",
                )
            )
    return jobs


_SOURCES = {
    "remotive": _remotive,
    "jobicy": _jobicy,
    "arbeitnow": _arbeitnow,
    "themuse": _themuse,
}


async def fetch_api_jobs(
    ctx: FetchContext, sources: list[str] | None = None
) -> list[ApiJob]:
    requested = sources if sources is not None else list(_SOURCES)
    results = await asyncio.gather(
        *(_SOURCES[name](ctx) for name in requested if name in _SOURCES),
        return_exceptions=True,
    )
    jobs: list[ApiJob] = []
    for result in results:
        if isinstance(result, list):
            jobs.extend(result)
    return jobs


def api_job_to_job(api_job: ApiJob) -> NormalizedJob | None:
    url = api_job.url.strip()
    title = api_job.title.strip()
    if not url or not title:
        return None
    classification = classify_internship(title, "")
    if not classification.is_internship:
        return None

    company = (api_job.company or "").strip() or None
    detection = detect_from_url(url)
    ats = detection.ats if detection is not None else "listing"
    token = detection.token if detection is not None else normalize_company_slug(company or "")
    loc = normalize_location(api_job.location)
    now = datetime.now(UTC)

    return NormalizedJob(
        job_uid=make_job_uid(ats, token, None, url),
        ats=ats,
        board_token=token,
        canonical_url=url,
        url_hash=make_url_hash(url),
        company=company,
        company_slug=normalize_company_slug(company or token),
        title=title,
        title_normalized=normalize_title(title),
        is_internship=True,
        internship_kind=classification.kind or "intern",
        level_tags=classification.level_tags,
        location_raw=api_job.location,
        location_normalized=loc.normalized,
        country=loc.country,
        region=loc.region,
        city=loc.city,
        is_remote=loc.is_remote,
        remote_scope=loc.remote_scope,
        posted_at=parse_datetime(api_job.posted),
        first_seen_at=now,
        last_seen_at=now,
        raw={"title": title, "company": company, "url": url, "source": api_job.source},
    )


def _board_refs(jobs: list[NormalizedJob]) -> list[BoardRef]:
    seen: set[tuple[str, str]] = set()
    refs: list[BoardRef] = []
    for job in jobs:
        detection = detect_from_url(job.canonical_url)
        if detection is None:
            continue
        key = (detection.ats, detection.token)
        if key in seen:
            continue
        seen.add(key)
        refs.append(detection_to_board_ref(detection, job.company))
    return refs


async def ingest_job_apis(
    settings: Settings | None = None, sources: list[str] | None = None
) -> tuple[int, int, int]:
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    async with build_fetch_context(resolved) as ctx:
        api_jobs = await fetch_api_jobs(ctx, sources)

    jobs = [job for api_job in api_jobs if (job := api_job_to_job(api_job)) is not None]
    boards = merge_boards(_board_refs(jobs))

    session = get_session()
    try:
        inserted, updated = upsert_jobs(session, jobs)
    finally:
        session.close()
    return len(api_jobs), inserted + updated, boards.new_boards
