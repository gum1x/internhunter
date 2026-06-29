from __future__ import annotations

import asyncio

from sqlalchemy import select

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Job, get_session, init_db
from internhunter.core.fetch import build_fetch_context
from internhunter.discovery.fingerprint import (
    Detection,
    detect_from_html,
    detect_from_url,
    detection_to_board_ref,
)
from internhunter.discovery.merge import merge_boards


async def reresolve_listings(
    settings: Settings | None = None, limit: int = 2000
) -> tuple[int, int]:
    """Recover real ATS boards from jobs stored as ats='listing'.

    These got 'listing' because their apply URL didn't fingerprint at ingest. Following
    the page (redirects + embedded board links) often reveals the real board. Bounded by
    settings.reresolve_budget_seconds; returns (jobs_examined_within_budget, new_boards).
    """
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    session = get_session()
    try:
        urls = list(
            session.scalars(
                select(Job.canonical_url)
                .where(Job.ats == "listing")
                .distinct()
                .limit(limit)
            )
        )
    finally:
        session.close()
    if not urls:
        return 0, 0

    async with build_fetch_context(resolved) as ctx:
        async def probe(url: str) -> list[Detection]:
            direct = detect_from_url(url)
            candidates = [direct] if direct is not None else []
            try:
                html = await ctx.get_text(url, respect_robots=False)
                candidates.extend(detect_from_html(html))
            except Exception:
                pass
            return [c for c in candidates if c is not None]

        # Fetch concurrently (bounded by the context's global/per-host semaphores) under a
        # wall-clock budget. Many listing URLs are slow JS portals clustered on a few hosts,
        # so a full serial pass took ~28min and stalled discover-all. Whatever isn't probed
        # in the budget stays ats='listing' and is retried next run.
        tasks = [asyncio.create_task(probe(url)) for url in urls]
        done, pending = await asyncio.wait(tasks, timeout=resolved.reresolve_budget_seconds)
        for task in pending:
            task.cancel()
        probed = [task.result() for task in done]

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for candidates in probed:
        for det in candidates:
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(det)

    merged = merge_boards([detection_to_board_ref(d) for d in detections])
    return len(probed), merged.new_boards
