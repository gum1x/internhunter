from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import (
    Detection,
    detect_from_html,
    detect_from_url,
)

# ATS host strings to grep GitHub source for. Mirrors the hosts common_crawl.py uses.
_ATS_HOSTS: dict[str, str] = {
    "greenhouse": "boards.greenhouse.io",
    "lever": "jobs.lever.co",
    "ashby": "jobs.ashbyhq.com",
    "recruitee": ".recruitee.com",
    "workable": "apply.workable.com",
    "pinpoint": "pinpointhq.com",
    "teamtailor": "teamtailor.com",
}

_SEARCH_BASE = "https://api.github.com/search/code"
# Code search is capped at ~10 req/min for authenticated users; stay well under it.
_PER_HOST_SLEEP = 7.0
_PER_PAGE = 30


def _search_url(host: str) -> str:
    params = {"q": f"{host} in:file", "per_page": _PER_PAGE}
    return f"{_SEARCH_BASE}?{urlencode(params)}"


def _extract(item: dict[str, Any], seen: set[tuple[str, str]], out: list[Detection]) -> None:
    """Pull Detections from a code-search result item (html_url + any text matches)."""
    candidates: list[Detection] = []
    html_url = item.get("html_url")
    if isinstance(html_url, str):
        det = detect_from_url(html_url)
        if det is not None:
            candidates.append(det)
    for match in item.get("text_matches") or []:
        fragment = match.get("fragment") if isinstance(match, dict) else None
        if isinstance(fragment, str):
            candidates.extend(detect_from_html(fragment))
    for det in candidates:
        key = (det.ats, det.token)
        if key in seen:
            continue
        seen.add(key)
        out.append(det)


async def discover_from_github_code(
    ctx: FetchContext,
    settings: Settings,
    ats: list[str] | None = None,
) -> list[Detection]:
    """Harvest ATS board tokens via GitHub code search.

    OPT-IN: requires ``settings.github_code_search`` to be True AND a GitHub token.
    Returns ``[]`` with no network call when disabled or unauthenticated, keeping the
    core keyless by default.
    """
    if not settings.github_code_search or not settings.github_token:
        ctx.logger.debug("github_code discovery disabled or no token; skipping")
        return []

    requested = ats if ats is not None else list(_ATS_HOSTS)
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github.text-match+json",
    }

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []

    for idx, name in enumerate(requested):
        host = _ATS_HOSTS.get(name)
        if host is None:
            continue
        if idx:
            await asyncio.sleep(_PER_HOST_SLEEP)
        try:
            data = await ctx.get_json(
                _search_url(host), headers=headers, respect_robots=False
            )
        except Exception:
            ctx.logger.debug("github_code search failed for {}", name)
            continue
        for item in data.get("items") or []:
            if isinstance(item, dict):
                _extract(item, seen, detections)

    return detections
