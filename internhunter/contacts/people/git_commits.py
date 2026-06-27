"""Commit-email mining via a bare ``git clone`` + ``git log``.

The GitHub people method samples recent commits through the API; this clones a company's top
public repos and walks their FULL history offline, surfacing every ``@domain`` author email —
the highest-confidence contact signal (a real commit) and a strong corpus for email-pattern
locking. Fail-soft: returns ``[]`` if ``git`` is missing or anything errors.
"""
from __future__ import annotations

import subprocess
import tempfile

from internhunter.contacts.types import DiscoveredPerson


def _repo_clone_urls(org: str, token: str | None, max_repos: int) -> list[str]:
    try:
        import httpx
    except Exception:
        return []
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(
            f"https://api.github.com/orgs/{org}/repos",
            params={"sort": "pushed", "per_page": max_repos},
            headers=headers, timeout=20.0,
        )
        if resp.status_code != 200:
            return []
        return [
            str(r["clone_url"]) for r in resp.json()
            if isinstance(r, dict) and r.get("clone_url") and not r.get("fork")
        ][:max_repos]
    except Exception:
        return []


def _authors(clone_url: str) -> list[tuple[str, str]]:
    """[(name, email)] from a bare clone's full history. Empty on any failure."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                ["git", "clone", "--bare", "--filter=blob:none", clone_url, tmp],
                capture_output=True, timeout=120, check=True,
            )
            out = subprocess.run(
                ["git", "-C", tmp, "log", "--all", "--format=%aN|%aE"],
                capture_output=True, timeout=60, check=True, text=True,
            ).stdout
        except Exception:
            return []
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        name, _, email = line.partition("|")
        if email:
            pairs.append((name.strip(), email.strip().lower()))
    return pairs


def discover_people_git_commits(
    org: str, domain: str | None, token: str | None = None,
    max_repos: int = 5, max_people: int = 30,
) -> list[DiscoveredPerson]:
    if not domain:
        return []
    d = domain.lower()
    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    for clone_url in _repo_clone_urls(org, token, max_repos):
        for name, email in _authors(clone_url):
            if not email.endswith("@" + d) or "users.noreply.github.com" in email:
                continue
            if email in seen:
                continue
            seen.add(email)
            people.append(
                DiscoveredPerson(
                    full_name=name or None,
                    title="Engineer",
                    known_email=email,
                    person_source="git_commit",
                    raw={"commit_email": email},
                )
            )
            if len(people) >= max_people:
                return people
    return people
