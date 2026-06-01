from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, or_, select

from internhunter.core.db import Job, Score, get_session

TEMPLATES_DIR = Path(__file__).parent / "templates"
SORT_COLUMNS = {
    "posted_at": Job.posted_at,
    "deadline_at": Job.deadline_at,
    "company": Job.company,
    "title": Job.title,
    "discovery_score": Job.discovery_score,
    "freshness_score": Job.freshness_score,
}


def _build_query(
    q: str | None,
    ats: str | None,
    remote: bool,
    sort: str,
    limit: int | None = 200,
) -> Select[tuple[Job]]:
    stmt = select(Job).where(Job.is_internship.is_(True))
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                Job.title.ilike(pattern),
                Job.company.ilike(pattern),
            )
        )
    if ats:
        stmt = stmt.where(Job.ats == ats)
    if remote:
        stmt = stmt.where(Job.is_remote.is_(True))
    if sort == "fit":
        fit_score = (
            select(Score.fit_score)
            .where(Score.job_uid == Job.job_uid)
            .order_by(Score.scored_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = stmt.order_by(fit_score.desc().nullslast())
    else:
        column = SORT_COLUMNS.get(sort, Job.posted_at)
        if sort in ("company", "title"):
            stmt = stmt.order_by(column.asc())
        elif sort == "deadline_at":
            stmt = stmt.order_by(column.asc().nullslast())
        else:
            stmt = stmt.order_by(column.desc().nullslast())
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt


def _fetch_jobs(
    q: str | None,
    ats: str | None,
    remote: bool,
    sort: str,
    limit: int | None = 200,
) -> list[Job]:
    session = get_session()
    try:
        return list(session.scalars(_build_query(q, ats, remote, sort, limit)).all())
    finally:
        session.close()


def _csv_safe(v: str) -> str:
    return "'" + v if v and v[0] in "=+-@\t\r" else v


def _ats_options() -> list[str]:
    session = get_session()
    try:
        rows = session.scalars(
            select(Job.ats).where(Job.is_internship.is_(True)).distinct().order_by(Job.ats)
        ).all()
        return [row for row in rows if row]
    finally:
        session.close()


def _stats(jobs: Sequence[Job]) -> dict[str, int]:
    return {
        "total": len(jobs),
        "internships": sum(1 for j in jobs if j.is_internship),
        "companies": len({j.company for j in jobs if j.company}),
        "remote": sum(1 for j in jobs if j.is_remote),
    }


def create_app() -> FastAPI:
    app = FastAPI()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        q: str | None = None,
        ats: str | None = None,
        remote: bool = False,
        sort: str = "posted_at",
    ) -> HTMLResponse:
        jobs = _fetch_jobs(q, ats, remote, sort)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "jobs": jobs,
                "stats": _stats(jobs),
                "ats_options": _ats_options(),
                "q": q or "",
                "ats": ats or "",
                "remote": remote,
                "sort": sort,
            },
        )

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_fragment(
        request: Request,
        q: str | None = None,
        ats: str | None = None,
        remote: bool = False,
        sort: str = "posted_at",
    ) -> HTMLResponse:
        jobs = _fetch_jobs(q, ats, remote, sort)
        return templates.TemplateResponse(
            request,
            "_table.html",
            {"jobs": jobs},
        )

    @app.get("/export.csv")
    def export_csv(
        q: str | None = None,
        ats: str | None = None,
        remote: bool = False,
        sort: str = "posted_at",
    ) -> Response:
        jobs = _fetch_jobs(q, ats, remote, sort, limit=None)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["title", "company", "location", "kind", "posted_at", "deadline_at", "ats", "url"]
        )
        for job in jobs:
            writer.writerow(
                [
                    _csv_safe(job.title),
                    _csv_safe(job.company or ""),
                    _csv_safe(job.location_normalized or ""),
                    _csv_safe(job.internship_kind or ""),
                    job.posted_at.strftime("%Y-%m-%d") if job.posted_at else "",
                    job.deadline_at.strftime("%Y-%m-%d") if job.deadline_at else "",
                    _csv_safe(job.ats),
                    _csv_safe(job.canonical_url),
                ]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=internships.csv"},
        )

    return app
