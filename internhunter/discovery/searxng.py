from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_url

_DEFAULT_QUERIES: list[str] = [
    "site:boards.greenhouse.io intern",
    "site:jobs.lever.co intern",
    "site:jobs.ashbyhq.com intern",
    "site:applytojob.com intern",
    "site:breezy.hr intern",
]


def _search_url(base_url: str, query: str) -> str:
    params = urlencode({"q": query, "format": "json"})
    return f"{base_url.rstrip('/')}/search?{params}"


async def discover_from_searxng(
    ctx: FetchContext,
    base_url: str,
    queries: list[str] | None = None,
    max_pages: int = 1,
) -> list[Detection]:
    resolved = queries if queries is not None else _DEFAULT_QUERIES

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []

    for query in resolved:
        url = _search_url(base_url, query)
        try:
            data: Any = await ctx.get_json(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("searxng search failed for {}", query)
            continue

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            continue

        for result in results:
            if not isinstance(result, dict):
                continue
            result_url = result.get("url")
            if not isinstance(result_url, str):
                continue
            detection = detect_from_url(result_url)
            if detection is None:
                continue
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)

    return detections
