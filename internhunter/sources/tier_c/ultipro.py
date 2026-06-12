from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

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


def _text(element: Any, name: str) -> str | None:
    child = element.find(name)
    if child is None:
        return None
    value = child.get_text(strip=True)
    return value or None


def _split_token(token: str) -> tuple[str, str] | None:
    parts = [p for p in token.split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _parse_opportunity(element: Any) -> dict[str, str | None]:
    return {
        "Id": _text(element, "Id"),
        "Title": _text(element, "Title"),
        "Location": _text(element, "Location"),
        "PostedDate": _text(element, "PostedDate"),
        "Url": _text(element, "Url"),
    }


@register_source
class UltiproSource(Source):
    ats: str = "ultipro"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        parsed = _split_token(ref.token)
        if parsed is None:
            return f"https://recruiting.ultipro.com/{ref.token}/JobBoard/Jobs.xml"
        short, board_id = parsed
        return f"https://recruiting.ultipro.com/{short}/JobBoard/{board_id}/Jobs.xml"

    def _html_url(self, ref: BoardRef) -> str:
        parsed = _split_token(ref.token)
        if parsed is None:
            return f"https://recruiting.ultipro.com/{ref.token}/JobBoard/Jobs"
        short, board_id = parsed
        return f"https://recruiting.ultipro.com/{short}/JobBoard/{board_id}/Jobs"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        if _split_token(ref.token) is None:
            ctx.logger.debug("ultipro token must be 'short/boardId', got {!r}", ref.token)
            return
        xml: str | None = None
        try:
            xml = await ctx.get_text(self.board_url(ref))
        except Exception:
            if ctx.browser is not None:
                try:
                    xml = await ctx.browser.render(self._html_url(ref))
                except Exception:
                    xml = None
        if xml is None:
            return
        soup = BeautifulSoup(xml, "xml")
        elements = soup.find_all("Opportunity") or soup.find_all("job")
        for element in elements:
            yield RawPosting(raw=_parse_opportunity(element))

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        opportunity = raw.raw
        short = ref.token.split("/")[0]
        title = str(opportunity.get("Title") or "").strip()
        source_job_id = str(opportunity["Id"]) if opportunity.get("Id") else None

        canonical_url = str(opportunity.get("Url") or self._html_url(ref))

        location_raw = opportunity.get("Location")
        location = normalize_location(location_raw)

        classification = classify_internship(title, "")
        company = ref.company or short
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
            description_text="",
            posted_at=parse_datetime(opportunity.get("PostedDate")),
            deadline_at=extract_deadline(""),
            is_rolling=is_rolling(""),
            first_seen_at=now,
            last_seen_at=now,
            raw=opportunity,
        )
