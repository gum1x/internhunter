"""Shared plumbing for the external-listing ingestors (LinkedIn, USAJobs, big-company,
university, Indeed, Handshake, Google Jobs).

Every one of these pulls postings that are NOT polled from a stable ATS board, so they all
share the same normalization + upsert shape: produce ``ListingJob`` rows, turn each into a
``NormalizedJob`` (real ATS auto-upgraded via ``detect_from_url``, otherwise ``ats="listing"``
with a ``raw["source"]`` tag), feed any recovered boards into the registry, and upsert. This
mirrors ``job_apis.api_job_to_job`` but adds description text + a source tag, and is reused so
each ingestor file stays a thin fetcher.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import get_session, init_db, upsert_jobs
from internhunter.core.fetch import FetchContext, build_fetch_context
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    is_rolling,
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
class ListingJob:
    """One posting from an aggregator / custom careers site, pre-normalization."""

    title: str
    company: str | None
    url: str
    location: str | None = None
    posted: Any = None
    source: str = ""
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_EARLY_TITLE_RE = re.compile(
    r"\b(founding (engineer|team|designer|scientist)|first (engineer|hire)"
    r"|entrepreneur in residence)\b",
    re.IGNORECASE,
)


def listing_to_job(item: ListingJob, *, keep_early: bool = False) -> NormalizedJob | None:
    """Normalize one listing. Internships only by default; ``keep_early=True`` also keeps
    founding/first-hire roles (startup sources), stored with ``is_internship=False`` and an
    ``early-stage`` level tag so the alert keyword layer can still surface them."""
    url = (item.url or "").strip()
    title = (item.title or "").strip()
    if not url or not title:
        return None

    description = item.description or ""
    classification = classify_internship(title, description)
    is_early = bool(keep_early and _EARLY_TITLE_RE.search(title))
    if not classification.is_internship and not is_early:
        return None

    company = (item.company or "").strip() or None
    detection = detect_from_url(url)
    ats = detection.ats if detection is not None else "listing"
    token = detection.token if detection is not None else normalize_company_slug(company or "")
    loc = normalize_location(item.location)
    now = datetime.now(UTC)

    raw: dict[str, Any] = {
        "title": title,
        "company": company,
        "url": url,
        "source": item.source,
    }
    if item.extra:
        raw.update(item.extra)

    level_tags = list(classification.level_tags)
    if is_early and not classification.is_internship and "early-stage" not in level_tags:
        level_tags.append("early-stage")

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
        is_internship=classification.is_internship,
        internship_kind=(classification.kind or "intern") if classification.is_internship else None,
        level_tags=level_tags,
        location_raw=item.location,
        location_normalized=loc.normalized,
        country=loc.country,
        region=loc.region,
        city=loc.city,
        is_remote=loc.is_remote,
        remote_scope=loc.remote_scope,
        description_text=description,
        is_rolling=is_rolling(description),
        posted_at=parse_datetime(item.posted),
        first_seen_at=now,
        last_seen_at=now,
        raw=raw,
    )


def board_refs(jobs: list[NormalizedJob]) -> list[BoardRef]:
    """Real ATS boards recovered from listing URLs -> registry candidates."""
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


async def ingest_listings(
    fetcher: Callable[[FetchContext, Settings], Awaitable[list[ListingJob]]],
    settings: Settings | None = None,
    *,
    need_browser: bool = False,
    keep_early: bool = False,
) -> tuple[int, int, int]:
    """Run a fetcher, normalize + dedupe boards + upsert. Returns (entries, jobs, new_boards).

    ``need_browser`` flips ``enable_browser`` on for the fetch context (Indeed/Handshake),
    mirroring how ``cli.py`` enables the browser for the ``vc`` discovery method.
    """
    resolved = settings or get_settings()
    if need_browser and not resolved.enable_browser:
        resolved = resolved.model_copy(update={"enable_browser": True})
    init_db(resolved.db_path)

    async with build_fetch_context(resolved) as ctx:
        items = await fetcher(ctx, resolved)

    jobs = [
        job for item in items if (job := listing_to_job(item, keep_early=keep_early)) is not None
    ]
    boards = merge_boards(board_refs(jobs))

    session = get_session()
    try:
        inserted, updated = upsert_jobs(session, jobs)
    finally:
        session.close()
    return len(items), inserted + updated, boards.new_boards
