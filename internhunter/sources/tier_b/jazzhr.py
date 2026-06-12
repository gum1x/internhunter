from __future__ import annotations

import re
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

_APPLY_RE = re.compile(r"/apply/([^/?#]+)")


def _location_for(anchor: Any) -> str | None:
    for sibling in anchor.parent.find_all(class_=re.compile(r"location|list-group-item")):
        text = str(sibling.get_text(strip=True))
        if text:
            return text
    return None


@register_source
class JazzHrSource(Source):
    ats: str = "jazzhr"
    tier: Tier = Tier.B
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.applytojob.com/"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        html = await ctx.get_text(self.board_url(ref))
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.find_all("a", href=_APPLY_RE):
            title = anchor.get_text(strip=True)
            if not title:
                continue
            yield RawPosting(
                raw={
                    "title": title,
                    "href": anchor.get("href"),
                    "location": _location_for(anchor),
                }
            )

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        posting = raw.raw
        title = str(posting.get("title") or "").strip()
        href = str(posting.get("href") or "")

        match = _APPLY_RE.search(href)
        source_job_id = match.group(1) if match else None

        canonical_url = urljoin(f"https://{ref.token}.applytojob.com", href)
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
