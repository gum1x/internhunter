"""Shared helpers for parsing internship posts out of free-form social text (Reddit, Bluesky,
and any future social source). Posts aren't structured job listings, so we extract a usable
title, the apply URL, and a best-effort company/location from the prose."""
from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
# "<Company> is hiring ...", "Hiring: ... at <Company>", "<Company> — Summer 2026 Intern"
_AT_COMPANY_RE = re.compile(r"\bat\s+([A-Z][\w&.\- ]{1,40})", re.MULTILINE)
_COMPANY_HIRING_RE = re.compile(r"^([A-Z][\w&.\- ]{1,40})\s+(?:is\s+)?hiring", re.MULTILINE)
_LOCATION_RE = re.compile(
    r"\b(remote|hybrid|on-?site|[A-Z][a-z]+(?:,\s*[A-Z]{2})?)\b"
)


def first_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,);") if m else None


def all_urls(text: str) -> list[str]:
    return [u.rstrip(".,);") for u in _URL_RE.findall(text or "")]


def extract_company(text: str) -> str | None:
    for rx in (_COMPANY_HIRING_RE, _AT_COMPANY_RE):
        m = rx.search(text or "")
        if m:
            return m.group(1).strip().rstrip(".,")
    return None


def title_from_text(text: str, max_len: int = 140) -> str:
    """First non-empty line, trimmed — used as the posting title."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:max_len]
    return (text or "").strip()[:max_len]
