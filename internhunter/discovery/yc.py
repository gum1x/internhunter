from __future__ import annotations

import asyncio
from typing import Any

from internhunter.core.fetch import FetchContext
from internhunter.discovery.careers import resolve_company_ats
from internhunter.discovery.fingerprint import Detection

_YC_URL = "https://yc-oss.github.io/api/companies/all.json"


async def fetch_yc_companies(
    ctx: FetchContext, limit: int | None = None
) -> list[dict[str, Any]]:
    data = await ctx.get_json(_YC_URL, respect_robots=False)
    if isinstance(data, list):
        companies = data
    elif isinstance(data, dict):
        companies = data.get("companies", [])
    else:
        companies = []
    active = [c for c in companies if isinstance(c, dict) and c.get("website")]
    return active[:limit] if limit is not None else active


async def discover_from_yc(ctx: FetchContext, limit: int = 400) -> list[Detection]:
    companies = await fetch_yc_companies(ctx, limit)
    sites = [c["website"] for c in companies if isinstance(c.get("website"), str)]
    resolved = await asyncio.gather(*(resolve_company_ats(ctx, site) for site in sites))

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for company_detections in resolved:
        for detection in company_detections:
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)
    return detections
