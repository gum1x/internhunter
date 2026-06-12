from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx

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

_API_BASE = "https://apply.workable.com/api/v1"


@register_source
class WorkableSource(Source):
    ats: str = "workable"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_API_BASE}/widget/accounts/{ref.token}"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload = await ctx.get_json(self.board_url(ref), params={"details": "true"})
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            return
        for job in jobs:
            if not isinstance(job, dict):
                continue
            detail = await self._fetch_detail(ref, job, ctx)
            yield RawPosting(raw=job, detail=detail)

    async def _fetch_detail(
        self, ref: BoardRef, job: dict[str, Any], ctx: FetchContext
    ) -> dict[str, Any] | None:
        shortcode = job.get("shortcode")
        if not shortcode:
            return None
        if job.get("description"):
            return None
        url = f"{_API_BASE}/accounts/{ref.token}/jobs/{shortcode}"
        try:
            detail = await ctx.get_json(url)
        except (httpx.HTTPError, PermissionError) as exc:
            ctx.logger.debug("workable detail fetch failed for {}: {}", shortcode, exc)
            return None
        return detail if isinstance(detail, dict) else None

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        detail = raw.detail or {}

        title = str(job.get("title") or "").strip()
        shortcode = job.get("shortcode") or job.get("code")
        source_job_id = str(shortcode) if shortcode else None

        canonical_url = str(
            job.get("url") or detail.get("url") or job.get("application_url") or ""
        ).strip()
        if not canonical_url and source_job_id:
            canonical_url = f"https://apply.workable.com/{ref.token}/j/{source_job_id}/"

        description_html = detail.get("description") or job.get("description")
        description_text = html_to_text(description_html)

        raw_location = job.get("location")
        location: dict[str, Any] = raw_location if isinstance(raw_location, dict) else {}
        location_raw = self._location_raw(location)
        loc = normalize_location(location_raw)
        is_remote = loc.is_remote or bool(location.get("telecommuting"))
        remote_scope = loc.remote_scope
        if is_remote and remote_scope is None:
            remote_scope = "fully_remote"

        company = job.get("company") or detail.get("company") or ref.company
        company_str = str(company).strip() if company else None
        company_slug = normalize_company_slug(company_str or ref.token)

        classification = classify_internship(title, description_text)

        posted_at = parse_datetime(job.get("created_at") or detail.get("created_at"))
        updated_at = parse_datetime(detail.get("updated_at") or job.get("updated_at"))
        deadline_at = extract_deadline(description_text)
        rolling = is_rolling(description_text)

        now = datetime.now(UTC)

        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, source_job_id, canonical_url),
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=make_url_hash(canonical_url),
            company=company_str,
            company_slug=company_slug,
            company_domain=None,
            title=title,
            title_normalized=normalize_title(title),
            department=(job.get("department") or detail.get("department") or None),
            employment_type=(job.get("employment_type") or detail.get("employment_type") or None),
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw,
            location_normalized=loc.normalized,
            country=location.get("country") or loc.country,
            region=location.get("region") or loc.region,
            city=location.get("city") or loc.city,
            is_remote=is_remote,
            remote_scope=remote_scope,
            description_text=description_text,
            description_html=description_html,
            posted_at=posted_at,
            updated_at=updated_at,
            deadline_at=deadline_at,
            is_rolling=rolling,
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )

    def _location_raw(self, location: dict[str, Any]) -> str | None:
        location_str = location.get("location_str")
        if location_str:
            return str(location_str).strip()
        parts = [
            str(location.get(key)).strip()
            for key in ("city", "region", "country")
            if location.get(key)
        ]
        if location.get("telecommuting"):
            parts.append("Remote")
        return ", ".join(parts) if parts else None
