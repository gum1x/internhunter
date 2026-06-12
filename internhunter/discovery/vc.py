from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from internhunter.core.fetch import FetchContext
from internhunter.discovery.careers import resolve_company_ats
from internhunter.discovery.fingerprint import Detection

_VC_PORTFOLIOS = (
    "https://a16z.com/portfolio/",
    "https://www.sequoiacap.com/our-companies/",
    "https://www.accel.com/relationships",
    "https://www.foundersfund.com/portfolio",
    "https://greylock.com/portfolio/",
    "https://www.bvp.com/companies",
    "https://www.indexventures.com/companies/",
    "https://www.kleinerperkins.com/companies/",
    "https://firstround.com/companies/",
    "https://www.generalcatalyst.com/portfolio",
)

_SKIP_HOST_PARTS = (
    "twitter.com",
    "x.com",
    "linkedin.com",
    "facebook.com",
    "youtube.com",
    "instagram.com",
    "github.com",
    "medium.com",
    "crunchbase.com",
    "apple.com",
    "google.com",
)


async def _company_links(ctx: FetchContext, portfolio_url: str) -> list[str]:
    try:
        html = await ctx.get_text(portfolio_url)
    except Exception:
        ctx.logger.debug("vc portfolio fetch failed {}", portfolio_url)
        return []
    soup = BeautifulSoup(html, "lxml")
    vc_host = urlsplit(portfolio_url).netloc.lower()
    seen: set[str] = set()
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not href.startswith("http"):
            continue
        host = urlsplit(href).netloc.lower()
        if not host or host == vc_host:
            continue
        if any(part in host for part in _SKIP_HOST_PARTS):
            continue
        base = f"https://{host}"
        if base in seen:
            continue
        seen.add(base)
        links.append(base)
    return links


async def discover_from_vc(
    ctx: FetchContext,
    portfolios: tuple[str, ...] | None = None,
    limit: int = 600,
) -> list[Detection]:
    pages = portfolios if portfolios is not None else _VC_PORTFOLIOS
    company_urls: list[str] = []
    seen_urls: set[str] = set()
    for page in pages:
        for url in await _company_links(ctx, page):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            company_urls.append(url)
            if len(company_urls) >= limit:
                break
        if len(company_urls) >= limit:
            break

    resolved = await asyncio.gather(*(resolve_company_ats(ctx, url) for url in company_urls))

    seen: set[tuple[str, str]] = set()
    detections: list[Detection] = []
    for company_detections in resolved:
        for detection in company_detections:
            key = (detection.ats, detection.token)
            if key in seen:
                continue
            seen.add(key)
            detections.append(detection)
    return detections
