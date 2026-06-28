"""Resolve company → ATS via DNS, the trail Common Crawl/search can't see.

Companies almost always point a ``careers.``/``jobs.`` subdomain at their ATS with a CNAME
(e.g. ``careers.acme.com`` → ``acme.recruitee.com`` or ``acme.wd1.myworkdayjobs.com``). Walking
that CNAME chain and fingerprinting the target recovers the board even when the company's own
pages never link it in crawlable HTML. Pairs with the existing ``reresolve`` (which follows
apply-link *redirects*); this follows DNS.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Company, get_session, init_db
from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_url, detection_to_board_ref
from internhunter.discovery.merge import merge_boards

_SUBS = ("careers", "jobs", "apply", "work", "talent", "join")


def _cname_chain(hostname: str, max_hops: int = 5) -> list[str]:
    """Follow CNAME records for ``hostname``, returning every target host in the chain."""
    try:
        import dns.resolver
    except ImportError:
        return []
    chain: list[str] = []
    name = hostname
    for _ in range(max_hops):
        try:
            answer = dns.resolver.resolve(name, "CNAME")
        except Exception:
            break
        target = str(answer[0].target).rstrip(".").lower()
        if not target or target in chain:
            break
        chain.append(target)
        name = target
    return chain


def resolve_domain_boards(domain: str) -> list[Detection]:
    """DNS-only board discovery for one company domain (sync; call via to_thread)."""
    seen: set[tuple[str, str]] = set()
    out: list[Detection] = []
    for sub in _SUBS:
        host = f"{sub}.{domain}"
        # The careers subdomain may itself be an ATS host, or CNAME to one.
        for candidate in [host, *_cname_chain(host)]:
            det = detect_from_url(f"https://{candidate}")
            if det is None:
                continue
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            out.append(det)
    return out


def _candidate_domains(limit: int) -> list[str]:
    session = get_session()
    try:
        rows = session.scalars(
            select(Company.domain).where(Company.domain.isnot(None)).limit(limit)
        ).all()
    finally:
        session.close()
    return sorted({str(d).lower() for d in rows if d})


async def discover_from_board_resolve(
    ctx: FetchContext | None = None, settings: Settings | None = None, limit: int = 500
) -> list[Detection]:
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    domains = _candidate_domains(limit)
    if not domains:
        return []
    results = await asyncio.gather(
        *(asyncio.to_thread(resolve_domain_boards, d) for d in domains)
    )
    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for group in results:
        for det in group:
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(det)
    return detections


async def run_board_resolve(settings: Settings | None = None) -> int:
    """Discover boards via DNS and merge into the registry. Returns new-board count."""
    detections = await discover_from_board_resolve(settings=settings)
    merged = merge_boards([detection_to_board_ref(d) for d in detections])
    return merged.new_boards
