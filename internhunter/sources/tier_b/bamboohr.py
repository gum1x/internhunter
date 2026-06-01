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


def _build_location(raw: dict[str, Any]) -> str | None:
    location = raw.get("location") or raw.get("atsLocation") or {}
    parts = [
        str(location[key]).strip()
        for key in ("city", "state")
        if location.get(key)
    ]
    if parts:
        return ", ".join(parts)
    return None


@register_source
class BambooHrSource(Source):
    ats: str = "bamboohr"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.bamboohr.com/careers/list"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload = await ctx.get_json(self.board_url(ref))
        for job in payload.get("result", []):
            yield RawPosting(raw=job)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        title = str(job.get("jobOpeningName") or "").strip()
        source_job_id = str(job["id"]) if job.get("id") is not None else None
        canonical_url = f"https://{ref.token}.bamboohr.com/careers/{source_job_id}"

        description_text = ""

        location_raw = _build_location(job)
        location = normalize_location(location_raw)
        is_remote = location.is_remote or bool(job.get("isRemote"))

        classification = classify_internship(title, description_text)
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
            department=job.get("departmentLabel"),
            employment_type=job.get("employmentStatusLabel"),
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw,
            location_normalized=location.normalized,
            country=location.country,
            region=location.region,
            city=location.city,
            is_remote=is_remote,
            remote_scope=location.remote_scope,
            description_text=description_text,
            posted_at=parse_datetime(job.get("datePosted")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )
