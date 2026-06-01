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


def _build_location(location: dict[str, Any]) -> str | None:
    name = location.get("name")
    if name:
        return str(name).strip()
    country = location.get("country")
    country_name = (
        str(country["name"]).strip()
        if isinstance(country, dict) and country.get("name")
        else None
    )
    parts = [
        part
        for part in (
            str(location["city"]).strip() if location.get("city") else None,
            country_name,
        )
        if part
    ]
    if parts:
        return ", ".join(parts)
    return None


@register_source
class BreezyHrSource(Source):
    ats: str = "breezy"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.breezy.hr/json"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload = await ctx.get_json(self.board_url(ref))
        for position in payload:
            yield RawPosting(raw=position)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        position = raw.raw
        title = str(position.get("name") or "").strip()
        source_job_id = str(position["_id"]) if position.get("_id") else None

        canonical_url = str(
            position.get("url")
            or f"https://{ref.token}.breezy.hr/p/{source_job_id}"
        )

        description_html = position.get("description")
        description_text = html_to_text(description_html)

        position_type = position.get("type")
        employment_type = (
            str(position_type["name"])
            if isinstance(position_type, dict) and position_type.get("name")
            else None
        )

        category = position.get("category")
        department = (
            str(category["name"])
            if isinstance(category, dict) and category.get("name")
            else None
        )

        location_data = position.get("location") or {}
        location_raw = _build_location(location_data) if isinstance(location_data, dict) else None
        location = normalize_location(location_raw)
        is_remote = location.is_remote or bool(
            location_data.get("is_remote") if isinstance(location_data, dict) else False
        )

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
            department=department,
            employment_type=employment_type,
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
            description_html=description_html,
            posted_at=parse_datetime(position.get("published_date")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=position,
        )
