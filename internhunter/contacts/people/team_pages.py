from __future__ import annotations

import json
from typing import TYPE_CHECKING

from internhunter.contacts.types import DiscoveredPerson
from internhunter.core.fetch import FetchContext

if TYPE_CHECKING:
    from internhunter.llm.client import LlmBackend, LlmCache

_EXTRACT_SYSTEM = (
    "You extract people from a company web page. Return ONLY a JSON object "
    '{"people":[{"name":"...","title":"..."}]} listing employees named on the page '
    "(leadership, recruiting, HR, hiring). Skip generic text. Max 12 people."
)


async def discover_people_team_pages(
    ctx: FetchContext,
    domain: str,
    backend: LlmBackend | None = None,
    cache: LlmCache | None = None,
    model: str = "local",
    paths: tuple[str, ...] = ("team", "about", "about/team", "leadership", "people", "company"),
) -> list[DiscoveredPerson]:
    """Render company team/about pages and LLM-extract (name, title). Best-effort."""
    if backend is None:
        return []
    from internhunter.llm.client import complete

    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for path in paths:
        url = f"https://{domain}/{path}"
        html: str | None = None
        try:
            if ctx.browser is not None:
                html = await ctx.browser.render(url)
            else:
                html = await ctx.get_text(url, respect_robots=False)
        except Exception:
            continue
        if not html:
            continue
        text = html[:18000]
        try:
            raw = complete(
                f"Page from {url}:\n\n{text}",
                backend,
                system=_EXTRACT_SYSTEM,
                cache=cache,
                model=model,
            )
            data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        except Exception:
            continue
        for entry in data.get("people", []) if isinstance(data, dict) else []:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            people.append(
                DiscoveredPerson(
                    full_name=name,
                    title=(entry.get("title") or "").strip() or None,
                    person_source="team_page",
                    raw={"page": url},
                )
            )
    return people
