from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    html_to_text,
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_location,
    normalize_title,
    parse_datetime,
)
from internhunter.sources.base import BoardRef, RawPosting, Source, Tier, register_source


def _build_location(raw: dict[str, Any]) -> str | None:
    parts = [
        str(raw[key]).strip()
        for key in ("city", "state_code", "country_code")
        if raw.get(key)
    ]
    if parts:
        return ", ".join(parts)
    location = raw.get("location")
    return str(location).strip() if location else None


@register_source
class RecruiteeSource(Source):
    ats: str = "recruitee"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.recruitee.com/api/offers/"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload = await ctx.get_json(self.board_url(ref))
        for offer in payload.get("offers", []):
            yield RawPosting(raw=offer)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        offer = raw.raw
        title = str(offer.get("title", "")).strip()
        description_html = offer.get("description")
        requirements_html = offer.get("requirements")
        description_text = html_to_text(description_html)
        requirements_text = html_to_text(requirements_html)

        canonical_url = str(
            offer.get("careers_url") or offer.get("careers_apply_url") or self.board_url(ref)
        )
        source_job_id = str(offer["id"]) if offer.get("id") is not None else None

        location_raw = _build_location(offer)
        location = normalize_location(location_raw)
        is_remote = location.is_remote or bool(offer.get("remote"))

        classification = classify_internship(title, description_text)
        now = datetime.now(UTC)

        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, source_job_id, canonical_url),
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=make_url_hash(canonical_url),
            company=ref.company,
            company_slug=normalize_company_slug(ref.company or ref.token),
            title=title,
            title_normalized=normalize_title(title),
            department=offer.get("department"),
            employment_type=offer.get("employment_type_code"),
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw,
            location_normalized=location.normalized,
            country=location.country or offer.get("country_code"),
            region=location.region or offer.get("state_code"),
            city=location.city or offer.get("city"),
            is_remote=is_remote,
            remote_scope=location.remote_scope,
            description_text=description_text,
            description_html=description_html,
            requirements=[requirements_text] if requirements_text else [],
            posted_at=parse_datetime(offer.get("created_at")),
            first_seen_at=now,
            last_seen_at=now,
            raw=offer,
        )
