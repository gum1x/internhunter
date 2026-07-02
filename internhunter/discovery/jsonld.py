from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_url

_MAX_DEPTH = 100


def _walk(node: object, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        return
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() == "jobposting" for x in types):
            out.append(node)
        for value in node.values():
            _walk(value, out, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out, depth + 1)


def _ld_json_blocks(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    return [
        script.string or script.get_text()
        for script in soup.find_all("script", type="application/ld+json")
    ]


def extract_jobpostings(html: str) -> list[dict[str, Any]]:
    """Every schema.org JobPosting object (as a dict) found in the page's JSON-LD."""
    postings: list[dict[str, Any]] = []
    for block in _ld_json_blocks(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        _walk(data, postings)
    return postings


def extract_jobposting_urls(html: str, page_url: str | None = None) -> list[str]:
    """Pull apply/posting URLs from any schema.org JobPosting JSON-LD on the page."""
    urls: list[str] = []
    for posting in extract_jobpostings(html):
        for key in ("url", "applyUrl", "sameAs"):
            value = posting.get(key)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
        org = posting.get("hiringOrganization")
        if isinstance(org, dict) and isinstance(org.get("sameAs"), str):
            urls.append(org["sameAs"])
    if page_url:
        urls.append(page_url)
    # dedupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def discover_from_jsonld(ctx: FetchContext, url: str) -> list[Detection]:
    """Fetch a careers page, read JobPosting JSON-LD, resolve any ATS board behind it."""
    try:
        html = await ctx.get_text(url, respect_robots=False)
    except Exception:
        ctx.logger.debug("jsonld fetch failed for {}", url)
        return []
    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for candidate in extract_jobposting_urls(html, page_url=url):
        det = detect_from_url(candidate)
        if det is None:
            continue
        key = (det.ats, det.token)
        if key in seen:
            continue
        seen.add(key)
        detections.append(det)
    return detections
