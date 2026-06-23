"""Phenom-hosted career sites (*.phenompeople.com). Best-effort keyless JSON jobs widget,
filtered to intern. Phenom markup/endpoints vary by tenant, so this fails soft."""
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


@register_source
class PhenomSource(Source):
    ats: str = "phenom"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.phenompeople.com/api/jobs?keywords=intern&limit=100"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        data = await ctx.get_json(self.board_url(ref), respect_robots=False)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        for item in jobs or []:
            row = item.get("data") if isinstance(item, dict) and "data" in item else item
            if isinstance(row, dict):
                yield RawPosting(raw=row)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        title = str(job.get("title") or job.get("name") or "").strip()
        canonical_url = str(job.get("applyUrl") or job.get("url") or job.get("jobUrl") or "")
        source_job_id = (
            str(job.get("jobId") or job.get("refNum") or job.get("id"))
            if (job.get("jobId") or job.get("refNum") or job.get("id")) is not None
            else None
        )
        location_raw = job.get("cityState") or job.get("location") or job.get("city")
        location = normalize_location(location_raw if isinstance(location_raw, str) else None)
        classification = classify_internship(title, "")
        company = ref.company or ref.token
        now = datetime.now(UTC)
        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, source_job_id, canonical_url),
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=make_url_hash(canonical_url),
            company=company,
            company_slug=normalize_company_slug(company),
            title=title,
            title_normalized=normalize_title(title),
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw if isinstance(location_raw, str) else None,
            location_normalized=location.normalized,
            country=location.country,
            region=location.region,
            city=location.city,
            is_remote=location.is_remote,
            remote_scope=location.remote_scope,
            posted_at=parse_datetime(job.get("postedDate") or job.get("dateCreated")),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )
