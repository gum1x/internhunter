from __future__ import annotations

from collections import defaultdict
from typing import Any

from internhunter.contacts.types import DiscoveredPerson

# Union-find identity resolution WITHIN one company: collapse a person found via LinkedIn
# in source A + GitHub in source B + an email in source C into one multi-channel record.
# Strong identifiers merge; conflicting strong identifiers (different github_login /
# different known_email) block a merge so two same-named people never fuse.

# Singular identity keys — at most one true value per real person.
_SINGULAR = ("gh", "li", "em")


def _strong_ids(p: DiscoveredPerson) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    if p.github_login:
        ids["gh"] = p.github_login.lower()
    if p.linkedin_url:
        ids["li"] = p.linkedin_url.lower().rstrip("/")
    if p.known_email:
        ids["em"] = p.known_email.lower()
    verified: set[tuple[str, str]] = set()
    for ch in p.channels:
        if ch.get("status") == "verified" and ch.get("value"):
            verified.add((ch["kind"], ch["value"].strip().lower().rstrip("/")))
    ids["_verified"] = verified
    ids["_name"] = (p.full_name or "").strip().lower()
    return ids


def _conflict(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return any(a.get(t) and b.get(t) and a[t] != b[t] for t in _SINGULAR)


def _has_identifier(x: dict[str, Any]) -> bool:
    """A strong id or a verified channel — any signal of identity beyond a bare name."""
    return bool(x.get("gh") or x.get("li") or x.get("em") or x["_verified"])


def _shares(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if any(a.get(t) and b.get(t) and a[t] == b[t] for t in _SINGULAR):
        return True
    if a["_verified"] & b["_verified"]:
        return True
    # Same name at the same company can merge — but absence of a *conflict* is not proof of
    # sameness when neither side carries any identifier. Two name-only "Jane Doe" records
    # could be two different people, so require at least one side to have a strong/verified
    # id corroborating that this is the same person (the other side's data is then folded in).
    if a["_name"] and a["_name"] == b["_name"]:
        return _has_identifier(a) or _has_identifier(b)
    return False


def _merge_into(base: DiscoveredPerson, other: DiscoveredPerson) -> None:
    base.full_name = base.full_name or other.full_name
    base.title = base.title or other.title
    base.role_category = base.role_category or other.role_category
    base.linkedin_url = base.linkedin_url or other.linkedin_url
    base.github_login = base.github_login or other.github_login
    base.known_email = base.known_email or other.known_email
    for ch in other.channels:
        base.add_channel(
            ch["kind"], ch["value"], ch.get("source"),
            ch.get("confidence"), ch.get("status", "guessed"),
        )


def merge_people(people: list[DiscoveredPerson]) -> list[DiscoveredPerson]:
    """Collapse records that are the same person (union-find over strong identifiers)."""
    n = len(people)
    if n < 2:
        return people
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = [_strong_ids(p) for p in people]
    for i in range(n):
        for j in range(i + 1, n):
            if _conflict(ids[i], ids[j]):
                continue
            if _shares(ids[i], ids[j]):
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    merged: list[DiscoveredPerson] = []
    for idxs in groups.values():
        base = people[idxs[0]]
        for k in idxs[1:]:
            _merge_into(base, people[k])
        merged.append(base)
    return merged
