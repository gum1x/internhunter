from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_html

_SEARCH_BASE = "https://hn.algolia.com/api/v1/search_by_date"
_ITEM_BASE = "https://hn.algolia.com/api/v1/items"


def _search_url() -> str:
    query = urlencode(
        {
            "query": "Ask HN: Who is hiring",
            "tags": "story,author_whoishiring",
            "hitsPerPage": "1",
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


async def discover_from_hackernews(
    ctx: FetchContext,
    thread_id: int | None = None,
    max_comments: int = 1000,
) -> list[Detection]:
    resolved = thread_id if thread_id is not None else await latest_hiring_thread_id(ctx)
    if resolved is None:
        return []

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    try:
        item = await ctx.get_json(_item_url(resolved), respect_robots=False)
    except Exception:
        ctx.logger.debug("failed to fetch hn item {}", resolved)
        return detections

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

    return detections
