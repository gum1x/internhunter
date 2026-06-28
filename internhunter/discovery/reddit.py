"""Reddit — keyless internship-subreddit ingest.

Reddit's own ``*.reddit.com/r/{sub}/new.json`` is IP-blocked (403) from datacenter/cloud hosts
regardless of User-Agent or OAuth, so we read keyless third-party archives that aren't behind
Reddit's IP wall — **PullPush** (primary) with **Arctic-Shift** as fallback. Both return the same
per-post field shape Reddit uses, just as a flat list under ``data`` (vs Reddit's nested
``data.children[].data``), so we re-wrap before reusing ``parse_listing``.
"""
from __future__ import annotations

from typing import Any

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.core.internship_filter import classify_internship
from internhunter.discovery.listing_common import ListingJob, ingest_listings
from internhunter.discovery.social_parsing import extract_company, first_url

_DEFAULT_SUBS = ("internships", "csMajors", "cscareerquestions")
_PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"
_ARCTIC = "https://arctic-shift.photon-reddit.com/api/posts/search"
_UA = {"User-Agent": "internhunter/1.0 (+https://github.com/gum1x/internhunter)"}


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


async def _fetch_sub(ctx: FetchContext, sub: str) -> Any:
    """Pull a subreddit's recent submissions from PullPush, then Arctic-Shift. Both return a
    flat ``{"data": [post, ...]}``; re-wrap into Reddit's nested children shape so parse_listing
    (written for Reddit's own ``.json``) works unchanged."""
    for url, params in (
        (_PULLPUSH, {"subreddit": sub, "size": 100, "sort": "desc", "sort_type": "created_utc"}),
        (_ARCTIC, {"subreddit": sub, "limit": 100, "sort": "desc"}),
    ):
        try:
            raw = await ctx.get_json(url, params=params, headers=_UA, respect_robots=False)
        except Exception:
            continue
        posts = raw.get("data") if isinstance(raw, dict) else None
        if isinstance(posts, list) and posts:
            return {"data": {"children": [{"data": p} for p in posts]}}
    return None


async def fetch_reddit(ctx: FetchContext, settings: Settings) -> list[ListingJob]:
    subs = [s.strip() for s in (settings.reddit_subreddits or "").split(",") if s.strip()]
    subs = subs or list(_DEFAULT_SUBS)
    seen: set[str] = set()
    jobs: list[ListingJob] = []
    for sub in subs:
        data = await _fetch_sub(ctx, sub)
        if data is None:
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
