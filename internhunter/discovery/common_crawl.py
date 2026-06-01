from __future__ import annotations

import json
from urllib.parse import urlencode

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_url

_ATS_PATTERNS: dict[str, str] = {
    "greenhouse": "boards.greenhouse.io/*",
    "lever": "jobs.lever.co/*",
    "ashby": "jobs.ashbyhq.com/*",
    "smartrecruiters": "jobs.smartrecruiters.com/*",
    "workable": "apply.workable.com/*",
    "recruitee": "*.recruitee.com/*",
    "personio": "*.jobs.personio.de/*",
    "breezy": "*.breezy.hr/*",
    "jazzhr": "*.applytojob.com/*",
    "jobvite": "jobs.jobvite.com/careers/*",
    "bamboohr": "*.bamboohr.com/*",
    "rippling": "*.rippling-ats.com/*",
    "dover": "jobs.dover.com/companies/*",
    "zohorecruit": "*.zohorecruit.com/*",
    "workday": "*.myworkdayjobs.com/*",
    "icims": "careers.icims.com/jobs/*",
    "adp": "jobs.adp.com/company/*",
    "ultipro": "recruiting.ultipro.com/*",
    "oracle_cloud": "*.fa.oraclecloud.com/*",
}

_COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
_FALLBACK_CRAWL = "CC-MAIN-2024-38"


def _cdx_url(crawl: str, pattern: str) -> str:
    query = urlencode({"url": pattern, "output": "json"})
    return f"https://index.commoncrawl.org/{crawl}-index?{query}"


async def latest_crawl(ctx: FetchContext) -> str:
    try:
        data = await ctx.get_json(_COLLINFO_URL, respect_robots=False)
        crawl_id = data[0]["id"]
        if isinstance(crawl_id, str) and crawl_id:
            return crawl_id
    except Exception:
        ctx.logger.debug("failed to resolve latest common crawl")
    return _FALLBACK_CRAWL


async def discover_from_common_crawl(
    ctx: FetchContext,
    ats: list[str] | None = None,
    crawl: str | None = None,
    limit_per_ats: int = 1000,
) -> list[Detection]:
    resolved_crawl = crawl if crawl is not None else await latest_crawl(ctx)
    requested = ats if ats is not None else list(_ATS_PATTERNS)

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []

    for name in requested:
        pattern = _ATS_PATTERNS.get(name)
        if pattern is None:
            continue
        url = _cdx_url(resolved_crawl, pattern)
        try:
            text = await ctx.get_text(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("common crawl fetch failed for {}", name)
            continue

        count = 0
        for line in text.splitlines():
            if count >= limit_per_ats:
                break
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            count += 1
            record_url = record.get("url")
            if not isinstance(record_url, str):
                continue
            detection = detect_from_url(record_url)
            if detection is None:
                continue
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)

    return detections
