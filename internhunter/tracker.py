"""Pipeline tracker: every matched posting gets a stage that can be advanced.

Canonical flow: found -> applied -> referral-requested -> interview -> offer -> rejected.
The DB keeps the dashboard's display vocabulary ("To Apply", "Applied", ...) so existing
rows and the web tracker keep working; the CLI accepts either form via STAGE_ALIASES.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internhunter.config.settings import Settings

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from internhunter.core.db import Application, Job

# Ordered pipeline stages, display form (what the DB + dashboard store/show).
STAGES: tuple[str, ...] = (
    "To Apply",  # = found
    "Applied",
    "Referral Requested",
    "Interviewing",
    "Offer",
    "Rejected",
)

STAGE_ALIASES: dict[str, str] = {
    "found": "To Apply",
    "to-apply": "To Apply",
    "to apply": "To Apply",
    "applied": "Applied",
    "apply": "Applied",
    "referral-requested": "Referral Requested",
    "referral requested": "Referral Requested",
    "referral": "Referral Requested",
    "interview": "Interviewing",
    "interviewing": "Interviewing",
    "offer": "Offer",
    "rejected": "Rejected",
    "reject": "Rejected",
}


def normalize_stage(value: str) -> str | None:
    """Accepts CLI aliases ('found', 'referral-requested') and display forms
    ('To Apply'); returns the canonical display form or None if unrecognized."""
    raw = value.strip()
    if raw in STAGES:
        return raw
    return STAGE_ALIASES.get(raw.lower())


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def track_job(
    session: Session,
    job: Job,
    *,
    stage: str = "To Apply",
    warm_intro: bool = False,
    connection_name: str | None = None,
    intro_draft: str | None = None,
    notes: str | None = None,
    enrich: bool = True,
    settings: Settings | None = None,
) -> Application | None:
    """Record a job in the pipeline (idempotent on job_uid). Returns the new row, or
    None when the job is already tracked — existing rows are never overwritten, so a
    stage the user advanced can't regress when the same posting alerts again."""
    existing = session.scalar(
        select(Application).where(Application.job_uid == job.job_uid)
    )
    if existing is not None:
        return None
    app = Application(
        job_uid=job.job_uid,
        status=normalize_stage(stage) or "To Apply",
        company=job.company or job.company_slug,
        company_slug=job.company_slug,
        role=job.title,
        location=job.location_normalized or job.location_raw,
        link=job.canonical_url,
        due_date=job.deadline_at,
        warm_intro=warm_intro,
        connection_name=connection_name,
        intro_draft=intro_draft,
        notes=notes,
    )
    try:
        # SAVEPOINT: a concurrent insert of the same job_uid (scheduler + dashboard)
        # must only unwind this row, not the caller's pending changes.
        with session.begin_nested():
            session.add(app)
    except IntegrityError:
        return None
    if enrich:
        from internhunter.outreach import enrich_application

        enrich_application(session, app, job, settings)
    return app


def find_application(session: Session, ident: str) -> Application | None:
    """Look up by numeric row id first, then by job_uid."""
    if ident.isdigit():
        app = session.get(Application, int(ident))
        if app is not None:
            return app
    return session.scalar(select(Application).where(Application.job_uid == ident))


def set_stage(session: Session, ident: str, stage: str) -> Application | None:
    display = normalize_stage(stage)
    if display is None:
        raise ValueError(
            f"unknown stage {stage!r}; use one of: "
            + ", ".join(sorted(set(STAGE_ALIASES) | set(STAGES)))
        )
    app = find_application(session, ident)
    if app is None:
        return None
    app.status = display
    if display == "Applied" and app.applied_at is None:
        app.applied_at = _utcnow()
    session.flush()
    return app


@dataclass(frozen=True)
class TrackerSummary:
    total: int
    by_stage: dict[str, int]
    warm: int


def tracker_summary(session: Session) -> TrackerSummary:
    rows = session.execute(
        select(Application.status, func.count()).group_by(Application.status)
    ).all()
    by_stage = {stage: 0 for stage in STAGES}
    total = 0
    for status, count in rows:
        by_stage[status or "To Apply"] = by_stage.get(status or "To Apply", 0) + count
        total += count
    warm = session.scalar(
        select(func.count()).select_from(Application).where(Application.warm_intro.is_(True))
    )
    return TrackerSummary(total=total, by_stage=by_stage, warm=int(warm or 0))


def list_applications(session: Session, stage: str | None = None) -> list[Application]:
    stmt = select(Application)
    if stage:
        display = normalize_stage(stage)
        if display is None:
            raise ValueError(f"unknown stage {stage!r}")
        stmt = stmt.where(Application.status == display)
    apps = list(session.scalars(stmt))
    rank = {stage: i for i, stage in enumerate(STAGES)}
    far = datetime(9999, 1, 1)
    apps.sort(key=lambda a: (rank.get(a.status, 99), a.due_date or far, a.id))
    return apps


_EXPORT_COLUMNS = (
    "id", "company", "role", "location", "status", "warm_intro", "connection_name",
    "due_date", "applied_at", "link", "notes",
)


def export_csv(session: Session, path: Path) -> int:
    """Single exportable view of the whole pipeline."""
    apps = list_applications(session)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_EXPORT_COLUMNS)
        for a in apps:
            writer.writerow(
                [
                    a.id,
                    a.company or "",
                    a.role or "",
                    a.location or "",
                    a.status or "",
                    "warm" if a.warm_intro else "cold",
                    a.connection_name or "",
                    a.due_date.date().isoformat() if a.due_date else "",
                    a.applied_at.date().isoformat() if a.applied_at else "",
                    a.link or "",
                    (a.notes or "").replace("\n", " "),
                ]
            )
    return len(apps)
