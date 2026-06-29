from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Company, Job, get_session, init_db
from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_html, detect_from_url

# Careers subdomains worth probing — these usually CNAME/redirect to the company's ATS,
# which URL-pattern matching on the bare company domain can never see.
_CAREERS_RE = re.compile(
    r"\b(careers?|jobs?|talent|apply|recruit(?:ing)?|work|hiring)\b", re.IGNORECASE
)


def _crtsh_url(domain: str) -> str:
    return f"https://crt.sh/?{urlencode({'q': f'%.{domain}', 'output': 'json'})}"


def careers_subdomains(rows: list[dict[str, Any]], domain: str) -> list[str]:
    """Extract distinct careers-like hostnames under ``domain`` from crt.sh JSON."""
    hosts: set[str] = set()
    for row in rows:
        names = str(row.get("name_value", "")) if isinstance(row, dict) else ""
        for name in names.splitlines():
            host = name.strip().lstrip("*.").lower()
            if not host.endswith(domain.lower()) or host == domain.lower():
                continue
            label = host[: -len(domain) - 1]
            if _CAREERS_RE.search(label):
                hosts.add(host)
    return sorted(hosts)


async def discover_from_crtsh(
    ctx: FetchContext, domain: str, max_hosts: int = 8
) -> list[Detection]:
    """Find ATS boards behind a company's careers subdomains via certificate transparency."""
    try:
        rows = await ctx.get_json(_crtsh_url(domain), respect_robots=False)
    except Exception:
        ctx.logger.debug("crt.sh query failed for {}", domain)
        return []
    if not isinstance(rows, list):
        return []

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for host in careers_subdomains(rows, domain)[:max_hosts]:
        url = f"https://{host}"
        # The careers host may itself be an ATS host, or its page embeds the board URL.
        candidates: list[Detection] = []
        direct = detect_from_url(url)
        if direct is not None:
            candidates.append(direct)
        try:
            html = await ctx.get_text(url, respect_robots=False)
            candidates.extend(detect_from_html(html))
        except Exception:
            pass
        for det in candidates:
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(det)
    return detections


def seed_domains(settings: Settings | None = None, limit: int = 200) -> list[str]:
    """Collect company domains from jobs and the companies table for crt.sh probing."""
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    session = get_session()
    domains: list[str] = []
    seen: set[str] = set()
    try:
        for row in session.scalars(
            select(Job.company_domain)
            .where(Job.company_domain.is_not(None))
            .distinct()
            .limit(limit * 2)
        ):
            if not row or not isinstance(row, str):
                continue
            domain = row.strip().lower().removeprefix("www.")
            if not domain or domain in seen:
                continue
            seen.add(domain)
            domains.append(domain)
            if len(domains) >= limit:
                break
        if len(domains) < limit:
            for row in session.scalars(
                select(Company.domain)
                .where(Company.domain.is_not(None))
                .distinct()
                .limit(limit * 2)
            ):
                if not row or not isinstance(row, str):
                    continue
                domain = row.strip().lower().removeprefix("www.")
                if not domain or domain in seen:
                    continue
                seen.add(domain)
                domains.append(domain)
                if len(domains) >= limit:
                    break
    finally:
        session.close()
    return domains


async def discover_crtsh_bulk(
    ctx: FetchContext,
    settings: Settings | None = None,
    *,
    domains: list[str] | None = None,
    max_domains: int | None = None,
) -> list[Detection]:
    """Probe careers subdomains for many company domains (rate-limited)."""
    resolved = settings or get_settings()
    cap = max_domains if max_domains is not None else resolved.crtsh_max_domains
    targets = domains if domains is not None else seed_domains(resolved, limit=cap)
    if not targets:
        return []

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for domain in targets[:cap]:
        for det in await discover_from_crtsh(ctx, domain):
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(det)
        await asyncio.sleep(resolved.crtsh_domain_delay_seconds)
    return detections
