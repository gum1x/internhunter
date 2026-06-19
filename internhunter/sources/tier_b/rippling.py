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
    work_location = raw.get("workLocation")
    if isinstance(work_location, dict):
        label = work_location.get("label")
        if label:
            return str(label).strip()
    location = raw.get("location")
    return str(location).strip() if location else None


@register_source
class RipplingSource(Source):
    ats: str = "rippling"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.rippling-ats.com/api/jobs"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload = await ctx.get_json(self.board_url(ref))
        if not isinstance(payload, list):
            return
        for job in payload:
            yield RawPosting(raw=job)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        title = str(job.get("name", "")).strip()
        description_text = ""

        source_job_id = str(job["id"]) if job.get("id") is not None else None
        canonical_url = str(
            job.get("url") or f"https://{ref.token}.rippling-ats.com/jobs/{source_job_id}"
        )

        department = job.get("department")
        if isinstance(department, dict):
            department = department.get("label")

        location_raw = _build_location(job)
        location = normalize_location(location_raw)
        is_remote = location.is_remote or bool(job.get("isRemote"))

        classification = classify_internship(title, description_text)
        now = datetime.now(UTC)

        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, source_job_id, canonical_url),
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=make_url_hash(canonical_url),
            company=ref.company or ref.token,
            company_slug=normalize_company_slug(ref.company or ref.token),
            title=title,
            title_normalized=normalize_title(title),
            department=str(department).strip() if department else None,
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
            posted_at=parse_datetime(job.get("postedAt") or job.get("createdAt")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )
