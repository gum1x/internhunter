"""Big-company *custom* career sites that aren't on a recognized ATS.

Each major runs its own keyless JSON careers API. We hit them directly (one small fetcher per
company, registered in ``_SOURCES``) and store results as listings tagged
``raw["source"]="bigco:<company>"``. Endpoints are public but undocumented and may change, so
every fetcher fails soft — one company's API change can't sink the batch.

Add a company by writing a ``_fetch_<co>(ctx) -> list[ListingJob]`` and adding it to ``_SOURCES``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings

Fetcher = Callable[[FetchContext], Awaitable[list[ListingJob]]]


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first(d: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        v = _str(d.get(key))
        if v:
            return v
    return None


async def _fetch_google(ctx: FetchContext) -> list[ListingJob]:
    data = await ctx.get_json(
        "https://careers.google.com/api/v3/search/?q=intern&page_size=100",
        respect_robots=False,
    )
    jobs: list[ListingJob] = []
    for j in data.get("jobs", []) if isinstance(data, dict) else []:
        if not isinstance(j, dict):
            continue
        title = _first(j, "title", "job_title")
        url = _first(j, "apply_url") or (
            f"https://www.google.com/about/careers/applications/jobs/results/{j.get('id')}"
            if j.get("id")
            else None
        )
        if not title or not url:
            continue
        locs = j.get("locations")
        loc = locs[0].get("display") if isinstance(locs, list) and locs else None
        jobs.append(
            ListingJob(title, "Google", url, loc if isinstance(loc, str) else None,
                       j.get("created"), "bigco:google")
        )
    return jobs


async def _fetch_amazon(ctx: FetchContext) -> list[ListingJob]:
    data = await ctx.get_json(
        "https://www.amazon.jobs/en/search.json?base_query=intern&result_limit=100",
        respect_robots=False,
    )
    jobs: list[ListingJob] = []
    for j in data.get("jobs", []) if isinstance(data, dict) else []:
        if not isinstance(j, dict):
            continue
        title = _first(j, "title")
        path = _first(j, "job_path")
        if not title or not path:
            continue
        jobs.append(
            ListingJob(title, "Amazon", urljoin("https://www.amazon.jobs", path),
                       _first(j, "normalized_location", "location"),
                       j.get("posted_date"), "bigco:amazon")
        )
    return jobs


async def _fetch_microsoft(ctx: FetchContext) -> list[ListingJob]:
    data = await ctx.get_json(
        "https://gcsservices.careers.microsoft.com/search/api/v1/search"
        "?q=intern&l=en_us&pgSz=100&o=Relevance",
        respect_robots=False,
    )
    result = (
        data.get("operationResult", {}).get("result", {}) if isinstance(data, dict) else {}
    )
    jobs: list[ListingJob] = []
    for j in result.get("jobs", []) if isinstance(result, dict) else []:
        if not isinstance(j, dict):
            continue
        title = _first(j, "title")
        job_id = j.get("jobId") or j.get("id")
        if not title or not job_id:
            continue
        raw_props = j.get("properties")
        props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
        locs = props.get("locations")
        loc = locs[0] if isinstance(locs, list) and locs else props.get("primaryLocation")
        jobs.append(
            ListingJob(title, "Microsoft",
                       f"https://jobs.careers.microsoft.com/global/en/job/{job_id}",
                       loc if isinstance(loc, str) else None,
                       props.get("postedDate"),
                       "bigco:microsoft")
        )
    return jobs


async def _fetch_apple(ctx: FetchContext) -> list[ListingJob]:
    data = await ctx.post_json(
        "https://jobs.apple.com/api/role/search",
        json_body={"query": "intern", "filters": {}, "page": 1},
        respect_robots=False,
    )
    res = data.get("res", {}) if isinstance(data, dict) else {}
    jobs: list[ListingJob] = []
    for j in res.get("searchResults", []) if isinstance(res, dict) else []:
        if not isinstance(j, dict):
            continue
        title = _first(j, "postingTitle", "transformedPostingTitle", "positionTitle")
        job_id = j.get("positionId") or j.get("id") or j.get("reqId")
        if not title or not job_id:
            continue
        locs = j.get("locations")
        loc = locs[0].get("name") if isinstance(locs, list) and locs and isinstance(
            locs[0], dict
        ) else None
        jobs.append(
            ListingJob(title, "Apple", f"https://jobs.apple.com/en-us/details/{job_id}",
                       loc if isinstance(loc, str) else None,
                       j.get("postDateInGMT"), "bigco:apple")
        )
    return jobs


async def _fetch_netflix(ctx: FetchContext) -> list[ListingJob]:
    data = await ctx.get_json(
        "https://explore.jobs.netflix.net/api/apply/v2/jobs"
        "?query=intern&start=0&num=100&domain=netflix.com",
        respect_robots=False,
    )
    jobs: list[ListingJob] = []
    for j in data.get("positions", []) if isinstance(data, dict) else []:
        if not isinstance(j, dict):
            continue
        title = _first(j, "name", "title")
        url = _first(j, "canonicalPositionUrl", "job_url")
        if not title or not url:
            continue
        jobs.append(
            ListingJob(title, "Netflix", url, _first(j, "location"),
                       j.get("t_create"), "bigco:netflix")
        )
    return jobs


_SOURCES: dict[str, Fetcher] = {
    "google": _fetch_google,
    "amazon": _fetch_amazon,
    "microsoft": _fetch_microsoft,
    "apple": _fetch_apple,
    "netflix": _fetch_netflix,
}


def _make_fetcher(settings: Settings) -> Fetcher:
    wanted = [c.strip().lower() for c in (settings.bigco_companies or "").split(",") if c.strip()]
    active = [name for name in wanted if name in _SOURCES] or list(_SOURCES)

    async def fetch(ctx: FetchContext, _settings: Settings | None = None) -> list[ListingJob]:
        results = await asyncio.gather(
            *(_SOURCES[name](ctx) for name in active), return_exceptions=True
        )
        jobs: list[ListingJob] = []
        for name, result in zip(active, results, strict=True):
            if isinstance(result, list):
                jobs.extend(result)
            else:
                ctx.logger.debug("bigco {} failed: {}", name, result)
        return jobs

    return fetch


async def ingest_bigco(settings: Settings | None = None) -> tuple[int, int, int]:
    from internhunter.config.settings import get_settings

    resolved = settings or get_settings()
    fetcher = _make_fetcher(resolved)

    async def adapter(ctx: FetchContext, _s: Settings) -> list[ListingJob]:
        return await fetcher(ctx)

    return await ingest_listings(adapter, resolved)
