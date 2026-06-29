"""Keyless RSS/JSON job feeds — RemoteOK, HN Firebase, etc."""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from xml.etree import ElementTree

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import get_session, init_db, upsert_jobs
from internhunter.core.fetch import FetchContext, build_fetch_context
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_title,
)
from internhunter.discovery.fingerprint import detect_from_url
from internhunter.discovery.listing_common import board_refs
from internhunter.discovery.merge import merge_boards

_INTERNSHIP_RE = re.compile(r"\bintern\b|co-?op|apprentice", re.IGNORECASE)

_HN_WHOISHIRING = (
    "https://hacker-news.firebaseio.com/v0/user/whoishiring/threads.json"
)


def _is_internship_title(title: str) -> bool:
    return bool(_INTERNSHIP_RE.search(title))


def _job_from_listing(
    title: str, url: str, company: str | None, source: str
) -> NormalizedJob | None:
    if not title.strip() or not url.strip():
        return None
    if not _is_internship_title(title):
        return None
    classification = classify_internship(title, "")
    if not classification.is_internship:
        return None
    detection = detect_from_url(url)
    ats = detection.ats if detection is not None else "listing"
    token = detection.token if detection is not None else normalize_company_slug(company or "")
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
        first_seen_at=now,
        last_seen_at=now,
        raw={"source": source, "title": title, "url": url},
    )


async def _remoteok(ctx: FetchContext) -> list[NormalizedJob]:
    data = await ctx.get_json("https://remoteok.com/api", respect_robots=False)
    if not isinstance(data, list):
        return []
    jobs: list[NormalizedJob] = []
    for row in data:
        if not isinstance(row, dict) or row.get("id") == "ok":
            continue
        title = str(row.get("position", ""))
        url = str(row.get("url", ""))
        company = row.get("company")
        job = _job_from_listing(title, url, str(company) if company else None, "remoteok")
        if job is not None:
            jobs.append(job)
    return jobs


async def _hn_whoishiring(ctx: FetchContext) -> list[NormalizedJob]:
    thread_ids = await ctx.get_json(_HN_WHOISHIRING, respect_robots=False)
    if not isinstance(thread_ids, list):
        return []
    jobs: list[NormalizedJob] = []
    for tid in thread_ids[:3]:
        item_url = f"https://hacker-news.firebaseio.com/v0/item/{tid}.json"
        try:
            item = await ctx.get_json(item_url, respect_robots=False)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", ""))
        for match in re.finditer(r'href="(https?://[^"]+)"[^>]*>([^<]+)</a>', text):
            url, title = match.group(1), match.group(2)
            job = _job_from_listing(title, url, None, "hn_whoishiring")
            if job is not None:
                jobs.append(job)
    return jobs


def _rss_items(xml_text: str) -> list[tuple[str, str, str | None]]:
    root = ElementTree.fromstring(xml_text)
    items: list[tuple[str, str, str | None]] = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or link_el is None:
            continue
        title = (title_el.text or "").strip()
        link = (link_el.text or "").strip()
        if title and link:
            items.append((title, link, None))
    return items


async def _weworkremotely(ctx: FetchContext) -> list[NormalizedJob]:
    text = await ctx.get_text(
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        respect_robots=False,
    )
    jobs: list[NormalizedJob] = []
    for title, url, _ in _rss_items(text):
        job = _job_from_listing(title, url, None, "weworkremotely")
        if job is not None:
            jobs.append(job)
    return jobs


async def fetch_feed_jobs(ctx: FetchContext) -> list[NormalizedJob]:
    results = await asyncio.gather(
        _remoteok(ctx),
        _hn_whoishiring(ctx),
        _weworkremotely(ctx),
        return_exceptions=True,
    )
    jobs: list[NormalizedJob] = []
    for result in results:
        if isinstance(result, list):
            jobs.extend(result)
    return jobs


async def ingest_feeds(settings: Settings | None = None) -> tuple[int, int, int]:
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    async with build_fetch_context(resolved) as ctx:
        jobs = await fetch_feed_jobs(ctx)
    boards = merge_boards(board_refs(jobs))
    session = get_session()
    try:
        inserted, updated = upsert_jobs(session, jobs)
    finally:
        session.close()
    return len(jobs), inserted + updated, boards.new_boards