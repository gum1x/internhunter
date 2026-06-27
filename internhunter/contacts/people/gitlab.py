"""GitLab — keyless public API. A company's public GitLab group exposes its members (name +
username, sometimes a public email) with no auth, a parallel to the GitHub org-members method."""
from __future__ import annotations

from internhunter.contacts.types import DiscoveredPerson


def discover_people_gitlab(
    group: str, domain: str | None, max_people: int = 12
) -> list[DiscoveredPerson]:
    """Public GitLab group members. Sync (runner calls via asyncio.to_thread); [] on failure."""
    try:
        import httpx
    except Exception:
        return []
    url = f"https://gitlab.com/api/v4/groups/{group}/members/all"
    try:
        resp = httpx.get(url, params={"per_page": 100}, timeout=20.0)
        if resp.status_code != 200:
            return []
        members = resp.json()
    except Exception:
        return []
    if not isinstance(members, list):
        return []

    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for m in members:
        if not isinstance(m, dict):
            continue
        username = m.get("username")
        if not isinstance(username, str) or username in seen:
            continue
        seen.add(username)
        email = m.get("public_email") or m.get("email")
        if isinstance(email, str) and domain and not email.lower().endswith("@" + domain.lower()):
            email = None
        person = DiscoveredPerson(
            full_name=m.get("name") or username,
            title="Engineer",
            known_email=email if isinstance(email, str) and email else None,
            person_source="gitlab",
            raw={"gitlab_username": username},
        )
        person.add_channel(
            "gitlab", f"https://gitlab.com/{username}", "gitlab", 85.0, "verified"
        )
        people.append(person)
        if len(people) >= max_people:
            break
    return people
