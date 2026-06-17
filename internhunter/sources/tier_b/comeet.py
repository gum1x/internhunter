from __future__ import annotations

import json
import re
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

_BASE_URL = "https://www.comeet.com"
_POSITIONS_RE = re.compile(r"COMPANY_POSITIONS_DATA\s*=\s*(\[.*?\]);", re.DOTALL)


def _board_path(token: str) -> str:
    return token.strip("/")


def _build_location(location: dict[str, Any]) -> str | None:
    name = location.get("name")
    if name:
        return str(name).strip()
    parts = [
        str(location[key]).strip()
        for key in ("city", "state", "country")
        if location.get(key)
    ]
    if parts:
        return ", ".join(parts)
    return None


@register_source
class ComeetSource(Source):
    ats: str = "comeet"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_BASE_URL}/jobs/{_board_path(ref.token)}"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        html = await ctx.get_text(self.board_url(ref))
        match = _POSITIONS_RE.search(html)
        if match is None:
            ctx.logger.debug("comeet positions data not found for {}", ref.token)
            return
        try:
            positions = json.loads(match.group(1))
        except json.JSONDecodeError:
            ctx.logger.debug("comeet positions parse failed for {}", ref.token)
            return
        for position in positions:
            yield RawPosting(raw=position)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        position = raw.raw
        title = str(position.get("name") or "").strip()
        source_job_id = str(position["uid"]) if position.get("uid") else None

        canonical_url = str(
            position.get("url_comeet_hosted_page")
            or position.get("url_active_page")
            or self.board_url(ref)
        )

        location_data = position.get("location") or {}
        location_raw = (
            _build_location(location_data) if isinstance(location_data, dict) else None
        )
        location = normalize_location(location_raw)
        is_remote = location.is_remote or bool(
            location_data.get("is_remote") if isinstance(location_data, dict) else False
        )

        department = position.get("department")
        employment_type = position.get("employment_type")

        description_text = ""
        classification = classify_internship(title, description_text)
        company = ref.company or str(position.get("company_name") or "") or ref.token
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
            department=str(department).strip() if department else None,
            employment_type=str(employment_type).strip() if employment_type else None,
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
            posted_at=parse_datetime(position.get("time_updated")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=position,
        )
