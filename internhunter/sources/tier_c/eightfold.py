"""Eightfold-hosted career sites (e.g. *.eightfold.ai). Keyless JSON apply API, same shape
Netflix's careers use. Best-effort: tenant token -> apply/v2 jobs feed, filtered to intern."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.core.models import NormalizedJob
from internhunter.core.normalize import (
    make_job_uid,
    make_url_hash,
    normalize_company_slug,
    normalize_location,
    normalize_title,
    parse_datetime,
)
from internhunter.sources.base import BoardRef, RawPosting, Source, Tier, register_source


@register_source
class EightfoldSource(Source):
    ats: str = "eightfold"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return (
            f"https://{ref.token}.eightfold.ai/api/apply/v2/jobs"
            "?query=intern&num=100&start=0"
        )

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        data = await ctx.get_json(self.board_url(ref), respect_robots=False)
        positions = data.get("positions") if isinstance(data, dict) else None
        for item in positions or []:
            if isinstance(item, dict):
                yield RawPosting(raw=item)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        pos = raw.raw
        title = str(pos.get("name") or pos.get("title") or "").strip()
        canonical_url = str(
            pos.get("canonicalPositionUrl")
            or pos.get("job_url")
            or f"https://{ref.token}.eightfold.ai/careers?pid={pos.get('id')}"
        )
        source_job_id = str(pos["id"]) if pos.get("id") is not None else None
        location_raw = pos.get("location")
        location = normalize_location(location_raw if isinstance(location_raw, str) else None)
        classification = classify_internship(title, "")
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
            is_internship=classification.is_internship,
            internship_kind=classification.kind,
            level_tags=classification.level_tags,
            location_raw=location_raw if isinstance(location_raw, str) else None,
            location_normalized=location.normalized,
            country=location.country,
            region=location.region,
            city=location.city,
            is_remote=location.is_remote,
            remote_scope=location.remote_scope,
            posted_at=parse_datetime(pos.get("t_create")),
            first_seen_at=now,
            last_seen_at=now,
            raw=pos,
        )
