"""Bulk certificate-transparency enumeration — the inverse of ``crt_sh.py``.

``crt_sh.py`` asks "what careers subdomains does THIS company have?". This asks the far more
powerful question "which companies are on THIS ATS?": a single crt.sh wildcard query for an ATS's
registrable domain (e.g. ``%.recruitee.com``) returns every company subdomain ever issued a TLS
cert on it. Each becomes a board via ``detect_from_url``. One request can surface hundreds of
boards that Common Crawl / HN / search never indexed.

Only works for **subdomain-per-company** ATSs (the company token is the subdomain). Path-based
ATSs (Greenhouse/Lever/Ashby) don't expose the token in DNS, so they're covered by the existing
channels instead.
"""
from __future__ import annotations

from urllib.parse import urlencode

from internhunter.core.fetch import FetchContext
from internhunter.discovery.fingerprint import Detection, detect_from_url

# Registrable ATS domains where each company is its own subdomain. detect_from_url already
# knows these host patterns (see fingerprint._SUBDOMAIN_ATS / _detect_workday / oracle).
_ATS_DOMAINS: tuple[str, ...] = (
    "recruitee.com",
    "breezy.hr",
    "teamtailor.com",
    "applytojob.com",       # jazzhr
    "pinpointhq.com",
    "bamboohr.com",
    "zohorecruit.com",
    "rippling-ats.com",
    "jobs.personio.com",
    "jobs.personio.de",
    "myworkdayjobs.com",
    "eightfold.ai",
    "phenompeople.com",
    "successfactors.com",
    "taleo.net",
    "fa.oraclecloud.com",
)


def _crtsh_url(domain: str) -> str:
    return f"https://crt.sh/?{urlencode({'q': f'%.{domain}', 'output': 'json'})}"


def hosts_from_rows(rows: list[dict[str, object]], domain: str) -> list[str]:
    """Distinct lowercased hostnames ending in ``domain`` from crt.sh JSON rows."""
    hosts: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        names = str(row.get("name_value", ""))
        for name in names.splitlines():
            host = name.strip().lstrip("*.").lower()
            if host.endswith("." + domain) and host != domain and " " not in host:
                hosts.add(host)
    return sorted(hosts)


async def discover_from_crt_bulk(
    ctx: FetchContext,
    domains: tuple[str, ...] | None = None,
    max_per_ats: int = 5000,
) -> list[Detection]:
    targets = domains if domains is not None else _ATS_DOMAINS
    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for domain in targets:
        try:
            rows = await ctx.get_json(_crtsh_url(domain), respect_robots=False)
        except Exception:
            ctx.logger.debug("crt_bulk query failed for {}", domain)
            continue
        if not isinstance(rows, list):
            continue
        for host in hosts_from_rows(rows, domain)[:max_per_ats]:
            det = detect_from_url(f"https://{host}")
            if det is None:
                continue
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(det)
    return detections
