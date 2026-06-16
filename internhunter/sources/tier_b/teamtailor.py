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

_JOB_LINK_RE = re.compile(r'href="(https://[^"]+\.teamtailor\.com/jobs/(\d+)[^"#?]*)"')
_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _base_url(token: str) -> str:
    return f"https://{token}.teamtailor.com"


def _build_location(job_location: Any) -> str | None:
    if isinstance(job_location, list):
        job_location = job_location[0] if job_location else None
    if not isinstance(job_location, dict):
        return None
    address = job_location.get("address")
    if not isinstance(address, dict):
        return None
    parts = [
        str(address[key]).strip()
        for key in ("addressLocality", "addressRegion", "addressCountry")
        if address.get(key)
    ]
    if parts:
        return ", ".join(parts)
    return None


@register_source
class TeamtailorSource(Source):
    ats: str = "teamtailor"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"{_base_url(ref.token)}/jobs"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        listing = await ctx.get_text(self.board_url(ref))
        seen: set[str] = set()
        for match in _JOB_LINK_RE.finditer(listing):
            job_url = match.group(1)
            if job_url in seen:
                continue
            seen.add(job_url)
            detail = await ctx.get_text(job_url)
            posting = _extract_job_posting(detail)
            if posting is None:
                ctx.logger.debug("teamtailor JobPosting not found for {}", job_url)
                continue
            yield RawPosting(raw=posting, detail={"url": job_url})

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        job = raw.raw
        title = str(job.get("title") or "").strip()

        identifier = job.get("identifier")
        source_job_id = (
            str(identifier["value"])
            if isinstance(identifier, dict) and identifier.get("value")
            else None
        )

        canonical_url = str((raw.detail or {}).get("url") or self.board_url(ref))

        description_html = job.get("description")
        description_text = html_to_text(description_html)

        location_raw = _build_location(job.get("jobLocation"))
        location = normalize_location(location_raw)

        employment_type = job.get("employmentType")

        hiring_org = job.get("hiringOrganization")
        org_name = (
            str(hiring_org["name"])
            if isinstance(hiring_org, dict) and hiring_org.get("name")
            else None
        )

        classification = classify_internship(title, description_text)
        company = ref.company or org_name or ref.token
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
            employment_type=str(employment_type).strip() if employment_type else None,
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
            posted_at=parse_datetime(job.get("datePosted")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=job,
        )


def _extract_job_posting(html: str) -> dict[str, Any] | None:
    for match in _LD_JSON_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None
