"""Keyless public-page research for company dossiers.

Fetches a small, bounded set of a firm's own pages (homepage / about / blog / news /
team) through the shared rate-limited + cached fetcher, plus optional SearXNG search
when configured. Everything returned is deterministic extraction — meta descriptions,
JSON-LD Organization facts, dated blog/news links — each carrying the URL it came
from, so downstream synthesis can be validated against what was actually fetched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext
from internhunter.core.normalize import html_to_text, parse_datetime

_PAGE_PATHS: tuple[tuple[str, str], ...] = (
    ("", "homepage"),
    ("/about", "about"),
    ("/blog", "blog"),
    ("/news", "news"),
    ("/team", "team"),
)
_PAGE_TEXT_LIMIT = 4000


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    kind: str
    text: str


@dataclass(frozen=True)
class SignalCandidate:
    title: str
    url: str
    date: str  # ISO date
    origin: str  # blog | news | searxng | edgar | disclosure


@dataclass
class ResearchBundle:
    company: str
    slug: str
    domain: str | None
    pages: list[PageSnapshot] = field(default_factory=list)
    description: str | None = None
    org_facts: dict[str, str] = field(default_factory=dict)
    signals: list[SignalCandidate] = field(default_factory=list)
    fetched_urls: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    @property
    def thin(self) -> bool:
        return not self.pages


def extract_description(html: str) -> str | None:
    soup = BeautifulSoup(html or "", "lxml")
    selectors: tuple[dict[str, Any], ...] = (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    )
    for selector in selectors:
        tag = soup.find("meta", attrs=selector)
        if tag is not None:
            content = str(tag.get("content") or "").strip()
            if content:
                return content
    return None


def _org_nodes(data: object, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(data, dict):
        t = data.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() in ("organization", "corporation") for x in types):
            out.append(data)
        for value in data.values():
            _org_nodes(value, out, depth + 1)
    elif isinstance(data, list):
        for item in data:
            _org_nodes(item, out, depth + 1)


def extract_org_facts(html: str) -> dict[str, str]:
    """numberOfEmployees / foundingDate from schema.org Organization JSON-LD, if any."""
    soup = BeautifulSoup(html or "", "lxml")
    facts: dict[str, str] = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except json.JSONDecodeError:
            continue
        nodes: list[dict[str, Any]] = []
        _org_nodes(data, nodes)
        for node in nodes:
            employees = node.get("numberOfEmployees")
            if isinstance(employees, dict):
                employees = employees.get("value")
            if employees and "team_size" not in facts:
                facts["team_size"] = str(employees)
            founded = node.get("foundingDate")
            if isinstance(founded, str) and founded and "founded" not in facts:
                facts["founded"] = founded
    return facts


_URL_DATE_RE = re.compile(r"/(20\d{2})/(\d{1,2})(?:/(\d{1,2}))?(?:/|$)")
_TEXT_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"\d{1,2},?\s+20\d{2})\b"
)


def _iso(value: str) -> str | None:
    parsed = parse_datetime(value)
    return parsed.date().isoformat() if parsed is not None else None


def _anchor_date(anchor: Any) -> str | None:
    """Date for a blog/news link: <time datetime> near the anchor, a /YYYY/MM/ path
    segment, or a textual date in the enclosing item. None -> the link is not used as
    a dated signal (undated links are never presented as 'recent')."""
    href = str(anchor.get("href") or "")
    parent = anchor
    for _ in range(3):
        if parent is None or not hasattr(parent, "find"):
            break
        if parent is not anchor and len(parent.find_all("a", href=True)) > 1:
            break  # reached a list container — a sibling item's date is not ours
        time_tag = parent.find("time")
        if time_tag is not None:
            stamp = str(time_tag.get("datetime") or time_tag.get_text() or "").strip()
            iso = _iso(stamp) if stamp else None
            if iso:
                return iso
        parent = parent.parent
    url_match = _URL_DATE_RE.search(href)
    if url_match:
        year, month = int(url_match.group(1)), int(url_match.group(2))
        day = int(url_match.group(3) or 1)
        try:
            return datetime(year, month, day, tzinfo=UTC).date().isoformat()
        except ValueError:
            return None
    container = anchor.parent
    for _ in range(2):
        if container is None or not hasattr(container, "find_all"):
            break
        if len(container.find_all("a", href=True)) > 1:
            break  # same sibling guard as above
        text_match = _TEXT_DATE_RE.search(container.get_text(" ", strip=True) or "")
        if text_match:
            return _iso(text_match.group(0))
        container = container.parent
    return None


def extract_dated_links(html: str, base_url: str, origin: str) -> list[SignalCandidate]:
    soup = BeautifulSoup(html or "", "lxml")
    page_host = urlsplit(base_url).netloc.lower()
    seen: set[str] = set()
    out: list[SignalCandidate] = []
    for anchor in soup.find_all("a", href=True):
        title = anchor.get_text(" ", strip=True)
        if not title or len(title) < 15:  # nav links ("Blog", "Read more") aren't signals
            continue
        if title.rstrip().endswith("?"):
            # question headlines are content items (e.g. Polymarket's own market
            # questions), not company news
            continue
        url = urljoin(base_url, str(anchor["href"]))
        if urlsplit(url).netloc.lower() != page_host or url in seen:
            continue
        date = _anchor_date(anchor)
        if date is None:
            continue
        seen.add(url)
        out.append(SignalCandidate(title=title[:180], url=url, date=date, origin=origin))
    return out


def recent_signals(
    candidates: list[SignalCandidate], now: datetime, window_days: int
) -> list[SignalCandidate]:
    cutoff = (now - timedelta(days=window_days)).date().isoformat()
    today = now.date().isoformat()
    fresh = [c for c in candidates if cutoff <= c.date <= today]
    fresh.sort(key=lambda c: c.date, reverse=True)
    deduped: list[SignalCandidate] = []
    seen: set[str] = set()
    for c in fresh:
        if c.url not in seen:
            seen.add(c.url)
            deduped.append(c)
    return deduped


async def _searxng_signals(
    ctx: FetchContext, base_url: str, company: str
) -> tuple[list[SignalCandidate], PageSnapshot | None]:
    from urllib.parse import urlencode

    query = urlencode({"q": f'"{company}" (funding OR raised OR launches)', "format": "json"})
    url = f"{base_url.rstrip('/')}/search?{query}"
    try:
        data = await ctx.get_json(url, respect_robots=False)
    except Exception:
        ctx.logger.debug("dossier: searxng lookup failed for {}", company)
        return [], None
    results = data.get("results") if isinstance(data, dict) else None
    signals: list[SignalCandidate] = []
    lines: list[str] = []
    for item in (results or [])[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        result_url = str(item.get("url") or "").strip()
        content = str(item.get("content") or "").strip()
        if title and result_url:
            lines.append(f"- {title} ({result_url}): {content}")
        published = item.get("publishedDate")
        iso = _iso(str(published)) if published else None
        if title and result_url and iso:
            signals.append(
                SignalCandidate(title=title[:180], url=result_url, date=iso, origin="searxng")
            )
    snapshot = (
        PageSnapshot(url=url, kind="searxng", text="\n".join(lines)[:_PAGE_TEXT_LIMIT])
        if lines
        else None
    )
    return signals, snapshot


async def gather_research(
    ctx: FetchContext,
    settings: Settings,
    company: str,
    slug: str,
    domain: str | None,
    now: datetime | None = None,
) -> ResearchBundle:
    """Fetch the firm's public pages (bounded by ``dossier_max_pages``) and extract
    facts + dated signal candidates. Fail-soft per page; a firm with no domain (or all
    fetches blocked) yields a thin bundle the builder marks low-confidence."""
    moment = now or datetime.now(UTC)
    bundle = ResearchBundle(company=company, slug=slug, domain=domain)
    if domain:
        base = f"https://{domain}"
        candidates: list[SignalCandidate] = []
        for path, kind in _PAGE_PATHS[: max(1, settings.dossier_max_pages)]:
            url = base + path
            try:
                html = await ctx.get_text(url)
            except Exception:
                bundle.errors.append(f"fetch failed: {url}")
                continue
            bundle.fetched_urls.add(url)
            text = html_to_text(html)[:_PAGE_TEXT_LIMIT]
            if text:
                bundle.pages.append(PageSnapshot(url=url, kind=kind, text=text))
            if kind == "homepage":
                bundle.description = extract_description(html)
                bundle.org_facts.update(extract_org_facts(html))
            elif kind in ("about", "team"):
                for key, value in extract_org_facts(html).items():
                    bundle.org_facts.setdefault(key, value)
            if kind in ("homepage", "blog", "news"):
                candidates.extend(extract_dated_links(html, url, kind))
        bundle.signals = recent_signals(candidates, moment, settings.dossier_signal_days)
    else:
        bundle.errors.append("no domain configured in targets.yaml")

    if settings.searxng_url:
        searx_signals, snapshot = await _searxng_signals(ctx, settings.searxng_url, company)
        if snapshot is not None:
            bundle.pages.append(snapshot)
            bundle.fetched_urls.add(snapshot.url)
        merged = recent_signals(
            bundle.signals + searx_signals, moment, settings.dossier_signal_days
        )
        bundle.signals = merged
        bundle.fetched_urls.update(s.url for s in searx_signals)
    return bundle
