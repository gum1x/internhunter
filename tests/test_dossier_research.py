from __future__ import annotations

from datetime import UTC, datetime

import pytest

from internhunter.config.settings import Settings
from internhunter.dossier.research import (
    SignalCandidate,
    extract_dated_links,
    extract_description,
    extract_org_facts,
    gather_research,
    recent_signals,
)

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def test_extract_description_prefers_meta_then_og() -> None:
    html = (
        '<head><meta name="description" content="Plain what-we-do."/>'
        '<meta property="og:description" content="OG text."/></head>'
    )
    assert extract_description(html) == "Plain what-we-do."
    assert extract_description('<meta property="og:description" content="OG."/>') == "OG."
    assert extract_description("<html></html>") is None


def test_extract_org_facts_from_jsonld() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Organization", "name": "TinyCo", '
        '"numberOfEmployees": {"@type": "QuantitativeValue", "value": 45}, '
        '"foundingDate": "2021"}</script>'
    )
    facts = extract_org_facts(html)
    assert facts["team_size"] == "45"
    assert facts["founded"] == "2021"
    assert extract_org_facts("<p>no ld</p>") == {}


def test_extract_dated_links_time_tag_and_url_pattern() -> None:
    html = """
    <ul>
      <li><a href="/blog/big-launch-announcement">We launched a big new market product</a>
          <time datetime="2026-06-12">June 12</time></li>
      <li><a href="/blog/2026/05/series-b">Announcing our Series B fundraising round</a></li>
      <li><a href="/blog/undated-post">A post with no date anywhere near this anchor at all</a></li>
      <li><a href="/blog/short">Blog</a><time datetime="2026-06-01">x</time></li>
      <li><a href="/market/will-x-happen">Will something dramatic happen by July 31?</a>
          <time datetime="2026-06-25">June 25</time></li>
      <li><a href="https://elsewhere.com/2026/06/offsite">Offsite article about other
          things</a></li>
    </ul>
    """
    links = extract_dated_links(html, "https://tinyco.com/blog", "blog")
    by_url = {link.url: link for link in links}
    assert "https://tinyco.com/blog/big-launch-announcement" in by_url
    assert by_url["https://tinyco.com/blog/big-launch-announcement"].date == "2026-06-12"
    assert "https://tinyco.com/blog/2026/05/series-b" in by_url
    assert by_url["https://tinyco.com/blog/2026/05/series-b"].date == "2026-05-01"
    assert "https://tinyco.com/blog/undated-post" not in by_url  # undated is never a signal
    assert "https://tinyco.com/blog/short" not in by_url  # nav-length titles skipped
    assert "https://tinyco.com/market/will-x-happen" not in by_url  # questions aren't news
    assert all("elsewhere.com" not in u for u in by_url)


def test_recent_signals_window_sort_dedupe() -> None:
    mk = lambda d, u="https://x/a": SignalCandidate("t", u, d, "blog")  # noqa: E731
    out = recent_signals(
        [mk("2026-06-01"), mk("2025-01-01", "https://x/old"), mk("2026-06-20", "https://x/b"),
         mk("2026-06-01")],
        NOW,
        window_days=180,
    )
    assert [s.date for s in out] == ["2026-06-20", "2026-06-01"]


class _Ctx:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

        class _Log:
            def debug(self, *a: object, **k: object) -> None: ...

        self.logger = _Log()

    async def get_text(self, url: str, **_: object) -> str:
        if url not in self.pages:
            raise RuntimeError("403")
        return self.pages[url]

    async def get_json(self, url: str, **_: object) -> object:
        raise RuntimeError("no searxng")


_HOME = (
    '<head><meta name="description" content="TinyCo builds prediction market '
    'infrastructure. Real-time settlement for event contracts."/></head>'
    "<body><p>TinyCo builds infra.</p></body>"
)


@pytest.mark.asyncio
async def test_gather_research_collects_pages_and_facts() -> None:
    ctx = _Ctx(
        {
            "https://tinyco.com": _HOME,
            "https://tinyco.com/blog": (
                '<a href="/blog/launch-of-new-settlement-engine">'
                "Launch of our new settlement engine</a>"
                '<time datetime="2026-06-15">June 15</time>'
            ),
        }
    )
    settings = Settings(dossier_max_pages=5)
    bundle = await gather_research(
        ctx, settings, "TinyCo", "tinyco", "tinyco.com", now=NOW  # type: ignore[arg-type]
    )
    assert not bundle.thin
    assert bundle.description is not None and "prediction market" in bundle.description
    assert {p.kind for p in bundle.pages} == {"homepage", "blog"}
    assert bundle.signals and bundle.signals[0].date == "2026-06-15"
    assert "https://tinyco.com" in bundle.fetched_urls
    assert any("fetch failed" in e for e in bundle.errors)  # /about etc. 403'd


@pytest.mark.asyncio
async def test_gather_research_no_domain_is_thin() -> None:
    bundle = await gather_research(
        _Ctx({}), Settings(), "Ghost Co", "ghost-co", None, now=NOW  # type: ignore[arg-type]
    )
    assert bundle.thin
    assert bundle.errors == ["no domain configured in targets.yaml"]


@pytest.mark.asyncio
async def test_gather_research_all_blocked_is_thin() -> None:
    bundle = await gather_research(
        _Ctx({}), Settings(), "Walled", "walled", "walled.io", now=NOW  # type: ignore[arg-type]
    )
    assert bundle.thin
    assert len(bundle.errors) >= 1
