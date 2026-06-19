from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

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

_BASE_URL = "https://recruiting.paylocity.com"
_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{)")


def _board_guid(token: str) -> str:
    return token.strip("/").split("/")[0]


@register_source
class PaylocitySource(Source):
    ats: str = "paylocity"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_BASE_URL}/recruiting/jobs/All/{_board_guid(ref.token)}"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        html = await ctx.get_text(self.board_url(ref))
        match = _PAGE_DATA_RE.search(html)
        if match is None:
            ctx.logger.debug("paylocity pageData not found for {}", ref.token)
            return
        try:
            data, _ = json.JSONDecoder().raw_decode(html, match.start(1))
        except json.JSONDecodeError:
            ctx.logger.debug("paylocity pageData parse failed for {}", ref.token)
            return
        if not isinstance(data, dict):
            return
        for job in data.get("Jobs") or []:
            yield RawPosting(raw=job)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        title = str(job.get("JobTitle") or "").strip()
        source_job_id = str(job["JobId"]) if job.get("JobId") else None
        canonical_url = (
            f"{_BASE_URL}/Recruiting/Jobs/Details/{source_job_id}"
            if source_job_id
            else self.board_url(ref)
        )

        description_text = str(job.get("Description") or "")
        location_raw = job.get("LocationName")
        location = normalize_location(location_raw)

        classification = classify_internship(title, description_text)
        company = ref.company or _board_guid(ref.token)
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
            location_raw=location_raw,
            location_normalized=location.normalized,
            country=location.country,
            region=location.region,
            city=location.city,
            is_remote=location.is_remote or bool(job.get("IsRemote")),
            remote_scope=location.remote_scope,
            description_text=description_text,
            posted_at=parse_datetime(job.get("PublishedDate")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )
