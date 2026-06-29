"""MCP server exposing InternHunter's discovered jobs, fit ratings, and outreach
contacts to an MCP client (e.g. Claude Desktop).

Run over stdio with ``internhunter mcp``. All tools are read-only queries against the
local SQLite DB — no network calls, no writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from internhunter.core.db import (
    Company,
    Contact,
    ContactChannel,
    Job,
    Score,
    get_session,
    init_db,
)

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise SystemExit(
        "The MCP SDK is not installed. Install it with:  pip install -e '.[mcp]'"
    ) from exc

mcp = FastMCP("internhunter")


# --------------------------------------------------------------------------- helpers


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _round(value: float | None, ndigits: int = 1) -> float | None:
    return round(value, ndigits) if value is not None else None


def _llm_scores(session: Session, uids: list[str]) -> dict[str, Score]:
    """Latest LLM fit Score per job_uid (model tag ``llm:*``)."""
    if not uids:
        return {}
    rows = session.scalars(
        select(Score)
        .where(Score.job_uid.in_(uids), Score.model.like("llm:%"))
        .order_by(Score.scored_at.asc())
    ).all()
    return {s.job_uid: s for s in rows}  # asc order -> latest wins on overwrite


def _job_dict(job: Job, score: Score | None, *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "job_uid": job.job_uid,
        "title": job.title,
        "company": job.company or job.company_slug,
        "company_slug": job.company_slug,
        "url": job.canonical_url,
        "ats": job.ats,
        "location": job.location_normalized or job.location_raw,
        "remote": job.is_remote,
        "remote_scope": job.remote_scope,
        "is_internship": job.is_internship,
        "internship_kind": job.internship_kind,
        "employment_type": job.employment_type,
        "department": job.department,
        "posted_at": _iso(job.posted_at),
        "deadline_at": _iso(job.deadline_at),
        "is_rolling": job.is_rolling,
        "discovery_score": _round(job.discovery_score),
        "quality_verdict": job.quality_verdict,
    }
    if score is not None:
        out["fit_score"] = _round(score.fit_score)  # 0-100 (LLM rating)
        out["fit_matched"] = score.matched or []
        out["fit_missing"] = score.missing or []
        out["fit_rationale"] = score.rationale
    if full:
        out["company_domain"] = job.company_domain
        out["level_tags"] = job.level_tags or []
        out["sectors"] = job.sectors or []
        salary = {
            k: v
            for k, v in {
                "min": job.salary_min,
                "max": job.salary_max,
                "currency": job.salary_currency,
                "period": job.salary_period,
            }.items()
            if v is not None
        }
        out["salary"] = salary or None
        out["description"] = (job.description_text or "")[:6000]
    return out


def _contact_dict(contact: Contact, channels: list[ContactChannel]) -> dict[str, Any]:
    return {
        "name": contact.full_name,
        "title": contact.title,
        "role": contact.role_category,
        "email": contact.email,
        "email_status": contact.email_status,
        "email_confidence": _round(contact.confidence, 0),
        "email_label": contact.label,  # verified / probable / guessed
        "linkedin": contact.linkedin_url,
        "github": contact.github_login,
        "source": contact.person_source,
        "other_channels": [
            {
                "kind": ch.kind,
                "value": ch.value,
                "label": ch.label,
                "confidence": _round(ch.confidence, 0),
            }
            for ch in channels
            if ch.kind not in ("email",)
        ],
    }


def _fit_subquery() -> Any:
    """Correlated subquery: latest LLM fit score for the outer Job row."""
    return (
        select(Score.fit_score)
        .where(Score.job_uid == Job.job_uid, Score.model.like("llm:%"))
        .order_by(Score.scored_at.desc())
        .limit(1)
        .scalar_subquery()
    )


def _apply_filters(
    stmt: Select[tuple[Job]],
    query: str | None,
    internships_only: bool,
    remote: bool | None,
    location: str | None,
    ats: str | None,
    company: str | None,
) -> Select[tuple[Job]]:
    if internships_only:
        stmt = stmt.where(Job.is_internship.is_(True))
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(Job.title.ilike(like), Job.description_text.ilike(like))
        )
    if remote is not None:
        stmt = stmt.where(Job.is_remote.is_(remote))
    if location:
        loc = f"%{location.strip()}%"
        stmt = stmt.where(
            or_(Job.location_normalized.ilike(loc), Job.location_raw.ilike(loc))
        )
    if ats:
        stmt = stmt.where(Job.ats == ats.strip().lower())
    if company:
        comp = f"%{company.strip()}%"
        stmt = stmt.where(
            or_(Job.company.ilike(comp), Job.company_slug.ilike(comp))
        )
    return stmt


def _top_contacts(session: Session, company_slug: str, limit: int) -> list[dict[str, Any]]:
    contacts = session.scalars(
        select(Contact)
        .where(Contact.company_slug == company_slug)
        .order_by(Contact.priority.desc().nulls_last(), Contact.confidence.desc().nulls_last())
        .limit(limit)
    ).all()
    if not contacts:
        return []
    ch_rows = session.scalars(
        select(ContactChannel).where(
            ContactChannel.contact_id.in_([c.id for c in contacts])
        )
    ).all()
    by_contact: dict[int, list[ContactChannel]] = {}
    for ch in ch_rows:
        by_contact.setdefault(ch.contact_id, []).append(ch)
    return [_contact_dict(c, by_contact.get(c.id, [])) for c in contacts]


# ----------------------------------------------------------------------------- tools


def _do_search(
    query: str | None,
    internships_only: bool,
    remote: bool | None,
    location: str | None,
    ats: str | None,
    company: str | None,
    min_fit: float | None,
    sort: str,
    limit: int,
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    session = get_session()
    try:
        fit_sq = _fit_subquery()
        stmt: Select[tuple[Job]] = select(Job)
        stmt = _apply_filters(stmt, query, internships_only, remote, location, ats, company)
        if min_fit is not None:
            stmt = stmt.where(fit_sq >= min_fit)
        if sort == "recent":
            stmt = stmt.order_by(Job.posted_at.desc().nulls_last())
        elif sort == "deadline":
            stmt = stmt.where(Job.deadline_at.is_not(None)).order_by(Job.deadline_at.asc())
        elif sort == "discovery":
            stmt = stmt.order_by(Job.discovery_score.desc().nulls_last())
        else:  # fit
            stmt = stmt.order_by(fit_sq.desc().nulls_last())
        jobs = list(session.scalars(stmt.limit(limit)))
        scores = _llm_scores(session, [j.job_uid for j in jobs])
        return {
            "count": len(jobs),
            "jobs": [_job_dict(j, scores.get(j.job_uid)) for j in jobs],
        }
    finally:
        session.close()


@mcp.tool()
def search_jobs(
    query: str | None = None,
    internships_only: bool = True,
    remote: bool | None = None,
    location: str | None = None,
    ats: str | None = None,
    company: str | None = None,
    min_fit: float | None = None,
    sort: str = "fit",
    limit: int = 25,
) -> dict[str, Any]:
    """Search discovered jobs/internships.

    Filters: ``query`` (keyword in title/description), ``internships_only`` (default True),
    ``remote`` (True/False), ``location`` (substring), ``ats`` (e.g. greenhouse, lever),
    ``company`` (name substring), ``min_fit`` (0-100 LLM fit floor). ``sort`` is one of
    ``fit`` (LLM rating, default), ``recent`` (newest), ``deadline`` (soonest), or
    ``discovery`` (rarity+freshness+fit). Returns up to ``limit`` (max 100) matches with
    apply URL, location, fit score + rationale, and deadline.
    """
    return _do_search(
        query, internships_only, remote, location, ats, company, min_fit, sort, limit
    )


@mcp.tool()
def top_internships(
    limit: int = 20, remote: bool | None = None, min_fit: float | None = None
) -> dict[str, Any]:
    """The best-fit internships for the user, ranked by LLM fit score (0-100).

    Use this when the user asks "what should I apply to" or "top internships". Returns
    apply URLs, fit rationale, and deadlines.
    """
    return _do_search(None, True, remote, None, None, None, min_fit, "fit", limit)


@mcp.tool()
def get_job(job_uid: str | None = None, url: str | None = None) -> dict[str, Any]:
    """Full detail for one job by ``job_uid`` or apply ``url``: description, salary, fit
    rating + rationale, plus the top outreach contacts at that company (names, titles,
    emails with confidence, LinkedIn)."""
    if not job_uid and not url:
        return {"error": "provide job_uid or url"}
    session = get_session()
    try:
        stmt = select(Job)
        stmt = (
            stmt.where(Job.job_uid == job_uid)
            if job_uid
            else stmt.where(Job.canonical_url == url)
        )
        job = session.scalars(stmt.limit(1)).first()
        if job is None:
            return {"error": "job not found"}
        score = _llm_scores(session, [job.job_uid]).get(job.job_uid)
        data = _job_dict(job, score, full=True)
        data["contacts"] = _top_contacts(session, job.company_slug, limit=8)
        return data
    finally:
        session.close()


@mcp.tool()
def get_contacts(company: str, limit: int = 10) -> dict[str, Any]:
    """Outreach contacts (recruiters, hiring/eng managers) for a company, by company slug
    or name. Returns each person's name, title, role, best-effort email with a confidence
    label (verified/probable/guessed), LinkedIn, and the company's inferred email pattern.
    Ranked by outreach priority."""
    session = get_session()
    try:
        comp = company.strip()
        company_row = session.scalars(
            select(Company)
            .where(or_(Company.company_slug == comp, Company.name.ilike(f"%{comp}%")))
            .limit(1)
        ).first()
        slug = company_row.company_slug if company_row else comp
        contacts = _top_contacts(session, slug, limit=max(1, min(limit, 50)))
        if not contacts and company_row is None:
            # fall back to a fuzzy slug match against the contacts table directly
            row = session.scalars(
                select(Contact.company_slug).where(Contact.company_slug.ilike(f"%{comp}%")).limit(1)
            ).first()
            if row:
                slug = row
                contacts = _top_contacts(session, slug, limit=max(1, min(limit, 50)))
        result: dict[str, Any] = {
            "company_slug": slug,
            "count": len(contacts),
            "contacts": contacts,
        }
        if company_row is not None:
            result["company"] = {
                "name": company_row.name,
                "domain": company_row.domain,
                "email_pattern": company_row.email_pattern,
                "linkedin": company_row.linkedin_url,
                "github_org": company_row.github_org,
                "headcount_band": company_row.headcount_band,
            }
        return result
    finally:
        session.close()


@mcp.tool()
def get_company(company: str, jobs_limit: int = 15) -> dict[str, Any]:
    """Everything known about a company: profile (domain, email pattern, size), its open
    internships/jobs (with apply URLs and fit scores), and its outreach contacts."""
    session = get_session()
    try:
        comp = company.strip()
        company_row = session.scalars(
            select(Company)
            .where(or_(Company.company_slug == comp, Company.name.ilike(f"%{comp}%")))
            .limit(1)
        ).first()
        slug = company_row.company_slug if company_row else comp
        jobs = list(
            session.scalars(
                select(Job)
                .where(or_(Job.company_slug == slug, Job.company.ilike(f"%{comp}%")))
                .order_by(_fit_subquery().desc().nulls_last())
                .limit(max(1, min(jobs_limit, 50)))
            )
        )
        scores = _llm_scores(session, [j.job_uid for j in jobs])
        # If there is no enriched Company row, anchor contacts to the matched jobs' slug.
        if company_row is None and jobs:
            slug = jobs[0].company_slug
        profile = None
        if company_row is not None:
            profile = {
                "name": company_row.name,
                "slug": company_row.company_slug,
                "domain": company_row.domain,
                "email_pattern": company_row.email_pattern,
                "linkedin": company_row.linkedin_url,
                "github_org": company_row.github_org,
                "headcount_band": company_row.headcount_band,
            }
        return {
            "company": profile or {"slug": slug},
            "jobs": [_job_dict(j, scores.get(j.job_uid)) for j in jobs],
            "contacts": _top_contacts(session, slug, limit=10),
        }
    finally:
        session.close()


@mcp.tool()
def stats() -> dict[str, Any]:
    """Quick overview of what InternHunter currently holds: counts of jobs, internships,
    LLM-rated internships, contacts, and companies. Useful to orient before searching."""
    from sqlalchemy import func

    session = get_session()
    try:
        def count(model: Any, *where: Any) -> int:
            stmt = select(func.count()).select_from(model)
            for w in where:
                stmt = stmt.where(w)
            return int(session.scalar(stmt) or 0)

        rated = int(
            session.scalar(
                select(func.count(func.distinct(Score.job_uid))).where(Score.model.like("llm:%"))
            )
            or 0
        )
        return {
            "jobs": count(Job),
            "internships": count(Job, Job.is_internship.is_(True)),
            "internships_rated": rated,
            "companies": count(Company),
            "contacts": count(Contact),
        }
    finally:
        session.close()


def main() -> None:
    """Entry point for ``internhunter mcp`` — initialise the DB then serve over stdio."""
    init_db()
    mcp.run()


if __name__ == "__main__":
    main()
