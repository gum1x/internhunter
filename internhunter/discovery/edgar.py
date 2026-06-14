from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from internhunter.config.settings import Settings, get_settings
from internhunter.contacts.domain import candidate_domains
from internhunter.core.db import OfficerLead, get_session, init_db, upsert_officer_leads
from internhunter.core.fetch import FetchContext
from internhunter.core.normalize import normalize_company_slug, parse_datetime
from internhunter.discovery.careers import resolve_many
from internhunter.discovery.fingerprint import Detection

# SEC Form D = a notice of an exempt securities offering, i.e. a company that JUST raised
# money — a strong "about to hire" temporal signal no other channel has. It also uniquely
# yields the offering's officer names (free people leads).

_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/primary_doc.xml"

# Form D industryGroupType values that are operating companies worth pursuing (drop funds).
_FUND_RE = re.compile(r"fund|investment|pooled|spv", re.IGNORECASE)

_ENTITY_RE = re.compile(r"<entityName>(.*?)</entityName>", re.DOTALL)
_INDUSTRY_RE = re.compile(r"<industryGroupType>(.*?)</industryGroupType>", re.DOTALL)
_PERSON_RE = re.compile(r"<relatedPersonName>(.*?)</relatedPersonName>", re.DOTALL)
_FIRST_RE = re.compile(r"<firstName>(.*?)</firstName>", re.DOTALL)
_MIDDLE_RE = re.compile(r"<middleName>(.*?)</middleName>", re.DOTALL)
_LAST_RE = re.compile(r"<lastName>(.*?)</lastName>", re.DOTALL)


def _tag(pattern: re.Pattern[str], block: str) -> str:
    m = pattern.search(block)
    return m.group(1).strip() if m else ""


def _officer_names(xml: str) -> list[str]:
    names: list[str] = []
    for block in _PERSON_RE.findall(xml):
        full = " ".join(
            p
            for p in (_tag(_FIRST_RE, block), _tag(_MIDDLE_RE, block), _tag(_LAST_RE, block))
            if p
        )
        if full:
            names.append(full)
    return names


def parse_form_d(xml: str) -> tuple[str | None, str | None, list[str]]:
    """(entity_name, industry, officer_names) from a Form D primary_doc.xml."""
    ent = _ENTITY_RE.search(xml)
    ind = _INDUSTRY_RE.search(xml)
    entity = ent.group(1).strip() if ent else None
    industry = ind.group(1).strip() if ind else None
    return entity, industry, _officer_names(xml)


def _adsh_from_id(hit_id: str) -> str | None:
    # "0001234567-25-000123:primary_doc.xml" -> "000123456725000123"
    base = hit_id.split(":", 1)[0]
    digits = base.replace("-", "")
    return digits or None


async def discover_from_edgar(
    ctx: FetchContext,
    settings: Settings | None = None,
    days: int | None = None,
    keyword: str = "software",
    max_filings: int = 25,
) -> list[Detection]:
    resolved = settings or get_settings()
    window = days if days is not None else resolved.edgar_days
    end = datetime.now(tz=UTC).date()
    start = end - timedelta(days=window)
    ua = resolved.edgar_user_agent or resolved.default_user_agent
    headers = {"User-Agent": ua}

    try:
        data = await ctx.get_json(
            _SEARCH,
            params={
                "q": keyword,
                "forms": "D",
                "dateRange": "custom",  # required, else startdt/enddt -> 500
                "startdt": start.isoformat(),
                "enddt": end.isoformat(),
            },
            headers=headers,
            respect_robots=False,
        )
    except Exception:
        ctx.logger.debug("edgar search failed")
        return []

    hits = (((data or {}).get("hits") or {}).get("hits")) if isinstance(data, dict) else None
    if not isinstance(hits, list):
        return []

    init_db(resolved.db_path)
    leads: list[OfficerLead] = []
    sites: list[str] = []
    for hit in hits[:max_filings]:
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source") or {}
        ciks = source.get("ciks") or source.get("cik") or []
        cik = (ciks[0] if isinstance(ciks, list) and ciks else ciks) or None
        adsh = _adsh_from_id(str(hit.get("_id") or ""))
        if not cik or not adsh:
            continue
        try:
            xml = await ctx.get_text(
                _ARCHIVE.format(cik=str(cik).lstrip("0") or cik, adsh=adsh),
                headers=headers,
                respect_robots=False,
            )
        except Exception:
            continue
        entity, industry, officers = parse_form_d(xml)
        if not entity or (industry and _FUND_RE.search(industry)):
            continue
        slug = normalize_company_slug(entity)
        if not slug:
            continue
        filed = parse_datetime(source.get("file_date"))
        for name in officers[:6]:
            leads.append(
                OfficerLead(
                    company_slug=slug, company_name=entity, full_name=name,
                    role_hint="officer", source="edgar", filed_at=filed,
                )
            )
        # Best-effort board resolution from guessed company domains (no SearXNG needed).
        sites.extend(f"https://{d}" for d in candidate_domains(entity, slug)[:2])

    if leads:
        session = get_session()
        try:
            upsert_officer_leads(session, leads)
        finally:
            session.close()

    if not sites:
        return []
    return await resolve_many(ctx, sites)
