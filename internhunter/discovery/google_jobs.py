"""Approximate Google Jobs without scraping Google.

Google Jobs is itself an aggregator of schema.org ``JobPosting`` data harvested from employer
sites — there's no public API and the for-jobs SERP is bot-hostile. So we approximate it with
pieces we already have: query SearXNG (Google engine) for intern postings, then run the JSON-LD
harvester over the result URLs to extract the same schema.org postings + fingerprint embedded
ATS boards. Inert if ``settings.searxng_url`` is empty (same gating as the searxng channel).
"""
from __future__ import annotations

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import init_db
from internhunter.core.fetch import FetchContext, build_fetch_context
from internhunter.discovery.fingerprint import Detection, detect_from_url, detection_to_board_ref
from internhunter.discovery.jsonld import discover_from_jsonld
from internhunter.discovery.merge import merge_boards

_QUERIES = (
    'intern OR "co-op" OR "summer 2026" "JobPosting"',
    'internship apply "early career"',
)


async def _search_urls(ctx: FetchContext, base_url: str) -> list[str]:
    from urllib.parse import urlencode

    urls: list[str] = []
    seen: set[str] = set()
    for query in _QUERIES:
        params = urlencode({"q": query, "format": "json", "engines": "google"})
        try:
            data = await ctx.get_json(
                f"{base_url.rstrip('/')}/search?{params}", respect_robots=False
            )
        except Exception:
            ctx.logger.debug("google_jobs searxng query failed: {}", query)
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            continue
        for result in results:
            url = result.get("url") if isinstance(result, dict) else None
            if isinstance(url, str) and url.startswith("http") and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


async def ingest_google_jobs(settings: Settings | None = None) -> tuple[int, int, int]:
    """Returns (urls_examined, jobs, new_boards) — jobs is 0 (we recover boards via JSON-LD)."""
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    if not resolved.searxng_url:
        return 0, 0, 0

    detections: list[Detection] = []
    seen: set[tuple[str, str]] = set()
    examined = 0
    async with build_fetch_context(resolved) as ctx:
        urls = await _search_urls(ctx, resolved.searxng_url)
        for url in urls:
            examined += 1
            # A result that is itself an ATS posting resolves directly; otherwise read its JSON-LD.
            direct = detect_from_url(url)
            found = [direct] if direct is not None else await discover_from_jsonld(ctx, url)
            for det in found:
                if det is None:
                    continue
                key = (det.ats, det.token)
                if key in seen:
                    continue
                seen.add(key)
                detections.append(det)

    boards = merge_boards([detection_to_board_ref(d) for d in detections])
    return examined, 0, boards.new_boards
