"""Referral engine: map firms/domains to people in the user's network.

Reads ``connections.yaml``; when a matched posting hits a firm where a connection
exists, the alert + tracker flag it as a warm-intro opportunity and a short draft
intro-request message is generated. Cold applies are flagged separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from internhunter.core.db import Job
from internhunter.core.normalize import canonical_company_slug, normalize_company_slug


@dataclass(frozen=True)
class Connection:
    name: str
    relationship: str = ""
    contact: str = ""
    firms: tuple[str, ...] = ()
    firm_slugs: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    notes: str = ""


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item).strip())


def load_connections(path: Path | str) -> tuple[Connection, ...]:
    """Parse connections.yaml; a missing or malformed file yields no connections (every
    job is then a cold apply) rather than breaking the pipeline."""
    p = Path(path)
    if not p.exists():
        return ()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return ()
    connections: list[Connection] = []
    for raw in data.get("connections") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        firms = _as_str_tuple(raw.get("firms"))
        connections.append(
            Connection(
                name=name,
                relationship=str(raw.get("relationship") or "").strip(),
                contact=str(raw.get("contact") or "").strip(),
                firms=firms,
                firm_slugs=tuple(
                    s for s in (canonical_company_slug(f) for f in firms) if s
                ),
                domains=tuple(
                    d.lower().removeprefix("www.")
                    for d in _as_str_tuple(raw.get("domains"))
                ),
                tags=_as_str_tuple(raw.get("tags")),
                notes=str(raw.get("notes") or "").strip(),
            )
        )
    return tuple(connections)


@lru_cache(maxsize=4)
def _cached_connections(path: str, mtime: float) -> tuple[Connection, ...]:
    return load_connections(path)


def get_connections(path: Path | str) -> tuple[Connection, ...]:
    """mtime-keyed cache so edits apply on the next run without a restart."""
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _cached_connections(str(p), mtime)


def match_connection(
    connections: tuple[Connection, ...],
    company: str | None,
    company_slug: str | None = None,
    company_domain: str | None = None,
) -> Connection | None:
    """First connection whose firms/domains cover this company. Firm names are compared
    on the suffix-stripped canonical slug so 'Polymarket' matches 'Polymarket Inc.'."""
    canonical = canonical_company_slug(company)
    slug = normalize_company_slug(company_slug or "")
    domain = (company_domain or "").lower().removeprefix("www.")
    for conn in connections:
        if domain and conn.domains and any(
            domain == d or domain.endswith("." + d) for d in conn.domains
        ):
            return conn
        if conn.firm_slugs and (
            (canonical and canonical in conn.firm_slugs)
            or (slug and canonical_company_slug(slug) in conn.firm_slugs)
        ):
            return conn
    return None


def connection_for_job(connections: tuple[Connection, ...], job: Job) -> Connection | None:
    return match_connection(connections, job.company, job.company_slug, job.company_domain)


def draft_intro(connection: Connection, job: Job) -> str:
    """A short, sendable intro-request draft. Deliberately template-based (no LLM) so it
    generates instantly and offline; personalize before sending."""
    company = job.company or (job.company_slug or "").replace("-", " ").title() or "the company"
    relationship = connection.relationship or "your connection to the team"
    first_name = connection.name.split()[0] if connection.name else "there"
    return (
        f"Hi {first_name} — hope you're doing well! {company} just posted a "
        f"{job.title} role ({job.canonical_url}) and I'm planning to apply right away. "
        f"Given {relationship}, would you be open to introducing me to someone on the "
        f"team, or pointing me to the right person? Happy to send a two-line blurb and "
        f"my resume to make it zero-effort. Thank you!"
    )
