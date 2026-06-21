from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from internhunter.apply.applicant import Applicant
from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Application

_NO_SPONSOR = re.compile(
    r"(no(t)?\s+.{0,20}sponsor|without\s+sponsor|unable\s+to\s+sponsor|"
    r"must\s+be\s+(a\s+)?(us\s+)?citizen|requires?\s+us\s+citizen)",
    re.IGNORECASE,
)


def kill_switch_active(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if not resolved.enable_auto_apply:
        return True
    return resolved.auto_apply_stop_file.exists()


def applications_today(session) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    return int(
        session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.status == "submitted", Application.applied_at >= cutoff)
        )
        or 0
    )


def eligible(job, a: Applicant) -> bool:
    if not a.requires_sponsorship:
        return True
    return _NO_SPONSOR.search(job.description_text or "") is None


def skip_reason(session, job, a: Applicant, settings: Settings | None = None) -> str | None:
    resolved = settings or get_settings()
    if kill_switch_active(resolved):
        return "auto-apply disabled (kill switch)"
    existing = session.scalar(
        select(Application).where(Application.job_uid == job.job_uid)
    )
    if existing is not None:
        return "already in applications"
    company_count = int(
        session.scalar(
            select(func.count()).select_from(Application).where(
                Application.company_slug == job.company_slug,
                Application.status == "submitted",
            )
        )
        or 0
    )
    if company_count >= resolved.auto_apply_per_company_cap:
        return "per-company cap reached"
    if not eligible(job, a):
        return "ineligible (sponsorship mismatch)"
    if applications_today(session) >= resolved.auto_apply_daily_cap:
        return "daily cap reached"
    return None
