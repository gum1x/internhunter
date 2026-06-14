from __future__ import annotations

import json
from urllib.parse import urlencode

from internhunter.core.fetch import FetchContext
from internhunter.discovery.common_crawl import _ATS_PATTERNS
from internhunter.discovery.fingerprint import Detection, detect_from_url


def _host(pattern: str) -> str:
    # "boards.greenhouse.io/*" -> "boards.greenhouse.io"; "*.recruitee.com/*" -> "recruitee.com"
    host = pattern.split("/", 1)[0]
    return host[2:] if host.startswith("*.") else host


def _cdx_url(host: str, limit: int, page: int = 0) -> str:
    params: dict[str, object] = {
        "url": host,  # matchType=domain already covers subdomains/paths; a trailing * returns []
        "matchType": "domain",
        "collapse": "urlkey",
        "fl": "original",
        "output": "json",
        "limit": limit,
    }
    if page:
        params["page"] = page
    return f"http://web.archive.org/cdx/search/cdx?{urlencode(params)}"


def _parse_cdx(data: object, seen: set[tuple[str, str]], out: list[Detection]) -> int:
    """CDX JSON is a list of rows; the first row is a header. Returns rows parsed."""
    if not isinstance(data, list):
        return 0
    rows = data[1:] if data and isinstance(data[0], list) else data
    parsed = 0
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        parsed += 1
        det = detect_from_url(str(row[0]))
        if det is None:
            continue
        key = (det.ats, det.token)
        if key in seen:
            continue
        seen.add(key)
        out.append(det)
    return parsed


async def discover_from_wayback(
    ctx: FetchContext,
    ats: list[str] | None = None,
    limit_per_ats: int = 1000,
    max_pages: int = 3,
) -> list[Detection]:
    """A second keyless URL index (Wayback CDX) complementing Common Crawl.

    Different corpus, continuously refreshed — catches ATS boards created since the last
    Common Crawl snapshot. Everything dedupes via merge_boards and is liveness-checked at
    poll time, so stale captures are harmless.
    """
    requested = ats if ats is not None else list(_ATS_PATTERNS)
    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for name in requested:
        pattern = _ATS_PATTERNS.get(name)
        if pattern is None:
            continue
        host = _host(pattern)
        for page in range(max_pages):
            url = _cdx_url(host, limit_per_ats, page=page)
            try:
                text = await ctx.get_text(url, respect_robots=False)
            except Exception:
                ctx.logger.debug("wayback cdx failed for {} p{}", host, page)
                break
            if not text.strip():
                break
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                break
            n = _parse_cdx(data, seen, detections)
            if n == 0:
                break
    return detections
