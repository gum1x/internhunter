from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from internhunter.core.db import Company, Job


@dataclass
class CompanyTarget:
    company_slug: str
    name: str | None
    domain: str | None
    best_score: float
    job_count: int = 0


def select_companies(
    session: Session,
    limit: int | None = 50,
    min_score: float = 0.0,
    only_slug: str | None = None,
    include_done: bool = False,
) -> list[CompanyTarget]:
    """Companies behind internship jobs that still need enrichment.

    Ordered by best discovery_score so the most promising companies enrich first.
    Skips companies already marked ``status='done'`` unless ``include_done``.
    """
    score = func.max(func.coalesce(Job.discovery_score, 0.0))
    stmt = (
        select(
            Job.company_slug,
            func.max(Job.company).label("name"),
            func.max(Job.company_domain).label("domain"),
            score.label("best_score"),
            func.count(Job.id).label("job_count"),
        )
        .where(Job.is_internship.is_(True))
        .group_by(Job.company_slug)
        .order_by(score.desc())
    )
    if only_slug:
        stmt = stmt.where(Job.company_slug == only_slug)
    if min_score > 0:
        stmt = stmt.having(score >= min_score)

    done: set[str] = set()
    if not include_done:
        done = {
            row
            for row in session.scalars(
                select(Company.company_slug).where(Company.status == "done")
            )
        }

    targets: list[CompanyTarget] = []
    for slug, name, domain, best, job_count in session.execute(stmt):
        if slug in done:
            continue
        if limit is not None and len(targets) >= limit:
            break
        targets.append(
            CompanyTarget(
                company_slug=slug,
                name=name,
                domain=domain,
                best_score=float(best or 0.0),
                job_count=int(job_count or 0),
            )
        )
    return targets
