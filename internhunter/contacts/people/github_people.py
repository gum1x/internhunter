from __future__ import annotations

from typing import Any

from internhunter.contacts.types import DiscoveredPerson


def _client(token: str | None):  # type: ignore[no-untyped-def]
    try:
        from github import Auth, Github
    except Exception:
        return None
    try:
        if token:
            return Github(auth=Auth.Token(token))
        return Github()  # unauthenticated: 60 req/hr
    except Exception:
        return None


def _profile_email(user: object, domain: str | None) -> str | None:
    email = (getattr(user, "email", None) or "").lower()
    if not email or "users.noreply.github.com" in email:
        return None
    if domain and not email.endswith("@" + domain.lower()):
        return None
    return email


def _social_accounts(login: str, token: str | None) -> list[tuple[str, str]]:
    """Keyless GET /users/{login}/social_accounts -> [(provider, url)] (self-declared
    x/mastodon/bluesky/linkedin/site). Best-effort; [] on any failure."""
    try:
        import httpx
    except Exception:
        return []
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(
            f"https://api.github.com/users/{login}/social_accounts",
            headers=headers, timeout=15.0,
        )
        if resp.status_code != 200:
            return []
        return [
            (str(a.get("provider") or ""), str(a["url"]))
            for a in resp.json()
            if isinstance(a, dict) and a.get("url")
        ]
    except Exception:
        return []


def _add_social_channels(
    person: DiscoveredPerson, member: object, login: str, token: str | None
) -> None:
    from internhunter.contacts.channels import classify_url, kind_for_provider

    person.add_channel("github", f"https://github.com/{login}", "github", 90.0, "verified")
    for provider, url in _social_accounts(login, token):
        person.add_channel(kind_for_provider(provider, url), url, "github_social", 85.0)
    twitter = getattr(member, "twitter_username", None)
    if twitter:
        person.add_channel("x", f"https://x.com/{twitter}", "github_profile", 85.0)
    blog = getattr(member, "blog", None)
    if blog and blog.startswith("http"):
        person.add_channel(classify_url(blog), blog, "github_profile", 80.0)


def _events_email(user: object, domain: str | None) -> tuple[str | None, str | None]:
    """Mine a user's public events (PushEvents across ALL their repos) for an @domain
    commit email — uses the core REST quota, not the 10/min Search API."""
    if not domain:
        return None, None
    d = domain.lower()
    try:
        events = list(user.get_public_events()[:30])  # type: ignore[attr-defined]
    except Exception:
        return None, None
    for event in events:
        if getattr(event, "type", None) != "PushEvent":
            continue
        for commit in (getattr(event, "payload", None) or {}).get("commits", []):
            author = commit.get("author") or {}
            email = (author.get("email") or "").lower()
            if email.endswith("@" + d) and "users.noreply.github.com" not in email:
                return email, author.get("name")
    return None, None


def discover_people_github(
    org: str,
    domain: str | None,
    token: str | None = None,
    max_people: int = 8,
    max_repos: int = 5,
) -> list[DiscoveredPerson]:
    """Org public members + commit-author emails (filtered to the company domain).

    Synchronous (PyGithub is sync); the runner calls this via ``asyncio.to_thread``.
    Returns ``[]`` on any failure (missing dep, bad org, rate limit).
    """
    gh = _client(token)
    if gh is None:
        return []
    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    try:
        organization = gh.get_organization(org)
    except Exception:
        return []

    # Public members -> engineers. Now also read profile .email/.blog/.company and mine
    # public events for a real @domain commit email.
    confirmed_members: list[Any] = []
    try:
        for member in organization.get_members():
            if len(people) >= max_people:
                break
            login = getattr(member, "login", None)
            if not login or login in seen:
                continue
            seen.add(login)
            known = _profile_email(member, domain)
            ev_name = None
            if known is None:
                known, ev_name = _events_email(member, domain)
            person = DiscoveredPerson(
                full_name=getattr(member, "name", None) or ev_name or login,
                title="Engineer",
                github_login=login,
                known_email=known,
                person_source="github",
                raw={
                    "github_login": login,
                    "blog": getattr(member, "blog", None) or None,
                    "company": getattr(member, "company", None) or None,
                },
            )
            _add_social_channels(person, member, login, token)
            people.append(person)
            if known:
                confirmed_members.append(member)
    except Exception:
        pass

    # Commit-author emails on the org's top repos -> real @domain emails.
    if domain:
        d = domain.lower()
        try:
            repos = list(organization.get_repos(sort="pushed"))[:max_repos]
        except Exception:
            repos = []
        for repo in repos:
            try:
                for commit in repo.get_commits()[:30]:
                    author = commit.commit.author
                    email = (getattr(author, "email", "") or "").lower()
                    name = getattr(author, "name", None)
                    if not email.endswith("@" + d):
                        continue
                    key = email
                    if key in seen:
                        continue
                    seen.add(key)
                    people.append(
                        DiscoveredPerson(
                            full_name=name,
                            title="Engineer",
                            github_login=getattr(commit.author, "login", None),
                            known_email=email,
                            person_source="github",
                            raw={"commit_email": email},
                        )
                    )
                    if len(people) >= max_people * 2:
                        break
            except Exception:
                pass

            # Full-history anonymous contributors -> bulk @domain emails, confirmed by
            # construction (they came from a commit). The only confirmation path on
            # Google-MX companies; each @domain hit also locks the company format.
            try:
                for contrib in repo.get_contributors(anon="true")[:50]:
                    if getattr(contrib, "type", None) != "Anonymous":
                        continue
                    email = (getattr(contrib, "email", "") or "").lower()
                    if not email.endswith("@" + d) or email in seen:
                        continue
                    seen.add(email)
                    people.append(
                        DiscoveredPerson(
                            full_name=getattr(contrib, "name", None),
                            title="Engineer",
                            known_email=email,
                            person_source="github",
                            raw={"contributor_email": email},
                        )
                    )
                    if len(people) >= max_people * 3:
                        break
            except Exception:
                continue

    # Gated social-graph walk: from a confirmed @domain committer, admit followed users
    # whose profile .company matches the org/domain. The same-company gate keeps it precise.
    if confirmed_members and domain and len(people) < max_people * 2:
        d = domain.lower()
        base = d.split(".")[0]
        try:
            for seed in confirmed_members[:2]:
                for followed in list(seed.get_following()[:30]):
                    if len(people) >= max_people * 2:
                        break
                    login = getattr(followed, "login", None)
                    if not login or login in seen:
                        continue
                    company = (getattr(followed, "company", "") or "").lower().lstrip("@")
                    known = _profile_email(followed, domain)
                    if not (known or (company and (org.lower() in company or base in company))):
                        continue
                    seen.add(login)
                    people.append(
                        DiscoveredPerson(
                            full_name=getattr(followed, "name", None) or login,
                            title="Engineer",
                            github_login=login,
                            known_email=known,
                            person_source="github_graph",
                            raw={"github_login": login, "via": "following"},
                        )
                    )
        except Exception:
            pass
    return people
