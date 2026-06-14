from __future__ import annotations

from urllib.parse import urlsplit

# Map a social/profile URL to a ContactChannel kind. Unknown hosts -> "site".
_MASTODON_HINTS = (
    "mastodon", "fosstodon", "hachyderm", "infosec.exchange", "mas.to", "fediverse",
    "ioc.exchange", "techhub.social", "social.",
)


def classify_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return "site"
    host = urlsplit(raw if "//" in raw else "https://" + raw).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if "linkedin.com" in host:
        return "linkedin"
    if host in ("x.com", "twitter.com", "t.co") or host.endswith(".twitter.com"):
        return "x"
    if "github.com" in host:
        return "github"
    if "bsky." in host or "bluesky" in host:
        return "bluesky"
    if any(h in host for h in _MASTODON_HINTS):
        return "mastodon"
    return "site"


# GitHub social_accounts `provider` -> kind (authoritative when present).
_PROVIDER_KIND = {
    "twitter": "x",
    "mastodon": "mastodon",
    "bluesky": "bluesky",
    "linkedin": "linkedin",
    "generic": "site",
}


def kind_for_provider(provider: str | None, url: str) -> str:
    if provider and provider.lower() in _PROVIDER_KIND:
        return _PROVIDER_KIND[provider.lower()]
    return classify_url(url)
