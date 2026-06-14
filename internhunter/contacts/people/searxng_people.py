from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from internhunter.contacts.types import DiscoveredPerson
from internhunter.core.fetch import FetchContext

# Dork templates run per company. {company} is substituted; results are public
# LinkedIn profiles indexed by the search engine (no LinkedIn login = no ban risk).
_DORKS: list[str] = [
    'site:linkedin.com/in ("recruiter" OR "talent acquisition") "{company}"',
    (
        'site:linkedin.com/in ("university recruiter" OR "campus recruiting" OR '
        '"early careers" OR "early talent" OR "emerging talent" OR "intern program" OR '
        '"new grad" OR "student programs") "{company}"'
    ),
    'site:linkedin.com/in ("hiring manager" OR "engineering manager") "{company}"',
    'site:linkedin.com/in ("software engineer" OR intern) "{company}"',
    # SEO data-aggregator pages — structured org charts, often recruiter-rich and not
    # behind a login. TheOrg first; the rest as backup name+title sources.
    'site:theorg.com "{company}" (recruiter OR "talent" OR "people")',
    'site:rocketreach.co "{company}" (recruiter OR "talent acquisition")',
    'site:signalhire.com "{company}" recruiter',
]

_PROFILE_RE = re.compile(r"linkedin\.com/in/[^/?#\s\"']+", re.IGNORECASE)
# "First Last - Title at Company | LinkedIn"  /  "First Last - Title - Company | LinkedIn"
_TITLE_RE = re.compile(
    r"^(?P<name>[^|\-–]+?)\s*[\-–]\s*(?P<title>.+?)(?:\s+(?:at|@)\s+.+)?\s*[|\-–]\s*LinkedIn",
    re.IGNORECASE,
)


def _search_url(base_url: str, query: str) -> str:
    params = urlencode({"q": query, "format": "json"})
    return f"{base_url.rstrip('/')}/search?{params}"


def parse_result(title: str, url: str) -> DiscoveredPerson | None:
    """Extract (name, title, profile url) from one SearXNG result."""
    profile_match = _PROFILE_RE.search(url or "")
    linkedin_url = ("https://www." + profile_match.group(0)) if profile_match else None

    name: str | None = None
    role_title: str | None = None
    m = _TITLE_RE.match(title or "")
    if m:
        name = m.group("name").strip()
        role_title = m.group("title").strip().rstrip(" |-–")
    elif title:
        # Fallback: take the text before the first separator as the name.
        name = re.split(r"[|\-–]", title, maxsplit=1)[0].strip() or None

    if not name and not linkedin_url:
        return None
    return DiscoveredPerson(
        full_name=name,
        title=role_title,
        linkedin_url=linkedin_url,
        person_source="searxng",
        raw={"result_title": title, "result_url": url},
    )


# Per-platform dorks that surface a person's social handle (a reach channel). Blind
# name-search => low base confidence (promoted only when corroborated by another source).
_SOCIAL_DORKS: list[str] = [
    'site:github.com "{company}"',
    '(site:x.com OR site:twitter.com) "{company}"',
    'site:bsky.app "{company}"',
    'site:about.me "{company}"',
]


def parse_social_result(title: str, url: str) -> DiscoveredPerson | None:
    from internhunter.contacts.channels import classify_url

    kind = classify_url(url)
    if kind == "site":  # generic sites are too noisy to attribute from a blind search
        return None
    name = re.split(r"[|\-–·@(]", title or "", maxsplit=1)[0].strip() or None
    if not name or len(name) < 3:
        return None
    person = DiscoveredPerson(full_name=name, person_source="searxng_social", raw={"url": url})
    person.add_channel(kind, url, "searxng_dork", 50.0, "guessed")
    return person


async def discover_social_searxng(
    ctx: FetchContext, base_url: str, company: str
) -> list[DiscoveredPerson]:
    people: list[DiscoveredPerson] = []
    for dork in _SOCIAL_DORKS:
        url = _search_url(base_url, dork.format(company=company))
        try:
            data: Any = await ctx.get_json(url, respect_robots=False)
        except Exception:
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            continue
        for result in results[:10]:
            if not isinstance(result, dict):
                continue
            person = parse_social_result(
                str(result.get("title") or ""), str(result.get("url") or "")
            )
            if person is not None:
                people.append(person)
    return people


async def discover_people_searxng(
    ctx: FetchContext,
    base_url: str,
    company: str,
    dorks: list[str] | None = None,
) -> list[DiscoveredPerson]:
    resolved = dorks if dorks is not None else _DORKS
    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for dork in resolved:
        query = dork.format(company=company)
        url = _search_url(base_url, query)
        try:
            data: Any = await ctx.get_json(url, respect_robots=False)
        except Exception:
            ctx.logger.debug("searxng people search failed for {}", query)
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            person = parse_result(
                str(result.get("title") or ""), str(result.get("url") or "")
            )
            if person is None:
                continue
            key = person.dedup_key()
            if key in seen:
                continue
            seen.add(key)
            people.append(person)
    return people
