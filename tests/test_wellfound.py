from __future__ import annotations

import json
from typing import Any

import pytest

from internhunter.config.settings import Settings
from internhunter.discovery.listing_common import ListingJob, listing_to_job
from internhunter.discovery.wellfound import fetch_wellfound, postings_to_listings

_POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Software Engineer Intern",
    "url": "https://wellfound.com/jobs/123-software-engineer-intern",
    "datePosted": "2026-06-30",
    "description": "Build things at a seed-stage startup.",
    "hiringOrganization": {"@type": "Organization", "name": "TinyCo"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "New York",
            "addressRegion": "NY",
            "addressCountry": "US",
        },
    },
}

_FOUNDING = {
    "@type": "JobPosting",
    "title": "Founding Engineer",
    "url": "https://wellfound.com/jobs/456-founding-engineer",
    "jobLocationType": "TELECOMMUTE",
    "hiringOrganization": {"@type": "Organization", "name": "TinyCo"},
}


def _page(*postings: dict[str, Any]) -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(p)}</script>' for p in postings
    )
    return f"<html><head>{blocks}</head><body>jobs</body></html>"


def test_postings_to_listings_parses_jsonld() -> None:
    listings = postings_to_listings(_page(_POSTING, _FOUNDING), "tinyco", "https://x")
    assert len(listings) == 2
    intern = listings[0]
    assert intern.title == "Software Engineer Intern"
    assert intern.company == "TinyCo"
    assert intern.location == "New York, NY, US"
    assert intern.posted == "2026-06-30"
    assert listings[1].location == "Remote"


def test_ignores_pages_without_postings() -> None:
    assert postings_to_listings("<html>DataDome says no</html>", "x", "https://x") == []


def test_founding_role_survives_with_keep_early() -> None:
    listing = ListingJob(
        title="Founding Engineer",
        company="TinyCo",
        url="https://wellfound.com/jobs/456",
        source="wellfound",
    )
    assert listing_to_job(listing) is None  # default path is interns-only
    job = listing_to_job(listing, keep_early=True)
    assert job is not None
    assert job.is_internship is False
    assert "early-stage" in job.level_tags


class _Ctx:
    """Stub FetchContext: canned HTML per URL, raises on unknown (blocked) URLs."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

        class _Log:
            def debug(self, *a: object, **k: object) -> None: ...
            def info(self, *a: object, **k: object) -> None: ...

        self.logger = _Log()

    async def get_text(self, url: str, **_: object) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise RuntimeError("403 bot-wall")
        return self.pages[url]


@pytest.mark.asyncio
async def test_fetch_disabled_by_default() -> None:
    ctx = _Ctx({})
    settings = Settings(wellfound_companies="tinyco")
    assert await fetch_wellfound(ctx, settings) == []  # type: ignore[arg-type]
    assert ctx.requested == []


@pytest.mark.asyncio
async def test_fetch_enabled_reads_each_company_and_survives_blocks() -> None:
    ok_url = "https://wellfound.com/company/tinyco/jobs"
    ctx = _Ctx({ok_url: _page(_POSTING)})
    settings = Settings(enable_wellfound=True, wellfound_companies="tinyco, blocked-co")
    jobs = await fetch_wellfound(ctx, settings)  # type: ignore[arg-type]
    assert len(jobs) == 1
    assert jobs[0].extra["wellfound_company"] == "tinyco"
    assert len(ctx.requested) == 2  # blocked company attempted, failure swallowed


@pytest.mark.asyncio
async def test_fetch_enabled_without_companies_is_inert() -> None:
    ctx = _Ctx({})
    settings = Settings(enable_wellfound=True)
    assert await fetch_wellfound(ctx, settings) == []  # type: ignore[arg-type]
    assert ctx.requested == []
