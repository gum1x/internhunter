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
