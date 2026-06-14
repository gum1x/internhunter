from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING
from urllib.parse import urlencode

if TYPE_CHECKING:
    from internhunter.core.fetch import FetchContext

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Generic-but-useful recruiting inboxes — legitimately the intended outreach target.
RECRUITING_ALIASES = [
    "careers",
    "jobs",
    "recruiting",
    "recruitment",
    "talent",
    "university",
    "universityrecruiting",
    "campus",
    "internships",
    "hr",
    "people",
    "hello",
]

_ROLE_LOCALPARTS = {
    "info",
    "support",
    "admin",
    "sales",
    "contact",
    "no-reply",
    "noreply",
    "postmaster",
    "webmaster",
    "abuse",
    "marketing",
}


def extract_emails(text: str, domain: str | None = None) -> list[str]:
    """All emails in a blob of HTML/text, optionally filtered to one domain."""
    found = {m.group(0).lower() for m in _EMAIL_RE.finditer(text)}
    if domain:
        d = domain.lower()
        found = {e for e in found if e.endswith("@" + d)}
    return sorted(found)


def is_role_account(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in _ROLE_LOCALPARTS


def is_recruiting_alias(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in RECRUITING_ALIASES


def candidate_aliases(domain: str) -> list[str]:
    return [f"{alias}@{domain}" for alias in RECRUITING_ALIASES]


async def harvest_site_emails(
    ctx: FetchContext,
    domain: str,
    paths: tuple[str, ...] = ("", "careers", "about", "contact", "team", "jobs"),
) -> list[str]:
    """Scrape common pages on a company domain for published emails."""
    found: set[str] = set()
    for path in paths:
        url = f"https://{domain}/{path}".rstrip("/")
        try:
            html = await ctx.get_text(url, respect_robots=False)
        except Exception:
            continue
        found.update(extract_emails(html, domain=domain))
    return sorted(found)


async def harvest_searxng_emails(
    ctx: FetchContext,
    searxng_url: str,
    domain: str,
    names: list[str] | None = None,
    max_queries: int = 8,
) -> list[str]:
    """Dork a self-hosted SearXNG for published ``@domain`` emails across the whole web
    (not just the company's own site). Keyless; grows the real-email corpus so patterns
    lock on non-Microsoft domains too."""
    queries = [
        f'"@{domain}"',
        f'site:{domain} "@{domain}"',
        f'"{domain}" (email OR contact OR recruiter)',
    ]
    for name in (names or [])[:5]:
        queries.append(f'"{name}" "@{domain}"')

    base = searxng_url.rstrip("/")
    found: set[str] = set()
    for query in queries[:max_queries]:
        url = f"{base}/search?{urlencode({'q': query, 'format': 'json'})}"
        try:
            data = await ctx.get_json(url, respect_robots=False)
        except Exception:
            continue
        results = data.get("results", []) if isinstance(data, dict) else []
        for result in results:
            if not isinstance(result, dict):
                continue
            blob = " ".join(str(result.get(k, "")) for k in ("title", "content", "url"))
            found.update(extract_emails(blob, domain=domain))
    return sorted(found)


def harvest_theharvester(domain: str, timeout: float = 120.0) -> list[str]:
    """Run theHarvester (if installed) for domain-wide email samples. Best-effort."""
    binary = shutil.which("theHarvester") or shutil.which("theharvester")
    if binary is None:
        return []
    try:
        proc = subprocess.run(
            [binary, "-d", domain, "-b", "duckduckgo,bing,crtsh,certspotter", "-f", "-"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return []
    emails: set[str] = set()
    # theHarvester -f - emits JSON to stdout on recent versions; fall back to regex.
    try:
        data = json.loads(proc.stdout)
        for e in data.get("emails", []) if isinstance(data, dict) else []:
            if isinstance(e, str):
                emails.add(e.lower())
    except Exception:
        emails.update(extract_emails(proc.stdout, domain=domain))
    return sorted(e for e in emails if e.endswith("@" + domain.lower()))
