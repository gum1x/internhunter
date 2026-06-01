from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import (
    Detection,
    detect_from_html,
    detect_from_url,
)

_MAX_DEPTH = 2


def _base_of(url: str) -> str:
    parts = urlsplit(url if "//" in url else f"https://{url}")
    scheme = parts.scheme or "https"
    return urlunsplit((scheme, parts.netloc, "", "", ""))


def _parse_robots_sitemaps(text: str) -> list[str]:
    sitemaps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                sitemaps.append(value)
    return sitemaps


async def _collect_sitemap_locs(
    sitemap_url: str,
    ctx: FetchContext,
    depth: int,
    seen_sitemaps: set[str],
    locs: list[str],
    max_urls: int,
) -> None:
    if depth > _MAX_DEPTH or len(locs) >= max_urls:
        return
    if sitemap_url in seen_sitemaps:
        return
    seen_sitemaps.add(sitemap_url)
    try:
        text = await ctx.get_text(sitemap_url)
    except Exception as exc:
        ctx.logger.debug("sitemap fetch failed {}: {}", sitemap_url, exc)
        return
    soup = BeautifulSoup(text, "xml")
    for sitemap in soup.find_all("sitemap"):
        loc = sitemap.find("loc")
        if loc is None:
            continue
        child = loc.get_text(strip=True)
        if child:
            await _collect_sitemap_locs(
                child, ctx, depth + 1, seen_sitemaps, locs, max_urls
            )
        if len(locs) >= max_urls:
            return
    for url_entry in soup.find_all("url"):
        loc = url_entry.find("loc")
        if loc is None:
            continue
        value = loc.get_text(strip=True)
        if value:
            locs.append(value)
        if len(locs) >= max_urls:
            return


async def discover_from_sitemap(
    root_url: str, ctx: FetchContext, max_urls: int = 5000
) -> list[Detection]:
    base = _base_of(root_url)
    seen_sitemaps: set[str] = set()
    locs: list[str] = []

    sitemap_urls: list[str] = []
    try:
        robots_text = await ctx.get_text(urljoin(base + "/", "robots.txt"))
        sitemap_urls.extend(_parse_robots_sitemaps(robots_text))
    except Exception as exc:
        ctx.logger.debug("robots fetch failed for {}: {}", base, exc)

    if not sitemap_urls:
        sitemap_urls.append(urljoin(base + "/", "sitemap.xml"))

    for sitemap_url in sitemap_urls:
        await _collect_sitemap_locs(sitemap_url, ctx, 0, seen_sitemaps, locs, max_urls)
        if len(locs) >= max_urls:
            break

    seen: set[tuple[str, str]] = set()
    found: list[Detection] = []

    def _add(detection: Detection) -> None:
        key = (detection.ats, detection.token)
        if key in seen:
            return
        seen.add(key)
        found.append(detection)

    try:
        root_html = await ctx.get_text(root_url)
        for detection in detect_from_html(root_html):
            _add(detection)
    except Exception as exc:
        ctx.logger.debug("root page fetch failed for {}: {}", root_url, exc)

    for loc in locs:
        loc_detection = detect_from_url(loc)
        if loc_detection is not None:
            _add(loc_detection)

    return found
