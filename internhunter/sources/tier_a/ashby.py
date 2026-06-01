from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

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

_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"


@register_source
class AshbySource(Source):
    ats: str = "ashby"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_API_BASE}/{ref.token}?includeCompensation=true"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        url = f"{_API_BASE}/{ref.token}"
        payload = await ctx.get_json(url, params={"includeCompensation": "true"})
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        for job in jobs or []:
            if isinstance(job, dict):
                yield RawPosting(raw=job)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        data = raw.raw

        title = str(data.get("title") or "").strip()
        description_html = data.get("descriptionHtml")
        description_plain = data.get("descriptionPlain")
        description_text = (
            description_plain.strip()
            if isinstance(description_plain, str) and description_plain.strip()
            else html_to_text(description_html)
        )

        location_parts = [data.get("location")]
        secondary = data.get("secondaryLocations")
        if isinstance(secondary, list):
            location_parts.extend(
                item.get("location") for item in secondary if isinstance(item, dict)
            )
        location_raw = ", ".join(
            part.strip() for part in location_parts if isinstance(part, str) and part.strip()
        ) or None
        location = normalize_location(location_raw)
        is_remote = location.is_remote or bool(data.get("isRemote"))

        department = data.get("department") or data.get("departmentName") or data.get("team")

        url = str(data.get("jobUrl") or data.get("applyUrl") or self.board_url(ref))
        source_job_id = str(data.get("id")) if data.get("id") is not None else None

        classification = classify_internship(title, description_text)

        compensation = data.get("compensation")
        salary_summary = None
        if isinstance(compensation, dict):
            salary_summary = compensation.get("compensationTierSummary")

        posted_at = parse_datetime(data.get("publishedAt"))
        deadline_at = extract_deadline(description_text)

        company = ref.company or data.get("organizationName")

        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, source_job_id, url),
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=url,
            url_hash=make_url_hash(url),
            company=company,
            company_slug=normalize_company_slug(company or ref.token),
            title=title,
            title_normalized=normalize_title(title),
            department=department,
            employment_type=data.get("employmentType"),
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
            description_html=description_html if isinstance(description_html, str) else None,
            salary_currency=None,
            posted_at=posted_at,
            deadline_at=deadline_at,
            is_rolling=is_rolling(description_text),
            first_seen_at=_now(),
            last_seen_at=_now(),
            raw={**data, **({"compensationTierSummary": salary_summary} if salary_summary else {})},
        )


def _now() -> datetime:
    return datetime.now(tz=UTC)
