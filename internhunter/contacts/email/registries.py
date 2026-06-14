from __future__ import annotations

from typing import Any

from internhunter.contacts.email.harvest import is_role_account
from internhunter.contacts.types import DiscoveredPerson
from internhunter.core.fetch import FetchContext

# Package-registry author/maintainer emails — keyless, and they skew PERSONAL (the
# maintainer's own address), giving a second reach channel beyond the work email.


def parse_npm(data: Any) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    if not isinstance(data, dict):
        return out
    author = data.get("author")
    if isinstance(author, dict) and isinstance(author.get("email"), str):
        out.append((author.get("name"), author["email"]))
    for m in data.get("maintainers", []) if isinstance(data.get("maintainers"), list) else []:
        if isinstance(m, dict) and isinstance(m.get("email"), str):
            out.append((m.get("name"), m["email"]))
    return out


def parse_pypi(data: Any) -> list[tuple[str | None, str]]:
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return []
    out: list[tuple[str | None, str]] = []
    for name_key, email_key in (("author", "author_email"), ("maintainer", "maintainer_email")):
        email = info.get(email_key)
        if isinstance(email, str) and "@" in email:
            # author_email can be "Name <email>" — keep just the address
            addr = email.split("<")[-1].strip(" <>") if "<" in email else email.strip()
            out.append((info.get(name_key), addr))
    return out


async def harvest_registry_people(
    ctx: FetchContext, packages: list[str], max_packages: int = 8
) -> list[DiscoveredPerson]:
    """For each candidate package name, pull maintainer emails from npm + PyPI."""
    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for pkg in packages[:max_packages]:
        pairs: list[tuple[str | None, str]] = []
        for url, parse in (
            (f"https://registry.npmjs.org/{pkg}", parse_npm),
            (f"https://pypi.org/pypi/{pkg}/json", parse_pypi),
        ):
            try:
                pairs += parse(await ctx.get_json(url, respect_robots=False))
            except Exception:
                continue
        for name, email in pairs:
            em = email.strip().lower()
            if em in seen or is_role_account(em) or "noreply" in em:
                continue
            seen.add(em)
            person = DiscoveredPerson(
                full_name=name, title="Engineer", known_email=em,
                person_source="registry",
            )
            person.add_channel("personal_email", em, "registry", 60.0, "guessed")
            people.append(person)
    return people
