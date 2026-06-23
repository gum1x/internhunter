"""SAP SuccessFactors career sites (*.successfactors.com). No clean keyless JSON feed, so this
renders the careers page with the browser and reads schema.org JobPosting JSON-LD. Highly
tenant-dependent and best-effort — yields nothing (rather than raising) when it can't parse."""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_location,
    normalize_title,
    parse_datetime,
)
from internhunter.sources.base import BoardRef, RawPosting, Source, Tier, register_source

_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _collect_postings(node: object, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() == "jobposting" for x in types):
            out.append(node)
        for value in node.values():
            _collect_postings(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_postings(item, out)


def extract_postings(markup: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for match in _SCRIPT_RE.finditer(markup or ""):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        _collect_postings(data, postings)
    return postings


def _location_of(posting: dict[str, Any]) -> str | None:
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


@register_source
class SuccessFactorsSource(Source):
    ats: str = "successfactors"
    tier: Tier = Tier.C
    needs_browser: bool = True

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.successfactors.com/"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        if ctx.browser is None:
            return
        try:
            markup = await ctx.browser.render(self.board_url(ref), timeout=30.0)
        except Exception:
            ctx.logger.debug("successfactors render failed for {}", ref.token)
            return
        for posting in extract_postings(markup):
            yield RawPosting(raw=posting)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        posting = raw.raw
        title = str(posting.get("title") or "").strip()
        canonical_url = str(posting.get("url") or posting.get("applyUrl") or "")
        location_raw = _location_of(posting)
        location = normalize_location(location_raw)
        classification = classify_internship(title, "")
        org = posting.get("hiringOrganization")
        company = (
            org.get("name") if isinstance(org, dict) and isinstance(org.get("name"), str)
            else (ref.company or ref.token)
        )
        now = datetime.now(UTC)
        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, None, canonical_url),
            ats=self.ats,
            board_token=ref.token,
            canonical_url=canonical_url,
            url_hash=make_url_hash(canonical_url),
            company=company,
            company_slug=normalize_company_slug(company),
            title=title,
            title_normalized=normalize_title(title),
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw,
            location_normalized=location.normalized,
            country=location.country,
            region=location.region,
            city=location.city,
            is_remote=location.is_remote,
            remote_scope=location.remote_scope,
            posted_at=parse_datetime(posting.get("datePosted")),
            first_seen_at=now,
            last_seen_at=now,
            raw=posting,
        )
