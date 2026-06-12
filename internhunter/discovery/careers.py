from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_html

_CAREERS_PATHS = ("", "/careers", "/jobs", "/careers/jobs", "/company/careers")


def company_base(url: str) -> str | None:
    parts = urlsplit(url if "//" in url else f"https://{url}")
    if not parts.netloc:
        return None
    scheme = parts.scheme or "https"
    return urlunsplit((scheme, parts.netloc, "", "", ""))


async def resolve_company_ats(
    ctx: FetchContext, website: str, paths: tuple[str, ...] = _CAREERS_PATHS
) -> list[Detection]:
    base = company_base(website)
    if base is None:
        return []
    seen: set[tuple[str, str]] = set()
    found: list[Detection] = []
    for path in paths:
        try:
            html = await ctx.get_text(base + path)
        except Exception:
            continue
        for detection in detect_from_html(html):
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            found.append(detection)
        if found:
            break
    return found


async def resolve_company_ats_safe(
    ctx: FetchContext, website: str, timeout: float = 25.0
) -> list[Detection]:
    try:
        return await asyncio.wait_for(resolve_company_ats(ctx, website), timeout)
    except Exception:
        return []


async def resolve_many(
    ctx: FetchContext,
    websites: list[str],
    concurrency: int = 24,
    timeout: float = 25.0,
) -> list[Detection]:
    sem = asyncio.Semaphore(concurrency)

    async def _run(site: str) -> list[Detection]:
        async with sem:
            return await resolve_company_ats_safe(ctx, site, timeout)

    results = await asyncio.gather(*(_run(site) for site in websites))

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for company_detections in results:
        for detection in company_detections:
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)
    return detections
