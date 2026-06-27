"""Extract full schema.org ``JobPosting`` objects (title + apply URL + location + company) from a
page's JSON-LD — the listing-level counterpart to ``jsonld.extract_jobposting_urls`` (which only
returns URLs). Used by aggregator ingestors (Idealist, Forage, …) that publish JobPosting JSON-LD.
"""
from __future__ import annotations

import json
import re
from typing import Any

from internhunter.discovery.listing_common import ListingJob

_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _collect(node: object, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and "jobposting" in x.lower() for x in types):
            out.append(node)
        for value in node.values():
            _collect(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect(item, out)


def _location_str(posting: dict[str, Any]) -> str | None:
    loc = posting.get("jobLocation")
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion"),
                     addr.get("addressCountry")]
            joined = ", ".join(p for p in parts if isinstance(p, str) and p)
            return joined or None
    return None


def listings_from_html(markup: str, source: str) -> list[ListingJob]:
    postings: list[dict[str, Any]] = []
    for match in _SCRIPT_RE.finditer(markup or ""):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        _collect(data, postings)

    jobs: list[ListingJob] = []
    for p in postings:
        title = str(p.get("title") or "").strip()
        url = p.get("url") or p.get("applyUrl")
        if not title or not isinstance(url, str) or not url.startswith("http"):
            continue
        org = p.get("hiringOrganization")
        company = org.get("name") if isinstance(org, dict) else None
        jobs.append(
            ListingJob(
                title=title,
                company=company if isinstance(company, str) else None,
                url=url,
                location=_location_str(p),
                posted=p.get("datePosted"),
                source=source,
            )
        )
    return jobs
