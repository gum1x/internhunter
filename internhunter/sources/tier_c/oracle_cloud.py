from __future__ import annotations

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


def _site(ref: BoardRef) -> str:
    extra = ref.extra or {}
    return str(extra.get("site", "CX"))


@register_source
class OracleCloudSource(Source):
    ats: str = "oracle_cloud"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        site = _site(ref)
        return (
            f"https://{ref.token}.fa.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions?onlyData=true"
            "&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={site},keyword=intern"
        )

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        data = await ctx.get_json(self.board_url(ref))
        data = data if isinstance(data, dict) else {}
        for item in data.get("items", []):
            requisitions = item.get("requisitionList")
            if isinstance(requisitions, list):
                for req in requisitions:
                    yield RawPosting(raw=req)
            else:
                yield RawPosting(raw=item)

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        req = raw.raw
        title = str(req.get("Title") or "").strip()
        source_job_id = str(req["Id"]) if req.get("Id") is not None else None
        site = _site(ref)
        canonical_url = (
            f"https://{ref.token}.fa.oraclecloud.com/hcmUI/CandidateExperience/en/"
            f"sites/{site}/job/{source_job_id}"
        )

        location_raw = req.get("PrimaryLocation")
        location = normalize_location(location_raw)

        description_text = ""
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
            posted_at=parse_datetime(req.get("PostedDate")),
            deadline_at=extract_deadline(description_text),
            is_rolling=is_rolling(description_text),
            first_seen_at=now,
            last_seen_at=now,
            raw=req,
        )
