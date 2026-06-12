from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urlsplit

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_url

_SEARCH_BASE = "https://urlscan.io/api/v1/search/"

_ATS_QUERIES: dict[str, str] = {
    "greenhouse": "domain:greenhouse.io",
    "lever": "domain:lever.co",
    "ashby": "domain:ashbyhq.com",
    "workable": "domain:workable.com",
    "smartrecruiters": "domain:smartrecruiters.com",
    "recruitee": "domain:recruitee.com",
    "personio": "domain:personio.de",
    "breezy": "domain:breezy.hr",
    "jazzhr": "domain:applytojob.com",
    "bamboohr": "domain:bamboohr.com",
    "zohorecruit": "domain:zohorecruit.com",
    "workday": "domain:myworkdayjobs.com",
    "icims": "domain:icims.com",
}

_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Za-z]{2}$")


def _search_url(query: str, size: int = 100, search_after: str | None = None) -> str:
    params: dict[str, Any] = {"q": query, "size": size}
    if search_after:
        params["search_after"] = search_after
    return f"{_SEARCH_BASE}?{urlencode(params)}"


def _workday_token(url: str) -> str | None:
    parts = urlsplit(url if "//" in url else f"https://{url}")
    host = parts.netloc.lower()
    if not host.endswith(".myworkdayjobs.com"):
        return None
    labels = host.split(".")
    if len(labels) < 4:
        return None
    tenant = labels[0]
    if not tenant:
        return None
    for segment in (s for s in parts.path.split("/") if s):
        if _LOCALE_RE.match(segment) or segment.lower() == "wday":
            continue
        return f"{tenant}/{segment}"
    return None


def _detection_from_url(url: str) -> Detection | None:
    token = _workday_token(url)
    if token is not None:
        return Detection("workday", token, url)
    return detect_from_url(url)


def _result_urls(data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for result in data.get("results", []):
        if not isinstance(result, dict):
            continue
        for key in ("task", "page"):
            obj = result.get(key)
            value = obj.get("url") if isinstance(obj, dict) else None
            if isinstance(value, str):
                urls.append(value)
    return urls


async def discover_from_urlscan(
    ctx: FetchContext,
    ats: list[str] | None = None,
    max_pages: int = 3,
    size: int = 100,
) -> list[Detection]:
    requested = ats if ats is not None else list(_ATS_QUERIES)
    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []

    for name in requested:
        query = _ATS_QUERIES.get(name)
        if query is None:
            continue
        search_after: str | None = None
        for _ in range(max_pages):
            try:
                data = await ctx.get_json(
                    _search_url(query, size, search_after), respect_robots=False
                )
            except Exception:
                ctx.logger.debug("urlscan fetch failed for {}", name)
                break
            if not isinstance(data, dict):
                break
            results = data.get("results")
            if not isinstance(results, list) or not results:
                break
            for url in _result_urls(data):
                detection = _detection_from_url(url)
                if detection is None:
                    continue
                key = (detection.ats, detection.token)
                if key in seen:
                    continue
                seen.add(key)
                detections.append(detection)
            if not data.get("has_more"):
                break
            last_sort = results[-1].get("sort") if isinstance(results[-1], dict) else None
            if not isinstance(last_sort, list) or not last_sort:
                break
            search_after = ",".join(str(part) for part in last_sort)

    return detections
