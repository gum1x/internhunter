"""Oracle Taleo career sites (*.taleo.net). Legacy, tenant-specific markup with no stable
keyless JSON, so this renders the career section and reads schema.org JobPosting JSON-LD.
Best-effort — yields nothing (rather than raising) when a tenant doesn't expose it. crt_bulk
discovers the boards; this makes them pollable."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

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
from internhunter.sources.tier_c.successfactors import _location_of, extract_postings


@register_source
class TaleoSource(Source):
    ats: str = "taleo"
    tier: Tier = Tier.C
    needs_browser: bool = True

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.taleo.net/careersection/jobsearch.ftl"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        if ctx.browser is None:
            return
        try:
            markup = await ctx.browser.render(self.board_url(ref), timeout=30.0)
        except Exception:
            ctx.logger.debug("taleo render failed for {}", ref.token)
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
        company = ref.company or ref.token
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
