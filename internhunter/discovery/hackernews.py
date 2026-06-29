from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_html

_SEARCH_BASE = "https://hn.algolia.com/api/v1/search_by_date"
_ITEM_BASE = "https://hn.algolia.com/api/v1/items"

# Global ceiling on comments scanned across all threads, so a large `months` knob
# cannot drive unbounded memory growth regardless of per-thread `max_comments`.
_MAX_TOTAL_COMMENTS = 10000


def _search_url(hits: int = 1) -> str:
    query = urlencode(
        {
            "query": "Ask HN: Who is hiring",
            "tags": "story,author_whoishiring",
            "hitsPerPage": str(hits),
        }
    )
    return f"{_SEARCH_BASE}?{query}"


def _item_url(thread_id: int) -> str:
    return f"{_ITEM_BASE}/{thread_id}"


async def latest_hiring_thread_id(ctx: FetchContext) -> int | None:
    try:
        data = await ctx.get_json(_search_url(), respect_robots=False)
        hits = data["hits"]
        return int(hits[0]["objectID"])
    except Exception:
        ctx.logger.debug("failed to resolve latest hn hiring thread")
        return None


async def recent_hiring_thread_ids(ctx: FetchContext, n: int = 6) -> list[int]:
    try:
        data = await ctx.get_json(_search_url(max(1, n * 3)), respect_robots=False)
    except Exception:
        ctx.logger.debug("failed to resolve recent hn hiring threads")
        return []
    ids: list[int] = []
    for hit in data.get("hits", []) if isinstance(data, dict) else []:
        if "who is hiring" not in str(hit.get("title", "")).lower():
            continue
        try:
            ids.append(int(hit["objectID"]))
        except (KeyError, TypeError, ValueError):
            continue
        if len(ids) >= n:
            break
    return ids


def _walk_texts(node: Any, texts: list[str], max_comments: int) -> None:
    stack: list[Any] = [node]
    while stack and len(texts) < max_comments:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        text = current.get("text")
        if isinstance(text, str):
            texts.append(text)
        children = current.get("children")
        if isinstance(children, list):
            stack.extend(children)


async def _scan_thread(
    ctx: FetchContext,
    thread_id: int,
    seen: set[tuple[str, str]],
    detections: list[Detection],
    max_comments: int,
) -> int:
    """Scan one thread, returning the number of comment texts collected."""
    try:
        item = await ctx.get_json(_item_url(thread_id), respect_robots=False)
    except Exception:
        ctx.logger.debug("failed to fetch hn item {}", thread_id)
        return 0

    texts: list[str] = []
    children = item.get("children") if isinstance(item, dict) else None
    if isinstance(children, list):
        for child in children:
            if len(texts) >= max_comments:
                break
            _walk_texts(child, texts, max_comments)

    for text in texts:
        for detection in detect_from_html(text):
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)
    return len(texts)


async def discover_from_hackernews(
    ctx: FetchContext,
    thread_id: int | None = None,
    months: int = 1,
    max_comments: int = 1000,
) -> list[Detection]:
    if thread_id is not None:
        thread_ids = [thread_id]
    elif months > 1:
        thread_ids = await recent_hiring_thread_ids(ctx, months)
    else:
        latest = await latest_hiring_thread_id(ctx)
        thread_ids = [latest] if latest is not None else []

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    total = 0
    for tid in thread_ids:
        budget = min(max_comments, _MAX_TOTAL_COMMENTS - total)
        if budget <= 0:
            break
        total += await _scan_thread(ctx, tid, seen, detections, budget)
    return detections
