from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

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

_BASE_URL = "https://jobs.jobvite.com"


def _location(anchor: Any) -> str | None:
    parent = anchor.parent
    if parent is None:
        return None
    node = parent.find(class_=lambda value: bool(value) and "jv-job-list-location" in value)
    if node is None:
        return None
    value = node.get_text(strip=True)
    return value or None


@register_source
class JobviteSource(Source):
    ats: str = "jobvite"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://jobs.jobvite.com/careers/{ref.token}/jobs"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        html = await ctx.get_text(self.board_url(ref))
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if "/job/" not in href:
                continue
            title = anchor.get_text(strip=True)
            if not title:
                continue
            yield RawPosting(
                raw={
                    "title": title,
                    "href": href,
                    "location": _location(anchor),
                }
            )

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        posting = raw.raw
        title = str(posting.get("title") or "").strip()
        href = str(posting.get("href") or "")
        canonical_url = urljoin(_BASE_URL, href)
        source_job_id = href.rstrip("/").rsplit("/", 1)[-1] if href else None

        description_text = ""
        location_raw = posting.get("location")
        location = normalize_location(location_raw)

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
            posted_at=parse_datetime(posting.get("date")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=posting,
        )
