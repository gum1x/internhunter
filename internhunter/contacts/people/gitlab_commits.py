"""Keyless GitLab public-commit email mining.

The group/project *members* API is 401 without a token, but public-project **commits** are
keyless (verified live; 500 req/min unauthenticated) and expose ``author_name`` + ``author_email``.
We resolve a company's GitLab group from its slug, list its projects, and harvest @domain author
emails — the same high-confidence signal as the GitHub ``git_commits`` method. Fail-soft to [].
"""
from __future__ import annotations

from typing import Any

from internhunter.contacts.types import DiscoveredPerson

_API = "https://gitlab.com/api/v4"


def _project_ids(client: Any, company_slug: str, max_projects: int) -> list[int]:
    ids: list[int] = []
    try:
        r = client.get(
            f"{_API}/groups/{company_slug}/projects",
            params={"order_by": "last_activity_at", "per_page": max_projects,
                    "include_subgroups": "true"},
            timeout=20.0,
        )
        if r.status_code == 200:
            ids += [p["id"] for p in r.json() if isinstance(p, dict) and "id" in p]
    except Exception:
        pass
    if not ids:
        try:
            r = client.get(
                f"{_API}/projects",
                params={"search": company_slug, "order_by": "star_count",
                        "per_page": max_projects},
                timeout=20.0,
            )
            if r.status_code == 200:
                ids += [
                    p["id"] for p in r.json()
                    if isinstance(p, dict)
                    and str(p.get("path_with_namespace", "")).startswith(company_slug)
                ]
        except Exception:
            pass
    return ids[:max_projects]


def discover_people_gitlab_commits(
    company_slug: str, domain: str | None,
    max_projects: int = 5, max_people: int = 30,
) -> list[DiscoveredPerson]:
    if not domain:
        return []
    try:
        import httpx
    except Exception:
        return []
    d = domain.lower()
    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    try:
        with httpx.Client(headers={"Accept": "application/json"}) as client:
            for pid in _project_ids(client, company_slug, max_projects):
                try:
                    r = client.get(
                        f"{_API}/projects/{pid}/repository/commits",
                        params={"per_page": 100}, timeout=20.0,
                    )
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                for c in r.json():
                    if not isinstance(c, dict):
                        continue
                    email = str(c.get("author_email", "")).strip().lower()
                    if not email.endswith("@" + d) or "noreply" in email or email in seen:
                        continue
                    seen.add(email)
                    person = DiscoveredPerson(
                        full_name=c.get("author_name") or None,
                        title="Engineer",
                        known_email=email,
                        person_source="gitlab_commit",
                        raw={"commit_email": email, "gitlab_project_id": pid},
                    )
                    person.add_channel("work_email", email, "gitlab_commit", 85.0, "verified")
                    people.append(person)
                    if len(people) >= max_people:
                        return people
    except Exception:
        return people
    return people
