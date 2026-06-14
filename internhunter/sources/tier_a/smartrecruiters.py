from __future__ import annotations

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

_API_BASE = "https://api.smartrecruiters.com/v1/companies"
_PAGE_LIMIT = 100


def _build_location_raw(location: dict[str, Any] | None) -> str | None:
    if not location:
        return None
    parts = [
        str(location[key]).strip()
        for key in ("city", "region", "country")
        if location.get(key)
    ]
    value = ", ".join(parts)
    if location.get("remote"):
        value = f"{value}, Remote" if value else "Remote"
    return value or None


def _sections_to_html(sections: dict[str, Any] | None) -> str:
    if not sections:
        return ""
    fragments: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        title = section.get("title")
        text = section.get("text")
        if title:
            fragments.append(f"<h2>{title}</h2>")
        if text:
            fragments.append(text)
    return "\n".join(fragments)


@register_source
class SmartRecruitersSource(Source):
    ats: str = "smartrecruiters"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_API_BASE}/{ref.token}/postings"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        base = self.board_url(ref)
        offset = 0
        while True:
            page = await ctx.get_json(
                base, params={"limit": _PAGE_LIMIT, "offset": offset}
            )
            content = page.get("content") or []
            for posting in content:
                detail = await self._fetch_detail(ref, ctx, posting.get("id"))
                yield RawPosting(raw=posting, detail=detail)
            total_found = int(page.get("totalFound") or 0)
            offset += _PAGE_LIMIT
            if offset >= total_found or not content:
                break

    async def _fetch_detail(
        self, ref: BoardRef, ctx: FetchContext, posting_id: str | None
    ) -> dict[str, Any] | None:
        if not posting_id:
            return None
        url = f"{_API_BASE}/{ref.token}/postings/{posting_id}"
        try:
            data = await ctx.get_json(url)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            ctx.logger.debug("smartrecruiters detail fetch failed for {}: {}", posting_id, exc)
            return None

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        posting = raw.raw
        detail = raw.detail or {}

        source_job_id = posting.get("id")
        title = posting.get("name") or ""
        canonical_url = f"https://jobs.smartrecruiters.com/{ref.token}/{source_job_id}"
        url_hash = make_url_hash(canonical_url)
        job_uid = make_job_uid(self.ats, ref.token, source_job_id, canonical_url)

        company = ref.company or ref.token
        company_slug = normalize_company_slug(company)

        location = posting.get("location") or {}
        location_raw = _build_location_raw(location)
        loc = normalize_location(location_raw)

        sections = (detail.get("jobAd") or {}).get("sections")
        description_html = _sections_to_html(sections) or None
        description_text = html_to_text(description_html)

        department = (posting.get("department") or {}).get("label")
        employment_type = (posting.get("typeOfEmployment") or {}).get("label")
        function_label = (posting.get("function") or {}).get("label")

        classification = classify_internship(title, description_text)

        posted_at = parse_datetime(posting.get("releasedDate"))
        deadline_at = extract_deadline(description_text)
        rolling = is_rolling(description_text)

        sectors = [function_label] if function_label else []

        now = datetime.now(UTC)

        # Persist the detail `creator` (recruiter name) instead of dropping it — the
        # contacts pipeline mines it. Merge into the stored raw (no schema change).
        stored_raw = dict(posting)
        creator = detail.get("creator")
        if creator:
            stored_raw["creator"] = creator

        return NormalizedJob(
            job_uid=job_uid,
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=url_hash,
            company=company,
            company_slug=company_slug,
            title=title,
            title_normalized=normalize_title(title),
            department=department,
            employment_type=employment_type,
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw,
            location_normalized=loc.normalized,
            country=loc.country,
            region=loc.region,
            city=loc.city,
            is_remote=loc.is_remote or bool(location.get("remote")),
            remote_scope=loc.remote_scope,
            description_text=description_text,
            description_html=description_html,
            posted_at=posted_at,
            deadline_at=deadline_at,
            is_rolling=rolling,
            sectors=sectors,
            first_seen_at=now,
            last_seen_at=now,
            raw=stored_raw,
        )
