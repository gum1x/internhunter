"""Reddit — keyless public JSON. ``old.reddit.com/r/{sub}/new.json`` needs no auth; we read the
internship-focused subreddits, keep posts that look like internship postings, and store the
linked apply URL as a listing (``reresolve`` recovers the real ATS)."""
from __future__ import annotations

from typing import Any

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.discovery.listing_common import ListingJob, ingest_listings
from internhunter.discovery.social_parsing import extract_company, first_url

_DEFAULT_SUBS = ("internships", "csMajors", "cscareerquestions")


def parse_listing(data: Any, subreddit: str) -> list[ListingJob]:
    children = (
        data.get("data", {}).get("children", []) if isinstance(data, dict) else []
    )
    jobs: list[ListingJob] = []
    for child in children:
        post = child.get("data") if isinstance(child, dict) else None
        if not isinstance(post, dict):
            continue
        title = str(post.get("title", "")).strip()
        body = str(post.get("selftext", ""))
        if not classify_internship(title, body).is_internship:
            continue
        # Prefer an external apply link; fall back to a link in the body, then the post itself.
        url = post.get("url_overridden_by_dest") or post.get("url")
        if not isinstance(url, str) or "reddit.com" in url:
            url = first_url(body) or (
                f"https://old.reddit.com{post.get('permalink', '')}"
                if post.get("permalink") else None
            )
        if not url:
            continue
        jobs.append(
            ListingJob(
                title=title,
                company=extract_company(f"{title}\n{body}"),
                url=url,
                location=None,
                posted=post.get("created_utc"),
                source=f"reddit:{subreddit}",
                description=body,
            )
        )
    return jobs


async def fetch_reddit(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    subs = [s.strip() for s in (settings.reddit_subreddits or "").split(",") if s.strip()]
    subs = subs or list(_DEFAULT_SUBS)
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for sub in subs:
        try:
            data = await ctx.get_json(
                f"https://old.reddit.com/r/{sub}/new.json?limit=100", respect_robots=False
            )
        except Exception:
            ctx.logger.debug("reddit fetch failed for r/{}", sub)
            continue
        for job in parse_listing(data, sub):
            if job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
    return jobs


async def ingest_reddit(settings: Settings | None = None) -> tuple[int, int, int]:
    return await ingest_listings(fetch_reddit, settings)
