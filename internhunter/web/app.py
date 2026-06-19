from __future__ import annotations

import base64
import binascii
import csv
import io
import secrets
import subprocess
import sys
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError

from internhunter.config.settings import get_settings
from internhunter.core.db import (
    Application,
    Contact,
    ContactChannel,
    Job,
    Score,
    get_session,
)

# Application-tracker pipeline + the badge swapped in when a job is tracked.
TRACKER_STATUSES = ["To Apply", "Applied", "Interviewing", "Offer", "Rejected"]
_TRACKED_BADGE = '<span class="tracked">✓ Tracked</span>'


def _check_basic_auth(header: str, user: str, password: str) -> bool:
    if not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    name, _, supplied = decoded.partition(":")
    return secrets.compare_digest(name, user) and secrets.compare_digest(supplied, password)

_search: dict[str, Any] = {"proc": None}


def _poll_bin() -> str:
    return str(Path(sys.executable).parent / "internhunter")


def _search_running() -> bool:
    proc = _search["proc"]
    return proc is not None and proc.poll() is None


def _start_search() -> None:
    if _search_running():
        return
    _search["proc"] = subprocess.Popen(
        [_poll_bin(), "poll"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _search_status_html() -> str:
    if _search_running():
        return (
            '<span class="searching" hx-get="/search-status" hx-target="#search-status" '
            'hx-trigger="load delay:4s" hx-swap="innerHTML">'
            "⏳ Searching all boards… this can take a few minutes.</span>"
        )
    return (
        '<span class="done" hx-get="/jobs" hx-target="#jobs" hx-trigger="load" '
        'hx-swap="innerHTML">✓ Search complete — results updated. '
        '<a href="/">reload page for stats</a></span>'
    )

TEMPLATES_DIR = Path(__file__).parent / "templates"
SORT_COLUMNS = {
    "posted_at": Job.posted_at,
    "deadline_at": Job.deadline_at,
    "company": Job.company,
    "title": Job.title,
    "discovery_score": Job.discovery_score,
    "freshness_score": Job.freshness_score,
}


# Verdicts hidden by the default-on "hide low quality" dashboard toggle. Jobs are NEVER
# deleted — this only filters the view; turn the toggle off to see everything.
_BAD_VERDICTS = ("spam", "ghost", "agency", "mlm")


def _filtered(
    stmt: Select[Any],
    q: str | None,
    ats: str | None,
    remote: bool,
    hide_low_quality: bool,
) -> Select[Any]:
    """Apply the dashboard's WHERE clauses — shared by the row query and the count."""
    stmt = stmt.where(Job.is_internship.is_(True))
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
    if hide_low_quality:
        # hide only confidently-bad jobs; keep unjudged / unclear / ok
        stmt = stmt.where(
            or_(
                Job.quality_verdict.is_(None),
                Job.quality_verdict.not_in(_BAD_VERDICTS),
                Job.quality_confidence < 70,
            )
        )
    return stmt


def _build_query(
    q: str | None,
    ats: str | None,
    remote: bool,
    sort: str,
    limit: int | None = 200,
    hide_low_quality: bool = False,
    offset: int = 0,
) -> Select[tuple[Job]]:
    stmt = _filtered(select(Job), q, ats, remote, hide_low_quality)
    if sort == "fit":
        fit_score = (
            select(Score.fit_score)
            .where(Score.job_uid == Job.job_uid, Score.model.like("llm:%"))
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
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt


def _fetch_jobs(
    q: str | None,
    ats: str | None,
    remote: bool,
    sort: str,
    limit: int | None = 200,
    hide_low_quality: bool = False,
    offset: int = 0,
) -> list[Job]:
    session = get_session()
    try:
        stmt = _build_query(q, ats, remote, sort, limit, hide_low_quality, offset)
        return list(session.scalars(stmt).all())
    finally:
        session.close()


def _count_jobs(
    q: str | None,
    ats: str | None,
    remote: bool,
    hide_low_quality: bool,
) -> int:
    """Total rows matching the current filters (ignores limit/offset) — for paging."""
    session = get_session()
    try:
        stmt = _filtered(
            select(func.count()).select_from(Job), q, ats, remote, hide_low_quality
        )
        return session.scalar(stmt) or 0
    finally:
        session.close()


def _page_context(
    q: str | None,
    ats: str | None,
    remote: bool,
    sort: str,
    hide_low_quality: bool,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Rows for one page plus the paging metadata the table fragment needs."""
    total = _count_jobs(q, ats, remote, hide_low_quality)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    jobs = _fetch_jobs(
        q, ats, remote, sort,
        limit=page_size,
        hide_low_quality=hide_low_quality,
        offset=(page - 1) * page_size,
    )
    return {
        "jobs": jobs,
        "scores": _scores_for(jobs),
        "tracked": _tracked_uids([j.job_uid for j in jobs]),
        "q": q or "",
        "ats": ats or "",
        "remote": remote,
        "sort": sort,
        "hide_low_quality": hide_low_quality,
        "page": page,
        "pages": pages,
        "total": total,
    }


def _scores_for(jobs: list[Job]) -> dict[str, Score]:
    """Latest LLM fit Score per displayed job (fit/matched/missing/rationale)."""
    uids = [j.job_uid for j in jobs]
    if not uids:
        return {}
    session = get_session()
    try:
        rows = session.scalars(
            select(Score)
            .where(Score.job_uid.in_(uids), Score.model.like("llm:%"))
            .order_by(Score.scored_at.asc())
        ).all()
    finally:
        session.close()
    return {s.job_uid: s for s in rows}  # asc order -> latest wins


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Tolerant bool for query params: absent -> default, empty string -> False, else
    parse. Avoids the 422 FastAPI raises when a checkbox/pager emits `remote=`."""
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "on", "yes")


def _csv_safe(v: str) -> str:
    return "'" + v if v and v[0] in "=+-@\t\r\n" else v


def _safe_url(u: str | None) -> str:
    """Neutralize crawled URLs before they reach an href — Jinja autoescaping does not
    stop `javascript:`/`data:` schemes. Only http(s) URLs pass through; else `#`."""
    return u if u and urlsplit(u).scheme in ("http", "https") else "#"


def _same_origin(request: Request) -> None:
    """CSRF guard for state-changing POSTs: when a cross-site request carries an Origin
    header whose host differs from ours, reject it (403). Same-origin requests and
    non-browser callers (no Origin) pass through."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(status_code=403, detail="cross-origin request rejected")


def _ats_options() -> list[str]:
    session = get_session()
    try:
        rows = session.scalars(
            select(Job.ats).where(Job.is_internship.is_(True)).distinct().order_by(Job.ats)
        ).all()
        return [row for row in rows if row]
    finally:
        session.close()


def _stats() -> dict[str, int]:
    session = get_session()
    try:
        intern = Job.is_internship.is_(True)
        return {
            "total": session.scalar(select(func.count()).select_from(Job)) or 0,
            "internships": session.scalar(select(func.count()).where(intern)) or 0,
            "companies": session.scalar(
                select(func.count(func.distinct(Job.company_slug))).where(intern)
            )
            or 0,
            "remote": session.scalar(
                select(func.count()).where(intern, Job.is_remote.is_(True))
            )
            or 0,
            "contacts": session.scalar(select(func.count()).select_from(Contact)) or 0,
        }
    finally:
        session.close()


def _fetch_contacts(
    company: str | None = None,
    role: str | None = None,
    label: str | None = None,
    has_email: bool = False,
    limit: int | None = 500,
) -> list[Contact]:
    session = get_session()
    try:
        stmt = select(Contact)
        if company:
            pattern = f"%{company.lower()}%"
            stmt = stmt.where(Contact.company_slug.ilike(pattern))
        if role:
            stmt = stmt.where(Contact.role_category == role)
        if label:
            stmt = stmt.where(Contact.label == label)
        if has_email:
            stmt = stmt.where(Contact.email.is_not(None))
        stmt = stmt.order_by(
            Contact.company_slug.asc(),
            Contact.priority.desc().nullslast(),
            Contact.confidence.desc().nullslast(),
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt).all())
    finally:
        session.close()


def _channels_for(contacts: list[Contact]) -> dict[int, list[ContactChannel]]:
    """Map contact_id -> its reach channels, best-confidence first."""
    ids = [c.id for c in contacts if c.id is not None]
    if not ids:
        return {}
    session = get_session()
    try:
        rows = session.scalars(
            select(ContactChannel)
            .where(ContactChannel.contact_id.in_(ids))
            .order_by(ContactChannel.confidence.desc().nullslast())
        ).all()
    finally:
        session.close()
    out: dict[int, list[ContactChannel]] = {}
    for ch in rows:
        out.setdefault(ch.contact_id, []).append(ch)
    return out


def _contacts_for_job(job_uid: str) -> list[Contact]:
    session = get_session()
    try:
        job = session.scalar(select(Job).where(Job.job_uid == job_uid))
        if job is None:
            return []
        return list(
            session.scalars(
                select(Contact)
                .where(Contact.company_slug == job.company_slug)
                .order_by(Contact.priority.desc().nullslast())
            ).all()
        )
    finally:
        session.close()


def _role_options() -> list[str]:
    session = get_session()
    try:
        rows = session.scalars(
            select(Contact.role_category).distinct().order_by(Contact.role_category)
        ).all()
        return [r for r in rows if r]
    finally:
        session.close()


_EMAIL_RANK = {"verified": 0, "probable": 1, "guessed": 2}
_STATUS_RANK = {"To Apply": 0, "Applied": 1, "Interviewing": 2, "Offer": 3, "Rejected": 4}


def _pick_best(contacts: list[Contact]) -> tuple[str | None, str | None]:
    """Best contact (name, email) from a company's saved contacts: prefer one with an
    email, best email_status, then priority; else the top-priority name with no email."""
    with_email = [c for c in contacts if c.email]
    if with_email:
        with_email.sort(
            key=lambda c: (_EMAIL_RANK.get(c.email_status or "guessed", 3), -(c.priority or 0.0))
        )
        return with_email[0].full_name, with_email[0].email
    if contacts:
        best = max(contacts, key=lambda c: (c.priority or 0.0))
        return best.full_name, None
    return None, None


def _best_contacts_for(slugs: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """Live best saved contact per company_slug — so the tracker reflects the contacts
    table even for jobs tracked before a contact was found."""
    wanted = {s for s in slugs if s}
    if not wanted:
        return {}
    session = get_session()
    try:
        rows = list(
            session.scalars(select(Contact).where(Contact.company_slug.in_(wanted))).all()
        )
    finally:
        session.close()
    by_slug: dict[str, list[Contact]] = {}
    for c in rows:
        by_slug.setdefault(c.company_slug, []).append(c)
    return {slug: _pick_best(cs) for slug, cs in by_slug.items()}


def _best_contact(company_slug: str | None) -> tuple[str | None, str | None]:
    if not company_slug:
        return None, None
    return _best_contacts_for([company_slug]).get(company_slug, (None, None))


def _tracked_uids(uids: list[str]) -> set[str]:
    """job_uids among `uids` already in the tracker — drives the 'Add / ✓ Tracked' badge."""
    if not uids:
        return set()
    session = get_session()
    try:
        rows = session.scalars(
            select(Application.job_uid).where(Application.job_uid.in_(uids))
        ).all()
        return set(rows)
    finally:
        session.close()


def _fetch_applications(status: str | None = None, sort: str = "due") -> list[Application]:
    session = get_session()
    try:
        stmt = select(Application)
        if status:
            stmt = stmt.where(Application.status == status)
        apps = list(session.scalars(stmt).all())
    finally:
        session.close()
    # SQLite reads datetimes back as naive, so naive max/min sentinels sort safely.
    far, near = datetime.max, datetime.min
    if sort == "company":
        apps.sort(key=lambda a: (a.company or "").lower())
    elif sort == "status":
        apps.sort(key=lambda a: (_STATUS_RANK.get(a.status, 9), a.due_date or far))
    elif sort == "applied":
        apps.sort(key=lambda a: a.applied_at or near, reverse=True)
    elif sort == "added":
        apps.sort(key=lambda a: a.created_at or near, reverse=True)
    else:  # "due" — soonest deadline first, undated last
        apps.sort(key=lambda a: a.due_date or far)
    return apps


def _row_view(
    a: Application, live: dict[str, tuple[str | None, str | None]], today: date
) -> dict[str, Any]:
    """Per-row display data: effective contact (manual override else live saved contact)
    and a due-date urgency class."""
    cname, cemail = a.contact_name, a.contact_email
    if not (cname or cemail):
        cname, cemail = live.get(a.company_slug or "", (None, None))
    due_status = ""
    if a.due_date:
        days = (a.due_date.date() - today).days
        due_status = "overdue" if days < 0 else ("soon" if days <= 7 else "")
    return {"a": a, "cname": cname or "", "cemail": cemail or "", "due_status": due_status}


def _parse_date(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def create_app() -> FastAPI:
    app = FastAPI()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["safe_url"] = _safe_url
    settings = get_settings()

    if settings.auth_user and settings.auth_pass:

        @app.middleware("http")
        async def _auth(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            header = request.headers.get("authorization", "")
            if not _check_basic_auth(header, settings.auth_user, settings.auth_pass):
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="InternHunter"'},
                )
            return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        q: str | None = None,
        ats: str | None = None,
        remote: str | None = None,
        sort: str = "fit",
        hide_low_quality: str | None = None,
        page: int = 1,
    ) -> HTMLResponse:
        ctx = _page_context(
            q, ats, _as_bool(remote), sort,
            _as_bool(hide_low_quality, settings.dashboard_hide_low_quality),
            page, settings.dashboard_page_size,
        )
        ctx["stats"] = _stats()
        ctx["ats_options"] = _ats_options()
        return templates.TemplateResponse(request, "index.html", ctx)

    @app.post("/search", response_class=HTMLResponse)
    def search(_: None = Depends(_same_origin)) -> HTMLResponse:
        _start_search()
        return HTMLResponse(_search_status_html())

    @app.get("/search-status", response_class=HTMLResponse)
    def search_status() -> HTMLResponse:
        return HTMLResponse(_search_status_html())

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_fragment(
        request: Request,
        q: str | None = None,
        ats: str | None = None,
        remote: str | None = None,
        sort: str = "fit",
        hide_low_quality: str | None = None,
        page: int = 1,
    ) -> HTMLResponse:
        ctx = _page_context(
            q, ats, _as_bool(remote), sort,
            _as_bool(hide_low_quality, settings.dashboard_hide_low_quality),
            page, settings.dashboard_page_size,
        )
        return templates.TemplateResponse(request, "_table.html", ctx)

    @app.get("/export.csv")
    def export_csv(
        q: str | None = None,
        ats: str | None = None,
        remote: str | None = None,
        sort: str = "fit",
    ) -> Response:
        jobs = _fetch_jobs(q, ats, _as_bool(remote), sort, limit=None)
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

    @app.get("/contacts", response_class=HTMLResponse)
    def contacts_page(
        request: Request,
        company: str | None = None,
        role: str | None = None,
        label: str | None = None,
        has_email: bool = False,
    ) -> HTMLResponse:
        contacts = _fetch_contacts(company, role, label, has_email)
        return templates.TemplateResponse(
            request,
            "contacts.html",
            {
                "contacts": contacts,
                "channels": _channels_for(contacts),
                "role_options": _role_options(),
                "company": company or "",
                "role": role or "",
                "label": label or "",
                "has_email": has_email,
            },
        )

    @app.get("/contacts/table", response_class=HTMLResponse)
    def contacts_table(
        request: Request,
        company: str | None = None,
        role: str | None = None,
        label: str | None = None,
        has_email: bool = False,
    ) -> HTMLResponse:
        contacts = _fetch_contacts(company, role, label, has_email)
        return templates.TemplateResponse(
            request, "_contacts_table.html",
            {"contacts": contacts, "channels": _channels_for(contacts)},
        )

    @app.get("/jobs/{job_uid}/contacts", response_class=HTMLResponse)
    def job_contacts(request: Request, job_uid: str) -> HTMLResponse:
        contacts = _contacts_for_job(job_uid)
        return templates.TemplateResponse(
            request, "_job_contacts.html",
            {"contacts": contacts, "channels": _channels_for(contacts)},
        )

    @app.get("/contacts/export.csv")
    def contacts_export(
        company: str | None = None,
        role: str | None = None,
        label: str | None = None,
        has_email: bool = False,
    ) -> Response:
        contacts = _fetch_contacts(company, role, label, has_email, limit=None)
        chan_map = _channels_for(contacts)
        extra_kinds = ["personal_email", "x", "bluesky", "mastodon", "github", "site"]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "company", "full_name", "title", "role", "email",
                "email_status", "confidence", "label", "identity_confidence", "linkedin",
            ]
            + extra_kinds
        )
        for c in contacts:
            chans = chan_map.get(c.id, [])
            by_kind: dict[str, list[str]] = {}
            for ch in chans:
                by_kind.setdefault(ch.kind, []).append(ch.value)
            ident = (c.evidence or {}).get("identity_confidence")
            writer.writerow(
                [
                    _csv_safe(c.company_slug),
                    _csv_safe(c.full_name or ""),
                    _csv_safe(c.title or ""),
                    _csv_safe(c.role_category or ""),
                    _csv_safe(c.email or ""),
                    _csv_safe(c.email_status or ""),
                    f"{c.confidence:.0f}" if c.confidence is not None else "",
                    _csv_safe(c.label or ""),
                    f"{ident:.0f}" if isinstance(ident, (int, float)) else "",
                    _csv_safe(c.linkedin_url or ""),
                ]
                + [_csv_safe(" ".join(by_kind.get(k, []))) for k in extra_kinds]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=contacts.csv"},
        )

    @app.get("/tracker", response_class=HTMLResponse)
    def tracker_page(
        request: Request, status: str | None = None, sort: str = "due"
    ) -> HTMLResponse:
        apps = _fetch_applications(status, sort)
        live = _best_contacts_for([a.company_slug or "" for a in apps])
        today = datetime.now().date()
        rows = [_row_view(a, live, today) for a in apps]
        return templates.TemplateResponse(
            request,
            "tracker.html",
            {
                "rows": rows,
                "count": len(apps),
                "statuses": TRACKER_STATUSES,
                "status": status or "",
                "sort": sort,
            },
        )

    @app.post("/jobs/{job_uid}/track", response_class=HTMLResponse)
    def track_job(job_uid: str, _: None = Depends(_same_origin)) -> HTMLResponse:
        """Idempotently add a job to the tracker, snapshotting its display fields. The
        contact is fetched live from the contacts table at render time (not snapshotted)."""
        session = get_session()
        try:
            existing = session.scalar(
                select(Application).where(Application.job_uid == job_uid)
            )
            if existing is None:
                job = session.scalar(select(Job).where(Job.job_uid == job_uid))
                if job is None:
                    return HTMLResponse("unknown job", status_code=404)
                session.add(
                    Application(
                        job_uid=job_uid,
                        status="To Apply",
                        company=job.company,
                        company_slug=job.company_slug,
                        role=job.title,
                        location=job.location_normalized or job.location_raw,
                        link=job.canonical_url,
                        due_date=job.deadline_at,
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    # A concurrent request (double-click / two tabs) won the race and
                    # inserted first — the unique constraint rejected ours. Already tracked.
                    session.rollback()
        finally:
            session.close()
        return HTMLResponse(_TRACKED_BADGE)

    @app.post("/tracker/{app_id}/update", response_class=HTMLResponse)
    async def tracker_update(
        request: Request, app_id: int, _: None = Depends(_same_origin)
    ) -> HTMLResponse:
        """Inline-edit one field of a tracker row. Keys on field PRESENCE in the raw form
        (HTMX posts only the changed input) so emptying an input clears it — FastAPI's
        Form() collapses empty-present to absent, which would make clearing impossible."""
        form = await request.form()
        session = get_session()
        try:
            a = session.get(Application, app_id)
            if a is None:
                return HTMLResponse("not found", status_code=404)
            if "status" in form:
                status = str(form["status"])
                if status in TRACKER_STATUSES:
                    a.status = status
                    if status == "Applied" and a.applied_at is None:
                        a.applied_at = datetime.now()
            if "emailed" in form:
                a.emailed = str(form["emailed"]).strip().lower() in ("yes", "true", "1", "on")
            if "due_date" in form:
                a.due_date = _parse_date(str(form["due_date"]))
            if "applied_at" in form:
                a.applied_at = _parse_date(str(form["applied_at"]))
            if "contact_name" in form:
                a.contact_name = str(form["contact_name"]).strip() or None
            if "contact_email" in form:
                a.contact_email = str(form["contact_email"]).strip() or None
            if "notes" in form:
                a.notes = str(form["notes"]).strip() or None
            session.commit()
            session.refresh(a)
            live = _best_contacts_for([a.company_slug or ""])
            ctx = {**_row_view(a, live, datetime.now().date()), "statuses": TRACKER_STATUSES}
        finally:
            session.close()
        return templates.TemplateResponse(request, "_tracker_row.html", ctx)

    @app.post("/tracker/{app_id}/delete", response_class=HTMLResponse)
    def tracker_delete(app_id: int, _: None = Depends(_same_origin)) -> HTMLResponse:
        session = get_session()
        try:
            a = session.get(Application, app_id)
            if a is not None:
                session.delete(a)
                session.commit()
        finally:
            session.close()
        return HTMLResponse("")  # HTMX swaps the row out of the table

    @app.get("/tracker/export.csv")
    def tracker_export(status: str | None = None, sort: str = "due") -> Response:
        apps = _fetch_applications(status, sort)
        live = _best_contacts_for([a.company_slug or "" for a in apps])
        today = datetime.now().date()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "company", "role", "location", "due_date", "status", "emailed",
                "contact_name", "contact_email", "link", "applied_on", "notes",
            ]
        )
        for a in apps:
            v = _row_view(a, live, today)
            writer.writerow(
                [
                    _csv_safe(a.company or ""),
                    _csv_safe(a.role or ""),
                    _csv_safe(a.location or ""),
                    a.due_date.strftime("%Y-%m-%d") if a.due_date else "",
                    _csv_safe(a.status or ""),
                    "yes" if a.emailed else "no",
                    _csv_safe(v["cname"]),
                    _csv_safe(v["cemail"]),
                    _csv_safe(a.link or ""),
                    a.applied_at.strftime("%Y-%m-%d") if a.applied_at else "",
                    _csv_safe(a.notes or ""),
                ]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tracker.csv"},
        )

    return app
