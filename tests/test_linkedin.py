from __future__ import annotations

from typing import Any

import httpx

from internhunter.discovery.linkedin import _page_url, fetch_linkedin, parse_cards

_FRAGMENT = """
<li>
  <div class="base-card">
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123?ref=abc"></a>
    <h3 class="base-search-card__title">Software Engineer Intern</h3>
    <h4 class="base-search-card__subtitle">Acme Corp</h4>
    <span class="job-search-card__location">New York, NY</span>
    <time datetime="2026-05-01"></time>
  </div>
</li>
<li>
  <div class="base-card">
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/456"></a>
    <h3 class="base-search-card__title">Senior Director</h3>
    <h4 class="base-search-card__subtitle">Beta</h4>
    <span class="job-search-card__location">Remote</span>
  </div>
</li>
"""


def test_parse_cards_extracts_fields() -> None:
    cards = parse_cards(_FRAGMENT)
    assert len(cards) == 2
    first = cards[0]
    assert first.title == "Software Engineer Intern"
    assert first.company == "Acme Corp"
    assert first.url == "https://www.linkedin.com/jobs/view/123"
    assert first.location == "New York, NY"
    assert first.posted == "2026-05-01"
    assert first.source == "linkedin"


async def test_fetch_linkedin_paginates_and_stops(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_page_url("intern", "United States", 0)] = httpx.Response(200, text=_FRAGMENT)
    # page 1 empty -> loop stops
    ctx.responses[_page_url("intern", "United States", 25)] = httpx.Response(200, text="")
    settings = ctx.settings.model_copy(
        update={
            "linkedin_locations": "United States",
            "linkedin_keywords": "intern",
            "linkedin_max_pages": 3,
        }
    )
    jobs = await fetch_linkedin(ctx, settings)
    assert {j.url for j in jobs} == {
        "https://www.linkedin.com/jobs/view/123",
        "https://www.linkedin.com/jobs/view/456",
    }
