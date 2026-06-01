from __future__ import annotations

import html
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    extract_deadline,
    html_to_text,
    is_rolling,
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_location,
    normalize_title,
    parse_datetime,
)
from internhunter.sources.base import BoardRef, RawPosting, Source, Tier, register_source


@register_source
class GreenhouseSource(Source):
    ats: str = "greenhouse"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{ref.token}/jobs?content=true"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload: dict[str, Any] = await ctx.get_json(self.board_url(ref))
        for job in payload.get("jobs", []):
            yield RawPosting(raw=job)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        source_job_id = str(job["id"]) if job.get("id") is not None else None
        canonical_url = job["absolute_url"]
        url_hash = make_url_hash(canonical_url)
        job_uid = make_job_uid(self.ats, ref.token, source_job_id, canonical_url)

        title = job.get("title", "")
        location_raw = (job.get("location") or {}).get("name")
        location = normalize_location(location_raw)

        description_html = html.unescape(job.get("content") or "")
        description_text = html_to_text(description_html)

        departments = job.get("departments") or []
        department = departments[0].get("name") if departments else None

        classification = classify_internship(title, description_text)

        updated_at = parse_datetime(job.get("updated_at"))
        deadline_at = extract_deadline(description_text)
        now = datetime.now(UTC)

        company = ref.company or ref.token

        return NormalizedJob(
            job_uid=job_uid,
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=url_hash,
            company=company,
            company_slug=normalize_company_slug(company),
            title=title,
            title_normalized=normalize_title(title),
            department=department,
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
            description_text=description_text,
            description_html=description_html or None,
            posted_at=updated_at,
            updated_at=updated_at,
            deadline_at=deadline_at,
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )
