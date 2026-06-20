from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import (
    Company,
    DisclosureLead,
    get_session,
    init_db,
    upsert_disclosure_leads,
)
from internhunter.core.fetch import build_fetch_context
from internhunter.core.normalize import normalize_company_slug, parse_datetime

_GENERIC_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com",
    "proton.me", "protonmail.com", "icloud.com", "live.com", "msn.com",
}

_SBIR_DEFAULT = "https://api.www.sbir.gov/public/api/awards"


@dataclass
class DisclosureSummary:
    rows: int = 0
    leads: int = 0
    companies: int = 0
    errors: list[str] = field(default_factory=list)


def _slug_variants(name: str | None) -> list[str]:
    if not name:
        return []
    slug = normalize_company_slug(name)
    variants = {slug, slug.replace("-", "")}
    for suffix in ("-inc", "-llc", "-corp", "-co", "-ltd", "-lp", "-plc", "-gmbh"):
        if slug.endswith(suffix):
            variants.add(slug[: -len(suffix)])
    return [v for v in variants if v]


def _domain_from_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.split("@", 1)[1].strip().lower().rstrip(".")
    if not domain or domain in _GENERIC_DOMAINS:
        return None
    return domain


def _pick(row: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"na", "n/a", "none", "null"}:
            return text
    return None


def _full_name(first: str | None, last: str | None) -> str | None:
    parts = [p for p in (first, last) if p]
    return " ".join(parts) if parts else None


def _is_tech_soc(soc: str | None, prefixes: list[str]) -> bool:
    if not soc or not prefixes:
        return False
    code = soc.strip().replace(".", "-")
    return any(code.startswith(p) for p in prefixes)


def lead_from_lca_row(
    row: dict[str, Any], soc_prefixes: list[str], source: str = "oflc_lca"
) -> DisclosureLead | None:
    """Map one OFLC LCA/PERM disclosure row to a DisclosureLead. Returns None unless the
    case is a tech SOC AND carries a usable employer/attorney email."""
    employer = _pick(row, "EMPLOYER_NAME", "EMPLOYER_BUSINESS_DBA")
    if not employer:
        return None
    soc = _pick(row, "SOC_CODE", "PW_SOC_CODE", "LCA_CASE_SOC_CODE")
    if not _is_tech_soc(soc, soc_prefixes):
        return None

    poc_email = _pick(row, "EMPLOYER_POC_EMAIL", "EMPLOYER_POINT_OF_CONTACT_EMAIL")
    attorney_email = _pick(
        row, "AGENT_ATTORNEY_EMAIL_ADDRESS", "AGENT_ATTORNEY_EMAIL", "ATTORNEY_EMAIL_ADDRESS"
    )
    email = poc_email or attorney_email
    if not email:
        return None

    if poc_email:
        name = _full_name(
            _pick(row, "EMPLOYER_POC_FIRST_NAME", "EMPLOYER_POINT_OF_CONTACT_FIRST_NAME"),
            _pick(row, "EMPLOYER_POC_LAST_NAME", "EMPLOYER_POINT_OF_CONTACT_LAST_NAME"),
        )
        title = (
            _pick(row, "EMPLOYER_POC_JOB_TITLE", "EMPLOYER_POINT_OF_CONTACT_JOB_TITLE")
            or "HR Contact"
        )
        role_hint, domain = "hr", _domain_from_email(poc_email)
    else:
        name = _full_name(
            _pick(row, "AGENT_ATTORNEY_FIRST_NAME", "ATTORNEY_FIRST_NAME"),
            _pick(row, "AGENT_ATTORNEY_LAST_NAME", "ATTORNEY_LAST_NAME"),
        )
        title = (
            _pick(row, "LAW_FIRM_NAME_BUSINESS_NAME", "AGENT_ATTORNEY_FIRM")
            or "Immigration Counsel"
        )
        role_hint, domain = "other", None

    wage = _pick(row, "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_FROM_1", "PREVAILING_WAGE")
    return DisclosureLead(
        company_slug=normalize_company_slug(employer),
        company_name=employer,
        domain=domain,
        full_name=name,
        title=title,
        email=email.lower(),
        phone=_pick(row, "EMPLOYER_POC_PHONE", "EMPLOYER_PHONE", "AGENT_ATTORNEY_PHONE"),
        role_hint=role_hint,
        source=source,
        signal={
            "soc": soc,
            "soc_title": _pick(row, "SOC_TITLE", "PW_SOC_TITLE"),
            "job_title": _pick(row, "JOB_TITLE", "JOB_TITLE_1"),
            "wage": wage,
            "tech": True,
        },
        filed_at=parse_datetime(
            _pick(row, "RECEIVED_DATE", "CASE_RECEIVED_DATE", "DECISION_DATE")
        ),
    )


def leads_from_sbir_award(award: dict[str, Any]) -> list[DisclosureLead]:
    firm = _pick(award, "firm", "company")
    if not firm:
        return []
    slug = normalize_company_slug(firm)
    company_url = _pick(award, "company_url", "uei_url")
    domain: str | None = None
    if company_url:
        from urllib.parse import urlsplit

        host = urlsplit(company_url if "//" in company_url else f"https://{company_url}").netloc
        domain = host.lower().removeprefix("www.") or None
    signal = {
        "award": _pick(award, "award_amount"),
        "keywords": _pick(award, "research_area_keywords"),
        "employees": _pick(award, "number_employees"),
        "tech": True,
    }
    out: list[DisclosureLead] = []
    contacts = (
        ("poc_name", "poc_title", "poc_email", "poc_phone", "hr"),
        ("pi_name", "pi_title", "pi_email", "pi_phone", "hiring_manager"),
    )
    for name_key, title_key, email_key, phone_key, role in contacts:
        email = _pick(award, email_key)
        name = _pick(award, name_key)
        if not email and not name:
            continue
        email_domain = _domain_from_email(email)
        out.append(
            DisclosureLead(
                company_slug=slug,
                company_name=firm,
                domain=domain or email_domain,
                full_name=name,
                title=_pick(award, title_key)
                or ("Principal Investigator" if role == "hiring_manager" else "Company Contact"),
                email=email.lower() if email else None,
                phone=_pick(award, phone_key),
                role_hint=role,
                source="sbir",
                signal=signal,
            )
        )
    return out


