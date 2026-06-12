from __future__ import annotations

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

_LISTS = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/vanshb03/Summer2026-Internships/dev/.github/scripts/listings.json",
)


async def fetch_list_entries(
    ctx: FetchContext, lists: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    pages = lists if lists is not None else _LISTS
    entries: list[dict[str, Any]] = []
    for url in pages:
        try:
            data = await ctx.get_json(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("internship list fetch failed {}", url)
            continue
        if isinstance(data, list):
            entries.extend(
                entry
                for entry in data
                if isinstance(entry, dict)
                and entry.get("active")
                and entry.get("is_visible", True)
            )
    return entries


def _location_raw(entry: dict[str, Any]) -> str | None:
    locations = entry.get("locations")
    if isinstance(locations, list) and locations:
        return ", ".join(str(loc) for loc in locations[:3])
    return None


def entry_to_job(entry: dict[str, Any]) -> NormalizedJob | None:
    apply_url = str(entry.get("url") or "").strip()
    title = str(entry.get("title") or "").strip()
    if not apply_url or not title:
        return None

    company = str(entry.get("company_name") or "").strip() or None
    detection = detect_from_url(apply_url)
    ats = detection.ats if detection is not None else "listing"
    token = detection.token if detection is not None else normalize_company_slug(company or "")
    source_job_id = str(entry.get("id")) if entry.get("id") is not None else None

    location_raw = _location_raw(entry)
    loc = normalize_location(location_raw)
    classification = classify_internship(title, "")
    now = datetime.now(UTC)

    return NormalizedJob(
        job_uid=make_job_uid(ats, token, source_job_id, apply_url),
        ats=ats,
        board_token=token,
        source_job_id=source_job_id,
        canonical_url=apply_url,
        url_hash=make_url_hash(apply_url),
        company=company,
        company_slug=normalize_company_slug(company or token),
        title=title,
        title_normalized=normalize_title(title),
        is_internship=True,
        internship_kind=classification.kind or "intern",
        level_tags=classification.level_tags,
        location_raw=location_raw,
        location_normalized=loc.normalized,
        country=loc.country,
        region=loc.region,
        city=loc.city,
        is_remote=loc.is_remote,
        remote_scope=loc.remote_scope,
        posted_at=parse_datetime(entry.get("date_posted")),
        first_seen_at=now,
        last_seen_at=now,
        raw=entry,
    )


def board_refs(entries: list[dict[str, Any]]) -> list[BoardRef]:
    seen: set[tuple[str, str]] = set()
    refs: list[BoardRef] = []
    for entry in entries:
        detection = detect_from_url(str(entry.get("url") or ""))
        if detection is None:
            continue
        key = (detection.ats, detection.token)
        if key in seen:
            continue
        seen.add(key)
        company = entry.get("company_name")
        refs.append(detection_to_board_ref(detection, str(company) if company else None))
    return refs


async def ingest_internship_lists(
    settings: Settings | None = None, lists: tuple[str, ...] | None = None
) -> tuple[int, int, int]:
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    async with build_fetch_context(resolved) as ctx:
        entries = await fetch_list_entries(ctx, lists)

    jobs = [job for entry in entries if (job := entry_to_job(entry)) is not None]
    boards = merge_boards(board_refs(entries))

    session = get_session()
    try:
        inserted, updated = upsert_jobs(session, jobs)
    finally:
        session.close()
    return len(entries), inserted + updated, boards.new_boards
