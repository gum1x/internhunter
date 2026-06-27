"""Bluesky — keyless, unauthenticated AT-Protocol post search.

``app.bsky.feed.searchPosts`` is a public AppView endpoint (no login/app-password needed for
read). We search for internship chatter, pull the apply URL from each post's richtext facets
(or the text), and store listings; ``reresolve`` later upgrades any that point at a real ATS.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.discovery.listing_common import ListingJob, ingest_listings
from internhunter.discovery.social_parsing import extract_company, first_url, title_from_text

# Use api.bsky.app (the AppView) not public.api.bsky.app (a CDN alias that WAF-blocks the
# searchPosts path from datacenter IPs). searchPosts is keyless on the AppView. Verified live.
_SEARCH = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
_DEFAULT_QUERIES = ("internship", '"summer 2026" intern', '"co-op" hiring intern')


def _facet_links(post_record: dict[str, Any]) -> list[str]:
    links: list[str] = []
    for facet in post_record.get("facets", []) if isinstance(post_record, dict) else []:
        for feature in facet.get("features", []) if isinstance(facet, dict) else []:
            uri = feature.get("uri") if isinstance(feature, dict) else None
            if isinstance(uri, str) and uri.startswith("http"):
                links.append(uri)
    return links


def parse_posts(data: Any) -> list[ListingJob]:
    posts = data.get("posts") if isinstance(data, dict) else None
    jobs: list[ListingJob] = []
    for post in posts or []:
        record = post.get("record") if isinstance(post, dict) else None
        if not isinstance(record, dict):
            continue
        text = str(record.get("text", ""))
        url = next(iter(_facet_links(record)), None) or first_url(text)
        if not url:
            continue
        jobs.append(
            ListingJob(
                title=title_from_text(text),
                company=extract_company(text),
                url=url,
                location=None,
                posted=record.get("createdAt"),
                source="bluesky",
                description=text,
            )
        )
    return jobs


async def fetch_bluesky(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    queries = [q.strip() for q in (settings.bluesky_queries or "").split("|") if q.strip()]
    queries = queries or list(_DEFAULT_QUERIES)
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for query in queries:
        url = f"{_SEARCH}?{urlencode({'q': query, 'limit': 100, 'sort': 'latest'})}"
        try:
            data = await ctx.get_json(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("bluesky search failed for {}", query)
            continue
        for job in parse_posts(data):
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
    return jobs


async def ingest_bluesky(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_bluesky, settings)
