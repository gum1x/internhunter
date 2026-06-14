from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# A Gravatar hit means the address is a real, used mailbox (someone made a profile for it)
# and often exposes the person's verified social accounts — a free HTTPS verification +
# enrichment signal that sidesteps the blocked port 25.


@dataclass
class GravatarResult:
    found: bool = False
    display_name: str | None = None
    social_urls: list[str] = field(default_factory=list)


def _hashes(email: str) -> list[str]:
    norm = email.strip().lower().encode("utf-8")
    return [
        hashlib.sha256(norm).hexdigest(),
        hashlib.md5(norm).hexdigest(),  # legacy gravatar hash
    ]


async def gravatar_lookup(email: str, timeout: float = 12.0) -> GravatarResult:
    try:
        import httpx
    except Exception:
        return GravatarResult()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for digest in _hashes(email):
            try:
                resp = await client.get(f"https://gravatar.com/{digest}.json")
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            entries = data.get("entry") if isinstance(data, dict) else None
            if not isinstance(entries, list) or not entries:
                continue
            entry = entries[0] if isinstance(entries[0], dict) else {}
            urls: list[str] = []
            seen: set[str] = set()
            # legacy `accounts` + the cryptographically owner-`verified_accounts` block
            for key in ("accounts", "verified_accounts"):
                for acc in entry.get(key, []):
                    url = acc.get("url") if isinstance(acc, dict) else None
                    if isinstance(url, str) and url not in seen:
                        seen.add(url)
                        urls.append(url)
            display = entry.get("displayName")
            return GravatarResult(found=True, display_name=display, social_urls=urls)
    return GravatarResult()
