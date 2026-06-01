from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

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


def _text(element: Any, name: str) -> str | None:
    child = element.find(name)
    if child is None:
        return None
    value = child.get_text(strip=True)
    return value or None


def _parse_position(element: Any) -> dict[str, Any]:
    descriptions: list[dict[str, str | None]] = []
    container = element.find("jobDescriptions")
    if container is not None:
        for desc in container.find_all("jobDescription"):
            descriptions.append(
                {
                    "name": _text(desc, "name"),
                    "value": _text(desc, "value"),
                }
            )
    return {
        "id": _text(element, "id"),
        "name": _text(element, "name"),
        "office": _text(element, "office"),
        "department": _text(element, "department"),
        "recruitingCategory": _text(element, "recruitingCategory"),
        "employmentType": _text(element, "employmentType"),
        "schedule": _text(element, "schedule"),
        "seniority": _text(element, "seniority"),
        "createdAt": _text(element, "createdAt"),
        "jobDescriptions": descriptions,
    }


@register_source
class PersonioSource(Source):
    ats: str = "personio"
    tier: Tier = Tier.A
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        return f"https://{ref.token}.jobs.personio.de/xml"

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        text = await ctx.get_text(self.board_url(ref))
        soup = BeautifulSoup(text, "xml")
        for element in soup.find_all("position"):
            yield RawPosting(raw=_parse_position(element))

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        position = raw.raw
        title = str(position.get("name") or "").strip()
        source_job_id = str(position["id"]) if position.get("id") else None

        if source_job_id:
            canonical_url = f"https://{ref.token}.jobs.personio.de/job/{source_job_id}"
        else:
            canonical_url = self.board_url(ref)

        description_html = "\n".join(
            str(desc["value"])
            for desc in position.get("jobDescriptions", [])
            if desc.get("value")
        ) or None
        description_text = html_to_text(description_html)

        location_raw = position.get("office")
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
            department=position.get("department"),
            employment_type=position.get("employmentType"),
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
            posted_at=parse_datetime(position.get("createdAt")),
            first_seen_at=now,
            last_seen_at=now,
            raw=position,
        )
