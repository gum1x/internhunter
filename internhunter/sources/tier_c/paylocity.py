from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    extract_deadline,
    is_rolling,
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_location,
    normalize_title,
    parse_datetime,
)
from internhunter.sources.base import BoardRef, RawPosting, Source, Tier, register_source


def _build_location(job: dict[str, Any]) -> str | None:
    parts = [str(job[key]).strip() for key in ("city", "state") if job.get(key)]
    return ", ".join(parts) if parts else None


@register_source
class PaylocitySource(Source):
    ats: str = "paylocity"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://recruiting.paylocity.com/recruiting/v2/api/jobs?companyId={ref.token}"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        data = await ctx.get_json(self.board_url(ref))
        if isinstance(data, list):
            jobs = data
        elif isinstance(data, dict):
            jobs = data.get("jobs") or []
        else:
            jobs = []
        for job in jobs:
            yield RawPosting(raw=job)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        title = str(job.get("title", "")).strip()

        source_job_id = job.get("jobId") if job.get("jobId") is not None else job.get("id")
        source_job_id = str(source_job_id) if source_job_id is not None else None

        canonical_url = str(
            job.get("applyUrl")
            or f"https://recruiting.paylocity.com/recruiting/jobs/{source_job_id}/{ref.token}"
        )

        location_raw = _build_location(job)
        location = normalize_location(location_raw)

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
            location_raw=location_raw,
            location_normalized=location.normalized,
            country=location.country,
            region=location.region or job.get("state"),
            city=location.city or job.get("city"),
            is_remote=location.is_remote,
            remote_scope=location.remote_scope,
            posted_at=parse_datetime(job.get("postedDate")),
            deadline_at=extract_deadline(title),
            is_rolling=is_rolling(title),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )
