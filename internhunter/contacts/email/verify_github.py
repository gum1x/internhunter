from __future__ import annotations

# GitHub's commit-search API maps an email to the GitHub account that authored commits
# with it. A hit is near-proof the mailbox is real (someone configured git with it) and,
# unlike holehe, works well for engineers at tech companies. HTTPS only — unaffected by
# the blocked port 25.

_API = "https://api.github.com/search/commits"


async def github_confirms(
    email: str, token: str | None = None, timeout: float = 15.0
) -> tuple[bool, str | None]:
    """Return (confirmed, login). confirmed=True if any commit was authored by this email."""
    try:
        import httpx
    except Exception:
        return False, None
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                _API,
                params={"q": f"author-email:{email}", "per_page": 1},
                headers=headers,
            )
        if resp.status_code != 200:
            return False, None
        data = resp.json()
        if int(data.get("total_count", 0)) <= 0:
            return False, None
        items = data.get("items") or []
        login = None
        if items and isinstance(items[0], dict):
            author = items[0].get("author")
            if isinstance(author, dict):
                login = author.get("login")
        return True, login
    except Exception:
        return False, None
