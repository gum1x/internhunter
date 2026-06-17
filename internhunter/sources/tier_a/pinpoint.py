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
    parts = [
        str(location[key]).strip()
        for key in ("city", "province", "name")
        if location.get(key)
    ]
    if parts:
        return ", ".join(dict.fromkeys(parts))
    return None


@register_source
class PinpointSource(Source):
    ats: str = "pinpoint"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.pinpointhq.com/postings.json"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        payload = await ctx.get_json(self.board_url(ref))
        postings = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(postings, list):
            return
        for posting in postings:
            if isinstance(posting, dict):
                yield RawPosting(raw=posting)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        posting = raw.raw
        title = str(posting.get("title") or "").strip()
        source_job_id = str(posting["id"]) if posting.get("id") is not None else None
        canonical_url = str(posting.get("url") or self.board_url(ref)).strip()

        description_html = posting.get("description")
        description_text = html_to_text(description_html)

        location = posting.get("location")
        location = location if isinstance(location, dict) else {}
        location_raw = _build_location(location)
        loc = normalize_location(location_raw)
        workplace_type = str(posting.get("workplace_type") or "").lower()
        is_remote = loc.is_remote or workplace_type in {"remote", "fully_remote"}
        remote_scope = loc.remote_scope
        if workplace_type == "hybrid":
            is_remote = True
            remote_scope = remote_scope or "hybrid"
        elif is_remote and remote_scope is None:
            remote_scope = "fully_remote"

        job = posting.get("job")
        job = job if isinstance(job, dict) else {}
        department = job.get("department")
        department_name = (
            department.get("name") if isinstance(department, dict) else None
        )

        classification = classify_internship(title, description_text)
        deadline_at = parse_datetime(posting.get("deadline_at")) or extract_deadline(
            description_text
        )
        rolling = is_rolling(description_text)
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
            department=department_name,
            employment_type=posting.get("employment_type"),
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw,
            location_normalized=loc.normalized,
            country=loc.country,
            region=loc.region or location.get("province"),
            city=loc.city or location.get("city"),
            is_remote=is_remote,
            remote_scope=remote_scope,
            description_text=description_text,
            description_html=description_html,
            deadline_at=deadline_at,
            is_rolling=rolling,
            first_seen_at=now,
            last_seen_at=now,
            raw=posting,
        )
