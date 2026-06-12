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

_PAGE_SIZE = 20


def _parse_token(token: str) -> tuple[str, str]:
    parts = [p for p in token.split("/") if p]
    if len(parts) < 2:
        raise RuntimeError(f"workday token must be 'tenant/site', got {token!r}")
    return parts[0], parts[1]


_DC_CANDIDATES = ("wd1", "wd5", "wd103", "wd3", "wd12", "wd2", "wd101", "wd10")


def _datacenter(ref: BoardRef) -> str:
    extra = ref.extra or {}
    return str(extra.get("dc", "wd1"))


def _cxs_url(tenant: str, site: str, dc: str) -> str:
    return f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"


@register_source
class WorkdaySource(Source):
    ats: str = "workday"
    tier: Tier = Tier.C
    needs_browser: bool = False

    def board_url(self, ref: BoardRef) -> str:
        tenant, site = _parse_token(ref.token)
        return _cxs_url(tenant, site, _datacenter(ref))

    async def _resolve_dc(
        self, ctx: FetchContext, tenant: str, site: str, candidates: list[str]
    ) -> str | None:
        for dc in candidates:
            try:
                payload = await ctx.post_json(
                    _cxs_url(tenant, site, dc),
                    json_body={
                        "appliedFacets": {},
                        "limit": 1,
                        "offset": 0,
                        "searchText": "intern",
                    },
                )
            except Exception:
                continue
            if isinstance(payload, dict) and "total" in payload:
                return dc
        return None

    async def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]:
        try:
            tenant, site = _parse_token(ref.token)
        except RuntimeError:
            ctx.logger.debug("workday bad token {}", ref.token)
            return
        extra_dc = (ref.extra or {}).get("dc")
        candidates = [str(extra_dc)] if extra_dc else list(_DC_CANDIDATES)
        dc = await self._resolve_dc(ctx, tenant, site, candidates)
        if dc is None:
            return

        url = _cxs_url(tenant, site, dc)
        offset = 0
        while True:
            try:
                payload = await ctx.post_json(
                    url,
                    json_body={
                        "appliedFacets": {},
                        "limit": _PAGE_SIZE,
                        "offset": offset,
                        "searchText": "intern",
                    },
                )
            except Exception:
                break
            postings = payload.get("jobPostings") or []
            if not postings:
                break
            for posting in postings:
                yield RawPosting(raw=posting, detail={"dc": dc})
            total = int(payload.get("total", 0))
            offset += _PAGE_SIZE
            if offset >= total:
                break

    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob:
        posting = raw.raw
        tenant, site = _parse_token(ref.token)
        dc = str((raw.detail or {}).get("dc") or _datacenter(ref))

        title = str(posting.get("title", "")).strip()
        external_path = str(posting.get("externalPath", ""))
        canonical_url = f"https://{tenant}.{dc}.myworkdayjobs.com/{site}{external_path}"

        segments = [s for s in external_path.split("/") if s]
        bullet_fields = posting.get("bulletFields") or []
        source_job_id: str | None = None
        if segments:
            source_job_id = segments[-1]
        elif bullet_fields:
            source_job_id = str(bullet_fields[0])

        location_raw = posting.get("locationsText")
        location = normalize_location(location_raw)

        classification = classify_internship(title, "")
        now = datetime.now(UTC)

        return NormalizedJob(
            job_uid=make_job_uid(self.ats, ref.token, source_job_id, canonical_url),
            ats=self.ats,
            board_token=ref.token,
            source_job_id=source_job_id,
            canonical_url=canonical_url,
            url_hash=make_url_hash(canonical_url),
            company=ref.company or tenant,
            company_slug=normalize_company_slug(ref.company or tenant),
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
            posted_at=parse_datetime(posting.get("postedOn")),
            deadline_at=extract_deadline(title),
            is_rolling=is_rolling(title),
            first_seen_at=now,
            last_seen_at=now,
            raw=posting,
        )