def _iter_xlsx_rows(path: Path) -> Iterator[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        if sheet is None:
            return
        rows = sheet.iter_rows(values_only=True)
        try:
            header = [str(c).strip() if c is not None else "" for c in next(rows)]
        except StopIteration:
            return
        for values in rows:
            yield {header[i]: values[i] for i in range(min(len(header), len(values)))}
    finally:
        workbook.close()


async def _download(settings: Settings, url: str) -> Path:
    user_agent = settings.disclosure_user_agent or settings.default_user_agent
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.cache_dir / f"disclosure_{normalize_company_slug(url)[:48]}.xlsx"
    async with build_fetch_context(settings) as ctx:
        response = await ctx.client.get(
            url, headers={"User-Agent": user_agent}, follow_redirects=True
        )
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest


def _apply_company_signals(
    leads: list[DisclosureLead], slug_signal: dict[str, dict[str, Any]]
) -> int:
    session = get_session()
    touched = 0
    try:
        for lead in leads:
            if lead.domain:
                slug_signal.setdefault(lead.company_slug, {})["domain"] = lead.domain
        for slug, signal in slug_signal.items():
            company = session.scalar(select(Company).where(Company.company_slug == slug))
            payload = {"hiring": signal}
            if company is None:
                session.add(
                    Company(
                        company_slug=slug,
                        name=signal.get("name"),
                        domain=signal.get("domain"),
                        status="pending",
                        notes={"disclosure": payload},
                    )
                )
            else:
                company.notes = {**(company.notes or {}), "disclosure": payload}
                if signal.get("domain") and not company.domain:
                    company.domain = signal["domain"]
            touched += 1
        session.commit()
    finally:
        session.close()
    return touched


async def ingest_oflc(
    settings: Settings | None = None,
    *,
    source: str | Path | None = None,
    program: str = "oflc_lca",
) -> DisclosureSummary:
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    summary = DisclosureSummary()
    target = source or resolved.oflc_lca_url
    if not target:
        summary.errors.append(
            "no OFLC source: pass --url (a data.gov LCA .xlsx URL or local path) "
            "or set INTERNHUNTER_OFLC_LCA_URL"
        )
        return summary

    if isinstance(target, str) and target.startswith("http"):
        try:
            path = await _download(resolved, target)
        except Exception as exc:
            summary.errors.append(f"download failed: {exc}")
            return summary
    else:
        path = Path(target)
        if not path.exists():
            summary.errors.append(f"file not found: {path}")
            return summary

    prefixes = [p.strip() for p in resolved.oflc_soc_prefixes.split(",") if p.strip()]
    leads: list[DisclosureLead] = []
    slug_signal: dict[str, dict[str, Any]] = {}
    try:
        for row in _iter_xlsx_rows(path):
            summary.rows += 1
            lead = lead_from_lca_row(row, prefixes, source=program)
            if lead is None:
                continue
            leads.append(lead)
            entry = slug_signal.setdefault(lead.company_slug, {"tech_filings": 0})
            entry["tech_filings"] = int(entry.get("tech_filings", 0)) + 1
            entry["name"] = lead.company_name
            entry["last_soc"] = lead.signal.get("soc")
    except Exception as exc:
        summary.errors.append(f"parse failed: {exc}")
        return summary

    session = get_session()
    try:
        summary.leads = upsert_disclosure_leads(session, leads)
    finally:
        session.close()
    summary.companies = _apply_company_signals(leads, slug_signal)
    return summary


async def ingest_sbir(
    settings: Settings | None = None, *, year: int | None = None, rows: int = 500
) -> DisclosureSummary:
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    summary = DisclosureSummary()
    params: dict[str, Any] = {"rows": rows}
    if year is not None:
        params["year"] = year
    user_agent = resolved.disclosure_user_agent or resolved.default_user_agent
    try:
        async with build_fetch_context(resolved) as ctx:
            data = await ctx.get_json(
                resolved.sbir_api_url or _SBIR_DEFAULT,
                params=params,
                headers={"User-Agent": user_agent},
                respect_robots=False,
            )
    except Exception as exc:
        summary.errors.append(f"sbir fetch failed: {exc}")
        return summary

    awards = data if isinstance(data, list) else (data.get("results") or data.get("data") or [])
    leads: list[DisclosureLead] = []
    slug_signal: dict[str, dict[str, Any]] = {}
    for award in awards:
        if not isinstance(award, dict):
            continue
        summary.rows += 1
        for lead in leads_from_sbir_award(award):
            leads.append(lead)
            entry = slug_signal.setdefault(lead.company_slug, {"sbir_awards": 0})
            entry["sbir_awards"] = int(entry.get("sbir_awards", 0)) + 1
            entry["name"] = lead.company_name

    session = get_session()
    try:
        summary.leads = upsert_disclosure_leads(session, leads)
    finally:
        session.close()
    summary.companies = _apply_company_signals(leads, slug_signal)
    return summary


def run_ingest_disclosure(
    source: str, settings: Settings | None = None, url: str | None = None
) -> DisclosureSummary:
    import asyncio

    if source == "sbir":
        return asyncio.run(ingest_sbir(settings))
    if source == "perm":
        return asyncio.run(ingest_oflc(settings, source=url, program="oflc_perm"))
    return asyncio.run(ingest_oflc(settings, source=url, program="oflc_lca"))
