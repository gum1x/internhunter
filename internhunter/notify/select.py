from __future__ import annotations

from datetime import UTC, datetime, timedelta

from internhunter.core.db import Job

# Verdicts the LLM judge assigns to clear slop. We don't PAGE about these (they stay in
# the dashboard — never deleted), only suppress them from push notifications.
_BAD_VERDICTS = {"spam", "ghost", "agency", "mlm"}
_BAD_CONFIDENCE = 70.0


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _is_clear_slop(job: Job) -> bool:
    return (
        job.quality_verdict in _BAD_VERDICTS
        and job.quality_confidence is not None
        and job.quality_confidence >= _BAD_CONFIDENCE
    )


def select_notifiable(
    jobs: list[Job],
    min_fit: float = 0.6,
    now: datetime | None = None,
    deadline_within_days: int = 14,
) -> list[Job]:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    horizon = moment + timedelta(days=deadline_within_days)

    selected: list[Job] = []
    seen: set[str] = set()
    for job in jobs:
        ident = job.job_uid or str(id(job))
        if ident in seen:
            continue
        if _is_clear_slop(job):
            continue
        high_fit = job.discovery_score is not None and job.discovery_score >= min_fit
        deadline = _aware(job.deadline_at)
        approaching = deadline is not None and moment <= deadline <= horizon
        if high_fit or approaching:
            seen.add(ident)
            selected.append(job)

    selected.sort(
        key=lambda j: j.discovery_score if j.discovery_score is not None else float("-inf"),
        reverse=True,
    )
    return selected
