from __future__ import annotations

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
    the page (redirects + embedded board links) often reveals the real board.
    Returns (jobs_examined, new_boards).
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

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    async with build_fetch_context(resolved) as ctx:
        for url in urls:
            direct = detect_from_url(url)
            candidates = [direct] if direct is not None else []
            try:
                html = await ctx.get_text(url, respect_robots=False)
                candidates.extend(detect_from_html(html))
            except Exception:
                pass
            for det in candidates:
                if det is None:
                    continue
                key = (det.ats, det.token)
                if key in seen:
                    continue
                seen.add(key)
                detections.append(det)

    merged = merge_boards([detection_to_board_ref(d) for d in detections])
    return len(urls), merged.new_boards
