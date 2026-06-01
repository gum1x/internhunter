from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import EmploymentType, NormalizedJob
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

_API_BASE = "https://api.lever.co/v0/postings"

_COMMITMENT_MAP: dict[str, str] = {
    "full-time": EmploymentType.full_time.value,
    "full time": EmploymentType.full_time.value,
    "part-time": EmploymentType.part_time.value,
    "part time": EmploymentType.part_time.value,
    "contract": EmploymentType.contract.value,
    "intern": EmploymentType.internship.value,
    "internship": EmploymentType.internship.value,
    "temporary": EmploymentType.temporary.value,
}


@register_source
class LeverSource(Source):
    ats: str = "lever"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_API_BASE}/{ref.token}?mode=json"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        url = f"{_API_BASE}/{ref.token}"
        payload = await ctx.get_json(url, params={"mode": "json"})
        if not isinstance(payload, list):
            return
        for entry in payload:
            if isinstance(entry, dict):
                yield RawPosting(raw=entry)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        data = raw.raw
        categories = data.get("categories") or {}

        title = str(data.get("text") or "")
        description_html = data.get("description")
        description_text = data.get("descriptionPlain") or html_to_text(description_html)

        location_raw = categories.get("location")
        location = normalize_location(location_raw)

        commitment = categories.get("commitment")
        employment_type: str | None = None
        if commitment:
            employment_type = _COMMITMENT_MAP.get(str(commitment).strip().lower())

        classification = classify_internship(title, description_text)

        canonical_url = str(data.get("hostedUrl") or data.get("applyUrl") or "")
        url_hash = make_url_hash(canonical_url)
        source_job_id = data.get("id")
        source_job_id_str = str(source_job_id) if source_job_id is not None else None
        job_uid = make_job_uid(self.ats, ref.token, source_job_id_str, canonical_url)

        posted_at = parse_datetime(data.get("createdAt"))
        deadline_at = extract_deadline(description_text)
        rolling = is_rolling(description_text)

        company = ref.company
        company_slug = normalize_company_slug(company or ref.token)

        now = datetime.now(tz=UTC)

        return NormalizedJob(
            job_uid=job_uid,
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id_str,
            canonical_url=canonical_url,
            url_hash=url_hash,
            company=company,
            company_slug=company_slug,
            title=title,
            title_normalized=normalize_title(title),
            department=categories.get("team"),
            employment_type=employment_type,
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
            description_html=description_html,
            posted_at=posted_at,
            deadline_at=deadline_at,
            is_rolling=rolling,
            first_seen_at=now,
            last_seen_at=now,
            raw=data,
        )
